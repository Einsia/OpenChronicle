"""RPA harness error types."""

from __future__ import annotations


class RPAError(RuntimeError):
    """Base class for RPA harness failures."""


class ManifestError(RPAError):
    """Raised when a provider manifest is invalid."""


class ProviderError(RPAError):
    """Raised when a provider cannot be loaded or used."""


class WorkflowError(RPAError):
    """Raised when a workflow is invalid or cannot run."""


class RPASafetyError(RPAError):
    """Raised when an RPA action violates safety policy."""
