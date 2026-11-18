import re

from src.capabilities.applications import APPROVED_APPS
from src.capabilities.contracts import ToolRequest, ToolResult, ToolStatus


ALIASES = {
    "notepad": "notepad", "windows notepad": "notepad",
    "calculator": "calculator", "windows calculator": "calculator", "calc": "calculator",
    "spotify": "spotify",
}


def application_request(prompt: str) -> ToolRequest | None:
    direct = re.fullmatch(r"/open(?:\s+(.*))?", prompt, re.IGNORECASE | re.DOTALL)
    if direct:
        target = direct[1] or ""
    else:
        match = re.fullmatch(
            r"(?:(?:please|can you|could you|would you|i want you to)\s+)*(open|launch|start)\b\s*(.*)",
            prompt, re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            return None
        target = match[2].strip().rstrip(".?!").strip()
        if match[1].casefold() == "start" and re.match(
            r"(?:(?:a|the) )?(?:story|conversation|example|explanation)\b|(?:by|with)\b", target, re.IGNORECASE,
        ):
            return None
        target = re.sub(r"\s+(?:for me(?: please)?|please)$", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^the\s+", "", target.strip(), flags=re.IGNORECASE).casefold()
    if target in {"", "app", "an app", "application", "an application", "it", "that"} or re.search(r"\s+(?:or|and)\s+", target):
        target = ""
    return ToolRequest("app.open", {"app_id": ALIASES.get(target, target)})


def format_application_result(result: ToolResult) -> str:
    if result.data and result.status in {ToolStatus.SUCCESS, ToolStatus.INCONCLUSIVE}:
        name = APPROVED_APPS[result.data["application"]][0]
        if result.status == ToolStatus.SUCCESS and result.verified:
            return f"{name} launch verified: the started process is running (PID {result.data['pid']}). Window readiness was not checked."
        return f"{name} launch initiated, but verification is inconclusive: the launcher exited, and I could not verify the application process or window."
    return f"Application launcher: {result.error or 'No verified launch result is available.'}"
