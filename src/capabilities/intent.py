import re

from src.capabilities.language import natural_text
from src.capabilities.contracts import ToolRequest, ToolResult, ToolStatus


def calculator_request(prompt: str) -> ToolRequest | None:
    direct = re.fullmatch(r"/calc(?:\s+(.*))?", prompt, re.IGNORECASE | re.DOTALL)
    if direct:
        return ToolRequest("calculator.evaluate", {"expression": direct[1] or ""})
    prompt = natural_text(prompt)
    explicit = re.fullmatch(r"(?:please\s+)?(?:calculate|compute|evaluate|work out)\b\s*(.*)", prompt, re.IGNORECASE | re.DOTALL)
    question = re.fullmatch(r"(?:what is|what's)\s+(.+)", prompt, re.IGNORECASE | re.DOTALL)
    text = explicit[1] if explicit else question[1] if question else prompt
    text = text.strip().removesuffix("?").removesuffix(".").strip()
    if not explicit and not re.match(r"[+\-.(]*[0-9]", text):
        return None
    for phrase, symbol in (
        ("multiplied by", "*"), ("divided by", "/"), ("times", "*"), ("plus", "+"), ("minus", "-"),
    ):
        text = re.sub(rf"\b{phrase}\b", symbol, text, flags=re.IGNORECASE)
    text = text.replace("×", "*").replace("÷", "/").replace("−", "-")
    text = re.sub(r"\bpercent\s+of\b", "% of", text, flags=re.I)
    if not explicit and not re.fullmatch(r"[0-9.\s()+*/%\-]+(?:of\s+[+\-]?[0-9.]+)?", text, re.IGNORECASE):
        return None
    if not explicit and not question and not re.search(r"[+*/%\-]", text.lstrip("+-")):
        return None
    return ToolRequest("calculator.evaluate", {"expression": text})


def format_result(result: ToolResult) -> str:
    if result.status == ToolStatus.SUCCESS and result.verified and result.data is not None:
        return result.data["result"]
    return f"Calculator error: {result.error or 'No verified result is available.'}"


def unsupported_action(prompt: str) -> bool:
    text = re.sub(r"^(?:(?:please|can you|could you|would you|i want you to)\s+)+", "", prompt, flags=re.IGNORECASE)
    return bool(re.match(r"(?:open|launch|close|execute|install|browse)\b", text, re.IGNORECASE) or re.match(
        r"(?:start|run)\s+(?!(?:(?:a |the )?(?:story|conversation|example|explanation)|by|with|through|me through)\b).+", text, re.IGNORECASE,
    ) or re.match(r"(?:delete|remove|move|rename|create|edit|modify|save|read|write)\b.*"
                 r"(?:\b(?:file|folder|directory|disk)\b|[A-Za-z]:[\\/]|\.[a-z0-9]{1,8}\b)", text, re.IGNORECASE)
        or re.match(r"(?:search (?:the )?(?:web|internet)|send (?:an? |the )?(?:email|message))\b", text, re.IGNORECASE))


def guard_action_claim(answer: str) -> str:
    if re.search(
        r"\b(?:i (?:used|ran|executed|called) (?:the )?(?:calculator|tool)|"
        r"(?:calculator|tool) (?:returned|produced|verified)|verified (?:calculator|tool) result)\b",
        answer.replace("’", "'"), re.IGNORECASE,
    ):
        return "I haven't executed a tool for this reply. Use /calc <expression> for a verified calculator result."
    if re.search(
        r"\b(?:i(?:'ve| have)? (?:just |successfully )?(?:opened|launched|started|closed|ran|executed|"
        r"deleted|removed|moved|renamed|created|edited|modified|sent|installed)|"
        r"(?:opened|launched|executed) successfully|"
        r"\w+ (?:has been|was) (?:opened|launched)|\w+ is now (?:open|running)|"
        r"(?:notepad|(?:windows )?calculator|spotify) (?:(?:has been|was|is(?: now)?) )?"
        r"(?:successfully )?(?:open(?:ed)?|launched|running|started)|"
        r"(?:opened|launched|started) (?:the )?(?:notepad|(?:windows )?calculator|spotify)|"
        r"i(?:'ll| will| am|'m) (?:open|launch|opening|launching) (?:the )?(?:notepad|(?:windows )?calculator|spotify))\b",
        answer.replace("’", "'"), re.IGNORECASE,
    ):
        return "I haven't performed a desktop action for this reply. Use /open with an approved application for an actual launch attempt."
    return answer
