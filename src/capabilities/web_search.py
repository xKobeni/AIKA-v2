import importlib
import ipaddress
import json
import math
import logging
import os
import re
from importlib.metadata import version
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic
from urllib.parse import unquote, urlsplit, urlunsplit

from src.capabilities.contracts import Permission, ToolDefinition, ToolExecutionError, ToolInputError, ToolStatus
from src.config import valid_tavily_key
from src.capabilities.web_diagnostics import WebFailure
from src.capabilities.web_budget import bounded_timeout


ENDPOINT = "https://api.tavily.com/search"
MAX_RESULTS = 5
MAX_RESPONSE_BYTES = 512 * 1024
READ_BUDGET = 15.0
REDACTED = "[API key redacted]"
KEY_TEXT = re.compile(r"\btvly-[A-Za-z0-9._~-]+", re.IGNORECASE)


class SearchProviderError(ToolExecutionError):
    """Controlled provider failure; only named transient categories permit fallback."""

    def __init__(self, message: str, kind: str, *, status=ToolStatus.EXECUTION_FAILED):
        super().__init__(message, status=status)
        self.stage = "provider"
        self.kind = kind


def redact(text: str, key: str = "") -> str:
    return KEY_TEXT.sub(REDACTED, text.replace(key, REDACTED) if key else text)


def _httpx():
    try:
        return importlib.import_module("httpx")
    except ImportError:
        raise ToolExecutionError("HTTPX is unavailable. Install project dependencies with python -m pip install -e .", status=ToolStatus.UNAVAILABLE) from None


def _open_client(httpx):
    return httpx.Client(timeout=httpx.Timeout(bounded_timeout(5.0), connect=bounded_timeout(3.0), write=bounded_timeout(3.0), pool=bounded_timeout(3.0)),
                        trust_env=False, follow_redirects=False)


def _clean(value: str, limit: int) -> str:
    return " ".join("".join(char if char.isprintable() else " " for char in value).split())[:limit].rstrip()


def _source_url(value: object, api_key: str = "") -> tuple[str, str] | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return None
    decoded = unquote(value)
    if (any(not char.isprintable() or char.isspace() for char in value) or "\\" in value
            or any(not char.isprintable() for char in decoded) or KEY_TEXT.search(decoded)
            or (api_key and (api_key in value or api_key in decoded))):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None or not host:
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or host.rsplit(".", 1)[-1].isdigit() or host.endswith((".local", ".localhost", ".internal"))
                    or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))):
                return None
        else:
            if not address.is_global:
                return None
        netloc = f"[{host}]" if ":" in host else host
        if port is not None and port != (443 if parsed.scheme == "https" else 80):
            if port == 0:
                return None
            netloc += f":{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, "")), host
    except (ValueError, UnicodeError):
        return None


def _published(value) -> str | None:
    if not isinstance(value, str) or len(value) > 80 or not value.isprintable():
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return value


def validate_arguments(arguments: dict) -> dict:
    query, count = arguments.get("query"), arguments.get("max_results", MAX_RESULTS)
    if (set(arguments) - {"query", "max_results", "provider"} or not isinstance(query, str)
            or not query.strip() or len(query) > 300 or not query.isprintable()):
        raise ToolInputError("Provide a specific web-search query of 1 to 300 printable characters, without extra options.")
    if type(count) is not int or not 1 <= count <= MAX_RESULTS:
        raise ToolInputError("Web search requires max_results from 1 through 5.")
    if REDACTED in query or KEY_TEXT.search(query):
        raise ToolInputError("Search queries cannot contain API credentials.")
    selected = arguments.get("provider")
    if "provider" in arguments and (not isinstance(selected, str) or selected not in {"ddgs", "tavily"}):
        raise ToolInputError("Select provider ddgs or tavily, without other provider flags.")
    return {"query": query.strip(), "max_results": count, **({"provider": selected} if selected else {})}


@dataclass(frozen=True)
class TavilySearchProvider:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    name = "tavily"

    def redact(self, text: str) -> str:
        return redact(text, self.api_key)

    def unavailable_reason(self) -> str | None:
        if type(self.enabled) is not bool or not valid_tavily_key(self.api_key):
            return "Web-search configuration is invalid."
        if ENDPOINT != "https://api.tavily.com/search":
            return "The fixed Tavily endpoint configuration is invalid."
        if not self.enabled:
            return "Web search is disabled. Enable AIKA_WEB_SEARCH_ENABLED explicitly to send queries to Tavily."
        if not self.api_key:
            return "Web search requires AIKA_TAVILY_API_KEY. No provider request was made."
        try:
            _httpx()
        except ToolExecutionError as exc:
            return str(exc)
        return None

    def search(self, query: str, max_results: int) -> dict:
        arguments = validate_arguments({"query": query, "max_results": max_results})
        if self.api_key and self.api_key in query:
            raise ToolInputError("Search queries cannot contain API credentials.")
        reason = self.unavailable_reason()
        if reason:
            raise SearchProviderError(reason, "unavailable", status=ToolStatus.UNAVAILABLE)
        httpx = _httpx()
        payload = {**arguments, "search_depth": "basic", "topic": "general", "auto_parameters": False,
                   "include_answer": False, "include_raw_content": False, "include_images": False}
        deadline = monotonic() + bounded_timeout(READ_BUDGET)
        try:
            with _open_client(httpx) as client:
                with client.stream("POST", ENDPOINT, json=payload,
                                   headers={"Authorization": f"Bearer {self.api_key}", "Accept-Encoding": "identity"}) as response:
                    status = response.status_code
                    if status != 200:
                        if status in {401, 403}:
                            kind = "authentication"
                            message = "Tavily authentication or access was denied. Check the configured key."
                        elif status == 429:
                            kind = "rate_limited"
                            message = "Tavily rate limit reached. No automatic retry was made."
                        elif status in {402, 432, 433}:
                            kind = "quota"
                            message = "Tavily quota or billing limit reached. Check your account; AIKA will not change billing settings."
                        elif status in {400, 422}:
                            kind = "rejected"
                            message = "Tavily rejected the bounded search request."
                        elif status >= 500:
                            kind = "unavailable"
                            message = "Tavily is temporarily unavailable due to a provider error."
                        else:
                            kind = "invalid_response"
                            message = "Tavily returned an unexpected HTTP status. Redirects are not followed."
                        raise SearchProviderError(message, kind)
                    length = response.headers.get("Content-Length")
                    if length is not None and (not length.isdecimal() or int(length) > MAX_RESPONSE_BYTES):
                        raise WebFailure("Tavily response exceeds the size limit or has an invalid size header.", "provider", "response_size")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise WebFailure("Tavily returned an unsupported encoded response.", "provider", "response_encoding")
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        if monotonic() > deadline:
                            raise WebFailure("Tavily response exceeded the total read budget.", "provider", "response_budget")
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise WebFailure("Tavily response exceeds the size limit.", "provider", "response_size")
                        body.extend(chunk)
                    if monotonic() > deadline:
                        raise WebFailure("Tavily response exceeded the total read budget.", "provider", "response_budget")
        except httpx.TimeoutException:
            raise SearchProviderError("Tavily search timed out. No automatic retry was made.", "timeout") from None
        except httpx.RequestError:
            raise SearchProviderError("Tavily could not be reached because of a network, DNS, or TLS failure. No automatic retry was made.", "unavailable") from None
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise WebFailure("Tavily returned malformed JSON.", "provider", "response_json") from None
        if not isinstance(data, dict) or "error" in data or "detail" in data or not isinstance(data.get("results"), list) or len(data["results"]) > 50:
            raise WebFailure("Tavily returned an invalid search response.", "provider", "response_shape")
        return normalize_results(data["results"], arguments["query"], max_results, self.name, self.api_key)


def normalize_results(rows: list, query: str, limit: int, provider: str, key: str = "") -> dict:
    if not isinstance(rows, list) or len(rows) > 50:
        raise WebFailure("Search normalization failed: invalid or oversized result list.", "normalization", "invalid_result_list")
    # Ignore malformed optional metadata before serialization; native provider values need not be JSON types.
    rows = [{**{name: row.get(name) if isinstance(row.get(name), str) else None
                for name in ("url", "title", "content", "published_date")},
             "score": row.get("score") if type(row.get("score")) in (int, float) and 0 <= row["score"] <= 1 else None}
            if isinstance(row, dict) else None for row in rows]
    if (sum(len(value) for row in rows if isinstance(row, dict) for value in row.values() if isinstance(value, str)) > MAX_RESPONSE_BYTES
            or len(json.dumps(rows, ensure_ascii=True).encode("utf-8")) > MAX_RESPONSE_BYTES):
        raise WebFailure("Search normalization failed: oversized result content.", "normalization", "oversized_result_content")
    retrieved = datetime.now(UTC).isoformat()
    results, seen, discarded = [], set(), 0
    for rank, raw in enumerate(rows, 1):
        source = _source_url(raw.get("url"), key) if isinstance(raw, dict) else None
        if not source or source[0] in seen:
            discarded += 1
            continue
        seen.add(source[0])
        title = _clean(redact(raw["title"], key), 200) if isinstance(raw.get("title"), str) else None
        snippet = _clean(redact(raw["content"], key), 1000) if isinstance(raw.get("content"), str) else None
        score = raw.get("score")
        if type(score) not in (int, float) or not 0 <= score <= 1 or not math.isfinite(score):
            score = None
        results.append({"title": title or None, "url": source[0], "domain": source[1], "snippet": snippet or None,
                        "published_at": _published(redact(raw["published_date"], key)) if isinstance(raw.get("published_date"), str) else None,
                        "rank": rank, "score": score, "retrieved_at": retrieved, "provider": provider})
        if len(results) == limit:
            break
    if rows and not results:
        raise WebFailure("Search normalization failed: no usable source entries; this is not a verified empty search.", "normalization", "no_usable_sources")
    return {"query": query, "provider": provider, "retrieved_at": retrieved, "results": results, "discarded_count": discarded}


def _ddgs_dependencies():
    try:
        if version("ddgs") != "9.16.1":
            raise ImportError("Unaudited DDGS version")
        module = importlib.import_module("ddgs")
        engines = importlib.import_module("ddgs.engines").ENGINES
        if not any(not engine.disabled for engine in engines.get("text", {}).values()):
            raise ImportError("Missing text backends")
        errors = importlib.import_module("ddgs.exceptions")
    except (ImportError, AttributeError, OSError):
        raise SearchProviderError("DDGS 9.16.1 and its text backends are unavailable. Install the project dependencies.", "unavailable", status=ToolStatus.UNAVAILABLE) from None
    # The library can log request exceptions containing query text; silence its namespace.
    logging.getLogger("ddgs").setLevel(logging.CRITICAL + 1)
    for name in ("ddgs", *tuple(logging.Logger.manager.loggerDict)):
        if name == "ddgs" or name.startswith("ddgs."):
            logging.getLogger(name).disabled = True
    return module, errors


def _open_ddgs():
    module, _ = _ddgs_dependencies()
    return module.DDGS(timeout=bounded_timeout(5), verify=True)


@dataclass(frozen=True)
class DDGSSearchProvider:
    enabled: bool = False
    redaction_key: str = field(default="", repr=False)
    name = "ddgs"

    def redact(self, text: str) -> str:
        return redact(text, self.redaction_key)

    def unavailable_reason(self) -> str | None:
        if type(self.enabled) is not bool:
            return "Web-search configuration is invalid."
        if not self.enabled:
            return "Web search is disabled. Enable AIKA_WEB_SEARCH_ENABLED explicitly to send queries externally."
        if os.environ.get("DDGS_PROXY"):
            return "DDGS_PROXY is unsupported in this audited configuration; no query was sent."
        try:
            _ddgs_dependencies()
        except SearchProviderError as exc:
            return str(exc)
        return None

    def search(self, query: str, max_results: int) -> dict:
        checked = validate_arguments({"query": query, "max_results": max_results})
        if self.redaction_key and self.redaction_key in query:
            raise ToolInputError("Search queries cannot contain API credentials.")
        reason = self.unavailable_reason()
        if reason:
            raise SearchProviderError(reason, "unavailable", status=ToolStatus.UNAVAILABLE)
        _, errors = _ddgs_dependencies()
        try:
            with _open_ddgs() as client:
                rows = client.text(checked["query"], max_results=max_results, backend="auto", page=1)
        except SearchProviderError:
            raise
        except Exception as exc:
            nested = exc.args[0] if exc.args and isinstance(exc.args[0], Exception) else exc
            if isinstance(nested, errors.TimeoutException):
                raise SearchProviderError("DDGS search timed out. No retry was made.", "timeout") from None
            if isinstance(nested, errors.RatelimitException):
                raise SearchProviderError("DDGS search was rate-limited. No retry was made.", "rate_limited") from None
            if type(nested) is errors.DDGSException and nested.args == ("No results found.",):
                # DDGS also emits this for rejected HTTP responses and parser failures.
                raise SearchProviderError(
                    "DDGS returned no results without confirming a successful search. Its backends may be blocked or returned no usable entries. "
                    "No retry or paid fallback was initiated.", "indeterminate"
                ) from None
            elif isinstance(nested, errors.DDGSException) or isinstance(exc, OSError):
                raise SearchProviderError("DDGS search is unavailable. No retry was made.", "unavailable") from None
            else:
                raise ToolExecutionError("DDGS search failed internally; no provider fallback was initiated.") from None
        if not isinstance(rows, list) or len(rows) > 50:
            raise WebFailure("DDGS normalization failed: invalid result list.", "normalization", "invalid_result_list")
        normalized = [{"title": row.get("title"), "url": row.get("href"), "content": row.get("body"),
                       "published_date": row.get("date"), "score": row.get("score")} if isinstance(row, dict) else None for row in rows]
        return normalize_results(normalized, checked["query"], max_results, self.name, self.redaction_key)


@dataclass
class SearchRouter:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    mode: str = "auto"
    fallback_enabled: bool = False
    secondary: str = "tavily"
    ddgs: DDGSSearchProvider | None = field(default=None, repr=False)
    tavily: TavilySearchProvider | None = field(default=None, repr=False)

    def __post_init__(self):
        self.ddgs = self.ddgs if self.ddgs is not None else DDGSSearchProvider(self.enabled, self.api_key)
        self.tavily = self.tavily if self.tavily is not None else TavilySearchProvider(self.enabled, self.api_key)

    def redact(self, text: str) -> str:
        return redact(text, self.api_key)

    def unavailable_reason(self) -> str | None:
        if type(self.enabled) is not bool or not valid_tavily_key(self.api_key):
            return "Search routing configuration is invalid."
        if not self.enabled:
            return "Web search is disabled. Enable AIKA_WEB_SEARCH_ENABLED explicitly to send queries externally."
        if self.mode not in {"auto", "ddgs", "tavily"} or self.secondary not in {"ddgs", "tavily"} or type(self.fallback_enabled) is not bool:
            return "Search routing configuration is invalid."
        primary = self.tavily if self.mode == "tavily" else self.ddgs
        reason = primary.unavailable_reason()
        if reason and self.mode == "auto" and self.fallback_enabled and self.secondary != "ddgs":
            return self.tavily.unavailable_reason()
        return reason

    def search(self, query: str, max_results: int, provider: str | None = None) -> dict:
        checked = validate_arguments({"query": query, "max_results": max_results, **({"provider": provider} if provider is not None else {})})
        if self.redact(checked["query"]) != checked["query"]:
            raise ToolInputError("Search queries cannot contain API credentials.")
        if type(self.enabled) is not bool or not valid_tavily_key(self.api_key):
            raise ToolExecutionError("Search routing configuration is invalid.", status=ToolStatus.UNAVAILABLE)
        if not self.enabled:
            raise ToolExecutionError("Web search is disabled. No provider request was made.", status=ToolStatus.UNAVAILABLE)
        if self.mode not in {"auto", "ddgs", "tavily"} or self.secondary not in {"ddgs", "tavily"} or type(self.fallback_enabled) is not bool:
            raise ToolExecutionError("Search routing configuration is invalid.", status=ToolStatus.UNAVAILABLE)
        selected = provider or ("ddgs" if self.mode == "auto" else self.mode)
        providers = {"ddgs": self.ddgs, "tavily": self.tavily}
        attempts = [selected]
        bounded_timeout(1)
        try:
            data = providers[selected].search(checked["query"], max_results)
        except SearchProviderError as primary_error:
            if (provider is not None or self.mode != "auto" or not self.fallback_enabled or self.secondary == selected
                    or primary_error.kind not in {"unavailable", "timeout", "rate_limited"}):
                raise
            attempts.append(self.secondary)
            bounded_timeout(1)
            try:
                data = providers[self.secondary].search(checked["query"], max_results)
            except ToolExecutionError:
                raise ToolExecutionError("Primary search failed and the explicitly enabled fallback was unavailable or failed. No further requests were made.",
                                         data={"attempted_providers": attempts}) from None
        bounded_timeout(1)
        return {**data, "attempted_providers": attempts, "fallback_used": len(attempts) == 2}


def validate_output(data: dict) -> dict:
    fields = {"query", "provider", "retrieved_at", "results", "discarded_count"}
    if not isinstance(data, dict) or set(data) not in (fields, fields | {"attempted_providers", "fallback_used"}):
        raise ValueError("Invalid search output.")
    validate_arguments({"query": data["query"]})
    stamp = datetime.fromisoformat(data["retrieved_at"])
    if (stamp.tzinfo is None or stamp.utcoffset() is None or data["provider"] not in {"ddgs", "tavily"}
            or not isinstance(data["results"], list) or len(data["results"]) > MAX_RESULTS
            or type(data["discarded_count"]) is not int or not 0 <= data["discarded_count"] <= 50):
        raise ValueError("Invalid search metadata.")
    if "attempted_providers" in data:
        attempts = data["attempted_providers"]
        if (not isinstance(attempts, list) or not 1 <= len(attempts) <= 2 or any(name not in {"ddgs", "tavily"} for name in attempts)
                or len(set(attempts)) != len(attempts) or attempts[-1] != data["provider"]
                or type(data["fallback_used"]) is not bool or data["fallback_used"] != (len(attempts) == 2)):
            raise ValueError("Invalid search routing evidence.")
    seen = set()
    for row in data["results"]:
        if not isinstance(row, dict) or set(row) != {"title", "url", "domain", "snippet", "published_at", "rank", "score", "retrieved_at", "provider"}:
            raise ValueError("Invalid source fields.")
        if (_source_url(row["url"]) != (row["url"], row["domain"]) or row["url"] in seen
                or row["retrieved_at"] != data["retrieved_at"] or row["provider"] != data["provider"]):
            raise ValueError("Invalid source identity.")
        for field_name, limit in (("title", 200), ("snippet", 1000)):
            value = row[field_name]
            if value is not None and (not isinstance(value, str) or not value or _clean(value, limit) != value):
                raise ValueError("Unsafe source text.")
        if (type(row["rank"]) is not int or not 1 <= row["rank"] <= 50
                or (row["published_at"] is not None and _published(row["published_at"]) != row["published_at"])
                or (row["score"] is not None and (type(row["score"]) not in (int, float) or not math.isfinite(row["score"]) or not 0 <= row["score"] <= 1))):
            raise ValueError("Invalid source metadata.")
        seen.add(row["url"])
    return data


def web_search_tool(provider: SearchRouter | TavilySearchProvider | DDGSSearchProvider) -> ToolDefinition:
    def validate(arguments):
        checked = validate_arguments(arguments)
        key = getattr(provider, "api_key", getattr(provider, "redaction_key", ""))
        if key and key in checked["query"]:
            raise ToolInputError("Search queries cannot contain API credentials.")
        if not isinstance(provider, SearchRouter) and checked.get("provider", provider.name) != provider.name:
            raise ToolInputError("This provider adapter cannot select another provider; use the search router.")
        return checked

    def handle(arguments):
        if isinstance(provider, SearchRouter):
            return provider.search(**arguments)
        return provider.search(arguments["query"], arguments["max_results"])

    return ToolDefinition("web.search", "Retrieve bounded DDGS or Tavily source snippets when web search is explicitly enabled.",
                          validate, validate_output, Permission.READ_ONLY,
                          handle)
