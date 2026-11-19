from dataclasses import replace
import json
from unittest.mock import Mock

import httpx
import pytest

from src.config import ConfigError, load_config
from src.intelligence.conversation import ConversationSession
from src.intelligence.ollama_client import OllamaClient, OllamaError
from src.intelligence.prompt_budget import bounded_context
from src.storage.conversation_store import ConversationStore, StorageError


@pytest.mark.parametrize("key,value", [
    ("AIKA_CONTEXT_TURNS", "51"), ("AIKA_CONTEXT_TURNS", "-1"), ("AIKA_CONTEXT_TURNS", "1.5"),
    ("AIKA_CONTEXT_CHARS", "4095"), ("AIKA_CONTEXT_CHARS", "64001"), ("AIKA_CONTEXT_CHARS", "private-value"),
    ("AIKA_CONTEXT_CHARS", "nan"), ("AIKA_RESPONSE_TOKENS", "63"), ("AIKA_RESPONSE_TOKENS", "4097"),
    ("AIKA_RESPONSE_TOKENS", "-1"), ("AIKA_RESPONSE_TOKENS", "private-value"),
])
def test_invalid_configuration_is_bounded_and_private(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError) as error:
        load_config()
    assert key in str(error.value) and "private-value" not in str(error.value)


@pytest.mark.parametrize("turns,chars,tokens", [(0, 4096, 64), (50, 64000, 4096), (10, 24000, 1024)])
def test_configuration_boundaries_and_defaults(monkeypatch, turns, chars, tokens):
    monkeypatch.setenv("AIKA_CONTEXT_TURNS", str(turns))
    monkeypatch.setenv("AIKA_CONTEXT_CHARS", str(chars))
    monkeypatch.setenv("AIKA_RESPONSE_TOKENS", str(tokens))
    settings = load_config()
    assert (settings.context_turns, settings.context_chars, settings.response_tokens) == (turns, chars, tokens)


def pair(user, answer):
    return [{"role": "user", "content": user}, {"role": "assistant", "content": answer}]


def test_exact_boundary_selects_newest_complete_suffix_without_mutation():
    history = [*pair("old-user", "old-answer"), *pair("new-user", "new-answer")]
    original = json.dumps(history)
    result, trimmed = bounded_context("SYS", history, "CURRENT", 28)
    assert trimmed and result == [{"role": "system", "content": "SYS"}, *pair("new-user", "new-answer"),
                                  {"role": "user", "content": "CURRENT"}]
    assert sum(len(row["content"]) for row in result) == 28
    assert json.dumps(history) == original


def test_oversized_recent_pair_does_not_pull_disconnected_older_context():
    history = [*pair("old", "answer"), *pair("large" * 100, "reply")]
    messages, trimmed = bounded_context("SYS", history, "CURRENT", 30)
    assert trimmed and messages == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "CURRENT"}]


def test_newest_unicode_and_system_instruction_are_kept_intact():
    current = "漢字🙂 café" * 20
    system = "Keep the full instruction."
    result, trimmed = bounded_context(system, pair("old" * 100, "answer"), current, len(system) + len(current))
    assert result[0]["content"] == system and result[-1]["content"] == current and trimmed


@pytest.mark.parametrize("turns", [-1, 51, 1000000, True])
def test_direct_session_cannot_bypass_turn_maximum(turns):
    with pytest.raises(ValueError, match="context_turns"):
        ConversationSession("SYS", turns, Mock(), Mock())


@pytest.mark.parametrize("chars", [4095, 64001, True])
def test_direct_session_cannot_bypass_content_maximum(chars):
    with pytest.raises(ValueError, match="context_chars"):
        ConversationSession("SYS", 10, Mock(), Mock(), context_chars=chars)


def test_long_and_restored_history_is_trimmed_only_for_model(tmp_path):
    captured = []
    generate = Mock(side_effect=lambda messages: captured.append(messages) or "A" * 1000)
    store = ConversationStore(tmp_path)
    session = ConversationSession("SYS", 10, generate, store, context_chars=4096)
    for index in range(6):
        session.reply(f"Discuss sample {index}: " + "x" * 1000)
    saved_id, history = session.session_id, session.history()
    assert len(history) == 12 and session.turn_count == 6
    assert all(sum(len(row["content"]) for row in messages) <= 4096 for messages in captured)
    assert captured[-1][0] == {"role": "system", "content": "SYS"}
    assert len(captured[-1]) == 4  # One whole prior exchange fits.
    restored = ConversationSession("SYS", 10, generate, store, context_chars=4096)
    restored.resume(saved_id)
    assert restored.history() == history and generate.call_count == 6
    trace = Mock()
    restored.reply("Discuss another sample: " + "x" * 1000, trace=trace)
    assert trace.call_args.args[2:] == (1, True)
    assert len(store.load_session(saved_id, 10)[1]) == 7


def test_oversized_mandatory_input_never_generates_or_saves(tmp_path):
    model, trace = Mock(), Mock()
    store = ConversationStore(tmp_path)
    session = ConversationSession("private system " * 300, 10, model, store, context_chars=4096)
    with pytest.raises(OllamaError, match="AIKA_CONTEXT_CHARS") as error:
        session.reply("A newest message that must not be truncated.", trace=trace)
    assert "private system" not in str(error.value)
    assert session.history() == [] and store.list_sessions() == []
    model.assert_not_called()
    trace.assert_not_called()


def test_large_valid_newest_input_does_not_get_truncated(tmp_path):
    generate = Mock(return_value="ok")
    session = ConversationSession("SYS", 10, generate, ConversationStore(tmp_path))
    prompt = "Discuss " + "x" * 15992
    session.reply(prompt)
    assert generate.call_args.args[0][-1]["content"] == prompt
    assert len(prompt) == 16000


def test_privacy_filter_runs_before_context_trimming(tmp_path):
    generate = Mock(return_value="ok")
    session = ConversationSession("SYS", 10, generate, ConversationStore(tmp_path), context_chars=4096)
    session._turns.extend([("/web public topic", "PRIVATE SOURCE BODY" * 300),
                           ("/system", "PRIVATE SNAPSHOT" * 300), ("Discuss something", "A useful response")])
    session.reply("Discuss a follow-up")
    sent = generate.call_args.args[0]
    assert len(sent) == 4 and "PRIVATE" not in json.dumps(sent)
    assert "PRIVATE" in json.dumps(session.history())


def test_storage_failure_does_not_retry_model_after_trim(tmp_path, monkeypatch):
    generate = Mock(return_value="ok")
    store = ConversationStore(tmp_path)
    session = ConversationSession("SYS", 10, generate, store, context_chars=4096)
    monkeypatch.setattr(store, "save_exchange", Mock(side_effect=StorageError("unavailable")))
    with pytest.raises(StorageError):
        session.reply("Discuss a topic")
    generate.assert_called_once()
    assert session.history() == []


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": "x" * 24001}],
    [{"role": "user", "content": ""}] * 103,
    [{"role": "user", "content": 123}], [{"role": [], "content": "private"}],
    [{"role": "tool", "content": "private"}], [{"role": "user", "content": "hi", "images": ["private"]}],
])
def test_adapter_rejects_invalid_or_oversized_input_before_metadata_or_transport(mock_ollama, messages):
    clients = mock_ollama()
    with OllamaClient(load_config()) as client:
        with pytest.raises(OllamaError):
            client.generate(messages)
    assert clients == []


@pytest.mark.parametrize("tokens", [-2, -1, 0, 4097, True, "512"])
def test_unlimited_or_invalid_explicit_output_limits_are_rejected(mock_ollama, tokens):
    clients = mock_ollama()
    with OllamaClient(load_config()) as client:
        with pytest.raises(OllamaError, match="token limit"):
            client.generate([], num_predict=tokens)
    assert clients == []


def test_default_and_workflow_output_limits_do_not_change_cache_identity(mock_ollama):
    bodies = []

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]})
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True, "message": {"role": "assistant", "content": "ok"}})

    clients = mock_ollama(handle)
    with OllamaClient(replace(load_config(), response_tokens=64)) as client:
        client.generate([])
        client.generate([], num_predict=768, response_format={"type": "object"})
        client.generate([], num_predict=512)
        client.settings = replace(client.settings, response_tokens=2048)
        client.generate([])
    assert [body["options"]["num_predict"] for body in bodies] == [64, 768, 512, 2048]
    assert bodies[1]["format"] == {"type": "object"} and "format" not in bodies[-1]
    assert len(clients) == 1 and clients[0].is_closed


def test_output_limit_hit_is_failure_without_saved_partial_reply(tmp_path, mock_ollama):
    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]})
        assert json.loads(request.content)["options"]["num_predict"] == 1024
        return httpx.Response(200, json={"done": True, "done_reason": "length",
                                        "message": {"role": "assistant", "content": "unfinished answer"}})

    mock_ollama(handle)
    store = ConversationStore(tmp_path)
    with OllamaClient(load_config()) as client:
        session = ConversationSession("SYS", 10, client.generate, store)
        with pytest.raises(OllamaError, match="generation limit"):
            session.reply("Discuss a topic")
    assert session.history() == [] and store.list_sessions() == []
