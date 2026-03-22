class TopologyError(Exception):
    """Base error for topology validation and orchestration failures."""


class ValidationError(TopologyError):
    """Raised when topology input is invalid."""


class ResolutionError(TopologyError):
    """Raised when named capabilities cannot be resolved."""
