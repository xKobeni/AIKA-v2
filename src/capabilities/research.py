"""Deterministic intent, candidate ranking and bounded research metadata; no tool runner."""

import json
import logging
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo

from src.capabilities.web_answer import _topics, _words
from src.capabilities.web_reader import validate_url, MAX_SOURCES
from src.memory.intent import parse_intent


MAX_ATTEMPTS = 5
FAILURES = {"http_status", "timeout", "network", "tls", "peer_mismatch", "workflow_budget", "response_size",
            "redirect_limit", "redirect_loop", "cross_host_redirect", "redirect_destination", "redirect_location",
            "html_parse", "primary_failed", "fallback_failed", "no_readable_text", "dependency", "html_size",
            "controlled_failure", "date_unverified", "unavailable", "execution_failed", "invalid_input", "indeterminate",
            "rate_limited", "invalid_result_list", "no_usable_sources", "oversized_result_content", "contract", "internal",
            "authentication", "quota", "rejected", "invalid_response", "response_json", "response_shape",
            "response_budget", "response_encoding"}
PUBLISHERS = {"python": {"python.org"}, "node": {"nodejs.org"}, "nodejs": {"nodejs.org"}, "ollama": {"ollama.com"}}
NEWS_PUBLISHERS = {"apnews.com", "pna.gov.ph"}


def research_question(prompt: str) -> str | None:
    direct = re.fullmatch(r"/research(?:\s+(.*))?", prompt, re.IGNORECASE | re.DOTALL)
    if direct:
        return direct[1] or ""
    if prompt.startswith("/"):
        return None
    if parse_intent(prompt) is not None:
        return None
    text = re.sub(r"^(?:AIKA[, :]\s*)?", "", prompt.strip(), flags=re.IGNORECASE)
    text = re.sub(r"^(?:(?:please|can you|could you|would you)\s+)+", "", text, flags=re.IGNORECASE)
    text = text.replace("’", "'")
    if parse_intent(text) is not None:
        return None
    if re.search(r"\b(?:my|our|saved|remembered|memory|memories|conversation|history|project)\b", text, re.IGNORECASE):
        return None
    if re.search(r"\b(?:cpu|processor)\s+(?:temperature|usage|utilization)\b|\b(?:ram|disk)\s+(?:usage|space)\b", text, re.IGNORECASE):
        return None
    explicit = re.match(r"^(?:search(?: the (?:web|internet))? for|look online for|look up|research)\b", text, re.IGNORECASE)
    find = re.match(r"^find (?:the )?(?:latest|recent|current|official)\b", text, re.IGNORECASE)
    current = (re.match(r"^(?:what(?:'s| is| are)|compare|tell me)\b", text, re.IGNORECASE)
               and re.search(r"\b(?:latest|newest|recent|current|today|yesterday)\b", text, re.IGNORECASE))
    if explicit or find or current:
        return text
    return None


def temporal_context(question: str, timezone: str = "local", *, now: datetime | None = None) -> dict:
    moment = now or datetime.now().astimezone()
    if timezone != "local":
        moment = moment.astimezone(ZoneInfo(timezone))
    else:
        moment = moment.astimezone()
    target = None
    if re.search(r"\byesterday\b", question, re.IGNORECASE):
        target = moment.date() - timedelta(days=1)
    elif re.search(r"\btoday\b", question, re.IGNORECASE):
        target = moment.date()
    news = bool(re.search(r"\b(?:news|happening|events|developments|announcements)\b", question, re.IGNORECASE))
    return {"local_date": moment.date().isoformat(), "as_of": moment.isoformat(), "target_date": target.isoformat() if target else None,
            "timezone": timezone, "local_timezone": str(moment.tzinfo), "require_publication_day": bool(target and news),
            "date_policy": "publication date is not event date; retrieval time is not publication time"}


def prepare_query(question: str, temporal: dict) -> str:
    query = re.sub(r"^(?:search(?: the (?:web|internet))? for|look online for|look up|research)(?:\s+|$)", "", question, flags=re.IGNORECASE)
    query = query.rstrip(".?!").strip()
    dated = f"{query} {temporal['target_date']}" if temporal["target_date"] else query
    return dated if len(dated) <= 300 else query


def _publication_time(value: str | None):
    if not isinstance(value, str) or not value:
        return None
    try:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return parsedate_to_datetime(value)
    except (ValueError, TypeError, OverflowError):
        return None


def publication_day(value: str | None, temporal: dict):
    moment = _publication_time(value)
    if moment is None:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(ZoneInfo(temporal["timezone"])) if temporal["timezone"] != "local" else moment.astimezone()
    return moment.date().isoformat()


def publication_matches_day(value: str | None, temporal: dict) -> bool:
    moment = _publication_time(value)
    return (moment is not None and moment.tzinfo is not None and moment <= datetime.fromisoformat(temporal["as_of"])
            and publication_day(value, temporal) == temporal["target_date"])


def ranked_candidates(data: dict, question: str, temporal: dict) -> list[int]:
    topics = _topics(question)
    preferred = set().union(*(domains for subject, domains in PUBLISHERS.items() if subject in topics))
    candidates, seen = [], set()
    for number, row in enumerate(data["results"], 1):
        try:
            _, host = validate_url(row["url"])
        except ValueError:
            continue
        parsed = urlsplit(row["url"])
        if re.search(r"\.(?:pdf|zip|exe|png|jpe?g|gif|mp4|docx?)(?:$|/)", parsed.path, re.IGNORECASE):
            continue
        parameters = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                      if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid"}]
        identity = (host, parsed.path.rstrip("/") or "/", urlencode(sorted(parameters)))
        if identity in seen:
            continue
        seen.add(identity)
        overlap = len(topics & _words((row["title"] or "") + " " + (row["snippet"] or "") + " " + parsed.path))
        if topics and not overlap:
            continue
        authority = any(host == domain or host.endswith("." + domain) for domain in preferred)
        if "ollama" in topics and host == "github.com" and parsed.path.startswith("/ollama/ollama"):
            authority = True
        day = publication_day(row["published_at"], temporal)
        fresh = (day == temporal["target_date"] if temporal["target_date"]
                 else bool(day and 0 <= (date.fromisoformat(temporal["local_date"]) - date.fromisoformat(day)).days <= 30))
        published = _publication_time(row["published_at"])
        if published is not None and published.tzinfo is not None and published > datetime.fromisoformat(temporal["as_of"]):
            fresh = False
        news = bool(re.search(r"\b(?:news|happening|events)\b", question, re.IGNORECASE))
        publisher_hint = news and any(host == domain or host.endswith("." + domain) for domain in NEWS_PUBLISHERS)
        direct = authority and re.search(r"/(?:downloads?|releases?)(?:/|$)", parsed.path, re.IGNORECASE) is not None
        score = overlap * 10 + authority * 25 + direct * 20 + publisher_hint * 12 + bool(day) * 3 + fresh * (40 if temporal["target_date"] else 12)
        candidates.append((score, day or "", -number, number))
    ordered = [item[-1] for item in sorted(candidates, reverse=True)]
    if re.search(r"\b(?:compare|news|happening)\b", question, re.IGNORECASE):
        first, repeated, publishers = [], [], set()
        for number in ordered:
            host = data["results"][number - 1]["domain"]
            group = next((domain for domain in preferred if host == domain or host.endswith("." + domain)), host)
            (repeated if group in publishers else first).append(number)
            publishers.add(group)
        return first + repeated
    return ordered


def safe_failure(result) -> str:
    category = result.failure_category
    return category if category in FAILURES else result.status.value


def log_summary(enabled: bool, summary: dict):
    if enabled:
        # Constructed only from fixed categories, generated IDs, provider names, counts and timings.
        logging.getLogger("aika.web").warning("event=research_summary metadata=%s", json.dumps(summary, sort_keys=True))
