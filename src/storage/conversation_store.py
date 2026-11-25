import re
import sqlite3
import sys
from datetime import UTC, datetime
from uuid import uuid4

from src.storage.database import Database, StorageError


class ConversationStore(Database):
    def context_statements(self, session_id: str, sequence: int) -> list[tuple[int, int, str]]:
        """Read at most 96 user rows/601 characters each from this active-session prefix."""
        if not re.fullmatch(r"[0-9a-f]{32}", session_id) or type(sequence) is not int or sequence < 0:
            raise StorageError("Invalid active conversation context boundary.")
        with self._transaction() as db:
            db.execute("PRAGMA query_only = ON")
            return db.execute(
                """SELECT id, sequence, substr(content, 1, 601) FROM conversation_messages
                   WHERE session_id = ? AND role = 'user' AND sequence <= ?
                   ORDER BY sequence DESC LIMIT 96""", (session_id, sequence),
            ).fetchall()

    def list_sessions(self) -> list[tuple[str, str | None]]:
        with self._transaction() as db:
            return db.execute(
                "SELECT id, title FROM conversation_sessions ORDER BY updated_at DESC, id"
            ).fetchall()

    def load_session(self, session_id: str, context_turns: int) -> tuple[int, list[tuple[str, str]]]:
        if not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise StorageError("Invalid conversation ID. Copy the full ID shown by /sessions.")

        with self._transaction() as db:
            if not db.execute("SELECT 1 FROM conversation_sessions WHERE id = ?", (session_id,)).fetchone():
                raise StorageError("Conversation not found. Use /sessions to see saved conversations.")
            sequence = self._last_sequence(db, session_id)
            rows = db.execute(
                """SELECT sequence, content FROM conversation_messages WHERE session_id = ?
                   ORDER BY sequence DESC LIMIT ?""",
                (session_id, min(context_turns * 2, sys.maxsize - 1)),
            ).fetchall()
            if (
                sequence % 2
                or len(rows) != min(sequence, context_turns * 2)
                or any(number != sequence - offset for offset, (number, _) in enumerate(rows))
            ):
                raise StorageError("The conversation contains incomplete history and could not be resumed.")
            contents = [content for _, content in reversed(rows)]
            return sequence, list(zip(contents[::2], contents[1::2], strict=True))

    @staticmethod
    def _last_sequence(db: sqlite3.Connection, session_id: str) -> int:
        return db.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM conversation_messages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]

    def save_exchange(
        self, session_id: str, expected_sequence: int, user: str, assistant: str,
        *, connection: sqlite3.Connection | None = None,
    ) -> int:
        with self._transaction(write=True, connection=connection) as db:
            if self._last_sequence(db, session_id) != expected_sequence:
                raise StorageError("This conversation changed in another session. Resume it again before retrying.")

            timestamp = datetime.now(UTC).isoformat()
            if expected_sequence == 0:
                db.execute(
                    "INSERT INTO conversation_sessions (id, created_at, updated_at, title) VALUES (?, ?, ?, ?)",
                    (session_id, timestamp, timestamp, " ".join(user.split())[:60]),
                )
            else:
                db.execute("UPDATE conversation_sessions SET updated_at = ? WHERE id = ?", (timestamp, session_id))
            db.executemany(
                """INSERT INTO conversation_messages (session_id, role, content, sequence, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                ((session_id, "user", user, expected_sequence + 1, timestamp),
                 (session_id, "assistant", assistant, expected_sequence + 2, timestamp)),
            )
        return expected_sequence + 2

    def verify(self) -> None:
        with self._transaction(write=True, probe=True) as db:
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",) or db.execute("PRAGMA foreign_key_check").fetchone():
                raise StorageError("The AIKA database failed its SQLite integrity checks.")
            if self.schema_version >= 2:
                db.execute("SELECT 1 FROM memory_facts LIMIT 1").fetchone()
                db.execute("SELECT 1 FROM memory_revisions LIMIT 1").fetchone()
            timestamp = datetime.now(UTC).isoformat()
            db.execute(
                "INSERT INTO conversation_sessions (id, created_at, updated_at) VALUES (?, ?, ?)",
                (uuid4().hex, timestamp, timestamp),
            )
