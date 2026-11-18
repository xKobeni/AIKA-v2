"""Bounded, inert evidence extracted only from already downloaded HTML."""

import json
import logging
import re
import warnings
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime

from src.capabilities.contracts import ToolExecutionError
from src.capabilities.web_diagnostics import WebFailure
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
    redirect_chain: tuple[str, ...] = ()
    extraction_method: str = "trafilatura"


def _fallback_text(tree) -> str | None:
    clean = deepcopy(tree)
    if clean.tag in {"nav", "footer", "header", "aside"}:
        return None
    for node in clean.xpath('//nav | //footer | //header | //aside | //*[@role="navigation" or @role="dialog" or @role="banner"]'):
        if node.getparent() is not None:
            node.drop_tree()
    heading = " ".join(clean.xpath("//title/text()"))
    if re.search(r"access denied|just a moment|captcha|sign in|checking your browser|verify.*human", heading, re.IGNORECASE):
        return None
    roots = clean.xpath('//main | //article | //*[@role="main"]')
    root = roots[0] if roots else clean
    paragraphs = root.xpath('.//h1 | .//h2 | .//h3 | .//p | .//li')
    lines, size = [], 0
    for node in paragraphs:
        # Parent list items can already include child paragraphs; do not duplicate them.
        if node.tag == "li" and node.xpath('.//p | .//li'):
            continue
        line = _clean(" ".join(node.itertext()), MAX_TEXT + 1)
        if line and (not lines or line != lines[-1]):
            lines.append(line)
            size += len(line) + 1
        if size > MAX_TEXT:
            break
    text = "\n".join(lines)
    if len(text) < 80 or len(text.split()) < 12:
        return None
    return text


def extract_evidence(html: bytes, selected: dict, number: int, key: str = "") -> SourceEvidence:
    if not isinstance(html, bytes) or not html or len(html) > 1024 * 1024:
        raise WebFailure("Source extraction requires nonempty bounded HTML.", "extraction", "html_size")
    try:
        from urllib3.exceptions import DependencyWarning
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DependencyWarning, module=r"urllib3\.contrib\.socks",
                                    message=r"SOCKS support in urllib3 requires the installation of optional dependencies: specifically, PySocks\.")
            import trafilatura
        from lxml import html as lhtml
    except ImportError:
        raise WebFailure("Source extraction dependencies are unavailable. Install project dependencies.", "extraction", "dependency") from None
    logging.getLogger("trafilatura").setLevel(logging.CRITICAL + 1)
    for name in tuple(logging.Logger.manager.loggerDict):
        if name == "trafilatura" or name.startswith("trafilatura."):
            logging.getLogger(name).disabled = True
    try:
        tree = lhtml.fromstring(html, parser=lhtml.HTMLParser(no_network=True, recover=True))
        title = _clean(redact(" ".join(tree.xpath("//head/title/text()")), key), 200) or None
        dates = tree.xpath('//meta[@property="article:published_time" or @itemprop="datePublished"]/@content'
                           ' | //time[@itemprop="datePublished"]/@datetime')
        published = _published(dates[0]) if dates else None
        for node in tree.xpath("//script | //style | //noscript | //template | //iframe | //object | //embed | //form"):
            if node.getparent() is None:
                raise ValueError("Unsupported document root")
            node.drop_tree()
    except Exception:
        raise WebFailure("Source HTML could not be parsed and sanitized safely.", "extraction", "html_parse") from None
    primary_failed = False
    try:
        # Primary extraction may mutate the tree; keep an inert clean copy for fallback.
        text = trafilatura.extract(deepcopy(tree), fast=True, favor_precision=True, include_comments=False,
                                   include_images=False, include_links=False, include_tables=True,
                                   with_metadata=False, deduplicate=False)
    except Exception:
        text, primary_failed = None, True
    method = "trafilatura"
    if not isinstance(text, str) or not text.strip():
        try:
            text = _fallback_text(tree)
        except Exception:
            raise WebFailure("Safe HTML-text fallback failed.", "extraction", "fallback_failed") from None
        method = "html_fallback"
    if not isinstance(text, str) or not text.strip():
        code = "primary_failed" if primary_failed else "no_readable_text"
        raise WebFailure("No readable static page content was found by the primary extractor or safe fallback. JavaScript, authentication, or a paywall may be required; no bypass was attempted.", "extraction", code)
    text = "\n".join(filter(None, (_clean(redact(line, key), MAX_TEXT + 1) for line in text.splitlines())))
    if not text:
        raise WebFailure("The page contained no usable extracted text.", "extraction", "no_readable_text")
    return SourceEvidence(
        f"source-{number}", json.dumps(selected, ensure_ascii=True, sort_keys=True),
        selected["url"], selected["url"], selected["domain"], title, text[:MAX_TEXT],
        datetime.now(UTC).isoformat(), published, truncated=len(text) > MAX_TEXT, extraction_method=method,
    )
