from src.capabilities.calculator import calculator_tool
from src.capabilities.applications import ApplicationRegistry, application_tool, create_applications
from src.capabilities.registry import ToolRegistry
from src.capabilities.system_info import system_tools
from src.capabilities.web_search import DDGSSearchProvider, SearchRouter, TavilySearchProvider, web_search_tool
from src.capabilities.web_reader import WebReader, web_read_tool


def create_registry(applications: ApplicationRegistry | None = None, web_search: SearchRouter | TavilySearchProvider | DDGSSearchProvider | None = None,
                    web_reader: WebReader | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(calculator_tool())
    registry.register(application_tool(applications if applications is not None else create_applications()))
    for tool in system_tools():
        registry.register(tool)
    registry.register(web_search_tool(web_search if web_search is not None else SearchRouter()))
    registry.register(web_read_tool(web_reader if web_reader is not None else WebReader()))
    return registry
