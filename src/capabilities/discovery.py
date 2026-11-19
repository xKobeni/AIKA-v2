"""Read-only presentation of the existing registry and session configuration."""

import re

from src.capabilities.application_intent import ALIASES, application_question
from src.capabilities.contracts import Permission, ToolExecutionError, ToolInputError
from src.capabilities.registry import ToolLookupError
from src.capabilities.language import natural_text
from src.capabilities.desktop_intent import desktop_question
from src.capabilities.system_info import initialize_measurements


COMMANDS = {"calculator.evaluate": "/calc 12*7", "app.open": "/apps; /open notepad",
            "system.snapshot": "/system", "system.processes": "/processes",
            "web.search": "/web <query>", "web.read": "/read 1", "desktop.context": "/desktop-context [--status|--enable|--disable]"}


def capability_lines(session) -> dict[str, str]:
    lines = {}
    for tool in session.tools.registry.list_tools():
        status = "LOCALLY READY" if tool.enabled else "DISABLED"
        detail = ""
        if tool.enabled:
            if tool.name == "desktop.context":
                status = "ENABLED; Windows API availability not tested"
                detail = " Explicit requests only; no background observation, stored activity or screen content."
            if tool.permission != Permission.READ_ONLY and not (tool.permission == Permission.LOCAL_ACTION and tool.name == "app.open" and tool.verify is not None):
                status = "UNAVAILABLE (permission category is not enabled)"
            elif tool.name.startswith("system."):
                try:
                    initialize_measurements()
                except ToolExecutionError:
                    status = "UNAVAILABLE (Windows/measurement dependency)"
            elif tool.name == "web.search":
                status = ("DISABLED" if not session.web_search.enabled else
                          "UNAVAILABLE" if session.web_search.unavailable_reason() else "ENABLED; locally ready")
                mode = getattr(session.web_search, "mode", getattr(session.web_search, "name", "configured"))
                fallback = "ENABLED" if getattr(session.web_search, "fallback_enabled", False) else "DISABLED"
                detail = f" Provider: {mode}; fallback configured: {fallback}. Provider policy is unchanged by this command."
            elif tool.name == "web.read":
                status = "ENABLED" if session.web_reader.enabled and session.web_reader.network_enabled else "DISABLED"
                detail = " Requires a selected search result and separate reading/network gates."
            elif tool.name == "app.open":
                apps = session.applications.list_apps()
                ready = [app.display_name for app in apps if app.enabled and session.applications.availability(app) == "AVAILABLE"]
                status = "LOCALLY READY" if ready else "UNAVAILABLE (no ready approved targets)"
                detail = " Approved targets only; use /apps for individual readiness. Cannot execute arbitrary programs."
        lines[tool.name] = f"{tool.name}: {status} [{tool.permission}]. {tool.description}{detail} {COMMANDS.get(tool.name, '')}"
    return lines


def capabilities(session) -> str:
    lines = capability_lines(session)
    enabled = {tool.name: tool.enabled and tool.permission == Permission.READ_ONLY
               for tool in session.tools.registry.list_tools()}
    research = (enabled.get("web.search", False) and enabled.get("web.read", False)
                and session.web_search.enabled and session.web_search.unavailable_reason() is None
                and session.web_reader.enabled and session.web_reader.network_enabled)
    return "\n".join([
        "AIKA Capabilities",
        "Local Ollama conversation: configured through the existing client; connectivity/model inference not tested here.",
        "Conversation history: configured; SQLite writes are verified when committed.",
        f"Explicit structured memory: {'CONFIGURED' if session._memory is not None else 'UNAVAILABLE in this session'}; no automatic fact saving.",
        *lines.values(),
        f"Research: {'ENABLED; locally ready' if research else 'UNAVAILABLE'} (/research <question>); bounded search/read/evidence workflow.",
        "Controlled agent: /agent <task>; maximum four steps/eight executions; existing permissions and budgets apply.",
        "Verified percentage dataflow and immediate conditional checks require system.snapshot and calculator.evaluate to be ready.",
        "Readiness is local configuration, not verified live execution. No model, network, measurement or launch was requested by this listing.",
        "Provider connectivity, authentication and remaining credits have not been tested.",
        "No general file deletion, shell execution, private-file access, window control, screen recording, voice or background monitoring.",
    ])


def capability_answer(prompt, session):
    if desktop_question(prompt):
        return session.desktop_context_status()
    text = natural_text(prompt).casefold()
    if text in {"/capabilities", "what can you do", "what tools do you have"}:
        return capabilities(session)
    target = application_question(prompt)
    if target is not None:
        if target in {"applications", "apps"}:
            return capability_lines(session).get("app.open", "Application launching is not registered.") + " Window readiness is not guaranteed."
        if target.endswith(" now"):
            return 'Do you want me to launch an approved application now? Say "Open Notepad now" to request a launch.'
        try:
            tool = session.tools.registry.lookup("app.open")
            app = session.applications.lookup(ALIASES.get(target, target))
        except ToolLookupError:
            return "The approved application launcher is unavailable or disabled. No launch was attempted."
        except ToolInputError:
            return "That application is not in the approved launcher set. Use /apps to see supported targets. No launch was attempted."
        if (tool.permission != Permission.LOCAL_ACTION or tool.verify is None or not app.enabled
                or session.applications.availability(app) != "AVAILABLE"):
            return f"{app.display_name} is an approved application, but launching it is currently unavailable or disabled. No launch was attempted."
        return (f'Yes, I can launch {app.display_name} through the approved Windows app launcher. '
                f'You can say "Open {app.display_name}" to launch it. Window readiness is not guaranteed.')
    question = re.sub(r"^(?:(?:hey )?aika[, :]\s*)?(?:please )?", "", " ".join(prompt.split()), flags=re.I)
    if not re.match(r"^(?:can|could) you\b", question, re.I):
        return None
    if text in {"browse the web", "search the web", "access the internet"}:
        lines = capability_lines(session)
        return lines.get("web.search", "Web search is not registered.") + "\n" + lines.get("web.read", "Source reading is not registered.") + "\nLive connectivity has not been tested."
    if text in {"remember information", "save information"}:
        return ("Explicit structured memory is configured. Use 'Remember that Orion uses SvelteKit.' Saves are reported only after commit; ordinary chat does not automatically save facts."
                if session._memory is not None else "Structured memory is unavailable in this session.")
    if text in {"control my computer", "open applications", "open apps"}:
        return capability_lines(session).get("app.open", "Application launching is not registered.") + " No arbitrary desktop or window control. Launch readiness is not live execution."
    if text in {"check my system", "access my system information"}:
        return capability_lines(session).get("system.snapshot", "System information is not registered.") + " Use /system for an actual measurement; GPU details and temperature are not measured."
    if text == "delete files":
        return "AIKA does not currently have a general file-deletion capability. No files were modified."
    return None


def clarification(prompt):
    text = natural_text(prompt).casefold()
    if text in {"open it", "open that", "open an app", "open application", "open"}:
        return "Which registered application should I open? Use /apps to see the list."
    if text in {"check the latest version", "what's the latest version", "what is the latest version"}:
        return "Which product's latest version should I check?"
    if text in {"show me the information", "show the information"}:
        return "Which information should I show: system information, saved project facts, or web sources?"
    return None


def unsupported_request(prompt):
    text = natural_text(prompt).casefold()
    if re.match(r"(?:delete|remove)\b.*\b(?:downloads|files|folder|everything)\b", text):
        return "AIKA does not currently support general file deletion. No files were modified."
    if re.match(r"(?:run|execute)\b.*\b(?:powershell|shell|command)\b|install\b|read all my private files\b|control (?:every|all)\b|record my screen\b", text):
        return "That operation is not implemented in the current capabilities. No action was executed."
    return None
