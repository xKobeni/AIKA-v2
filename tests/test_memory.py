import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

import aika
from src.diagnostics import inspect_storage
from src.memory.store import MemoryInputError, MemoryStore
from src.storage import database
from src.storage.conversation_store import ConversationStore
from src.storage.database import APPLICATION_ID, CONVERSATION_SCHEMA, DATABASE_NAME, StorageError


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


def test_fact_normalization_timestamps_and_missing_lookup(store):
    assert store.get_fact("project", "Orion", "frontend") is None
    assert store.get_history("project", "Orion", "frontend") is None
    fact, previous = store.set_fact(" Project ", " Solar\t  Finch ", " Frontend  Framework ", " Next.js ")
    assert (fact.entity_type, fact.subject, fact.key, fact.value, fact.revision, previous) == (
        "project", "Solar Finch", "Frontend Framework", "Next.js", 1, None,
    )
    assert fact.created_at == fact.updated_at
    assert datetime.fromisoformat(fact.created_at).utcoffset() == timedelta(0)
    assert store.get_fact("PROJECT", "SOLAR   FINCH", "frontend framework") == fact
    assert store.list_facts("project", "solar finch") == [fact]


def test_revision_is_atomic_idempotent_and_independent_of_other_facts(tmp_path, store):
    first, _ = store.set_fact("project", "Orion", "Frontend", "Next.js")
    database_fact, _ = store.set_fact("project", "Orion", "database", "MySQL")
    nova, _ = store.set_fact("project", "Nova", "frontend", "Godot")
    other_type, _ = store.set_fact("team", "Orion", "frontend", "React")
    updated, previous = store.set_fact("project", "orion", "frontend", "SvelteKit", source="manual correction")
    assert (updated.id, updated.created_at, updated.key, updated.revision, previous) == (
        first.id, first.created_at, "Frontend", 2, "Next.js",
    )
    repeated, previous = store.set_fact("project", "Orion", "frontend", " SvelteKit ")
    assert (repeated, previous) == (updated, "SvelteKit")

    reopened = MemoryStore(tmp_path)
    active, history = reopened.get_history("project", "Orion", "frontend")
    assert active == updated
    assert [(item.revision, item.previous_value, item.value, item.source) for item in history] == [
        (1, None, "Next.js", "manual"), (2, "Next.js", "SvelteKit", "manual correction"),
    ]
    assert reopened.list_facts("project", "Orion") == [database_fact, updated]
    assert reopened.list_facts("project", "Nova") == [nova]
    assert reopened.list_facts("team", "Orion") == [other_type]


@pytest.mark.parametrize(("args", "error"), [
    (("", "Orion", "frontend", "Next.js"), "Entity type"),
    (("project", "   ", "frontend", "Next.js"), "Subject"),
    (("project", "Orion", "\x00", "Next.js"), "Key"),
    (("project", "Orion", "frontend", " \t "), "Value"),
    (("project", "Orion", "frontend", "invalid\nline"), "Value"),
])
def test_invalid_updates_preserve_existing_fact(store, args, error):
    original, _ = store.set_fact("project", "Orion", "frontend", "Next.js")
    with pytest.raises(MemoryInputError, match=error):
        store.set_fact(*args)
    active, history = store.get_history("project", "Orion", "frontend")
    assert active == original and len(history) == 1


def test_delete_requires_confirmation_and_cascades_only_selected_fact(tmp_path, store):
    fact, _ = store.set_fact("project", "Orion", "frontend", "Next.js")
    store.set_fact("project", "Orion", "frontend", "SvelteKit")
    other, _ = store.set_fact("project", "Orion", "database", "MySQL")
    session_id = uuid4().hex
    conversations = ConversationStore(tmp_path)
    conversations.save_exchange(session_id, 0, "Orion uses Next.js", "Understood")

    with pytest.raises(MemoryInputError, match="confirmation"):
        store.delete_fact("project", "Orion", "frontend")
    assert store.get_fact("project", "Orion", "frontend").value == "SvelteKit"
    assert store.delete_fact("PROJECT", "orion", "FRONTEND", confirm=True)
    assert not store.delete_fact("project", "Orion", "frontend", confirm=True)
    assert store.get_fact("project", "Orion", "frontend") is None
    assert store.list_facts("project", "Orion") == [other]
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM memory_revisions WHERE fact_id = ?", (fact.id,)).fetchone() == (0,)
    assert conversations.load_session(session_id, 10) == (2, [("Orion uses Next.js", "Understood")])


def test_revision_insert_failure_rolls_back_value_and_new_fact(store):
    original, _ = store.set_fact("project", "Orion", "frontend", "Next.js")
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("""CREATE TRIGGER fail_revision BEFORE INSERT ON memory_revisions
                      BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(StorageError, match="operation failed"):
        store.set_fact("project", "Orion", "frontend", "SvelteKit")
    with pytest.raises(StorageError, match="operation failed"):
        store.set_fact("project", "Orion", "database", "MySQL")
    active, history = store.get_history("project", "Orion", "frontend")
    assert active == original and len(history) == 1
    assert store.list_facts("project", "Orion") == [original]


@pytest.fixture
def phase_1c_database(tmp_path):
    path = tmp_path / DATABASE_NAME
    session_id = uuid4().hex
    timestamp = "2026-11-17T00:00:00+00:00"
    with closing(sqlite3.connect(path)) as db, db:
        for statement in CONVERSATION_SCHEMA:
            db.execute(statement)
        db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        db.execute("PRAGMA user_version = 1")
        db.execute("INSERT INTO conversation_sessions VALUES (?, ?, ?, ?)", (session_id, timestamp, timestamp, "Saved chat"))
        db.executemany("INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?, ?)", [
            (1, session_id, "user", "Existing question", 1, timestamp),
            (2, session_id, "assistant", "Existing answer", 2, timestamp),
        ])
    return path, session_id


def test_migrates_phase_1c_without_changing_existing_messages(phase_1c_database):
    path, session_id = phase_1c_database
    with closing(sqlite3.connect(path)) as db:
        original = db.execute("SELECT * FROM conversation_messages ORDER BY sequence").fetchall()
    assert inspect_storage(path.parent)[1].status == "WARN"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
    store = MemoryStore(path.parent)
    store.set_fact("project", "Orion", "frontend", "Next.js")
    reopened = ConversationStore(path.parent)
    assert reopened.schema_version == 2
    assert reopened.list_sessions() == [(session_id, "Saved chat")]
    assert reopened.load_session(session_id, 10) == (2, [("Existing question", "Existing answer")])
    assert inspect_storage(path.parent)[1].status == "PASS"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT * FROM conversation_messages ORDER BY sequence").fetchall() == original
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_failed_migration_rolls_back_schema_and_can_retry(phase_1c_database, monkeypatch):
    path, session_id = phase_1c_database
    with monkeypatch.context() as patch:
        patch.setattr(database, "MIGRATIONS", (CONVERSATION_SCHEMA, (database.MEMORY_SCHEMA[0], "INVALID SQL")))
        with pytest.raises(StorageError, match="operation failed"):
            MemoryStore(path.parent)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        assert db.execute("SELECT name FROM sqlite_schema WHERE name LIKE 'memory_%'").fetchall() == []
    assert ConversationStore(path.parent).load_session(session_id, 10) == (2, [("Existing question", "Existing answer")])
    assert MemoryStore(path.parent).schema_version == 2


def test_memory_cli_and_chat_remain_separate(capsys, mock_ollama, monkeypatch):
    scope = ["--type", "project", "--subject", "Orion", "--key", "frontend"]
    assert aika.main(["memory", "set", *scope, "--value", "Private framework"]) == 0
    assert "Revision: 1" in capsys.readouterr().out
    assert aika.main(["memory", "get", *scope]) == 0
    assert "frontend: Private framework" in capsys.readouterr().out
    assert aika.main(["memory", "delete", *scope]) == 1
    assert "--confirm" in capsys.readouterr().err

    mock_ollama()
    generate = Mock(return_value="Could you tell me which framework?")
    monkeypatch.setattr("src.cli.OllamaClient.generate", generate)
    inputs = iter(["Let's chat about Orion.", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert aika.main(["chat"]) == 0
    messages = generate.call_args.args[0]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert all("Private framework" not in message["content"] for message in messages)

    assert aika.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "PASS  Structured Memory: READY" in output and "Automatic Memory: NOT IMPLEMENTED" in output
    assert "Private framework" not in output
    assert aika.main(["memory", "delete", *scope, "--confirm"]) == 0
    assert "revisions deleted" in capsys.readouterr().out
    assert aika.main(["memory", "get", *scope]) == 1
    assert "Fact not found" in capsys.readouterr().err
