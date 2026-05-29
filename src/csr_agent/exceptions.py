"""Project-specific exceptions."""


class CSRConfigError(ValueError):
    """Raised when configuration files are invalid."""


class ContractValidationError(ValueError):
    """Raised when runtime contract checks fail."""


class ToolExecutionError(RuntimeError):
    """Raised when a tool operation fails."""


class AgentExecutionError(RuntimeError):
    """Raised when an agent cannot complete its action."""
