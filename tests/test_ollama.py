import json
import re

import httpx
import pytest

import aika
from src.config import ConfigError, load_config
from src.intelligence.ollama_client import ModelUnavailable, OllamaClient, OllamaError


def tags(*models):
    return httpx.Response(200, json={"models": list(models)})


def answer(content):
    return httpx.Response(200, json={
        "done": True,
        "message": {"role": "assistant", "content": content, "thinking": "private reasoning"},
    })


def refused(request):
    raise httpx.ConnectError("private connection detail", request=request)


def test_model_configuration(monkeypatch):
    monkeypatch.setenv("AIKA_RUNTIME_URL", "http://localhost:11435")
    assert load_config().runtime_url == "http://localhost:11435"
    monkeypatch.setenv("AIKA_OLLAMA_URL", "http://[::1]:11436")
    monkeypatch.setenv("AIKA_OLLAMA_MODEL", "example/test-model:latest")
    monkeypatch.setenv("AIKA_MODEL_TIMEOUT", "42.5")
    settings = load_config()
    assert settings.runtime_url == "http://[::1]:11436"
    assert settings.model == "example/test-model:latest"
    assert settings.model_timeout == 42.5


def test_default_model_is_qwen35_and_existing_override_still_works(monkeypatch, mock_ollama, capsys):
    monkeypatch.delenv("AIKA_OLLAMA_MODEL")
    assert load_config().model == "qwen3.5:4b"
    mock_ollama(lambda request: tags())
    assert aika.main(["doctor"]) == 0
    assert "ollama pull qwen3.5:4b" in capsys.readouterr().out
    monkeypatch.setenv("AIKA_OLLAMA_MODEL", "qwen2.5:3b")
    assert load_config().model == "qwen2.5:3b"


@pytest.mark.parametrize(("key", "value"), [
    ("AIKA_OLLAMA_URL", "https://example.test"),
    ("AIKA_OLLAMA_MODEL", ""),
    ("AIKA_OLLAMA_MODEL", "--option"),
    ("AIKA_OLLAMA_MODEL", "bad model"),
    ("AIKA_OLLAMA_MODEL", "model:cloud"),
    ("AIKA_MODEL_TIMEOUT", "0"),
    ("AIKA_MODEL_TIMEOUT", "NaN"),
    ("AIKA_MODEL_TIMEOUT", "Infinity"),
    ("AIKA_MODEL_TIMEOUT", "bad-value"),
    ("AIKA_OLLAMA_THINK", "unsupported"),
    ("AIKA_CONTEXT_DEBUG", "unsupported"),
])
def test_invalid_model_configuration(key, value, monkeypatch):
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError, match=key):
        load_config()


@pytest.mark.parametrize(("ollama_model", "installed_model"), [
    ("llama3", "llama3:latest"),
    ("qwen2.5:3b", "qwen2.5:3b"),
    ("qwen3:4b", "qwen3:4b"),
], indirect=["ollama_model"])
def test_generation_uses_selected_model_and_returns_only_text(mock_ollama, monkeypatch, ollama_model, installed_model):
    monkeypatch.setenv("AIKA_MODEL_TIMEOUT", "42.5")
    messages = [{"role": "system", "content": "Identity"}, {"role": "user", "content": "Hello"}]

    def handle(request):
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/tags":
            assert request.extensions["timeout"]["read"] == 3.0
            return tags({"name": installed_model})
        assert request.method == "POST" and request.url.path == "/api/chat"
        assert request.extensions["timeout"]["read"] == 42.5
        assert json.loads(request.content) == {
            "messages": messages, "model": ollama_model, "stream": False, "think": False,
            "options": {"temperature": 0.2},
        }
        return answer("  Generated answer.  ")

    mock_ollama(handle)
    assert OllamaClient(load_config()).generate(messages) == "Generated answer."


@pytest.mark.parametrize(("mode", "metadata", "expected"), [
    ("off", {"values": [False, True], "default": True}, {"think": False}),
    ("on", {"values": [False, True], "default": True}, {"think": True}),
    ("on", {"values": ["low", "medium", "high"], "default": "medium"}, {"think": "medium"}),
    ("off", {"values": ["low", "medium", "high"], "default": "medium"}, {"think": False}),
    ("default", None, {}),
])
def test_thinking_uses_model_supported_controls(mode, metadata, expected, monkeypatch, mock_ollama):
    model = "qwen3.5:4b"
    monkeypatch.setenv("AIKA_OLLAMA_MODEL", model)
    monkeypatch.setenv("AIKA_OLLAMA_THINK", mode)
    requests = []

    def handle(request):
        requests.append(request.url.path)
        if request.url.path == "/api/tags":
            return tags({"name": model, "capabilities": ["completion", "thinking"]})
        if request.url.path == "/api/show":
            assert json.loads(request.content) == {"model": model}
            return httpx.Response(200, json={"thinking": metadata})
        assert request.url.path == "/api/chat"
        assert json.loads(request.content) == {
            "model": model, "messages": [], "stream": False, "options": {"temperature": 0.2}, **expected,
        }
        return answer("Final answer")

    mock_ollama(handle)
    assert OllamaClient(load_config()).generate([]) == "Final answer"
    assert requests == (["/api/tags", "/api/chat"] if mode == "default" else ["/api/tags", "/api/show", "/api/chat"])


def test_model_without_thinking_omits_control_and_reports_explicit_on(ollama_model, mock_ollama, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return tags({"name": ollama_model, "capabilities": ["completion"]})
        assert request.url.path == "/api/chat"
        assert "think" not in json.loads(request.content)
        return answer("Final answer")

    mock_ollama(handle)
    assert OllamaClient(load_config()).generate([]) == "Final answer"
    monkeypatch.setenv("AIKA_OLLAMA_THINK", "on")
    with pytest.raises(OllamaError, match="does not support thinking"):
        OllamaClient(load_config()).generate([])
    assert calls == ["/api/tags", "/api/chat", "/api/tags"]


def test_connection_refused_is_safe(mock_ollama):
    mock_ollama(refused)
    with pytest.raises(OllamaError, match="Cannot connect to Ollama") as exc:
        OllamaClient(load_config()).generate([])
    assert "private connection detail" not in str(exc.value)


def test_missing_model_never_posts_chat(mock_ollama, ollama_model):
    def handle(request):
        assert request.url.path == "/api/tags"
        return tags()

    mock_ollama(handle)
    with pytest.raises(ModelUnavailable, match=re.escape(f"ollama pull {ollama_model}")):
        OllamaClient(load_config()).generate([])


def test_remote_model_alias_never_posts_chat(mock_ollama, ollama_model):
    def handle(request):
        assert request.url.path == "/api/tags"
        return tags({"name": ollama_model, "remote_host": "https://example.test"})

    mock_ollama(handle)
    with pytest.raises(ModelUnavailable, match="remote model"):
        OllamaClient(load_config()).generate([])


def test_generation_timeout(mock_ollama, ollama_model):
    def handle(request):
        if request.url.path == "/api/tags":
            return tags({"name": ollama_model})
        raise httpx.ReadTimeout("private timeout detail", request=request)

    mock_ollama(handle)
    with pytest.raises(OllamaError, match="took too long to generate"):
        OllamaClient(load_config()).generate([])


@pytest.mark.parametrize(("response", "message"), [
    (httpx.Response(404, json={"error": "private backend detail"}), "ollama pull {model}"),
    (httpx.Response(500, json={"error": "private backend detail"}), "HTTP 500"),
    (httpx.Response(302, headers={"Location": "https://example.test"}), "HTTP 302"),
    (httpx.Response(200, text="invalid JSON"), "invalid JSON"),
    (httpx.Response(200, json=[]), "unexpected API response"),
    (httpx.Response(200, json={"done": True}), "invalid assistant response"),
    (answer("   "), "no usable assistant text"),
    (httpx.Response(200, json={"done": True, "done_reason": "length", "message": {
        "role": "assistant", "content": "Partial answer", "thinking": "private reasoning",
    }}), "generation limit"),
])
def test_generation_failures_are_controlled(mock_ollama, response, message, ollama_model):
    requests = []

    def handle(request):
        requests.append(request.url.path)
        if request.url.path == "/api/tags":
            return tags({"name": ollama_model})
        assert request.url.path == "/api/chat"
        return response

    mock_ollama(handle)
    with pytest.raises(OllamaError, match=re.escape(message.format(model=ollama_model))) as exc:
        OllamaClient(load_config()).generate([])
    assert requests == ["/api/tags", "/api/chat"]
    assert "private backend detail" not in str(exc.value)
    assert "private reasoning" not in str(exc.value)


def test_chat_retries_after_generation_error_without_retaining_failed_turn(mock_ollama, monkeypatch, capsys, ollama_model):
    inputs = iter([" ", "First", "Second", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    payloads = []

    def handle(request):
        if request.url.path == "/api/tags":
            return tags({"name": ollama_model})
        payloads.append(json.loads(request.content))
        return answer("Generated second answer.") if len(payloads) == 2 else httpx.Response(500)

    mock_ollama(handle)
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "Status: CONNECTED" in output.out
    assert "AIKA > Generated second answer." in output.out
    assert "Session ended." in output.out
    assert "Ollama error:" in output.err
    assert "private reasoning" not in output.out
    assert len(payloads) == 2
    for payload, sent in zip(payloads, ("First", "Second"), strict=True):
        system, user = payload["messages"]
        assert system["role"] == "system" and "AIKA" in system["content"]
        assert user == {"role": "user", "content": sent}


@pytest.mark.parametrize("exit_action", ["exit", EOFError, KeyboardInterrupt])
def test_chat_exits_cleanly_when_ollama_unavailable(exit_action, mock_ollama, monkeypatch, capsys):
    def user_input(_):
        if isinstance(exit_action, type):
            raise exit_action
        return exit_action

    monkeypatch.setattr("builtins.input", user_input)
    mock_ollama(refused)
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr().out
    assert "Status: UNAVAILABLE. Cannot connect to Ollama" in output
    assert "Session ended." in output


def test_doctor_warns_about_missing_model(mock_ollama, capsys, ollama_model):
    mock_ollama(lambda request: tags())
    assert aika.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "PASS  Ollama:" in output and "WARN  Model:" in output
    assert f"ollama pull {ollama_model}" in output


def test_doctor_warns_about_disconnection(mock_ollama, capsys):
    mock_ollama(refused)
    assert aika.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "WARN  Ollama: Cannot connect" in output
    assert "WARN  Model: Could not verify" in output
