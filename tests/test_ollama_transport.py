from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import socket

import httpx
import pytest

import aika
from src.config import ConfigError, load_config
from src.diagnostics import inspect_ollama
from src.intelligence import ollama_client as module
from src.intelligence.ollama_client import METADATA_TTL, ModelUnavailable, OllamaClient, OllamaError
from src.capabilities.web_budget import request_budget
from src.capabilities.web_diagnostics import WebFailure


@pytest.fixture
def transport(mock_ollama, monkeypatch):
    state = {"time": 0.0, "model": "qwen3:4b", "thinking": [True, False], "calls": [],
             "chat_error": None, "tags": None, "show_error": None, "cookies": []}
    monkeypatch.setattr(module, "monotonic", lambda: state["time"])

    def handle(request):
        path = request.url.path
        state["calls"].append((path, json.loads(request.content) if request.content else None))
        state["cookies"].append(request.headers.get("cookie"))
        if path == "/api/tags":
            return httpx.Response(200, json={"models": state["tags"] if state["tags"] is not None else [
                {"name": state["model"], "digest": "synthetic-digest", "capabilities": ["completion", "thinking"]}
            ]}, headers={"Set-Cookie": "private=not-forwarded"})
        error = state["show_error"] if path == "/api/show" else state["chat_error"]
        if isinstance(error, BaseException):
            raise error
        if isinstance(error, httpx.Response):
            return error
        if path == "/api/show":
            return httpx.Response(200, json={"thinking": {"values": state["thinking"], "default": "medium"}})
        assert path == "/api/chat"
        return httpx.Response(200, json={"done": True, "message": {"role": "assistant", "content": "verified model response"}})

    clients = mock_ollama(handle)
    with OllamaClient(load_config()) as client:
        yield client, state, clients


def paths(state):
    return [path for path, _ in state["calls"]]


def test_warm_generation_uses_one_pool_and_only_chat(transport):
    client, state, clients = transport
    client.check_model()
    client.generate([{"role": "user", "content": "First private prompt"}])
    client.generate([{"role": "user", "content": "Second private prompt"}], response_format={"type": "object"}, num_predict=512)
    assert paths(state) == ["/api/tags", "/api/show", "/api/chat", "/api/chat"]
    assert len(clients) == 1 and not clients[0].is_closed
    assert state["cookies"] == [None] * 4
    body = state["calls"][-1][1]
    assert body["messages"] == [{"role": "user", "content": "Second private prompt"}]
    assert body["format"] == {"type": "object"} and body["options"]["num_predict"] == 512
    assert "private prompt" not in repr(client._model)


def test_cache_ttl_is_not_extended_by_warm_generations(transport):
    client, state, _ = transport
    client.generate([])
    state["time"] = METADATA_TTL - 0.001
    client.generate([])
    state["time"] = METADATA_TTL
    client.generate([])
    assert paths(state) == ["/api/tags", "/api/show", "/api/chat", "/api/chat",
                            "/api/tags", "/api/show", "/api/chat"]


def test_explicit_check_refreshes_even_inside_ttl_and_returns_independent_copy(transport):
    client, state, _ = transport
    metadata = client.check_model()
    metadata["capabilities"].clear()
    client.generate([])
    client.check_model()
    client.generate([])
    assert paths(state) == ["/api/tags", "/api/show", "/api/chat", "/api/tags", "/api/show", "/api/chat"]


@pytest.mark.parametrize("change", ["model", "runtime_url", "ollama_think"])
def test_configuration_identity_changes_clear_metadata_and_close_old_pool(transport, change):
    client, state, clients = transport
    client.generate([])
    if change == "model":
        state["model"] = "other:latest"
        value = state["model"]
    elif change == "runtime_url":
        value = "http://localhost:11435"
    else:
        value = "on"
        state["thinking"] = ["low", "medium", "high"]
    client.settings = replace(client.settings, **{change: value})
    client.generate([])
    assert clients[0].is_closed and len(clients) == 2
    assert paths(state) == ["/api/tags", "/api/show", "/api/chat"] * 2
    if change == "ollama_think":
        assert state["calls"][-1][1]["think"] == "medium"


@pytest.mark.parametrize("mode", ["default", "off"])
def test_none_or_false_thinking_values_are_cached(transport, mode):
    client, state, _ = transport
    client.settings = replace(client.settings, ollama_think=mode)
    client.generate([])
    client.generate([])
    assert paths(state).count("/api/tags") == 1
    assert paths(state).count("/api/show") == (0 if mode == "default" else 1)
    body = state["calls"][-1][1]
    assert ("think" not in body) if mode == "default" else body["think"] is False


@pytest.mark.parametrize("error", [httpx.ConnectError("private connection"), httpx.ReadTimeout("private timeout"),
    httpx.RemoteProtocolError("private protocol"), httpx.Response(404, json={"error": "private backend"}),
    httpx.Response(500, text="private backend"), httpx.Response(200, text="private non-JSON")])
def test_failure_invalidates_and_next_request_recovers_without_replay(transport, error):
    client, state, clients = transport
    client.generate([])
    state["chat_error"] = error
    with pytest.raises(OllamaError) as failure:
        client.generate([])
    assert "private" not in str(failure.value)
    assert paths(state) == ["/api/tags", "/api/show", "/api/chat", "/api/chat"]
    assert client._model is None and clients[0].is_closed
    state["chat_error"] = None
    assert client.generate([]) == "verified model response"
    assert paths(state)[-3:] == ["/api/tags", "/api/show", "/api/chat"]
    assert len(clients) == 2


@pytest.mark.parametrize("error", [httpx.Response(200, json={"done": False}),
    httpx.Response(200, json={"done": True, "message": {"role": "assistant", "content": " "}})])
def test_invalid_generation_never_returns_cached_reply(transport, error):
    client, state, _ = transport
    client.generate([])
    state["chat_error"] = error
    with pytest.raises(OllamaError):
        client.generate([])
    assert client._model is None
    assert paths(state).count("/api/chat") == 2


@pytest.mark.parametrize("tags", [[], [{"name": "qwen3:4b", "remote_host": "https://private.test"}],
                                [{"name": "qwen3:4b", "remote_model": "private-cloud"}]])
def test_removed_or_remote_model_after_refresh_stops_before_chat_and_is_not_negatively_cached(transport, tags):
    client, state, _ = transport
    client.generate([])
    state["tags"] = tags
    state["time"] = METADATA_TTL
    with pytest.raises(ModelUnavailable):
        client.generate([])
    assert paths(state)[-1] == "/api/tags" and paths(state).count("/api/chat") == 1
    state["tags"] = None
    client.generate([])
    assert paths(state)[-3:] == ["/api/tags", "/api/show", "/api/chat"]


def test_show_failure_does_not_cache_partial_metadata(transport):
    client, state, _ = transport
    state["show_error"] = httpx.Response(404)
    with pytest.raises(ModelUnavailable):
        client.generate([])
    assert paths(state) == ["/api/tags", "/api/show"] and client._model is None
    state["show_error"] = None
    client.generate([])
    assert paths(state)[-3:] == ["/api/tags", "/api/show", "/api/chat"]


def test_restart_recovery_rechecks_remote_alias_before_chat(transport):
    client, state, _ = transport
    client.generate([])
    state["chat_error"] = httpx.ConnectError("synthetic service restart")
    with pytest.raises(OllamaError):
        client.generate([])
    state["chat_error"] = None
    state["tags"] = [{"name": state["model"], "remote_host": "https://private.test"}]
    with pytest.raises(ModelUnavailable):
        client.generate([])
    assert paths(state)[-1] == "/api/tags" and paths(state).count("/api/chat") == 2


def test_interrupt_drops_pool_and_does_not_replay_generation(transport):
    client, state, clients = transport
    client.generate([])
    state["chat_error"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        client.generate([])
    assert clients[0].is_closed and client._model is None
    assert paths(state) == ["/api/tags", "/api/show", "/api/chat", "/api/chat"]


def test_malformed_tags_do_not_cache_success(transport):
    client, state, _ = transport
    state["tags"] = [{"name": None}]
    with pytest.raises(OllamaError, match="invalid model list"):
        client.generate([])
    assert client._model is None and paths(state) == ["/api/tags"]
    state["tags"] = None
    client.generate([])
    assert paths(state)[-3:] == ["/api/tags", "/api/show", "/api/chat"]


def test_close_is_terminal_idempotent_and_clears_metadata(transport):
    client, state, clients = transport
    client.generate([])
    client.close()
    client.close()
    assert client._model is None and clients[0].is_closed
    with pytest.raises(OllamaError, match="closed"):
        client.generate([])
    assert len(state["calls"]) == 3


def test_context_exit_closes_after_exception(mock_ollama):
    clients = mock_ollama()
    with pytest.raises(RuntimeError):
        with OllamaClient(load_config()) as client:
            client.check_model()
            raise RuntimeError("synthetic caller failure")
    assert clients[0].is_closed


def test_closed_unused_client_never_constructs_transport(mock_ollama):
    clients = mock_ollama()
    client = OllamaClient(load_config())
    client.close()
    with pytest.raises(OllamaError, match="closed"):
        client.check_model()
    assert clients == []


def test_invalid_endpoint_cannot_construct_transport(mock_ollama):
    clients = mock_ollama()
    with OllamaClient(load_config()) as client:
        client.settings = replace(client.settings, runtime_url="https://private.test")
        with pytest.raises(ConfigError):
            client.generate([])
    assert clients == []


def test_warm_cache_still_honors_expired_workflow_budget(transport):
    client, state, _ = transport
    client.generate([])
    with request_budget(-1), pytest.raises(WebFailure):
        client.generate([])
    assert len(state["calls"]) == 3


@pytest.mark.parametrize("exit_action", ["/exit", EOFError, KeyboardInterrupt])
def test_cli_closes_session_transport(exit_action, mock_ollama, monkeypatch):
    clients = mock_ollama()

    def user_input(_):
        if isinstance(exit_action, type):
            raise exit_action
        return exit_action

    monkeypatch.setattr("builtins.input", user_input)
    assert aika.main(["chat"]) == 0
    assert len(clients) == 1 and clients[0].is_closed


def test_doctor_closes_one_shot_transport(mock_ollama):
    clients = mock_ollama()
    assert all(check.status == "PASS" for check in inspect_ollama(load_config()))
    assert len(clients) == 1 and clients[0].is_closed


def test_real_http11_connection_is_reused_on_synthetic_loopback_server(monkeypatch):
    # Synthetic local server only: no Ollama service, provider, user data or inference.
    calls, ports = [], []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_GET(self):
            calls.append(self.path)
            ports.append(self.client_address[1])
            result = ({"models": [{"name": "qwen3:4b"}]} if self.path == "/api/tags" else
                      {"done": True, "message": {"role": "assistant", "content": "synthetic"}})
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.do_GET()

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        def only_this_server(host, port, *_args, **_kwargs):
            assert host == "127.0.0.1" and port == server.server_port
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port))]

        monkeypatch.setattr(socket, "getaddrinfo", only_this_server)
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        try:
            settings = replace(load_config(), runtime_url=f"http://127.0.0.1:{server.server_port}")
            with OllamaClient(settings) as client:
                client.generate([])
                client.generate([])
            assert calls == ["/api/tags", "/api/chat", "/api/chat"]
            assert len(set(ports)) == 1
        finally:
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()
