"""Mock observer used by the RPA recorder MVP."""

from __future__ import annotations

from .schemas import StepSnapshot


class MockObserver:
    """Return deterministic snapshot metadata without talking to a real device."""

    def observe(
        self,
        *,
        session_id: str,
        step_id: str,
        phase: str,
        action: str,
    ) -> StepSnapshot:
        return StepSnapshot(
            screenshot=f"screens/{session_id}/{step_id}_{phase}.png",
            ui_tree=f"ui/{session_id}/{step_id}_{phase}.xml",
            ocr_text=[f"{phase}:{action}", "mock"],
            screen_state=f"{phase}_{action}_screen",
        )
