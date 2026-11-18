import sqlite3
import subprocess
import sys
from contextlib import closing
from uuid import uuid4

import pytest

import aika
from src.diagnostics import inspect_storage
from src.storage.conversation_store import ConversationStore
from src.storage.database import DATABASE_NAME, SCHEMA_VERSION, StorageError


def test_schema_initialization_enforces_foreign_keys_and_preserves_existing_chats(tmp_path):
    store = ConversationStore(tmp_path)
    session_id = uuid4().hex
    with store._transaction() as db:
        assert db.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
        tables = db.execute("SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name").fetchall()
        assert tables == [("conversation_messages",), ("conversation_sessions",), ("memory_facts",), ("memory_revisions",)]

    with pytest.raises(StorageError), store._transaction(write=True) as db:
        db.execute(
            "INSERT INTO conversation_messages (session_id, role, content, sequence, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, "user", "orphan", 1, "timestamp"),
        )

    assert store.save_exchange(session_id, 0, "Orion's first message", "First reply") == 2
    reopened = ConversationStore(tmp_path)
    assert reopened.save_exchange(session_id, 2, "Second message", "Second reply") == 4
    assert reopened.list_sessions() == [(session_id, "Orion's first message")]
    assert reopened.load_session(session_id, 1) == (4, [("Second message", "Second reply")])
    assert ConversationStore(tmp_path).load_session(session_id, 10) == (
        4, [("Orion's first message", "First reply"), ("Second message", "Second reply")],
    )


def test_failed_second_insert_rolls_back_first_message_and_new_session(tmp_path):
    store = ConversationStore(tmp_path)
    original_id = uuid4().hex
    store.save_exchange(original_id, 0, "Preserved", "Original answer")
    with closing(sqlite3.connect(store.path)) as db, db:
        original_timestamp = db.execute("SELECT updated_at FROM conversation_sessions").fetchone()
        db.execute("""CREATE TRIGGER fail_assistant BEFORE INSERT ON conversation_messages
                      WHEN NEW.role = 'assistant' BEGIN SELECT RAISE(ABORT, 'simulated failure'); END""")
    for session_id, sequence in [(uuid4().hex, 0), (original_id, 2)]:
        with pytest.raises(StorageError, match="operation failed"):
            store.save_exchange(session_id, sequence, "Uncommitted user text", "Uncommitted answer")
    assert store.list_sessions() == [(original_id, "Preserved")]
    assert store.load_session(original_id, 10) == (2, [("Preserved", "Original answer")])
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT updated_at FROM conversation_sessions").fetchone() == original_timestamp


def test_abrupt_process_exit_rolls_back_unfinished_exchange(tmp_path):
    store = ConversationStore(tmp_path)
    session_id = uuid4().hex
    store.save_exchange(session_id, 0, "First", "First reply")
    script = """
import os
import sqlite3
import sys
from pathlib import Path
from src.storage.conversation_store import ConversationStore

store = ConversationStore(Path(sys.argv[1]))
connect = sqlite3.connect

class InterruptedConnection(sqlite3.Connection):
    def executemany(self, sql, parameters):
        self.execute(sql, next(iter(parameters)))
        os._exit(17)

sqlite3.connect = lambda *args, **kwargs: connect(*args, factory=InterruptedConnection, **kwargs)
store.save_exchange(sys.argv[2], 2, "Interrupted user message", "Interrupted reply")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), session_id], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 17, result.stderr
    reopened = ConversationStore(tmp_path)
    assert reopened.load_session(session_id, 10) == (2, [("First", "First reply")])
    reopened.save_exchange(session_id, 2, "Retry", "Second reply")
    assert reopened.load_session(session_id, 10) == (4, [("First", "First reply"), ("Retry", "Second reply")])


def test_stale_session_cannot_append_against_older_context(tmp_path):
    store = ConversationStore(tmp_path)
    session_id = uuid4().hex
    store.save_exchange(session_id, 0, "First", "First reply")
    other = ConversationStore(tmp_path)
    assert other.load_session(session_id, 0) == (2, [])
    store.save_exchange(session_id, 2, "Second", "Second reply")
    with pytest.raises(StorageError, match="Resume it again"):
        other.save_exchange(session_id, 2, "Stale prompt", "Stale reply")
    assert other.load_session(session_id, 10) == (4, [("First", "First reply"), ("Second", "Second reply")])


def test_doctor_preserves_database_and_rejects_incompatible_version(tmp_path):
    store = ConversationStore(tmp_path)
    session_id = uuid4().hex
    store.save_exchange(session_id, 0, "Keep this", "Saved reply")
    assert inspect_storage(tmp_path)[0].status == "PASS"
    assert store.list_sessions() == [(session_id, "Keep this")]
    assert store.load_session(session_id, 10) == (2, [("Keep this", "Saved reply")])
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("PRAGMA user_version = 99")
    before = store.path.read_bytes()
    assert inspect_storage(tmp_path)[0].status == "FAIL"
    with pytest.raises(StorageError, match="Incompatible"):
        ConversationStore(tmp_path)
    assert store.path.read_bytes() == before


def test_doctor_detects_read_only_database(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path)
    connect = sqlite3.connect

    def read_only(database, **kwargs):
        return connect(database.replace("?mode=rw", "?mode=ro"), **kwargs)

    monkeypatch.setattr(sqlite3, "connect", read_only)
    check = inspect_storage(tmp_path)[0]
    assert check.status == "FAIL"
    assert "Cannot write" in check.detail
    assert store.list_sessions() == []


def test_corrupt_storage_prevents_chat_without_overwriting_file(tmp_path, capsys, mock_ollama):
    path = tmp_path / DATABASE_NAME
    data = b"not a SQLite database"
    path.write_bytes(data)
    mock_ollama(lambda request: pytest.fail("Unexpected Ollama request"))
    assert aika.main(["chat"]) == 1
    output = capsys.readouterr()
    assert "Storage error:" in output.err and "corrupt" in output.err
    assert "Traceback" not in output.err
    assert path.read_bytes() == data


def test_unrecognized_sqlite_database_is_preserved(tmp_path):
    path = tmp_path / DATABASE_NAME
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")
    before = path.read_bytes()
    with pytest.raises(StorageError, match="Incompatible"):
        ConversationStore(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(("session_id", "error"), [
    ("1", "Invalid conversation ID"),
    ("0" * 32, "Conversation not found"),
])
def test_load_rejects_invalid_or_missing_ids(tmp_path, session_id, error):
    store = ConversationStore(tmp_path)
    with pytest.raises(StorageError, match=error):
        store.load_session(session_id, 10)
