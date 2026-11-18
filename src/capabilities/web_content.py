"""Bounded, inert evidence extracted only from already downloaded HTML."""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.capabilities.contracts import ToolExecutionError
from src.capabilities.web_search import _clean, _published, redact


MAX_TEXT = 12_000


@dataclass(frozen=True)
class SourceEvidence:
    source_id: str
    selected_source_json: str
    requested_url: str
    fetched_url: str
    domain: str
    title: str | None
    content: str
    retrieved_at: str
    published_at: str | None
    extraction_status: str = "success"
    truncated: bool = False


def extract_evidence(html: bytes, selected: dict, number: int, key: str = "") -> SourceEvidence:
    try:
        import trafilatura
        from lxml import html as lhtml

        logging.getLogger("trafilatura").setLevel(logging.CRITICAL + 1)
        for name in tuple(logging.Logger.manager.loggerDict):
            if name == "trafilatura" or name.startswith("trafilatura."):
                logging.getLogger(name).disabled = True
        tree = lhtml.fromstring(html, parser=lhtml.HTMLParser(no_network=True, recover=True))
        title = _clean(redact(" ".join(tree.xpath("//head/title/text()")), key), 200) or None
        dates = tree.xpath('//meta[@property="article:published_time" or @itemprop="datePublished"]/@content'
                           ' | //time[@itemprop="datePublished"]/@datetime')
        published = _published(dates[0]) if dates else None
        for node in tree.xpath("//script | //style | //noscript | //template | //iframe | //object | //embed | //form"):
            node.drop_tree()
        # No metadata heuristics or URL downloader: extraction receives an inert parsed tree.
        text = trafilatura.extract(tree, fast=True, favor_precision=True, include_comments=False,
                                   include_images=False, include_links=False, include_tables=True,
                                   with_metadata=False, deduplicate=False)
    except Exception:
        raise ToolExecutionError("The selected page could not be extracted safely.") from None
    if not isinstance(text, str) or not text.strip():
        raise ToolExecutionError("No readable static page content was found. JavaScript, authentication, or a paywall may be required; no bypass was attempted.")
    text = "\n".join(filter(None, (_clean(redact(line, key), MAX_TEXT + 1) for line in text.splitlines())))
    if not text:
        raise ToolExecutionError("The page contained no usable extracted text.")
    return SourceEvidence(
        f"source-{number}", json.dumps(selected, ensure_ascii=True, sort_keys=True),
        selected["url"], selected["url"], selected["domain"], title, text[:MAX_TEXT],
        datetime.now(UTC).isoformat(), published, truncated=len(text) > MAX_TEXT,
    )
