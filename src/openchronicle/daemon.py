"""Top-level daemon: capture scheduler + timeline aggregator + session cutter.

The v2 writer is driven by session boundaries. ``SessionManager.on_session_end``
(wired in ``session/tick.py``) spawns the S2 reducer on a daemon thread, and
the reducer's success callback kicks the classifier. No periodic writer loop
is needed — each session produces exactly one reducer + classifier pass.
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress

from . import paths
from .capture import scheduler as capture_scheduler
from .config import Config
from .logger import get
from .session import tick as session_tick
from .timeline import tick as timeline_tick

logger = get("openchronicle.daemon")


async def _mcp_loop(cfg: Config) -> None:
    """Host the MCP server inside the daemon. On crash, back off and restart."""
    from .mcp import server as mcp_server

    delay = 2.0
    while True:
        try:
            logger.info("mcp server starting (%s)", cfg.mcp.transport)
            await mcp_server.run_async(cfg)
            logger.info("mcp server exited cleanly")
            return
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            logger.error(
                "mcp server failed to bind %s:%d — %s",
                cfg.mcp.host, cfg.mcp.port, exc,
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp server crashed: %s (restarting in %.0fs)", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


async def _run(cfg: Config, *, capture_only: bool = False) -> None:
    paths.ensure_dirs()
    paths.pid_file().write_text(str(os.getpid()), encoding="utf-8")

    # SessionManager observes every capture-worthy event and fires the
    # reducer via its on_session_end callback. Built even when
    # capture_only is true so session rows still land on disk.
    session_manager = session_tick.build_manager(cfg)

    tasks: list[asyncio.Task] = [
        asyncio.create_task(
            capture_scheduler.run_forever(
                cfg.capture, pre_capture_hook=session_manager.on_event,
            ),
            name="capture",
        ),
        asyncio.create_task(
            session_tick.run_check_cuts(cfg, session_manager), name="session",
        ),
        asyncio.create_task(
            session_tick.run_daily_safety_net(cfg, session_manager),
            name="daily-safety-net",
        ),
    ]
    if not capture_only:
        tasks.append(asyncio.create_task(timeline_tick.run_forever(cfg), name="timeline"))
        tasks.append(
            asyncio.create_task(
                session_tick.run_flush_tick(cfg, session_manager), name="flush",
            )
        )
        tasks.append(
            asyncio.create_task(
                session_tick.run_classifier_tick(cfg, session_manager),
                name="classifier-tick",
            )
        )
    if cfg.mcp.auto_start and cfg.mcp.transport in ("sse", "streamable-http"):
        tasks.append(asyncio.create_task(_mcp_loop(cfg), name="mcp"))

    stop = asyncio.Event()

    def _handle_stop() -> None:
        logger.info("shutdown signal received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handle_stop)

    done_task = asyncio.create_task(stop.wait())
    await asyncio.wait(
        [done_task, *tasks], return_when=asyncio.FIRST_COMPLETED
    )

    for t in tasks:
        t.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.gather(*tasks, return_exceptions=True)

    # Flush the currently open session so its S2 reducer has a chance
    # to run. The daemon-thread reducer spawned by the callback will be
    # killed when the process exits, but a row with status='ended'
    # survives and the next boot's safety-net picks it up.
    with suppress(Exception):
        session_manager.force_end(reason="daemon-shutdown")

    with suppress(FileNotFoundError):
        paths.pid_file().unlink()
    logger.info("daemon stopped")


def run(cfg: Config, *, capture_only: bool = False) -> None:
    asyncio.run(_run(cfg, capture_only=capture_only))
