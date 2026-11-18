from time import perf_counter
import json

from src.capabilities.contracts import (
    LocalActionAuthorization, Permission, ToolExecutionError, ToolInputError, ToolRequest, ToolResult, ToolStatus,
)
from src.capabilities.registry import ToolLookupError, ToolRegistry
from src.capabilities.web_diagnostics import record


MAX_TOOL_OUTPUT_BYTES = 128 * 1024


def bounded_output(data):
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(data):
        if len(chunk) > MAX_TOOL_OUTPUT_BYTES:
            raise ToolExecutionError("Tool result exceeded the output limit.")
        size += len(chunk.encode("utf-8"))
        if size > MAX_TOOL_OUTPUT_BYTES:
            raise ToolExecutionError("Tool result exceeded the output limit.")


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, *, web_debug: bool = False):
        self.registry = registry
        self.web_debug = web_debug

    def execute(self, request: ToolRequest, *, authorization: LocalActionAuthorization | None = None) -> ToolResult:
        start = perf_counter()
        permission = None
        validation = "NOT_RUN"

        def result(status, *, data=None, error=None, category=None):
            if data is not None:
                try:
                    bounded_output(data)
                except Exception:
                    status, data, category = ToolStatus.EXECUTION_FAILED, None, "result_size"
                    error = "Tool result could not be retained within its output limit."
                    if permission == Permission.LOCAL_ACTION:
                        error += " An action may have been initiated; check its state before retrying."
            return ToolResult(
                request.tool, status, data, status == ToolStatus.SUCCESS, error,
                permission, validation, (perf_counter() - start) * 1000, category,
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
            return result(ToolStatus.EXECUTION_FAILED, error="Tool input validation failed internally.", category="input_internal")
        validation = "PASS"
        phase = "internal"
        try:
            data = tool.handler(arguments)
            phase = "contract"
            try:
                bounded_output(data)
            except ToolExecutionError:
                message = "Tool result exceeded the output limit."
                if allowed_action:
                    message += " A launch may have been initiated; check the application before retrying."
                return result(ToolStatus.EXECUTION_FAILED, error=message, category="result_size")
            data = tool.output_contract(data)
            if not isinstance(data, dict):
                raise ValueError("Tool output must be an object.")
            verified = tool.verify(data) if tool.verify is not None else True
            if type(verified) is not bool:
                raise ValueError("Tool verification must be boolean.")
        except ToolExecutionError as exc:
            if tool.name in {"web.search", "web.read"}:
                record(self.web_debug, getattr(exc, "stage", phase), "controlled_failure", start)
            return result(exc.status, data=exc.data, error=str(exc), category=getattr(exc, "code", getattr(exc, "kind", None)))
        except TimeoutError:
            message = "Tool operation timed out. No retry was made."
            if allowed_action:
                message += " A launch may have been initiated; check the application before retrying."
            return result(ToolStatus.EXECUTION_FAILED, error=message, category="timeout")
        except Exception:
            message = "Tool execution or output validation failed."
            if tool.name in {"web.search", "web.read"}:
                record(self.web_debug, phase, "unexpected_failure", start)
                message = "Web tool output contract validation failed." if phase == "contract" else "Web tool execution failed internally."
                return result(ToolStatus.EXECUTION_FAILED, error=message, category=phase)
            if allowed_action:
                message += " A launch may have been initiated; check the application before retrying."
            return result(ToolStatus.EXECUTION_FAILED, error=message, category=phase)
        if not verified:
            return result(ToolStatus.INCONCLUSIVE, data=data, error="Tool execution completed, but verification is inconclusive.")
        if tool.name in {"web.search", "web.read"}:
            record(self.web_debug, "contract", "success", start)
        return result(ToolStatus.SUCCESS, data=data)
