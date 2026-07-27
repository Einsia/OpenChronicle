"""Capture scheduler: event-driven + heartbeat. Writes one JSON per tick to capture-buffer/."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..config import CaptureConfig
from ..logger import get
from ..store import fts as fts_store
from . import ax_capture, s1_parser, screenshot, window_meta
from .event_dispatcher import EventDispatcher
from .signal_store import CAPTURE_SCHEMA_VERSION, SignalStore
from .watcher import AXWatcherProcess

logger = get("openchronicle.capture")

_AX_RETRY_EVENTS = {
    "AXApplicationActivated",
    "AXFocusedWindowChanged",
    "UserMouseClick",
    "UserTextInput",
    "UserEnter",
}
_AX_RETRY_DELAYS = (0.15, 0.35)


class CaptureDaemonAlreadyRunning(RuntimeError):
    """Raised when another capture daemon owns the same data root."""


class _CaptureDaemonLock:
    def __init__(self) -> None:
        self._handle: Any = None

    def acquire(self) -> None:
        paths.ensure_dirs()
        self._handle = paths.capture_daemon_lock_file().open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise CaptureDaemonAlreadyRunning("already_running") from exc

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="milliseconds")


def _safe_filename(ts: str) -> str:
    return ts.replace(":", "-").replace("+", "p")


def _normalize_title(value: Any) -> str:
    return " ".join(str(value or "").split())


def _snapshot_window_meta(ax_tree: dict[str, Any]) -> dict[str, Any]:
    apps = ax_tree.get("apps") or []
    app = next((item for item in apps if item.get("is_frontmost")), None)
    if app is None:
        app = apps[0] if apps else None
    if not isinstance(app, dict):
        return {
            "app_name": "",
            "title": "",
            "bundle_id": "",
            "pid": 0,
            "window_identity": "",
            "window_identity_confidence": "low",
        }

    windows = app.get("windows") or []
    window = next((item for item in windows if item.get("focused")), None)
    if window is None:
        window = windows[0] if windows else None
    bundle_id = str(app.get("bundle_id") or "")
    pid = app.get("pid") if isinstance(app.get("pid"), int) else 0
    window_number = window.get("window_number") if isinstance(window, dict) else None
    if isinstance(window_number, int):
        window_identity = f"{bundle_id}:{pid}:{window_number}"
        confidence = "high"
    else:
        window_identity = f"{bundle_id}:{pid}" if bundle_id else ""
        confidence = "low"
    return {
        "app_name": _normalize_title(app.get("name")),
        "title": _normalize_title(window.get("title")) if isinstance(window, dict) else "",
        "bundle_id": bundle_id,
        "pid": pid,
        "window_identity": window_identity,
        "window_identity_confidence": confidence,
    }


def _frontmost_snapshot_app(ax_tree: dict[str, Any]) -> dict[str, Any] | None:
    apps = ax_tree.get("apps") or []
    app = next((item for item in apps if item.get("is_frontmost")), None)
    if app is None:
        app = apps[0] if apps else None
    return app if isinstance(app, dict) else None


def _snapshot_quality(ax_tree: dict[str, Any]) -> int:
    """Score fields that indicate the focused app's AX tree is ready."""
    app = _frontmost_snapshot_app(ax_tree)
    if app is None:
        return 0

    score = 1
    if app.get("focused_element"):
        score += 100
    windows = app.get("windows") or []
    focused_window = next((item for item in windows if item.get("focused")), None)
    if isinstance(focused_window, dict):
        score += 10
        if _normalize_title(focused_window.get("title")):
            score += 2
        if focused_window.get("elements"):
            score += 5
    return score


def _snapshot_needs_retry(ax_tree: dict[str, Any], trigger: dict[str, Any] | None) -> bool:
    if (trigger or {}).get("event_type") not in _AX_RETRY_EVENTS:
        return False
    app = _frontmost_snapshot_app(ax_tree)
    if app is None or app.get("focused_element"):
        return False
    # Browser page content often has no focused AX element at all. If the
    # focused window already exposes one unambiguous address-bar URL, the
    # snapshot is useful and complete; retrying only adds 500 ms of latency.
    url, source = s1_parser._extract_url(app)
    if url is not None and source == "ax_address_bar":
        return False
    return any(window.get("focused") for window in (app.get("windows") or []))


def _capture_ax_with_retry(
    provider: ax_capture.AXProvider,
    trigger: dict[str, Any] | None,
) -> tuple[ax_capture.AXCaptureResult | None, int, bool]:
    """Capture AX, retrying incomplete snapshots without crossing app identity."""
    result = provider.capture_frontmost(focused_window_only=True)
    if result is None:
        return None, 0, True

    best = result
    best_quality = _snapshot_quality(result.raw_json)
    initial_bundle = _snapshot_window_meta(result.raw_json)["bundle_id"]
    retry_count = 0
    consistent = True

    if not _snapshot_needs_retry(result.raw_json, trigger):
        return best, retry_count, consistent

    for delay in _AX_RETRY_DELAYS:
        time.sleep(delay)
        candidate = provider.capture_frontmost(focused_window_only=True)
        retry_count += 1
        if candidate is None:
            continue

        candidate_bundle = _snapshot_window_meta(candidate.raw_json)["bundle_id"]
        if initial_bundle and candidate_bundle != initial_bundle:
            consistent = False
            logger.debug(
                "AX retry discarded after app changed: %r -> %r",
                initial_bundle,
                candidate_bundle,
            )
            break

        quality = _snapshot_quality(candidate.raw_json)
        if quality > best_quality:
            best = candidate
            best_quality = quality
        if not _snapshot_needs_retry(candidate.raw_json, trigger):
            break

    return best, retry_count, consistent


def _build_capture(
    cfg: CaptureConfig,
    provider: ax_capture.AXProvider,
    trigger: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build an enriched capture dict in memory. Returns None if capturing is paused."""
    paths.ensure_dirs()

    if paths.paused_flag().exists():
        logger.info("capture skipped (paused)")
        return None

    excluded_bundles = set(cfg.excluded_signal_bundle_ids)
    if excluded_bundles:
        active = window_meta.active_window()
        if active.bundle_id in excluded_bundles:
            logger.info("capture skipped (privacy excluded app)")
            return None

    ts = _now_iso()
    out: dict[str, Any] = {
        "timestamp": ts,
        "schema_version": 2,
        "capture_schema_version": CAPTURE_SCHEMA_VERSION,
        "trigger": trigger or {"event_type": "heartbeat"},
    }

    if provider.available:
        result, retry_count, ax_consistent = _capture_ax_with_retry(provider, trigger)
        if result is not None:
            out["ax_tree"] = result.raw_json
            out["ax_metadata"] = {
                **result.metadata,
                "retry_count": retry_count,
                "app_consistent": ax_consistent,
            }
    else:
        out["ax_unavailable"] = True

    snapshot_meta = _snapshot_window_meta(out.get("ax_tree") or {})
    bundle_id = snapshot_meta["bundle_id"]
    if bundle_id in excluded_bundles:
        logger.info("capture skipped (privacy excluded AX snapshot)")
        return None
    app_name = snapshot_meta["app_name"]
    title = snapshot_meta["title"]
    title_source = "ax_snapshot" if title else "unavailable"

    trigger_data = trigger or {}
    trigger_bundle = str(trigger_data.get("bundle_id") or "")
    trigger_title = _normalize_title(trigger_data.get("window_title"))
    if not title and trigger_title and trigger_bundle and trigger_bundle == bundle_id:
        title = trigger_title
        title_source = "trigger"

    # System Events is a last-resort metadata source. Only combine it with an
    # AX snapshot when both identify the same app.
    if not app_name or not bundle_id or not title:
        fallback = window_meta.active_window()
        if not bundle_id:
            bundle_id = fallback.bundle_id
        if not app_name and (not bundle_id or fallback.bundle_id == bundle_id):
            app_name = _normalize_title(fallback.app_name)
        if not title and fallback.bundle_id == bundle_id:
            title = _normalize_title(fallback.title)
            if title:
                title_source = "system_events"

    out["window_meta"] = {
        "app_name": app_name,
        "title": title,
        "bundle_id": bundle_id,
        "title_source": title_source,
        "sampled_at": ts,
        "pid": snapshot_meta["pid"],
        "window_identity": snapshot_meta["window_identity"],
        "window_identity_confidence": snapshot_meta["window_identity_confidence"],
    }

    if cfg.include_screenshot:
        shot = screenshot.grab(
            max_width=cfg.screenshot_max_width, jpeg_quality=cfg.screenshot_jpeg_quality
        )
        if shot is not None:
            out["screenshot"] = {
                "image_base64": shot.image_base64,
                "mime_type": shot.mime_type,
                "width": shot.width,
                "height": shot.height,
            }

    s1_parser.enrich(out)
    return out


def _write_capture(out: dict[str, Any]) -> Path:
    """Persist a built capture dict to the buffer, index it for search, and log."""
    ts = out["timestamp"]
    path = paths.capture_buffer_dir() / f"{_safe_filename(ts)}-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(out, ensure_ascii=False))
    _index_capture(path.stem, out)
    meta = out.get("window_meta") or {}
    logger.info(
        "capture ok: %s trigger=%s app=%r title=%r ax=%s screenshot=%s",
        path.name,
        (out.get("trigger") or {}).get("event_type"),
        meta.get("app_name"),
        (meta.get("title") or "")[:60],
        "ax_tree" in out,
        "screenshot" in out,
    )
    return path


def _index_capture(file_stem: str, out: dict[str, Any]) -> None:
    """Insert/upsert the capture's S1 fields into the FTS5 index.

    Failures here are non-fatal — a missed FTS row is recoverable via
    ``openchronicle rebuild-captures-index``; killing the capture worker
    over an indexing hiccup would lose the JSON too.
    """
    meta = out.get("window_meta") or {}
    focused = out.get("focused_element") or {}
    try:
        with fts_store.cursor() as conn:
            fts_store.insert_capture(
                conn,
                id=file_stem,
                timestamp=out.get("timestamp", ""),
                app_name=meta.get("app_name") or "",
                bundle_id=meta.get("bundle_id") or "",
                window_title=meta.get("title") or "",
                focused_role=focused.get("role") or "",
                focused_value=focused.get("value") or "",
                visible_text=out.get("visible_text") or "",
                url=out.get("url") or "",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("captures FTS insert failed for %s: %s", file_stem, exc)


def _content_fingerprint(out: dict[str, Any]) -> str:
    """Hash the content-bearing fields of a capture for consecutive-duplicate detection.

    Excludes timestamp, trigger metadata, screenshots, and the raw ax_tree (which
    contains coordinate noise). Focuses on what actually drives downstream stages:
    the window identity + what the user can see + what they've typed.
    """
    meta = out.get("window_meta") or {}
    focused = out.get("focused_element") or {}
    payload = "\x1f".join(
        [
            meta.get("bundle_id") or "",
            meta.get("title") or "",
            focused.get("role") or "",
            focused.get("value") or "",
            out.get("visible_text") or "",
            out.get("url") or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def capture_once(
    cfg: CaptureConfig,
    provider: ax_capture.AXProvider,
    *,
    trigger: dict[str, Any] | None = None,
) -> Path | None:
    """Perform one capture and write it to the buffer. Returns the file path on success.

    ``trigger`` (optional) carries the watcher event metadata that caused this
    capture. When absent the capture is treated as a heartbeat / manual tick.

    This helper always writes — content-dedup lives in ``_CaptureRunner`` so the
    CLI ``capture-once`` smoke test still produces a fresh file on demand.
    """
    out = _build_capture(cfg, provider, trigger)
    if out is None:
        return None
    return _write_capture(out)


class _CaptureRunner:
    """Serializes capture_once calls from the watcher thread + heartbeat task.

    Captures execute on a single dedicated worker thread fed by a bounded
    queue, so the watcher reader thread never blocks on AX / screenshot I/O
    and a runaway burst of events can never spawn unbounded threads.

    Also enforces *consecutive-duplicate dedup*: if the content fingerprint
    (bundle+title+focused value+visible_text+url) matches the previously
    written capture, the new one is dropped. Time-based dedup in the
    dispatcher handles rapid-fire bursts; this handles a static screen
    (e.g. the lock screen overnight) that keeps generating identical
    captures. When deduped, the ``pre_capture_hook`` is NOT fired, so the
    session manager's idle timer isn't reset by meaningless repetition.
    """

    # Bounded queue for backpressure. Captures are de-duplicated by the
    # dispatcher upstream and again by content-fingerprint here, so a
    # backlog past this size is a sign the worker is stuck or LLM/AX
    # calls are slow — drop with a warning rather than build an
    # unbounded thread/memory backlog.
    _MAX_PENDING = 16
    _SENTINEL: Any = object()

    def __init__(
        self,
        cfg: CaptureConfig,
        provider: ax_capture.AXProvider,
        *,
        signal_store: SignalStore | None = None,
        pre_capture_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._provider = provider
        self._signal_store = signal_store
        self._pre_capture_hook = pre_capture_hook
        self._lock = threading.Lock()
        self._last_fingerprint: str | None = None
        self._last_snapshot_ref: str | None = None
        self._last_snapshot_bundle: str = ""
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self._MAX_PENDING)
        self._worker: threading.Thread | None = None

    def start_worker(self) -> None:
        """Spawn the dedicated worker thread. Idempotent."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="capture-worker",
            daemon=True,
        )
        self._worker.start()

    def context_snapshot_ref(self, bundle_id: str) -> str | None:
        """Return the latest same-app Snapshot ref for key-down-time context."""
        with self._lock:
            if bundle_id and bundle_id == self._last_snapshot_bundle:
                return self._last_snapshot_ref
            return None

    def stop_worker(self, *, timeout: float = 5.0) -> None:
        """Drain the queue and join the worker thread."""
        if self._worker is None:
            return
        with contextlib.suppress(queue.Full):
            self._queue.put(self._SENTINEL, timeout=1.0)
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            logger.warning("capture worker did not exit within %.1fs", timeout)
        self._worker = None

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._SENTINEL:
                return
            self.run(item)

    def run(self, trigger: dict[str, Any] | None) -> dict[str, Any]:
        # Serialize so two near-simultaneous triggers don't double-capture.
        with self._lock:
            capture_trigger = dict(trigger or {})
            completion = capture_trigger.pop("_capture_complete", None)
            signal_id = str(capture_trigger.get("signal_id") or "")
            context_snapshot_ref = self._last_snapshot_ref
            outcome: dict[str, Any]
            try:
                out = _build_capture(self._cfg, self._provider, capture_trigger)
                if out is None:
                    outcome = {
                        "status": "capture_unavailable",
                        "quality_status": "degraded",
                        "error_reason": "capture_unavailable",
                        "context_snapshot_ref": context_snapshot_ref,
                    }
                    self._finish_capture(signal_id, outcome, completion)
                    return outcome
                meta = out.get("window_meta") or {}
                snapshot_bundle = str(meta.get("bundle_id") or "")
                trigger_bundle = str(capture_trigger.get("bundle_id") or "")
                trigger_window = str(capture_trigger.get("window_identity") or "")
                snapshot_window = str(meta.get("window_identity") or "")
                trigger_confidence = str(
                    capture_trigger.get("window_identity_confidence") or "low"
                )
                if signal_id and (
                    not trigger_bundle
                    or not snapshot_bundle
                    or trigger_bundle != snapshot_bundle
                    or (
                        trigger_confidence == "high"
                        and trigger_window
                        and snapshot_window
                        and trigger_window != snapshot_window
                    )
                ):
                    outcome = {
                        "status": "app_changed",
                        "quality_status": "failed",
                        "error_reason": "bundle_changed",
                        "context_snapshot_ref": context_snapshot_ref,
                    }
                    self._finish_capture(signal_id, outcome, completion)
                    return outcome
                fingerprint = _content_fingerprint(out)
                if fingerprint == self._last_fingerprint:
                    logger.debug(
                        "capture skipped (content dedup): trigger=%s app=%r title=%r",
                        (trigger or {}).get("event_type"),
                        meta.get("app_name"),
                        (meta.get("title") or "")[:60],
                    )
                    if (
                        signal_id
                        and self._last_snapshot_ref
                        and snapshot_bundle == self._last_snapshot_bundle
                    ):
                        outcome = {
                            "status": "reused",
                            "quality_status": "good",
                            "snapshot_ref": self._last_snapshot_ref,
                            "context_snapshot_ref": context_snapshot_ref,
                        }
                    else:
                        outcome = {
                            "status": "unchanged",
                            "quality_status": "degraded",
                            "error_reason": "duplicate_without_ref",
                            "context_snapshot_ref": context_snapshot_ref,
                        }
                    self._finish_capture(signal_id, outcome, completion)
                    return outcome
                self._last_fingerprint = fingerprint
                path = _write_capture(out)
                self._last_snapshot_ref = path.name
                self._last_snapshot_bundle = snapshot_bundle
                outcome = {
                    "status": "new",
                    "quality_status": "good",
                    "snapshot_ref": path.name,
                    "context_snapshot_ref": context_snapshot_ref,
                }
                self._finish_capture(signal_id, outcome, completion)
                if self._pre_capture_hook is not None and trigger is not None:
                    try:
                        self._pre_capture_hook(trigger)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("pre_capture_hook failed: %s", exc)
                return outcome
            except Exception as exc:  # noqa: BLE001
                outcome = {
                    "status": "unresolved",
                    "quality_status": "failed",
                    "error_reason": type(exc).__name__,
                    "context_snapshot_ref": context_snapshot_ref,
                }
                self._finish_capture(signal_id, outcome, completion)
                logger.error("capture failed: %s", exc, exc_info=True)
                return outcome

    def run_threaded(self, trigger: dict[str, Any] | None) -> None:
        """Enqueue a capture for the worker thread; drop with a warning if full."""
        trigger_data = trigger or {}
        excluded_bundles = set(self._cfg.excluded_signal_bundle_ids)
        if (
            trigger is not None
            and not trigger_data.get("signal_id")
            and excluded_bundles
            and window_meta.active_window().bundle_id in excluded_bundles
        ):
            # A stale event from another app can arrive after the user switches
            # into an excluded app. Drop it before queueing so capture logging
            # cannot cause a Terminal AXValueChanged feedback loop. Signal-
            # linked requests still run so their attempt ledger is finalized.
            return
        try:
            self._queue.put_nowait(trigger)
        except queue.Full:
            signal_id = str((trigger or {}).get("signal_id") or "")
            completion = (trigger or {}).get("_capture_complete")
            outcome = {
                "status": "deferred_queue_full",
                "quality_status": "failed",
                "error_reason": "queue_full",
            }
            self._finish_capture(signal_id, outcome, completion)
            logger.warning(
                "capture queue full (%d pending); dropping trigger=%s",
                self._queue.qsize(),
                (trigger or {}).get("event_type") if trigger else "heartbeat",
            )

    def _finish_capture(
        self,
        signal_id: str,
        outcome: dict[str, Any],
        completion: Any,
    ) -> None:
        if callable(completion):
            completion(outcome)
            return
        compatibility = {
            "new": "captured",
            "reused": "reused",
            "unchanged": "duplicate_without_ref",
            "deferred_queue_full": "queue_full",
            "app_changed": "app_changed",
            "capture_unavailable": "capture_unavailable",
            "unresolved": "capture_failed",
        }
        self._update_signal(signal_id, compatibility.get(str(outcome.get("status")), "capture_failed"), snapshot_ref=outcome.get("snapshot_ref"))

    def _update_signal(
        self,
        signal_id: str,
        status: str,
        *,
        snapshot_ref: str | None = None,
    ) -> None:
        if signal_id and self._signal_store is not None:
            self._signal_store.update_snapshot(
                signal_id,
                status=status,
                snapshot_ref=snapshot_ref,
            )


async def run_forever(
    cfg: CaptureConfig,
    *,
    pre_capture_hook: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Run the capture pipeline until cancelled.

    If ``cfg.event_driven`` is true, starts the watcher subprocess and routes
    events through the dispatcher. A heartbeat timer also runs so long idle
    periods (no window changes, no typing) still get periodic snapshots.

    ``pre_capture_hook`` (optional) fires with the trigger dict for every
    capture that actually wrote new content to the buffer — duplicates
    collapsed by content-dedup do NOT fire it, so the session manager's idle
    timer isn't refreshed by a screen that isn't changing (e.g. the lock
    screen overnight).
    """
    daemon_lock = _CaptureDaemonLock()
    daemon_lock.acquire()
    provider = ax_capture.create_provider(
        depth=cfg.ax_depth,
        timeout=cfg.ax_timeout_seconds,
        manual_accessibility_bundles=(
            cfg.electron_accessibility_bundles if cfg.enable_electron_accessibility else []
        ),
    )
    if not provider.available:
        logger.warning("AX capture unavailable: %s", getattr(provider, "reason", "unknown reason"))

    signal_store = SignalStore(excluded_bundle_ids=set(cfg.excluded_signal_bundle_ids))
    recoverable_signal_ids = signal_store.recover_incomplete()
    if recoverable_signal_ids:
        logger.info(
            "signal recovery candidates deferred until context verification: count=%d",
            len(recoverable_signal_ids),
        )
    runner = _CaptureRunner(
        cfg,
        provider,
        signal_store=signal_store,
        pre_capture_hook=pre_capture_hook,
    )
    runner.start_worker()
    watcher: AXWatcherProcess | None = None
    dispatcher: EventDispatcher | None = None

    def _on_capture(trigger: dict[str, Any] | None) -> None:
        # Hook firing is deferred into the runner so content-deduped captures
        # (e.g. overnight lock-screen repeats) don't refresh the session timer.
        runner.run_threaded(trigger)

    if cfg.event_driven:
        watcher = AXWatcherProcess(
            excluded_bundle_ids=set(cfg.excluded_signal_bundle_ids),
        )
        if watcher.available:
            dispatcher = EventDispatcher(
                _on_capture,
                signal_store=signal_store,
                context_snapshot_ref_fn=runner.context_snapshot_ref,
                debounce_seconds=cfg.debounce_seconds,
                min_capture_gap_seconds=cfg.min_capture_gap_seconds,
                dedup_interval_seconds=cfg.dedup_interval_seconds,
                same_window_dedup_seconds=cfg.same_window_dedup_seconds,
            )
            watcher.on_event(dispatcher.on_event)
            watcher.start()
            for signal_id in recoverable_signal_ids:
                signal = signal_store.read(signal_id)
                if signal is not None:
                    dispatcher.recover_signal(signal)
            logger.info("event-driven capture started")
        else:
            logger.warning("AX watcher unavailable — falling back to heartbeat-only captures")

    # One capture immediately so the user sees something in the buffer right away.
    runner.run_threaded(None)

    try:
        if cfg.heartbeat_minutes > 0:
            heartbeat_interval = max(60.0, cfg.heartbeat_minutes * 60.0)
            logger.info(
                "heartbeat capture every %.0fs (event_driven=%s)",
                heartbeat_interval,
                cfg.event_driven,
            )
            while True:
                await asyncio.sleep(heartbeat_interval)
                try:
                    await asyncio.to_thread(runner.run, None)
                except Exception as exc:  # noqa: BLE001
                    logger.error("heartbeat capture failed: %s", exc, exc_info=True)
        else:
            logger.info(
                "heartbeat disabled (heartbeat_minutes=%d); event-driven only",
                cfg.heartbeat_minutes,
            )
            # Park until the task is cancelled so the watcher keeps streaming.
            await asyncio.Event().wait()
    finally:
        # Stop in producer→consumer order so no new work piles up after we've
        # told the worker to drain: watcher (no new events) → dispatcher
        # (cancel debounce) → runner worker (drain + join).
        if watcher is not None:
            watcher.stop()
        if dispatcher is not None:
            dispatcher.shutdown()
        runner.stop_worker()
        daemon_lock.release()


def cleanup_buffer(
    retention_hours: int,
    processed_before_ts: str | None = None,
    *,
    screenshot_retention_hours: int | None = None,
    max_mb: int = 0,
) -> dict[str, int]:
    """Tiered buffer hygiene. Returns {deleted, stripped, evicted}.

    Three passes, all gated on ``processed_before_ts`` so an unprocessed
    trailing capture is never evicted:

    1. **Delete whole file** when mtime is older than ``retention_hours``.
    2. **Strip screenshot** when mtime is older than
       ``screenshot_retention_hours`` (if provided and smaller than
       ``retention_hours``). The screenshot field is 77% of the payload
       and nothing downstream consumes it, so stripping keeps AX+text
       queryable for much longer at ~20% of the original size.
    3. **Evict by size** once total buffer size exceeds ``max_mb`` MB.
       Oldest already-absorbed files go first. ``max_mb=0`` disables this.
    """
    buf = paths.capture_buffer_dir()
    if not buf.exists():
        return {"deleted": 0, "stripped": 0, "evicted": 0}

    now = time.time()
    delete_cutoff = now - retention_hours * 3600
    strip_cutoff = (
        now - screenshot_retention_hours * 3600
        if screenshot_retention_hours and screenshot_retention_hours > 0
        else None
    )
    absorbed_before = (
        _safe_filename(processed_before_ts) if processed_before_ts is not None else None
    )

    deleted = stripped = evicted = 0
    surviving: list[tuple[float, Path, int]] = []  # (mtime, path, size_after_pass)
    removed_stems: list[str] = []  # for FTS delete-through

    for p in sorted(buf.iterdir()):
        if not p.is_file() or p.suffix != ".json":
            continue
        is_absorbed = absorbed_before is None or p.stem < absorbed_before
        try:
            st = p.stat()
        except OSError:
            continue

        if is_absorbed and st.st_mtime <= delete_cutoff:
            try:
                p.unlink()
                deleted += 1
                removed_stems.append(p.stem)
            except OSError:
                pass
            continue

        if (
            is_absorbed
            and strip_cutoff is not None
            and st.st_mtime <= strip_cutoff
            and _strip_screenshot_inplace(p)
        ):
            stripped += 1
            with contextlib.suppress(OSError):
                st = p.stat()

        surviving.append((st.st_mtime, p, st.st_size))

    if max_mb > 0:
        limit = max_mb * 1024 * 1024
        total = sum(sz for _, _, sz in surviving)
        if total > limit:
            surviving.sort()  # oldest first by mtime
            for _mtime, path, size in surviving:
                if total <= limit:
                    break
                if absorbed_before is not None and path.stem >= absorbed_before:
                    continue  # don't evict un-absorbed captures
                try:
                    path.unlink()
                    total -= size
                    evicted += 1
                    removed_stems.append(path.stem)
                except OSError:
                    pass

    if removed_stems:
        _delete_captures_from_fts(removed_stems)

    return {"deleted": deleted, "stripped": stripped, "evicted": evicted}


def _delete_captures_from_fts(stems: list[str]) -> None:
    """Drop matching rows from the captures index. Non-fatal on failure."""
    try:
        with fts_store.cursor() as conn:
            for stem in stems:
                fts_store.delete_capture(conn, stem)
    except Exception as exc:  # noqa: BLE001
        logger.warning("captures FTS delete failed for %d stems: %s", len(stems), exc)


def _strip_screenshot_inplace(path: Path) -> bool:
    """Rewrite a capture JSON without its ``screenshot`` field. Returns True if stripped."""
    try:
        raw = path.read_text()
    except OSError:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if "screenshot" not in data:
        return False
    data.pop("screenshot", None)
    data["screenshot_stripped"] = True
    try:
        path.write_text(json.dumps(data, ensure_ascii=False))
        return True
    except OSError:
        return False
