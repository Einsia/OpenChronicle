"""Capture scheduler: event-driven + heartbeat. Writes one JSON per tick to capture-buffer/."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import queue
import threading
import time
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
from .watcher import EventWatcher, create_watcher

logger = get("openchronicle.capture")


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()


def _safe_filename(ts: str) -> str:
    return ts.replace(":", "-").replace("+", "p")


def _public_trigger(trigger: dict[str, Any] | None) -> dict[str, Any]:
    """Return the schema-stable trigger fields suitable for capture.json.

    Internal-only hints (windows HWND, PID — used to anchor the helper
    subprocess) live on the trigger dict for plumbing convenience but
    must not leak into the persisted JSON, otherwise the on-disk schema
    diverges between mac and Windows.
    """
    if not trigger:
        return {"event_type": "heartbeat"}
    return {
        "event_type": trigger.get("event_type", ""),
        "bundle_id": trigger.get("bundle_id", ""),
        "window_title": trigger.get("window_title", ""),
    }


def _resolve_window_meta(
    primary: dict[str, str],
    ax_tree: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
) -> dict[str, str]:
    """Backfill empty ``window_meta`` fields from authoritative secondaries.

    The primary source — ``window_meta.active_window()`` — calls
    ``GetForegroundWindow`` on Windows. From a session-isolated daemon
    worker thread (a known ConPTY edge case) that returns 0, leaving the
    capture's ``window_meta`` empty even when the AX helper *did*
    successfully introspect the same window via the anchored HWND/PID.
    Downstream stages then surface the missing app name as ``Unknown``.

    Two ranked fallbacks fill the gap, mirroring the data the macOS
    osascript path would have produced:

    1. **AX tree's frontmost app** — the helper was invoked with the
       watcher's anchor hwnd/pid, so its ``apps[].name`` /
       ``apps[].bundle_id`` / ``windows[].title`` describe exactly the
       window the user was on at capture time.
    2. **Watcher trigger** — what `WinEventHook` saw when the event
       fired. Used last because the hwnd may have changed in the few ms
       before `_build_capture` ran. ``app_name`` is derived from
       ``bundle_id`` (the executable path) since the trigger schema
       intentionally has no app_name field.

    Mac never hits the fallbacks because ``osascript`` is reliable when
    AX permission is granted, but the function is platform-agnostic so
    behaviour stays uniform.
    """
    out = dict(primary)

    ax_app: dict[str, Any] | None = None
    ax_window: dict[str, Any] | None = None
    if isinstance(ax_tree, dict):
        apps = ax_tree.get("apps") or []
        for app in apps:
            if app.get("is_frontmost"):
                ax_app = app
                break
        if ax_app is None and apps:
            ax_app = apps[0]
        if ax_app is not None:
            windows = ax_app.get("windows") or []
            for w in windows:
                if w.get("focused"):
                    ax_window = w
                    break
            if ax_window is None and windows:
                ax_window = windows[0]

    if not out.get("app_name"):
        if ax_app and ax_app.get("name"):
            out["app_name"] = str(ax_app["name"])
        elif trigger and trigger.get("bundle_id"):
            # Trigger has no app_name; derive it from the exe path's stem.
            out["app_name"] = Path(str(trigger["bundle_id"])).stem

    if not out.get("title"):
        if ax_window and ax_window.get("title"):
            out["title"] = str(ax_window["title"])
        elif trigger and trigger.get("window_title"):
            out["title"] = str(trigger["window_title"])

    if not out.get("bundle_id"):
        if ax_app and ax_app.get("bundle_id"):
            out["bundle_id"] = str(ax_app["bundle_id"])
        elif trigger and trigger.get("bundle_id"):
            out["bundle_id"] = str(trigger["bundle_id"])

    return out


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

    ts = _now_iso()
    out: dict[str, Any] = {
        "timestamp": ts,
        "schema_version": 2,
        "trigger": _public_trigger(trigger),
    }

    meta = window_meta.active_window()
    out["window_meta"] = {
        "app_name": meta.app_name,
        "title": meta.title,
        "bundle_id": meta.bundle_id,
    }

    if provider.available:
        # On Windows the helper subprocess can't see the desktop, so we
        # must hand it the foreground HWND/PID. The watcher includes
        # ``hwnd`` in every event it emits — that's the exact window the
        # event came from, eliminating any race vs polling. Heartbeat
        # captures (no trigger) fall back to GetForegroundWindow inside
        # the provider. Mac ignores these hints.
        anchor_hwnd = int((trigger or {}).get("hwnd") or 0)
        anchor_pid = int((trigger or {}).get("pid") or 0)
        result = provider.capture_frontmost(
            focused_window_only=True,
            anchor_hwnd=anchor_hwnd,
            anchor_pid=anchor_pid,
        )
        if result is not None:
            out["ax_tree"] = result.raw_json
            out["ax_metadata"] = result.metadata
    else:
        out["ax_unavailable"] = True

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

    # Backfill empty window_meta fields from the AX tree / trigger so a
    # GetForegroundWindow hiccup on Windows doesn't surface downstream as
    # "Unknown". See _resolve_window_meta for ranking + rationale.
    out["window_meta"] = _resolve_window_meta(
        out["window_meta"], out.get("ax_tree"), trigger,
    )

    s1_parser.enrich(out, trigger=trigger)
    return out


def _write_capture(out: dict[str, Any]) -> Path:
    """Persist a built capture dict to the buffer, index it for search, and log."""
    ts = out["timestamp"]
    path = paths.capture_buffer_dir() / f"{_safe_filename(ts)}.json"
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
        pre_capture_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._provider = provider
        self._pre_capture_hook = pre_capture_hook
        self._lock = threading.Lock()
        self._last_fingerprint: str | None = None
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self._MAX_PENDING)
        self._worker: threading.Thread | None = None

    def start_worker(self) -> None:
        """Spawn the dedicated worker thread. Idempotent."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_loop, name="capture-worker", daemon=True,
        )
        self._worker.start()

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

    def run(self, trigger: dict[str, Any] | None) -> None:
        # Serialize so two near-simultaneous triggers don't double-capture.
        with self._lock:
            try:
                out = _build_capture(self._cfg, self._provider, trigger)
                if out is None:
                    return
                fingerprint = _content_fingerprint(out)
                if fingerprint == self._last_fingerprint:
                    meta = out.get("window_meta") or {}
                    logger.debug(
                        "capture skipped (content dedup): trigger=%s app=%r title=%r",
                        (trigger or {}).get("event_type"),
                        meta.get("app_name"),
                        (meta.get("title") or "")[:60],
                    )
                    return
                self._last_fingerprint = fingerprint
                _write_capture(out)
                if self._pre_capture_hook is not None and trigger is not None:
                    try:
                        self._pre_capture_hook(trigger)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("pre_capture_hook failed: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("capture failed: %s", exc, exc_info=True)

    def run_threaded(self, trigger: dict[str, Any] | None) -> None:
        """Enqueue a capture for the worker thread; drop with a warning if full."""
        try:
            self._queue.put_nowait(trigger)
        except queue.Full:
            logger.warning(
                "capture queue full (%d pending); dropping trigger=%s",
                self._queue.qsize(),
                (trigger or {}).get("event_type") if trigger else "heartbeat",
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
    provider = ax_capture.create_provider(depth=cfg.ax_depth, timeout=cfg.ax_timeout_seconds)
    if not provider.available:
        logger.warning(
            "AX capture unavailable: %s", getattr(provider, "reason", "unknown reason")
        )

    runner = _CaptureRunner(cfg, provider, pre_capture_hook=pre_capture_hook)
    runner.start_worker()
    watcher: EventWatcher | None = None
    dispatcher: EventDispatcher | None = None

    def _on_capture(trigger: dict[str, Any] | None) -> None:
        # Hook firing is deferred into the runner so content-deduped captures
        # (e.g. overnight lock-screen repeats) don't refresh the session timer.
        runner.run_threaded(trigger)

    if cfg.event_driven:
        watcher = create_watcher()
        if watcher.available:
            dispatcher = EventDispatcher(
                _on_capture,
                debounce_seconds=cfg.debounce_seconds,
                min_capture_gap_seconds=cfg.min_capture_gap_seconds,
                dedup_interval_seconds=cfg.dedup_interval_seconds,
                same_window_dedup_seconds=cfg.same_window_dedup_seconds,
            )
            watcher.on_event(dispatcher.on_event)
            watcher.start()
            logger.info("event-driven capture started")
        else:
            logger.warning(
                "AX watcher unavailable — falling back to heartbeat-only captures"
            )

    # One capture immediately so the user sees something in the buffer right away.
    runner.run_threaded(None)

    try:
        if cfg.heartbeat_minutes > 0:
            heartbeat_interval = max(60.0, cfg.heartbeat_minutes * 60.0)
            logger.info(
                "heartbeat capture every %.0fs (event_driven=%s)",
                heartbeat_interval, cfg.event_driven,
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
        logger.warning(
            "captures FTS delete failed for %d stems: %s", len(stems), exc
        )


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
