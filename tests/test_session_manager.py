from __future__ import annotations

from datetime import datetime, timedelta, timezone

from openchronicle.session.manager import SessionManager


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now = self.now + timedelta(**kwargs)


_T0 = datetime(2026, 4, 21, 10, 0, 0, tzinfo=timezone.utc)


def _event(bundle: str = "com.apple.dt.Xcode") -> dict:
    return {"event_type": "AXFocusedWindowChanged", "bundle_id": bundle, "window_title": ""}


def test_session_auto_starts_on_first_event() -> None:
    clock = _FakeClock(_T0)
    m = SessionManager(clock=clock)
    assert m.current_id is None
    m.on_event(_event())
    assert m.current_id is not None


def test_hard_cut_after_idle_gap() -> None:
    clock = _FakeClock(_T0)
    ended: list[tuple[str, datetime, datetime]] = []
    m = SessionManager(clock=clock, on_session_end=lambda s, a, b: ended.append((s, a, b)))

    m.on_event(_event())
    sid = m.current_id
    clock.advance(minutes=6)
    m.check_cuts()

    assert m.current_id is None
    assert len(ended) == 1
    assert ended[0][0] == sid


def test_no_hard_cut_below_threshold() -> None:
    clock = _FakeClock(_T0)
    m = SessionManager(clock=clock, gap_minutes=5)
    m.on_event(_event())
    clock.advance(minutes=4)
    m.check_cuts()
    assert m.current_id is not None


def test_timeout_cut_after_max_hours() -> None:
    clock = _FakeClock(_T0)
    m = SessionManager(clock=clock, max_session_hours=2, gap_minutes=60)
    m.on_event(_event())
    # Keep feeding events so idle-gap rule doesn't fire first.
    for _ in range(13):
        clock.advance(minutes=10)
        m.on_event(_event())
    clock.advance(minutes=1)
    m.check_cuts()
    assert m.current_id is None


def test_soft_cut_on_unrelated_app_switch() -> None:
    clock = _FakeClock(_T0)
    m = SessionManager(clock=clock, soft_cut_minutes=3)
    m.on_event(_event("com.apple.dt.Xcode"))
    clock.advance(seconds=30)
    m.on_event(_event("com.apple.Safari"))  # switch → app_switched_at set, 2 apps
    clock.advance(minutes=4)                 # stay on Safari past soft-cut threshold
    m.check_cuts()
    assert m.current_id is None


def test_frequent_switching_prevents_soft_cut() -> None:
    clock = _FakeClock(_T0)
    m = SessionManager(clock=clock, soft_cut_minutes=3)
    m.on_event(_event("com.apple.dt.Xcode"))
    clock.advance(seconds=20)
    m.on_event(_event("com.apple.Safari"))
    clock.advance(seconds=20)
    m.on_event(_event("com.apple.dt.Xcode"))
    clock.advance(seconds=20)
    m.on_event(_event("com.apple.Safari"))
    # Most recent switch is now — not "same app for 3+ min" — so nothing to cut yet.
    clock.advance(minutes=2)
    m.check_cuts()
    # Two distinct apps seen in the last 2 min → frequent switching → no cut.
    assert m.current_id is not None


def test_force_end_closes_session() -> None:
    clock = _FakeClock(_T0)
    ended: list[str] = []
    m = SessionManager(clock=clock, on_session_end=lambda s, a, b: ended.append(s))
    m.on_event(_event())
    sid = m.current_id
    assert m.force_end(reason="daily-cron") == sid
    assert m.current_id is None
    assert ended == [sid]
    assert m.force_end() is None


def test_check_cuts_noop_when_no_session() -> None:
    clock = _FakeClock(_T0)
    m = SessionManager(clock=clock)
    m.check_cuts()  # must not raise
    assert m.current_id is None


def test_session_end_callback_receives_correct_range() -> None:
    clock = _FakeClock(_T0)
    captured: list[tuple[str, datetime, datetime]] = []
    m = SessionManager(clock=clock, on_session_end=lambda s, a, b: captured.append((s, a, b)))
    m.on_event(_event())
    start = clock.now
    clock.advance(minutes=2)
    m.on_event(_event())
    last_event = clock.now
    clock.advance(minutes=6)
    m.check_cuts()
    assert len(captured) == 1
    _, a, b = captured[0]
    assert a == start
    assert b == last_event
