"""CLI entry point: reduce any pending sessions and classify their entries.

The v2 writer is driven by session boundaries. `SessionManager.on_session_end`
spawns the reducer asynchronously (see ``session/tick.py``), and the
reducer's success callback kicks the classifier. This module exists for the
manual ``openchronicle writer run`` path — it catches up on any
``ended``/``failed`` sessions whose async work didn't finish (e.g. daemon
crashed mid-reduce) and runs the classifier against each.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config
from ..logger import get
from . import classifier as classifier_mod
from . import session_reducer

logger = get("openchronicle.writer")


@dataclass
class WriterRunResult:
    reduced: int = 0
    classified: int = 0
    written_ids: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)


def run(cfg: Config) -> WriterRunResult:
    """Reduce pending sessions, then classify each fresh event-daily entry."""
    result = WriterRunResult()
    if not cfg.reducer.enabled:
        logger.info("writer run: reducer disabled, nothing to do")
        return result

    reduce_results = session_reducer.reduce_all_pending(cfg)
    for rr in reduce_results:
        if not rr.succeeded:
            continue
        result.reduced += 1
        if not (rr.written and rr.entry_id and rr.path and rr.is_final):
            continue
        try:
            cr = classifier_mod.classify_after_reduce(
                cfg,
                session_id=rr.session_id,
                event_daily_path=rr.path,
                just_written_entry_id=rr.entry_id,
                session_start=rr.start_time,
                session_end=rr.end_time,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "classifier %s crashed: %s", rr.session_id, exc, exc_info=True
            )
            continue
        if cr.committed:
            result.classified += 1
            result.written_ids.extend(cr.written_ids)
            if cr.summary:
                result.summaries.append(cr.summary)
    return result
