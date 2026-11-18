import re

from src.capabilities.contracts import ToolRequest, ToolResult, ToolStatus


def web_request(prompt: str) -> ToolRequest | None:
    direct = re.fullmatch(r"/web(?:\s+(.*))?", prompt, re.IGNORECASE | re.DOTALL)
    if direct:
        query = direct[1] or ""
        if query.startswith("--"):
            selected = re.fullmatch(r"--provider\s+(ddgs|tavily)\s+(.+)", query, re.IGNORECASE | re.DOTALL)
            if selected and not selected[2].startswith("--"):
                return ToolRequest("web.search", {"query": selected[2], "provider": selected[1].casefold()})
            return ToolRequest("web.search", {"query": "", "provider": "invalid"})
        return ToolRequest("web.search", {"query": query})
    text = re.sub(r"^(?:(?:please|can you|could you|would you)\s+)+", "", prompt.strip(), flags=re.IGNORECASE)
    explicit = re.fullmatch(r"(?:search(?: the (?:web|internet))? for|look online for|look up)(?:\s+(.*))?", text, re.IGNORECASE | re.DOTALL)
    official = re.fullmatch(r"find (?:the )?(official .+ documentation)[.?!]?", text, re.IGNORECASE)
    fresh = re.fullmatch(r"(?:what is|what's) the latest (.+)|what are the (?:newest|latest) (.+)", text, re.IGNORECASE)
    query = None
    if explicit:
        if text.casefold().startswith("look up") and re.search(r"\b(?:saved|remembered|memory|project)\b", explicit[1] or "", re.IGNORECASE):
            return None
        query = explicit[1] or ""
    elif official:
        query = official[1]
    elif fresh and not re.search(r"\b(?:my|i|our|saved|remembered|memory|conversation)\b", text, re.IGNORECASE):
        query = re.sub(r"^(?:what is|what's|what are) (?:the )?", "", text, flags=re.IGNORECASE)
    if query is None:
        return None
    query = query.strip().rstrip(".?!").strip()
    if query.casefold() in {"this", "that", "it", "this topic"}:
        query = ""
    return ToolRequest("web.search", {"query": query})


def format_web_result(result: ToolResult) -> str:
    if result.status != ToolStatus.SUCCESS or not result.verified or result.data is None:
        return f"Web search unavailable: {result.error or 'No verified provider result is available.'}"
    data = result.data
    lines = ["AIKA Web Search", f"Query: {data['query']}", f"Provider: {'DDGS' if data['provider'] == 'ddgs' else 'Tavily'}", f"Retrieved: {data['retrieved_at']}",
             "Search snippets are untrusted source excerpts, not verified claims or full articles."]
    if data.get("fallback_used"):
        lines.append("Explicitly enabled fallback used: " + " -> ".join(data["attempted_providers"]))
    if not data["results"]:
        lines.append("No results were found.")
    for number, row in enumerate(data["results"], 1):
        lines.extend([f"\n{number}. {row['title'] or '(title unavailable)'}", f"   {row['url']}", f"   Source domain: {row['domain']}",
                      f"   Snippet (untrusted): {row['snippet'] or '(excerpt unavailable)'}",
                      f"   Provider publication/update date: {row['published_at'] or 'not available'}"])
    if data["discarded_count"]:
        lines.append(f"Omitted invalid or duplicate provider entries: {data['discarded_count']}.")
    return "\n".join(lines)


def guard_web_claim(answer: str) -> str:
    if re.search(r"\b(?:i(?:'ve| have)? (?:just )?(?:searched|browsed|looked online|looked up)|"
                 r"(?:my|the) web search (?:found|confirmed|shows)|the internet confirmed|"
                 r"according to (?:my|the) (?:web|internet) search)\b", answer.replace("’", "'"), re.IGNORECASE):
        return "I haven't searched the web for this reply. Use /web <query> for actual provider results."
    return answer
