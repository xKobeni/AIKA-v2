import re

from src.capabilities.contracts import Permission, ToolDefinition, ToolStatus


class ToolLookupError(LookupError):
    def __init__(self, status: ToolStatus):
        self.status = status
        super().__init__("Tool is disabled." if status == ToolStatus.DISABLED else "Unknown tool.")


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", tool.name):
            raise ValueError("Invalid tool name.")
        if tool.name in self._tools:
            raise ValueError("Duplicate tool registration.")
        if (not isinstance(tool.permission, Permission) or type(tool.enabled) is not bool
                or (tool.verify is not None and not callable(tool.verify))
                or not tool.description or not all(callable(item) for item in (
                    tool.input_contract, tool.output_contract, tool.handler,
                ))):
            raise ValueError("Invalid tool definition.")
        self._tools[tool.name] = tool

    def lookup(self, name: str) -> ToolDefinition:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolLookupError(ToolStatus.UNKNOWN)
        if not tool.enabled:
            raise ToolLookupError(ToolStatus.DISABLED)
        return tool

    def list_tools(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools.values())
