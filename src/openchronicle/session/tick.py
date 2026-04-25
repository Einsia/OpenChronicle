"""Async daemon wiring for the session/reducer pipeline.

Three asyncio tasks live here:

  * ``run_check_cuts`` — calls ``SessionManager.check_cuts`` every
    ``session.tick_seconds`` so idle gaps / soft cuts fire even when
    the dispatcher is quiet.
  * ``run_daily_safety_net`` — once per local day at HH:MM (from
    ``reducer.daily_tick_hour/minute``), force-ends the currently open
    session, retries any ``failed`` sessions, and covers the edge case
    where the process was offline across midnight.
  * ``build_manager`` — factory that wires ``on_session_end`` to
    persist a ``sessions`` row and spawn the S2 reducer thread.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from ..config import Config
from ..logger import get
from ..store import fts
from ..writer import classifier as classifier_mod
from ..writer import session_reducer
from . import store as session_store
from .manager import SessionManager

logger = get("openchronicle.session")


def build_manager(cfg: Config) -> SessionManager:
    """Construct a SessionManager whose end-callback wires the reducer."""

    def _on_start(session_id: str, start: datetime) -> None:
        """Persist an 'active' row immediately so crashes are recoverable."""
        with fts.cursor() as conn:
            session_store.insert(
                conn,
                session_store.SessionRow(
                    id=session_id, start_time=start, status="active",
                ),
            )

    def _on_end(session_id: str, start: datetime, end: datetime) -> None:
        with fts.cursor() as conn:
            existing = session_store.get_by_id(conn, session_id)
            if existing is None:
                session_store.insert(
                    conn,
                    session_store.SessionRow(
                        id=session_id, start_time=start, end_time=end, status="ended",
                    ),
                )
            else:
                session_store.mark_ended(conn, session_id, end)

        if not cfg.reducer.enabled:
            logger.info("reducer disabled — session %s stored without reduce", session_id)
            return

        session_reducer.reduce_session_async(
            cfg,
            session_id=session_id,
            start_time=start,
            end_time=end,
            on_done=_after_reduce,
        )

    def _after_reduce(result: session_reducer.ReduceResult) -> None:
        """Terminal reducer succeeded → classify any window the 30-min tick missed."""
        if not result.written or not result.entry_id or not result.path:
            return
        if not result.is_final:
            # Incremental flushes are handled by run_classifier_tick on its
            # own cadence — the reducer callback only fires the terminal
            # catch-up for any trailing window the tick hadn't reached yet.
            return
        window_start: datetime | None = None
        if result.end_time is not None:
            with fts.cursor() as conn:
                row = session_store.get_by_id(conn, result.session_id)
                if row and row.classified_end:
                    window_start = row.classified_end
        try:
            classify = classifier_mod.classify_after_reduce(
                cfg,
                session_id=result.session_id,
                event_daily_path=result.path,
                just_written_entry_id=result.entry_id,
                session_start=result.start_time,
                session_end=result.end_time,
                window_start=window_start,
            )
            if classify.committed and classify.written_ids:
                logger.info(
                    "classifier %s: wrote %d entries into %s",
                    result.session_id,
                    len(classify.written_ids),
                    ", ".join(classify.created_paths) or "existing files",
                )
            elif classify.skipped_reason:
                logger.info(
                    "classifier %s: skipped (%s)", result.session_id, classify.skipped_reason
                )
            else:
                logger.info(
                    "classifier %s: committed with no writes", result.session_id
                )
            if classify.committed and result.end_time is not None:
                with fts.cursor() as conn:
                    session_store.set_classified_end(
                        conn, result.session_id, result.end_time,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "classifier %s: crashed: %s", result.session_id, exc, exc_info=True
            )

    return SessionManager(
        gap_minutes=cfg.session.gap_minutes,
        soft_cut_minutes=cfg.session.soft_cut_minutes,
        max_session_hours=cfg.session.max_session_hours,
        on_session_start=_on_start,
        on_session_end=_on_end,
    )


async def run_check_cuts(cfg: Config, manager: SessionManager) -> None:
    """Periodic check_cuts tick."""
    interval = max(5, int(cfg.session.tick_seconds))
    logger.info("session check_cuts loop started (every %ds)", interval)
    while True:
        try:
            await asyncio.to_thread(manager.check_cuts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("session check_cuts failed: %s", exc, exc_info=True)
        await asyncio.sleep(interval)


async def run_flush_tick(cfg: Config, manager: SessionManager) -> None:
    """Incremental reducer tick for the active session.

    Every ``session.flush_minutes`` (min 5) checks for an active session and
    reduces any closed timeline blocks since the last flush into a partial
    entry in the event-daily file. Classifier is not fired here — it only
    runs on the terminal reduce at session end.
    """
    if not cfg.reducer.enabled:
        logger.info("flush tick loop not started (reducer disabled)")
        return
    interval = max(300, int(cfg.session.flush_minutes) * 60)
    logger.info("session flush loop started (every %ds)", interval)
    while True:
        try:
            await asyncio.sleep(interval)
            snap = manager.current_snapshot()
            if snap is None:
                continue
            session_id, session_start = snap
            await asyncio.to_thread(
                session_reducer.flush_active_session,
                cfg,
                session_id=session_id,
                session_start=session_start,
                now=datetime.now().astimezone(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("session flush tick failed: %s", exc, exc_info=True)


async def run_classifier_tick(cfg: Config, manager: SessionManager) -> None:
    """Periodic durable-fact classification for the active session.

    Every ``classifier.interval_minutes`` (min 5) checks for an active
    session and classifies any event-daily entries tagged with the
    session that have landed since the last classifier pass. The
    terminal reduce runs its own catch-up for the trailing window, so
    this tick is a pure incremental step — no effect at session end.
    """
    if not cfg.reducer.enabled:
        logger.info("classifier tick loop not started (reducer disabled)")
        return
    interval = max(300, int(cfg.classifier.interval_minutes) * 60)
    logger.info("classifier tick loop started (every %ds)", interval)
    while True:
        try:
            await asyncio.sleep(interval)
            snap = manager.current_snapshot()
            if snap is None:
                continue
            session_id, session_start = snap
            now = datetime.now().astimezone()
            event_daily_name = f"event-{session_start.strftime('%Y-%m-%d')}.md"

            window_start = session_start
            with fts.cursor() as conn:
                row = session_store.get_by_id(conn, session_id)
                if row and row.classified_end:
                    window_start = row.classified_end

            if now - window_start < timedelta(seconds=interval):
                continue

            result = await asyncio.to_thread(
                classifier_mod.classify_window,
                cfg,
                session_id=session_id,
                event_daily_path=event_daily_name,
                start=window_start,
                end=now,
                include_prior_day=window_start == session_start,
            )

            if result.committed and result.written_ids:
                logger.info(
                    "classifier tick %s: wrote %d entries into %s",
                    session_id,
                    len(result.written_ids),
                    ", ".join(result.created_paths) or "existing files",
                )
            elif result.skipped_reason:
                logger.info(
                    "classifier tick %s: skipped (%s)",
                    session_id, result.skipped_reason,
                )
            else:
                logger.info(
                    "classifier tick %s: committed with no writes", session_id,
                )

            if result.committed or result.skipped_reason:
                with fts.cursor() as conn:
                    session_store.set_classified_end(conn, session_id, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("classifier tick failed: %s", exc, exc_info=True)


def _seconds_until_next_local(hour: int, minute: int) -> float:
    """Seconds from now until the next local-time HH:MM."""
    now = datetime.now().astimezone()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily_safety_net(cfg: Config, manager: SessionManager) -> None:
    """Once per local day at HH:MM, force-end open session + retry failed."""
    hour = cfg.reducer.daily_tick_hour
    minute = cfg.reducer.daily_tick_minute
    logger.info("daily safety-net loop started (fires at %02d:%02d local)", hour, minute)
    while True:
        try:
            wait = _seconds_until_next_local(hour, minute)
            await asyncio.sleep(wait)
            logger.info("daily safety-net tick: force-ending open session + reducing pending rows")
            await asyncio.to_thread(manager.force_end, reason="daily-safety-net")
            if cfg.reducer.enabled:
                # Give the just-force-ended session's async reducer thread a
                # chance to finish before the catch-up pass would re-process it.
                await asyncio.sleep(2)
                await asyncio.to_thread(session_reducer.reduce_all_pending, cfg)
            # Truncate the WAL sidecar after the heavy daily writes settle —
            # auto-checkpoint resets the WAL pointer but never shrinks the
            # file, so without this the sidecar drifts unbounded.
            try:
                busy, log_pages, ckpt_pages = await asyncio.to_thread(fts.checkpoint)
                logger.info(
                    "daily wal_checkpoint(TRUNCATE): busy=%d log=%d checkpointed=%d",
                    busy, log_pages, ckpt_pages,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("daily wal_checkpoint failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("daily safety-net failed: %s", exc, exc_info=True)
            # Sleep a minute so a tight error loop doesn't hammer the CPU.
            await asyncio.sleep(60)
