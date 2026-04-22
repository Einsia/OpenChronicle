"""Periodic tick that builds closed timeline windows into TimelineBlocks.

Wall-clock-aligned so windows always line up at :00/:05/:10/... regardless
of when the tick fires. Idempotent via ``store.has_window`` — safe to
re-run or re-schedule. Runs as an asyncio task inside the daemon.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from ..capture import scheduler as capture_scheduler
from ..config import Config
from ..logger import get
from ..store import fts
from . import aggregator, store

logger = get("openchronicle.timeline")

# How often to wake up and check for new closed windows. Slightly smaller
# than the window length so closed windows are picked up within one window
# of real time.
_TICK_INTERVAL_SECONDS = 60


def _now() -> datetime:
    return datetime.now().astimezone()


def _run_once(cfg: Config) -> int:
    window_minutes = cfg.timeline.window_minutes
    lookback_minutes = cfg.timeline.cold_lookback_minutes
    now = _now()
    current_floor = store.floor_to_window(now, window_minutes)

    with fts.cursor() as conn:
        latest_end = store.get_latest_end(conn)
        if latest_end is None:
            # First run — only build windows within the lookback horizon
            # so we don't LLM-process hours of backfill on startup.
            latest_end = current_floor - timedelta(minutes=lookback_minutes)

        cursor = store.floor_to_window(latest_end, window_minutes)
        if cursor < latest_end:
            cursor = latest_end

        step = timedelta(minutes=window_minutes)
        produced = 0
        while cursor + step <= current_floor:
            window_start = cursor
            window_end = cursor + step
            block = aggregator.produce_block_for_window(
                cfg, conn, start=window_start, end=window_end,
            )
            if block is not None:
                produced += 1
            cursor = window_end
        return produced


async def run_forever(cfg: Config) -> None:
    """Daemon task: every minute, materialise any closed windows."""
    logger.info(
        "timeline loop started (window=%d min, tick=%d s)",
        cfg.timeline.window_minutes, _TICK_INTERVAL_SECONDS,
    )
    while True:
        try:
            produced = await asyncio.to_thread(_run_once, cfg)
            if produced:
                logger.info("timeline: produced %d block(s) this tick", produced)
            # Clean buffer files once the aggregator has absorbed them —
            # safe cutoff is the newest block's end_time.
            try:
                with fts.cursor() as conn:
                    safe_end = store.get_latest_end(conn)
                stats = await asyncio.to_thread(
                    capture_scheduler.cleanup_buffer,
                    cfg.capture.buffer_retention_hours,
                    safe_end.isoformat() if safe_end else None,
                    screenshot_retention_hours=cfg.capture.screenshot_retention_hours,
                    max_mb=cfg.capture.buffer_max_mb,
                )
                if any(stats.values()):
                    logger.info(
                        "timeline: buffer hygiene deleted=%d stripped=%d evicted=%d",
                        stats["deleted"], stats["stripped"], stats["evicted"],
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("timeline: buffer cleanup failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("timeline tick failed: %s", exc, exc_info=True)
        await asyncio.sleep(_TICK_INTERVAL_SECONDS)


def tick_now(cfg: Config) -> int:
    """Synchronous one-shot — for CLI debug. Returns blocks produced."""
    return _run_once(cfg)
