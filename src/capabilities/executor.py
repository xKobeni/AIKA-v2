from time import perf_counter

from src.capabilities.contracts import (
    LocalActionAuthorization, Permission, ToolExecutionError, ToolInputError, ToolRequest, ToolResult, ToolStatus,
)
from src.capabilities.registry import ToolLookupError, ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, request: ToolRequest, *, authorization: LocalActionAuthorization | None = None) -> ToolResult:
        start = perf_counter()
        permission = None
        validation = "NOT_RUN"

        def result(status, *, data=None, error=None):
            return ToolResult(
                request.tool, status, data, status == ToolStatus.SUCCESS, error,
                permission, validation, (perf_counter() - start) * 1000,
            )

        if not isinstance(request.tool, str):
            validation = "FAIL"
            return result(ToolStatus.INVALID_INPUT, error="Tool name must be a registered string.")
        try:
            tool = self.registry.lookup(request.tool)
        except ToolLookupError as exc:
            return result(exc.status, error=str(exc))
        permission = tool.permission
        allowed_action = (
            permission == Permission.LOCAL_ACTION and tool.name == "app.open"
            and isinstance(authorization, LocalActionAuthorization)
            and authorization.tool == tool.name and isinstance(authorization.app_id, str)
            and request.arguments == {"app_id": authorization.app_id}
            and tool.verify is not None
        )
        if permission != Permission.READ_ONLY and not allowed_action:
            return result(ToolStatus.DENIED, error="This tool's permission category is not enabled.")
        try:
            if not isinstance(request.arguments, dict):
                raise ToolInputError("Tool arguments must be an object.")
            arguments = tool.input_contract(request.arguments)
        except ToolInputError as exc:
            validation = "FAIL"
            return result(ToolStatus.INVALID_INPUT, error=str(exc))
        except Exception:
            validation = "FAIL"
            return result(ToolStatus.EXECUTION_FAILED, error="Tool input validation failed internally.")
        validation = "PASS"
        try:
            data = tool.output_contract(tool.handler(arguments))
            if not isinstance(data, dict):
                raise ValueError("Tool output must be an object.")
            verified = tool.verify(data) if tool.verify is not None else True
            if type(verified) is not bool:
                raise ValueError("Tool verification must be boolean.")
        except ToolExecutionError as exc:
            return result(exc.status, data=exc.data, error=str(exc))
        except Exception:
            message = "Tool execution or output validation failed."
            if allowed_action:
                message += " A launch may have been initiated; check the application before retrying."
            return result(ToolStatus.EXECUTION_FAILED, error=message)
        if not verified:
            return result(ToolStatus.INCONCLUSIVE, data=data, error="Tool execution completed, but verification is inconclusive.")
        return result(ToolStatus.SUCCESS, data=data)
