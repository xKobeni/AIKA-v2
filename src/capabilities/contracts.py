from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Permission(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOCAL_ACTION = "LOCAL_ACTION"
    SENSITIVE_ACTION = "SENSITIVE_ACTION"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    INVALID_INPUT = "invalid_input"
    DENIED = "denied"
    EXECUTION_FAILED = "execution_failed"
    UNKNOWN = "unknown_tool"
    DISABLED = "disabled_tool"
    UNAVAILABLE = "unavailable"
    INCONCLUSIVE = "inconclusive"


class ToolInputError(ValueError):
    """A validation message safe for display, without private input values."""


class ToolExecutionError(ValueError):
    """A controlled execution failure safe for display."""

    def __init__(self, message: str, *, status: ToolStatus = ToolStatus.EXECUTION_FAILED, data: dict | None = None):
        if status not in {ToolStatus.EXECUTION_FAILED, ToolStatus.UNAVAILABLE, ToolStatus.DISABLED}:
            raise ValueError("Invalid execution failure status.")
        super().__init__(message)
        self.status = status
        self.data = data


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LocalActionAuthorization:
    """Trusted caller evidence bound to one explicit application request; never model input."""

    tool: str
    app_id: str


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_contract: Callable[[dict[str, Any]], dict[str, Any]]
    output_contract: Callable[[Any], dict[str, Any]]
    permission: Permission
    handler: Callable[[dict[str, Any]], Any]
    enabled: bool = True
    verify: Callable[[dict[str, Any]], bool] | None = None


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: ToolStatus
    data: dict[str, Any] | None = None
    verified: bool = False
    error: str | None = None
    permission: Permission | None = None
    validation: str = "NOT_RUN"
    elapsed_ms: float = 0.0
    failure_category: str | None = None
