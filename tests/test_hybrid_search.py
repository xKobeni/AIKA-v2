import json
import logging
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import httpx
import pytest
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

import aika
import src.capabilities.web_search as web
from src.capabilities import create_registry
from src.capabilities.contracts import ToolExecutionError, ToolRequest, ToolStatus
from src.capabilities.web_intent import web_request
from src.config import ConfigError, load_config
from src.diagnostics import inspect_web_search
from src.intelligence.conversation import ConversationSession
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore
from src.capabilities.executor import ToolExecutor
from src.capabilities.web_search import DDGSSearchProvider, SearchProviderError, SearchRouter, TavilySearchProvider, _open_ddgs as open_native


KEY = "tvly-hybrid-synthetic-credential"


def data(provider, query="public query", rows=None):
    if rows is None:
        rows = [{"url": "https://example.com/docs", "title": "Synthetic source", "content": "Synthetic excerpt"}]
    return web.normalize_results(rows, query, 5, provider, KEY)


def adapters():
    return (NS(search=Mock(side_effect=lambda query, count: data("ddgs", query)), unavailable_reason=Mock(return_value=None)),
            NS(search=Mock(side_effect=lambda query, count: data("tavily", query)), unavailable_reason=Mock(return_value=None)))


def execute(router, arguments=None):
    return ToolExecutor(create_registry(web_search=router)).execute(ToolRequest("web.search", arguments or {"query": "public query"}))


@pytest.fixture
def ddgs_client(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.text.return_value = [{"title": "Synthetic DDGS title", "href": "https://example.com/docs", "body": "Synthetic DDGS excerpt"}]
    monkeypatch.setattr(web, "_open_ddgs", lambda: client)
    return client


def test_ddgs_constructor_is_keyless_bounded_and_verified(monkeypatch):
    module = NS(DDGS=Mock())
    monkeypatch.setattr(web, "_ddgs_dependencies", lambda: (module, None))
    open_native()
    module.DDGS.assert_called_once_with(timeout=5, verify=True)


def test_ddgs_adapter_uses_documented_auto_backend_once(ddgs_client):
    result = execute(DDGSSearchProvider(True))
    assert result.verified and result.data["provider"] == "ddgs"
    ddgs_client.text.assert_called_once_with("public query", max_results=5, backend="auto", page=1)
    row = result.data["results"][0]
    assert row["title"] == "Synthetic DDGS title" and row["snippet"] == "Synthetic DDGS excerpt"
    assert row["url"] == "https://example.com/docs"
    assert row["provider"] == "ddgs" and row["domain"] == "example.com"
    assert row["published_at"] is None and datetime.fromisoformat(row["retrieved_at"]).utcoffset() is not None


def test_both_adapters_use_identical_source_contract(ddgs_client, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [{"title": "Synthetic source", "url": "https://example.com/docs", "content": "Synthetic excerpt"}]})
    monkeypatch.setattr(web, "_open_client", lambda module: module.Client(transport=httpx.MockTransport(respond), trust_env=False))
    ddgs = execute(DDGSSearchProvider(True)).data
    tavily = execute(TavilySearchProvider(True, KEY)).data
    assert ddgs.keys() == tavily.keys() and ddgs["results"][0].keys() == tavily["results"][0].keys()
    assert ddgs["results"][0]["provider"] == "ddgs" and tavily["results"][0]["provider"] == "tavily"
    assert json.loads(calls[0].content)["search_depth"] == "basic" and calls[0].headers["Authorization"] == f"Bearer {KEY}"


def test_ddgs_deduplicates_sanitizes_and_preserves_supplied_date(ddgs_client):
    ddgs_client.text.return_value = [
        {"href": "https://EXAMPLE.com:443/docs#one", "title": "Unsafe\x1btitle " + KEY, "body": "X"*2000, "date": "2026-11-18"},
        {"href": "https://example.com/docs#two", "title": "duplicate"}, {"href": "file:///C:/secret"},
    ]
    result = execute(DDGSSearchProvider(True, KEY))
    assert result.verified and len(result.data["results"]) == 1 and result.data["discarded_count"] == 2
    row = result.data["results"][0]
    assert row["title"].isprintable() and KEY not in repr(result.data)
    assert len(row["snippet"]) == 1000 and row["published_at"] == "2026-11-18"


@pytest.mark.parametrize("mode", ["auto", "ddgs", "tavily"])
def test_provider_modes_use_exactly_one_provider(mode):
    ddgs, tavily = adapters()
    result = execute(SearchRouter(True, KEY, mode, ddgs=ddgs, tavily=tavily))
    expected = "tavily" if mode == "tavily" else "ddgs"
    assert result.verified and result.data["provider"] == expected
    assert result.data["attempted_providers"] == [expected] and not result.data["fallback_used"]
    assert ddgs.search.call_count == (expected == "ddgs") and tavily.search.call_count == (expected == "tavily")


def test_key_alone_never_authorizes_automatic_paid_usage():
    ddgs, tavily = adapters()
    ddgs.search.side_effect = SearchProviderError("DDGS unavailable", "unavailable")
    result = execute(SearchRouter(True, KEY, ddgs=ddgs, tavily=tavily))
    assert not result.verified and ddgs.search.call_count == 1
    tavily.search.assert_not_called()


@pytest.mark.parametrize("kind", ["unavailable", "timeout", "rate_limited"])
def test_fallback_requires_opt_in_and_runs_secondary_once(kind):
    ddgs, tavily = adapters()
    ddgs.search.side_effect = SearchProviderError("Controlled DDGS failure", kind)
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily))
    assert result.verified and result.data["provider"] == "tavily"
    assert result.data["attempted_providers"] == ["ddgs", "tavily"] and result.data["fallback_used"]
    assert ddgs.search.call_count == tavily.search.call_count == 1


@pytest.mark.parametrize("kind", ["authentication", "quota", "rejected", "invalid_response"])
def test_non_transient_failures_never_trigger_paid_fallback(kind):
    ddgs, tavily = adapters()
    ddgs.search.side_effect = SearchProviderError("Controlled failure", kind)
    assert not execute(SearchRouter(True, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily)).verified
    tavily.search.assert_not_called()


@pytest.mark.parametrize("mode,override", [("ddgs", None), ("tavily", None), ("auto", "ddgs"), ("auto", "tavily")])
def test_explicit_selection_never_falls_back(mode, override):
    ddgs, tavily = adapters()
    ddgs.search.side_effect = tavily.search.side_effect = SearchProviderError("Controlled timeout", "timeout")
    router = SearchRouter(True, KEY, mode, True, ddgs=ddgs, tavily=tavily)
    args = {"query": "public query", **({"provider": override} if override else {})}
    result = execute(router, args)
    selected = override or mode
    assert not result.verified and result.data is None
    assert ddgs.search.call_count == (selected == "ddgs") and tavily.search.call_count == (selected == "tavily")


def test_empty_results_are_not_a_reason_to_use_paid_fallback():
    ddgs, tavily = adapters()
    ddgs.search.side_effect = lambda query, count: data("ddgs", query, [])
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily))
    assert result.verified and result.data["results"] == [] and not result.data["fallback_used"]
    tavily.search.assert_not_called()


def test_fallback_never_retries_primary_or_secondary():
    ddgs, tavily = adapters()
    ddgs.search.side_effect = SearchProviderError("Controlled unavailable", "unavailable")
    tavily.search.side_effect = SearchProviderError("Controlled timeout", "timeout")
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily))
    assert not result.verified and result.data["attempted_providers"] == ["ddgs", "tavily"]
    assert ddgs.search.call_count == tavily.search.call_count == 1


def test_identical_secondary_is_not_a_retry():
    ddgs, tavily = adapters()
    ddgs.search.side_effect = SearchProviderError("Controlled unavailable", "unavailable")
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, secondary="ddgs", ddgs=ddgs, tavily=tavily))
    assert not result.verified and ddgs.search.call_count == 1
    tavily.search.assert_not_called()


@pytest.mark.parametrize("override", [None, "ddgs", "tavily"])
def test_network_gate_blocks_every_provider_and_override(override):
    ddgs, tavily = adapters()
    result = execute(SearchRouter(False, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily),
                     {"query": "public query", **({"provider": override} if override else {})})
    assert result.status == ToolStatus.UNAVAILABLE and not result.verified
    ddgs.search.assert_not_called()
    tavily.search.assert_not_called()


def test_ddgs_needs_no_key_but_tavily_does(ddgs_client):
    assert execute(SearchRouter(True)).verified
    tavily = execute(SearchRouter(True, mode="tavily"))
    assert tavily.status == ToolStatus.UNAVAILABLE and "AIKA_TAVILY_API_KEY" in tavily.error
    assert ddgs_client.text.call_count == 1


@pytest.mark.parametrize("error,kind", [(TimeoutException(KEY), "timeout"), (RatelimitException(KEY), "rate_limited"),
    (DDGSException(TimeoutException(KEY)), "timeout"), (DDGSException(RatelimitException(KEY)), "rate_limited"), (DDGSException(KEY), "unavailable")])
def test_library_errors_are_safe_typed_and_not_retried(ddgs_client, error, kind):
    ddgs_client.text.side_effect = error
    with pytest.raises(SearchProviderError) as failure:
        DDGSSearchProvider(True).search("public query", 5)
    assert failure.value.kind == kind and KEY not in str(failure.value)
    assert ddgs_client.text.call_count == 1


@pytest.mark.parametrize("error", [DDGSException("No results found."), DDGSException(DDGSException("No results found."))])
def test_library_no_results_signal_does_not_fall_back(ddgs_client, error):
    ddgs_client.text.side_effect = error
    _, tavily = adapters()
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, tavily=tavily))
    assert not result.verified and result.data is None
    assert "without confirming a successful search" in result.error
    assert ddgs_client.text.call_count == 1
    tavily.search.assert_not_called()


def test_raw_empty_list_is_success_without_paid_fallback(ddgs_client):
    ddgs_client.text.return_value = []
    _, tavily = adapters()
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, tavily=tavily))
    assert result.verified and result.data["results"] == []
    assert result.data["provider"] == "ddgs" and result.data["discarded_count"] == 0
    assert result.data["attempted_providers"] == ["ddgs"] and not result.data["fallback_used"]
    ddgs_client.text.assert_called_once()
    tavily.search.assert_not_called()


def test_invalid_raw_entries_are_filtered_individually(ddgs_client):
    ddgs_client.text.return_value = [
        None, {"href": "javascript:unsafe"},
        {"title": "First", "href": "https://example.com/one", "body": "First excerpt"},
        {"href": 42},
        {"title": "Second", "href": "https://example.org/two", "body": "Second excerpt"},
    ]
    result = execute(DDGSSearchProvider(True))
    assert result.verified and result.data["discarded_count"] == 3
    assert [(row["title"], row["url"], row["snippet"]) for row in result.data["results"]] == [
        ("First", "https://example.com/one", "First excerpt"),
        ("Second", "https://example.org/two", "Second excerpt"),
    ]


@pytest.mark.parametrize("status", [202, 403, 429])
def test_pinned_library_hidden_http_rejection_is_not_verified_empty(monkeypatch, status):
    from ddgs.ddgs import DDGS
    from ddgs.engines.duckduckgo import Duckduckgo

    # Exercise the installed library's status suppression without making HTTP requests.
    engine = object.__new__(Duckduckgo)
    engine.http_client = NS(request=Mock(return_value=NS(status_code=status)))
    monkeypatch.setattr(DDGS, "_get_engines", lambda *args: [engine])
    monkeypatch.setattr(web, "_open_ddgs", open_native)
    _, tavily = adapters()
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, tavily=tavily))
    assert not result.verified and result.data is None
    assert "backends may be blocked" in result.error
    engine.http_client.request.assert_called_once()
    tavily.search.assert_not_called()


def test_auto_readiness_does_not_require_duckduckgo(monkeypatch):
    import ddgs.engines

    monkeypatch.setattr(ddgs.engines, "ENGINES", {"text": {"other": NS(disabled=False)}})
    assert DDGSSearchProvider(True).unavailable_reason() is None
    monkeypatch.setattr(ddgs.engines, "ENGINES", {"text": {"other": NS(disabled=True)}})
    assert "text backends are unavailable" in DDGSSearchProvider(True).unavailable_reason()


@pytest.mark.parametrize("rows", [None, {}, [None], [{"href": "javascript:unsafe"}], [{"href": "https://example.com/", "body": "x"*(web.MAX_RESPONSE_BYTES+1)}]])
def test_invalid_ddgs_results_do_not_trigger_paid_fallback(ddgs_client, rows):
    ddgs_client.text.return_value = rows
    _, tavily = adapters()
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, tavily=tavily))
    assert not result.verified and ddgs_client.text.call_count == 1
    tavily.search.assert_not_called()


def test_unexpected_library_error_is_not_paid_fallback(ddgs_client):
    ddgs_client.text.side_effect = RuntimeError(KEY)
    _, tavily = adapters()
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, tavily=tavily))
    assert not result.verified and KEY not in result.error
    tavily.search.assert_not_called()


@pytest.mark.parametrize("query", ["", "x"*301, "line\nbreak", KEY])
def test_invalid_queries_do_not_reach_either_provider(query):
    ddgs, tavily = adapters()
    result = execute(SearchRouter(True, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily), {"query": query})
    assert result.status == ToolStatus.INVALID_INPUT
    ddgs.search.assert_not_called()
    tavily.search.assert_not_called()


@pytest.mark.parametrize("value", ["auto", "unknown", None, [], True])
def test_invalid_per_request_provider_is_rejected(value):
    ddgs, tavily = adapters()
    result = execute(SearchRouter(True, KEY, ddgs=ddgs, tavily=tavily), {"query": "public query", "provider": value})
    assert result.status == ToolStatus.INVALID_INPUT
    ddgs.search.assert_not_called()
    tavily.search.assert_not_called()


@pytest.mark.parametrize("name", ["ddgs", "tavily"])
def test_explicit_cli_intent_selects_only_named_provider(name):
    assert web_request(f"/web --provider {name} official Python documentation") == ToolRequest(
        "web.search", {"query": "official Python documentation", "provider": name})


@pytest.mark.parametrize("command", ["/web --provider", "/web --provider ddgs", "/web --provider auto x",
    "/web --provider evil x", "/web --provider ddgs --provider tavily x", "/web --headers x"])
def test_bad_cli_provider_flags_never_make_requests(command):
    ddgs, tavily = adapters()
    result = execute(SearchRouter(True, KEY, ddgs=ddgs, tavily=tavily), web_request(command).arguments)
    assert result.status == ToolStatus.INVALID_INPUT
    ddgs.search.assert_not_called()
    tavily.search.assert_not_called()


def test_status_and_doctor_do_not_instantiate_or_search(ddgs_client, monkeypatch, capsys, mock_ollama):
    mock_ollama()
    monkeypatch.setenv("AIKA_WEB_SEARCH_ENABLED", "on")
    assert aika.main(["doctor"]) == 0
    entries = iter(["/web-status", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(entries))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr().out
    assert "Provider mode: auto" in output and "Primary: ddgs" in output and "Fallback enabled: NO" in output
    assert "Available: YES" in output and "API key present: NO" in output
    ddgs_client.__enter__.assert_not_called()
    ddgs_client.text.assert_not_called()


def test_cli_ddgs_and_explicit_tavily_use_same_executor(ddgs_client, monkeypatch, capsys, mock_ollama):
    mock_ollama()
    monkeypatch.setenv("AIKA_WEB_SEARCH_ENABLED", "on")
    monkeypatch.setenv("AIKA_TAVILY_API_KEY", KEY)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [{"url": "https://example.com/tavily", "title": "Tavily synthetic source"}]})
    monkeypatch.setattr(web, "_open_client", lambda module: module.Client(transport=httpx.MockTransport(respond), trust_env=False))
    entries = iter(["/web public query", "/web --provider ddgs public query", "/web --provider tavily public query", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(entries))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr().out
    assert "Provider: DDGS" in output and "Provider: Tavily" in output
    assert ddgs_client.text.call_count == 2 and len(calls) == 1 and KEY not in output


def test_fallback_output_persistence_and_context_privacy(tmp_path):
    ddgs, tavily = adapters()
    ddgs.search.side_effect = SearchProviderError("Controlled timeout", "timeout")
    router = SearchRouter(True, KEY, fallback_enabled=True, ddgs=ddgs, tavily=tavily)
    generate = Mock(return_value="Ordinary reply")
    session = ConversationSession("Identity", 10, generate, ConversationStore(tmp_path), MemoryStore(tmp_path), web_search=router)
    session.reply("Remember that Orion uses SvelteKit for its frontend.")
    answer = session.reply("/web --provider tavily public query")
    assert "Provider: Tavily" in answer and "fallback used" not in answer
    fallback = session.reply("/web public query")
    assert "Explicitly enabled fallback used: ddgs -> tavily" in fallback
    restored = ConversationSession("Identity", 10, generate, ConversationStore(tmp_path), MemoryStore(tmp_path))
    restored.resume(session.session_id)
    assert restored.history() == session.history()
    restored.reply("Explain how a search engine works")
    outbound = repr(generate.call_args.args[0])
    assert "Synthetic excerpt" not in outbound and KEY not in outbound
    assert ddgs.search.call_count == 1 and tavily.search.call_count == 2
    assert len(MemoryStore(tmp_path).list_facts("project", "Orion")) == 1


@pytest.mark.parametrize("setting,value", [("AIKA_WEB_SEARCH_PROVIDER", "evil"), ("AIKA_WEB_SEARCH_FALLBACK_PROVIDER", "auto"),
                                          ("AIKA_WEB_SEARCH_FALLBACK_ENABLED", "yes please")])
def test_invalid_routing_configuration_is_safe(monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ConfigError, match=setting) as error:
        load_config()
    assert value not in str(error.value)


def test_default_config_is_keyless_auto_and_no_paid_fallback():
    settings = load_config()
    assert not settings.web_search_enabled and settings.web_search_provider == "auto"
    assert not settings.web_search_fallback_enabled and settings.web_search_fallback_provider == "tavily"
    assert not settings.tavily_api_key


def test_dependency_version_or_backend_failure_does_not_switch_engines(monkeypatch):
    monkeypatch.setattr(web, "version", lambda _: "unsupported")
    result = execute(SearchRouter(True))
    assert result.status == ToolStatus.UNAVAILABLE and not result.verified
    assert "9.16.1" in result.error


def test_ddgs_proxy_configuration_is_not_used_or_leaked(monkeypatch, ddgs_client):
    monkeypatch.setenv("DDGS_PROXY", "https://private-credential@proxy.invalid")
    result = execute(SearchRouter(True))
    assert result.status == ToolStatus.UNAVAILABLE and "private-credential" not in result.error
    ddgs_client.text.assert_not_called()


def test_ddgs_logs_cannot_leak_queries_or_errors(ddgs_client, caplog):
    caplog.set_level(logging.DEBUG)
    def raise_logged(*args, **kwargs):
        logging.getLogger("ddgs.ddgs").warning("private query %s", KEY)
        raise DDGSException(KEY)
    ddgs_client.text.side_effect = raise_logged
    result = execute(DDGSSearchProvider(True))
    assert not result.verified and KEY not in caplog.text + result.error
