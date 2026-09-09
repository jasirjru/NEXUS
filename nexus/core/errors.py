"""Typed exceptions used across NEXUS with consistent API error mapping."""


class NexusError(Exception):
    """Base class for all NEXUS errors."""

    code = "nexus_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class ProviderError(NexusError):
    code = "provider_error"


class ValidationError(NexusError):
    code = "validation_error"


class NotFoundError(NexusError):
    code = "not_found"


class ModelNotTrainedError(NexusError):
    code = "model_not_trained"


class ToolDeniedError(NexusError):
    code = "tool_denied"
