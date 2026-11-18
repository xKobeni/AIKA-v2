import json
import logging
import socket
from dataclasses import asdict, replace
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest

from src.capabilities import create_registry
from src.capabilities import web_reader as reader
from src.capabilities import web_content as content
from src.capabilities import web_search as search
from src.capabilities.contracts import ToolExecutionError, ToolRequest, ToolStatus
from src.capabilities.executor import ToolExecutor
from src.capabilities.web_answer import grounded_answer, INSUFFICIENT
from src.capabilities.web_diagnostics import WebFailure
from src.config import ConfigError, load_config
from src.intelligence.ollama_client import OllamaClient, OllamaError


KEY = "tvly-private-test-credential"
PUBLIC = "https://example.com/start"
TEXT = "The test page identifies version 3.15 as stable. Its original release information is available in this public document."
HTML = ("<html><head><title>Test article</title></head><body><nav>Navigation should disappear</nav>"
        "<main><h1>Release</h1><p>" + TEXT + "</p></main><script>SecretScript()</script></body></html>").encode()


def source():
    return search.normalize_results([{"url": PUBLIC, "title": "Search title", "content": "Search snippet"}], "public query", 5, "ddgs")["results"][0]


def response(status=200, *, location=None, html=HTML):
    obj = MagicMock()
    obj.__enter__.return_value = obj
    obj.status = status
    headers = {"Content-Type": "text/html", "Content-Length": str(len(html))}
    if location is not None:
        headers["Location"] = location
    obj.getheader.side_effect = lambda key, default=None: headers.get(key, default)
    obj.read1.side_effect = [html, b""]
    return obj


def connections(monkeypatch, responses):
    clients = []
    for item in responses:
        client = MagicMock()
        client.getresponse.return_value = item
        clients.append(client)
    factory = Mock(side_effect=clients)
    monkeypatch.setattr(reader, "_open_connection", factory)
    return clients, factory


def test_native_optional_metadata_cannot_crash_normalization():
    # These previously reached json.dumps/math.isfinite before type/range checking.
    data = search.normalize_results([
        {"url": PUBLIC, "title": "Valid", "content": "Real excerpt", "score": object(), "published_date": object()},
        {"url": "https://example.org/", "content": "Second", "score": 10**400},
    ], "public query", 5, "ddgs")
    assert len(data["results"]) == 2
    assert data["results"][0]["snippet"] == "Real excerpt"
    assert all(item["score"] is None and item["published_at"] is None for item in data["results"])
    search.validate_output(data)


@pytest.mark.parametrize("rows", [None, {}, [None], [{"url": "javascript:unsafe"}], [{"url": PUBLIC, "content": "x" * (search.MAX_RESPONSE_BYTES + 1)}]])
def test_normalization_failures_are_specific_and_never_paid_fallback(rows):
    ddgs = NS(search=Mock(side_effect=lambda *args: search.normalize_results(rows, "public query", 5, "ddgs")))
    tavily = NS(search=Mock())
    router = search.SearchRouter(True, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily)
    with pytest.raises(WebFailure) as error:
        router.search("public query", 5)
    assert error.value.stage == "normalization"
    tavily.search.assert_not_called()


@pytest.mark.parametrize("phase", ["handler", "output_contract"])
def test_execution_and_contract_failures_are_distinct_private_and_opt_in(phase, caplog):
    caplog.set_level(logging.WARNING)
    registry = create_registry()
    original = registry.lookup("web.search")
    failing = Mock(side_effect=RuntimeError("private query raw body " + KEY))
    good = search.normalize_results([], "public query", 5, "ddgs")
    replacement = replace(original, handler=Mock(return_value=good), **({phase: failing} if phase != "handler" else {}))
    if phase == "handler":
        replacement = replace(replacement, handler=failing)
    from src.capabilities.registry import ToolRegistry
    isolated = ToolRegistry()
    isolated.register(replacement)
    request = ToolRequest("web.search", {"query": "private query"})
    result = ToolExecutor(isolated).execute(request)
    assert not caplog.text and not result.verified and result.data is None
    result = ToolExecutor(isolated, web_debug=True).execute(request)
    expected = "contract" if phase == "output_contract" else "internally"
    assert expected in result.error
    assert "stage=contract" in caplog.text if phase == "output_contract" else "stage=internal" in caplog.text
    assert "private query" not in caplog.text + result.error and KEY not in caplog.text + result.error
    assert "raw body" not in caplog.text and "Traceback" not in caplog.text


def test_controlled_normalization_diagnostic_has_only_fixed_labels(caplog):
    caplog.set_level(logging.WARNING)
    provider = NS(name="ddgs", search=Mock(side_effect=WebFailure("Safe normalization failure", "normalization", "invalid_result_list")))
    result = ToolExecutor(create_registry(web_search=provider), web_debug=True).execute(ToolRequest("web.search", {"query": "private topic"}))
    assert not result.verified and "stage=normalization" in caplog.text
    assert "private topic" not in caplog.text


@pytest.mark.parametrize("locations", [["/final"], ["/middle", "https://EXAMPLE.com:443/final"]])
def test_same_host_redirects_and_trace_with_single_budget(monkeypatch, locations):
    responses = [response(302, location=location) for location in locations] + [response()]
    clients, factory = connections(monkeypatch, responses)
    timer = Mock()
    timer_factory = Mock(return_value=timer)
    monkeypatch.setattr(reader.threading, "Timer", timer_factory)
    trace = []
    assert reader.fetch_html(PUBLIC, redirects=trace) == HTML
    assert trace[0] == PUBLIC and trace[-1] == "https://example.com/final"
    assert len(trace) == len(locations) + 1
    assert len({client.deadline for client in clients}) == 1
    assert factory.call_count == len(clients)
    timer_factory.assert_called_once()
    timer.cancel.assert_called_once()
    for item in responses[:-1]:
        item.read1.assert_not_called()
    for client in clients:
        client.connect.assert_called_once()
        client.close.assert_called_once()
        headers = client.request.call_args.kwargs["headers"]
        assert not {"Cookie", "Authorization", "Referer"} & set(headers)


@pytest.mark.parametrize("location", ["https://other.example/path", "http://example.com/path", "https://example.com:444/path",
    "https://127.0.0.1/", "https://user:pass@example.com/", "file:///secret", "//localhost/",
    "https://example.com/\r\nsecret", "https://example.com/path#fragment", "//other.example/", "", None])
def test_unsafe_redirect_never_opens_second_connection(monkeypatch, location):
    clients, factory = connections(monkeypatch, [response(302, location=location)])
    with pytest.raises(ToolExecutionError):
        reader.fetch_html(PUBLIC)
    factory.assert_called_once()
    clients[0].close.assert_called_once()


@pytest.mark.parametrize("locations,code", [(["/start"], "redirect_loop"), (["/a", "/b", "/c"], "redirect_limit")])
def test_redirect_loop_and_limit(monkeypatch, locations, code):
    _, factory = connections(monkeypatch, [response(302, location=location) for location in locations])
    with pytest.raises(WebFailure) as error:
        reader.fetch_html(PUBLIC)
    assert error.value.code == code and factory.call_count <= 3


def test_configured_secret_in_redirect_path_is_not_sent(monkeypatch):
    _, factory = connections(monkeypatch, [response(302, location="/path?token=customPrivateToken")])
    with pytest.raises(WebFailure, match="credential") as error:
        reader.fetch_html(PUBLIC, redaction_key="customPrivateToken")
    assert "customPrivateToken" not in str(error.value)
    factory.assert_called_once()


def test_redirect_revalidates_dns_and_blocks_rebinding(monkeypatch):
    def addresses(ip):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]
    lookup = Mock(side_effect=[addresses("93.184.216.34"), addresses("169.254.169.254")])
    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    clients, factory = connections(monkeypatch, [response(302, location="/final"), response()])
    for client in clients:
        client.connect.side_effect = lambda: reader._resolve("example.com")
    with pytest.raises(ToolExecutionError, match="nonpublic"):
        reader.fetch_html(PUBLIC)
    assert lookup.call_count == 2 and factory.call_count == 2
    clients[1].request.assert_not_called()


def test_peer_address_must_match_validated_ip(monkeypatch):
    monkeypatch.setattr(reader, "_resolve", lambda _: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))])
    raw = MagicMock()
    raw.getpeername.return_value = ("127.0.0.1", 443)
    monkeypatch.setattr(socket, "socket", Mock(return_value=raw))
    context = Mock()
    connection = reader._PinnedHTTPSConnection("example.com", context=context)
    with pytest.raises(WebFailure, match="connected address"):
        connection.connect()
    raw.close.assert_called_once()
    context.wrap_socket.assert_not_called()


def test_deadline_prevents_next_hop_connection(monkeypatch):
    clients, factory = connections(monkeypatch, [response(302, location="/final"), response()])
    clock = [0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    clients[0].getresponse.side_effect = lambda: (clock.__setitem__(0, 16) or response(302, location="/final"))
    with pytest.raises(ToolExecutionError, match="budget"):
        reader.fetch_html(PUBLIC)
    factory.assert_called_once()


def test_redirect_final_body_still_has_one_size_limit(monkeypatch):
    big = response(html=b"x" * (reader.MAX_HTML + 1))
    _, factory = connections(monkeypatch, [response(302, location="/final"), big])
    with pytest.raises(ToolExecutionError, match="size limit"):
        reader.fetch_html(PUBLIC)
    assert factory.call_count == 2
    big.read1.assert_not_called()


def test_redirect_evidence_records_requested_final_and_original(monkeypatch):
    import trafilatura
    monkeypatch.setattr(trafilatura, "extract", Mock(return_value=TEXT))
    connections(monkeypatch, [response(302, location="/final"), response()])
    instance = reader.WebReader(True, True)
    instance.select_search(search.normalize_results([{"url": PUBLIC}], "public query", 5, "ddgs"))
    data = instance.read(1)
    assert data["requested_url"] == PUBLIC and data["fetched_url"] == "https://example.com/final"
    assert data["redirect_chain"] == (PUBLIC, "https://example.com/final")
    assert json.loads(data["selected_source_json"])["url"] == PUBLIC
    reader.read_output(data)
    data["fetched_url"] = "https://other.example/final"
    with pytest.raises(ValueError):
        reader.read_output(data)


@pytest.mark.parametrize("mode", ["empty", "exception", "mutating_exception"])
def test_safe_fallback_after_primary_failure_is_bounded_and_sanitized(monkeypatch, mode):
    import trafilatura
    def primary(tree, **kwargs):
        if mode == "empty":
            return None
        if mode == "mutating_exception":
            tree.clear()
        raise RuntimeError(KEY)
    monkeypatch.setattr(trafilatura, "extract", primary)
    item = content.extract_evidence(HTML, source(), 1)
    assert item.extraction_method == "html_fallback" and TEXT in item.content
    assert "SecretScript" not in item.content and "Navigation should disappear" not in item.content
    assert item.requested_url == PUBLIC and item.title == "Test article"
    assert item.retrieved_at.endswith("+00:00") and len(item.content) <= content.MAX_TEXT


@pytest.mark.parametrize("html", [b"<html><p>Too short</p></html>", b"<html><script>secret</script></html>",
    ("<html><head><title>Access denied</title></head><p>" + TEXT + "</p></html>").encode(),
    ("<html><nav><p>" + TEXT + "</p></nav></html>").encode()])
def test_fallback_does_not_invent_body_or_bypass_challenges(monkeypatch, html):
    import trafilatura
    monkeypatch.setattr(trafilatura, "extract", Mock(return_value=None))
    with pytest.raises(WebFailure) as error:
        content.extract_evidence(html, source(), 1)
    assert error.value.stage == "extraction" and error.value.code == "no_readable_text"


def test_fallback_limits_and_secret_redaction(monkeypatch):
    import trafilatura
    monkeypatch.setattr(trafilatura, "extract", Mock(side_effect=RuntimeError(KEY)))
    html = ("<html><main><p>" + TEXT * 150 + KEY + "</p></main></html>").encode()
    item = content.extract_evidence(html, source(), 1, KEY)
    assert item.truncated and len(item.content) == content.MAX_TEXT
    assert KEY not in item.content


def test_navigation_only_fragment_is_not_article_fallback(monkeypatch):
    import trafilatura
    monkeypatch.setattr(trafilatura, "extract", Mock(return_value=None))
    with pytest.raises(WebFailure):
        content.extract_evidence(("<nav><p>" + TEXT + "</p></nav>").encode(), source(), 1)


def test_model_error_categories_no_retry_and_no_private_logs(caplog):
    caplog.set_level(logging.WARNING)
    item = content.SourceEvidence("source-1", "{}", PUBLIC, PUBLIC, "example.com", "Page", TEXT,
                                  "2026-11-18T00:00:00+00:00", None)
    generate = Mock(side_effect=OllamaError(KEY, kind="timeout"))
    answer = grounded_answer("private question", {1: item}, generate, KEY, debug=True)
    assert "configured model budget" in answer and "stage=grounding" in caplog.text
    assert KEY not in caplog.text + answer and "private question" not in caplog.text
    generate.assert_called_once()


def test_fenced_json_still_requires_real_quotes_and_ids():
    item = content.SourceEvidence("source-1", "{}", PUBLIC, PUBLIC, "example.com", "Page", TEXT,
                                  "2026-11-18T00:00:00+00:00", None)
    value = {"claims": [{"text": "The page identifies version 3.15 as stable.", "source": 1, "quote": TEXT}]}
    generate = Mock(return_value="```json\n" + json.dumps(value) + "\n```")
    assert "[1] " + PUBLIC in grounded_answer("Which version?", {1: item}, generate)
    value["claims"][0]["source"] = 9
    generate.return_value = "```json\n" + json.dumps(value) + "\n```"
    assert grounded_answer("Which version?", {1: item}, generate) == INSUFFICIENT


def test_debug_gate_is_explicit_and_validated(monkeypatch):
    assert not load_config().web_debug
    monkeypatch.setenv("AIKA_WEB_DEBUG", "on")
    assert load_config().web_debug
    monkeypatch.setenv("AIKA_WEB_DEBUG", KEY)
    with pytest.raises(ConfigError) as error:
        load_config()
    assert KEY not in str(error.value)


def test_grounded_format_and_token_cap_do_not_change_timeout_or_ordinary_chat(monkeypatch):
    from src.capabilities.web_answer import ANSWER_SCHEMA
    settings = load_config()
    client = OllamaClient(settings)
    monkeypatch.setattr(client, "check_model", lambda: {})
    monkeypatch.setattr(client, "_thinking_value", lambda _: False)
    request = Mock(return_value={"done": True, "message": {"role": "assistant", "content": '{"claims": []}'}})
    monkeypatch.setattr(client, "_request", request)
    messages = [{"role": "user", "content": "synthetic evidence"}]
    client.generate(messages, response_format=ANSWER_SCHEMA, num_predict=768)
    args = request.call_args.args
    assert args[2] == settings.model_timeout
    assert args[3]["format"] == ANSWER_SCHEMA and args[3]["options"]["num_predict"] == 768
    assert args[3]["model"] == settings.model and args[3]["think"] is False
    request.assert_called_once()
    client.generate(messages)
    assert "format" not in request.call_args.args[3]
    assert "num_predict" not in request.call_args.args[3]["options"]


def test_same_session_uses_grounded_callback_without_tools_or_ordinary_context(tmp_path):
    from src.intelligence.conversation import ConversationSession
    from src.storage.conversation_store import ConversationStore
    ordinary = Mock(return_value="An ordinary explanation.")
    value = {"claims": [{"text": "The page identifies version 3.15 as stable.", "source": 1, "quote": TEXT}]}
    grounded = Mock(return_value=json.dumps(value))
    session = ConversationSession("PRIVATE_SYSTEM", 10, ordinary, ConversationStore(tmp_path), grounded_generate=grounded)
    session.web_reader.evidence[1] = content.SourceEvidence("source-1", "{}", PUBLIC, PUBLIC, "example.com", "Page", TEXT,
                                                          "2026-11-18T00:00:00+00:00", None)
    execute = Mock(side_effect=AssertionError("Grounded answer must not execute tools"))
    session.tools.execute = execute
    assert "[1] " + PUBLIC in session.reply("/ask-web Which version?")
    assert "PRIVATE_SYSTEM" not in repr(grounded.call_args)
    ordinary.assert_not_called()
    execute.assert_not_called()
    session.reply("Explain recursion.")
    ordinary.assert_called_once()
    assert TEXT not in repr(ordinary.call_args)


def test_typed_ollama_timeout_keeps_safe_category(monkeypatch):
    import httpx
    client = OllamaClient(load_config())
    monkeypatch.setattr(httpx, "request", Mock(side_effect=httpx.ReadTimeout(KEY)))
    with pytest.raises(OllamaError) as error:
        client._request("POST", "/api/chat", client.settings.model_timeout, {})
    assert error.value.kind == "timeout" and KEY not in str(error.value)
