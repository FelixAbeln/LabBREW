class ParameterDBError(Exception):
    """Base shared error for ParameterDB."""


class ProtocolError(ParameterDBError):
    """Malformed or unsupported protocol message."""


class ValidationError(ParameterDBError):
    """Invalid request payload."""


class CommandError(ParameterDBError):
    """Known command/runtime failure."""
