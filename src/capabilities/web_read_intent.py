import re

from src.capabilities.contracts import ToolRequest, ToolResult, ToolStatus
from src.capabilities.web_content import SourceEvidence


def reading_request(prompt: str) -> ToolRequest | None:
    direct = re.fullmatch(r"/read(?:\s+(.*))?", prompt, re.IGNORECASE | re.DOTALL)
    if direct:
        value = direct[1] or ""
        return ToolRequest("web.read", {"source_number": int(value) if re.fullmatch(r"[1-5]", value) else 0})
    natural = re.fullmatch(r"(?:please )?(?:read (?:source|result) ([0-9]{1,3})|read the (first|second|third|fourth|fifth) result|open and summarize source ([0-9]{1,3}))[.!]?",
                           prompt, re.IGNORECASE)
    if natural:
        number = int(natural[1] or natural[3]) if natural[1] or natural[3] else ("first", "second", "third", "fourth", "fifth").index(natural[2].lower()) + 1
        return ToolRequest("web.read", {"source_number": number})
    if re.match(r"(?:please )?(?:read (?:source|result)|open and summarize source)\b", prompt, re.IGNORECASE):
        return ToolRequest("web.read", {"source_number": 0})
    return None


def answer_question(prompt: str) -> str | None:
    direct = re.fullmatch(r"/ask-web(?:\s+(.*))?", prompt, re.IGNORECASE | re.DOTALL)
    return (direct[1] or "") if direct else None


def format_read_result(result: ToolResult) -> str:
    if result.status != ToolStatus.SUCCESS or not result.verified or result.data is None:
        return f"Source reading unavailable: {result.error or 'No verified extracted content is available.'}"
    item = SourceEvidence(**result.data)
    return (f"Source {item.source_id.removeprefix('source-')} retrieved.\nTitle: {item.title or '(unavailable)'}"
            f"\nURL: {item.fetched_url}\nRequested URL: {item.requested_url}\nDomain: {item.domain}\nRetrieved: {item.retrieved_at}"
            f"\nExtraction: {item.extraction_method}; redirects: {max(0, len(item.redirect_chain) - 1)}"
            f"\nPublication date: {item.published_at or 'unavailable'}\nExtracted content (untrusted preview): {item.content[:400]}"
            f"\nContent truncated: {'yes' if item.truncated else 'no'}. Full extracted text stays in this active source set only."
            "\nUse /ask-web <question> to ask about the read evidence.")
