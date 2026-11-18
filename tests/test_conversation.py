import json
import re
from unittest.mock import Mock

import httpx
import pytest

import aika
from src.cli import SYSTEM_INSTRUCTION
from src.config import load_config
from src.intelligence.conversation import ConversationSession
from src.intelligence.ollama_client import OllamaError
from src.storage.conversation_store import ConversationStore, StorageError


def message(role, content):
    return {"role": role, "content": content}


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path)


def test_follow_up_receives_one_system_message_and_previous_complete_turn(store):
    generate = Mock(side_effect=["Framework noted.", "Next.js"])
    session = ConversationSession("Identity", load_config().context_turns, generate, store)
    assert session.history() == []
    assert load_config().context_turns == 10

    first_user = message("user", "Orion uses Next.js.")
    system = message("system", "Identity")
    assert session.reply(first_user["content"]) == "Framework noted."
    generate.assert_called_once_with([system, first_user])

    first_reply = message("assistant", "Framework noted.")
    second_user = message("user", "What framework did I mention?")
    assert session.reply(second_user["content"]) == "Next.js"
    generate.assert_called_with([system, first_user, first_reply, second_user])
    assert session.history() == [first_user, first_reply, second_user, message("assistant", "Next.js")]


def test_new_session_is_empty_even_with_the_same_generator(store):
    generate = Mock(return_value="A reply")
    first = ConversationSession("Identity", 10, generate, store)
    first.reply("My project is Orion.")
    second = ConversationSession("Identity", 10, generate, store)
    assert second.history() == []
    second.reply("Do you know my project?")
    generate.assert_called_with([message("system", "Identity"), message("user", "Do you know my project?")])
    assert first.history()[0] == message("user", "My project is Orion.")


def test_failed_generation_and_empty_input_preserve_the_last_successful_turn(store):
    generate = Mock(side_effect=["First reply", OllamaError("Unavailable"), "Retry reply"])
    session = ConversationSession("Identity", 1, generate, store)
    session.reply("First")
    history = session.history()
    assert session.reply(" \t ") is None
    generate.assert_called_once()
    with pytest.raises(OllamaError, match="Unavailable"):
        session.reply("Failed prompt")
    assert session.turn_count == 1
    assert session.history() == history
    assert store.load_session(session.session_id, 10) == (2, [("First", "First reply")])

    assert session.reply("Retry prompt") == "Retry reply"
    generate.assert_called_with([message("system", "Identity"), *history, message("user", "Retry prompt")])
    assert session.history() == [message("user", "Retry prompt"), message("assistant", "Retry reply")]


def test_zero_turn_limit_disables_context_but_still_saves_exchanges(monkeypatch, store):
    monkeypatch.setenv("AIKA_CONTEXT_TURNS", "0")
    generate = Mock(return_value="A reply")
    session = ConversationSession("Identity", load_config().context_turns, generate, store)
    session.reply("First prompt")
    assert session.history() == []
    session.reply("Second prompt")
    generate.assert_called_with([message("system", "Identity"), message("user", "Second prompt")])
    assert store.load_session(session.session_id, 10) == (4, [("First prompt", "A reply"), ("Second prompt", "A reply")])
    assert store.load_session(session.session_id, 0) == (4, [])


def test_chat_context_limit_history_clear_and_local_commands(mock_ollama, monkeypatch, capsys, ollama_model):
    monkeypatch.setenv("AIKA_CONTEXT_TURNS", "2")
    inputs = iter([
        "/help", "/unknown", " ", "First prompt", "Second prompt", "Third prompt", "Fourth prompt",
        "/status", "/history", "/clear", "/history", "After clear", "/exit",
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    requests = []
    payloads = []

    def handle(request):
        requests.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": ollama_model}]})
        assert request.url.path == "/api/chat"
        payloads.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"done": True, "message": message("assistant", f"Reply {len(payloads)}")})

    mock_ollama(handle)
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "/exit     End the session" in output.out
    assert "Unknown chat command" in output.out
    assert f"Local Model: {ollama_model}" in output.out
    assert "History: 2/2 completed turns retained" in output.out
    assert "You: First prompt" not in output.out
    assert "You: Second prompt" not in output.out
    assert "AIKA: Reply 1" not in output.out
    assert "AIKA: Reply 2" not in output.out
    assert "You: Third prompt\nAIKA: Reply 3\nYou: Fourth prompt\nAIKA: Reply 4\n" in output.out
    assert "Conversation context cleared. Saved history is retained" in output.out
    assert "No completed turns in this session." in output.out
    assert requests == ["/api/tags", *["/api/tags", "/api/chat"] * 5]

    system = payloads[0][0]
    assert system["role"] == "system"
    assert "session" in system["content"]
    assert payloads == [
        [system, message("user", "First prompt")],
        [system, message("user", "First prompt"), message("assistant", "Reply 1"), message("user", "Second prompt")],
        [system, message("user", "First prompt"), message("assistant", "Reply 1"),
         message("user", "Second prompt"), message("assistant", "Reply 2"), message("user", "Third prompt")],
        [system, message("user", "Second prompt"), message("assistant", "Reply 2"),
         message("user", "Third prompt"), message("assistant", "Reply 3"), message("user", "Fourth prompt")],
        [system, message("user", "After clear")],
    ]


def test_resume_and_new_keep_saved_sessions_isolated(store, mock_ollama, monkeypatch, capsys, ollama_model):
    monkeypatch.setenv("AIKA_CONTEXT_TURNS", "1")
    payloads = []
    requested_models = []

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": ollama_model}, {"name": "qwen3.5:4b"}]})
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        requested_models.append(body["model"])
        payloads.append(body["messages"])
        return httpx.Response(200, json={"done": True, "message": message("assistant", f"Reply {len(payloads)}")})

    mock_ollama(handle)
    inputs = iter(["Old context", "Recent context", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert aika.main(["chat"]) == 0
    capsys.readouterr()
    original_id, _ = store.list_sessions()[0]
    monkeypatch.setenv("AIKA_OLLAMA_MODEL", "qwen3.5:4b")

    inputs = iter([
        "/history", "/sessions", "/resume bad-id", f"/resume {original_id}", "/history", "Follow-up",
        "/clear", "/new", "Ask from a fresh session", f"/resume {original_id}", "/history", "/exit",
    ])
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "No completed turns in this session." in output.out
    assert f"[{original_id}] Old context" in output.out
    assert "Invalid conversation ID" in output.err
    assert output.out.count("Conversation restored. Loaded 1 recent completed turns.") == 2
    assert "You: Recent context\nAIKA: Reply 2" in output.out
    assert "You: Follow-up\nAIKA: Reply 3" in output.out
    assert len(payloads) == 4
    assert requested_models == [ollama_model, ollama_model, "qwen3.5:4b", "qwen3.5:4b"]
    system = payloads[0][0]
    assert payloads[2] == [system, message("user", "Recent context"), message("assistant", "Reply 2"), message("user", "Follow-up")]
    assert payloads[3] == [system, message("user", "Ask from a fresh session")]
    assert store.load_session(original_id, 10) == (6, [
        ("Old context", "Reply 1"), ("Recent context", "Reply 2"), ("Follow-up", "Reply 3"),
    ])
    assert len(store.list_sessions()) == 2


def test_prompt_prioritizes_grounded_answers_and_restored_turns():
    assert "Keep answers brief" in SYSTEM_INSTRUCTION
    assert "including restored turns" in SYSTEM_INSTRUCTION
    assert "state known answers plainly" in SYSTEM_INSTRUCTION
    assert "use only facts explicitly stated by the user" in SYSTEM_INSTRUCTION
    assert "Never infer missing facts" in SYSTEM_INSTRUCTION
    assert "Orion" not in SYSTEM_INSTRUCTION


@pytest.mark.parametrize("debug_mode", ["off", "roles", "content"])
def test_context_debug_limits_output_and_reports_order(debug_mode, monkeypatch, capsys, mock_ollama, ollama_model):
    approved = "Public sample message"
    credential = "password: synthetic-password-value"
    unapproved = "unmarked-credential"
    monkeypatch.setenv("AIKA_CONTEXT_DEBUG", debug_mode)
    monkeypatch.setenv("AIKA_CONTEXT_DEBUG_PUBLIC", json.dumps([approved, credential]))
    monkeypatch.setenv("AIKA_CONTEXT_TURNS", "1")
    entries = iter([approved, credential, unapproved, "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(entries))

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": ollama_model}]})
        return httpx.Response(200, json={"done": True, "message": {
            **message("assistant", "Public reply"), "thinking": "hidden reasoning trace",
        }})

    mock_ollama(handle)
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "hidden reasoning trace" not in output.out + output.err
    assert credential not in output.err and unapproved not in output.err
    if debug_mode == "off":
        assert output.err == ""
        return

    session_id = re.search(r"Session ID: ([0-9a-f]{32})", output.out)[1]
    assert f"model={ollama_model} session={session_id} completed_turns=1 system=yes truncated=yes" in output.err
    assert re.findall(r"\[context\] \d+ (\w+)", output.err) == [
        "system", "user", "system", "user", "assistant", "user", "system", "user", "assistant", "user",
    ]
    if debug_mode == "content":
        assert "Privacy warning" in output.err
        assert repr(approved) in output.err
        assert "[content withheld]" in output.err
    else:
        assert approved not in output.err and "Public reply" not in output.err


def test_chat_hides_uncommitted_answer_and_can_retry(store, mock_ollama, monkeypatch, capsys):
    write = ConversationStore.save_exchange
    mock_ollama()
    generate = Mock(side_effect=["Uncommitted answer", "Saved answer"])
    monkeypatch.setattr("src.cli.OllamaClient.generate", generate)

    def fail_once(self, session_id, sequence, user, assistant):
        if user == "First prompt":
            raise StorageError("Simulated database failure")
        return write(self, session_id, sequence, user, assistant)

    monkeypatch.setattr(ConversationStore, "save_exchange", fail_once)
    inputs = iter(["First prompt", "/history", "Retry prompt", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "Storage error: Simulated database failure" in output.err
    assert "Uncommitted answer" not in output.out
    assert "No completed turns in this session." in output.out
    assert "AIKA > Saved answer" in output.out
    assert generate.call_args.args[0][1:] == [message("user", "Retry prompt")]
    session_id, _ = store.list_sessions()[0]
    assert store.load_session(session_id, 10) == (2, [("Retry prompt", "Saved answer")])


def test_interrupted_generation_leaves_no_saved_exchange(store, mock_ollama, monkeypatch, capsys):
    mock_ollama()
    monkeypatch.setattr("src.cli.OllamaClient.generate", Mock(side_effect=KeyboardInterrupt))
    monkeypatch.setattr("builtins.input", lambda _: "Incomplete prompt")
    assert aika.main(["chat"]) == 0
    assert "Session ended." in capsys.readouterr().out
    assert store.list_sessions() == []
