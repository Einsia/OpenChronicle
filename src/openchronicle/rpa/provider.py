"""Provider contract for OpenChronicle RPA backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RPAProvider(ABC):
    """Abstract interface implemented by every RPA backend."""

    name: str
    platform: str

    @abstractmethod
    def observe(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return current device/application state in a provider-neutral shape."""

    @abstractmethod
    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute one provider action and return a structured result."""

    def run_task(self, task: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Optional high-level task runner for providers that support it."""
        return {
            "ok": False,
            "status": "unsupported",
            "message": f"{self.name} does not implement run_task",
            "task": task,
            "context": context or {},
        }

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """Return supported actions, observation types, and safety limits."""

    def stop(self) -> dict[str, Any]:
        """Stop current task if the provider supports cancellation."""
        return {"ok": True, "status": "stopped", "provider": self.name}
