import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from src.storage.database import Database


FACT_COLUMNS = "id, entity_type, subject, key, value, source, created_at, updated_at, revision"
FACT_SCOPE = "entity_type = ? AND normalized_subject = ? AND normalized_key = ?"


class MemoryInputError(ValueError):
    """A validation or confirmation error safe to display."""


@dataclass(frozen=True)
class Fact:
    id: str
    entity_type: str
    subject: str
    key: str
    value: str
    source: str
    created_at: str
    updated_at: str
    revision: int


@dataclass(frozen=True)
class Revision:
    fact_id: str
    revision: int
    previous_value: str | None
    value: str
    created_at: str
    source: str


def _text(raw: str, label: str, *, collapse_whitespace: bool = False) -> str:
    if not isinstance(raw, str):
        raise MemoryInputError(f"{label} must be nonempty printable text.")
    if collapse_whitespace:
        raw = " ".join(raw.split())
    cleaned = raw.strip()
    if not cleaned or not cleaned.isprintable():
        raise MemoryInputError(f"{label} must be nonempty printable text.")
    return cleaned


def _scope(entity_type: str, subject: str, key: str) -> tuple[str, str, str]:
    return (
        _text(entity_type, "Entity type", collapse_whitespace=True).casefold(),
        _text(subject, "Subject", collapse_whitespace=True).casefold(),
        _text(key, "Key", collapse_whitespace=True).casefold(),
    )


class MemoryStore(Database):
    """Structured facts managed explicitly, independently of chat and Ollama."""

    def context_facts(self, subjects: tuple[str, ...], keys: tuple[str, ...]) -> tuple[int, list[Fact]]:
        """Bounded exact project/property lookup of active facts only; never read revisions."""
        if not subjects or not keys or len(subjects)>256 or len(keys)>272:
            return 0, []
        with self._transaction() as db:
            db.execute("PRAGMA query_only = ON")
            names = db.execute(
                "SELECT DISTINCT normalized_subject FROM memory_facts WHERE entity_type = 'project' "
                f"AND normalized_subject IN ({','.join('?' for _ in subjects)}) LIMIT 2", subjects,
            ).fetchall()
            if len(names)!=1:
                return len(names), []
            rows = db.execute(
                "SELECT id, entity_type, subject, key, substr(value,1,601), substr(source,1,129), "
                "created_at, updated_at, revision FROM memory_facts WHERE entity_type = 'project' "
                f"AND normalized_subject = ? AND normalized_key IN ({','.join('?' for _ in keys)}) "
                "ORDER BY normalized_key LIMIT 3", (names[0][0], *keys),
            ).fetchall()
            return 1, [Fact(*row) for row in rows]

    @staticmethod
    def _find(db: sqlite3.Connection, scope: tuple[str, str, str]) -> Fact | None:
        row = db.execute(f"SELECT {FACT_COLUMNS} FROM memory_facts WHERE {FACT_SCOPE}", scope).fetchone()
        return Fact(*row) if row else None

    def set_fact(
        self, entity_type: str, subject: str, key: str, value: str, *, source: str = "manual",
        connection: sqlite3.Connection | None = None,
    ) -> tuple[Fact, str | None]:
        """Return the active fact and its prior value, if one existed."""
        subject = _text(subject, "Subject", collapse_whitespace=True)
        key = _text(key, "Key", collapse_whitespace=True)
        scope = _scope(entity_type, subject, key)
        value = _text(value, "Value")
        source = _text(source, "Source")

        with self._transaction(write=True, connection=connection) as db:
            existing = self._find(db, scope)
            previous = existing.value if existing else None
            if existing is not None and previous == value:
                return existing, previous

            now = datetime.now(UTC).isoformat()
            if existing is None:
                fact = Fact(uuid4().hex, scope[0], subject, key, value, source, now, now, 1)
                db.execute(
                    """INSERT INTO memory_facts (
                        id, entity_type, subject, normalized_subject, key, normalized_key,
                        value, source, created_at, updated_at, revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fact.id, fact.entity_type, subject, scope[1], key, scope[2], value, source, now, now, fact.revision),
                )
            else:
                fact = Fact(
                    existing.id, existing.entity_type, existing.subject, existing.key,
                    value, source, existing.created_at, now, existing.revision + 1,
                )
                db.execute(
                    "UPDATE memory_facts SET value = ?, source = ?, updated_at = ?, revision = ? WHERE id = ?",
                    (value, source, now, fact.revision, fact.id),
                )

            db.execute(
                """INSERT INTO memory_revisions (fact_id, revision, previous_value, value, created_at, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (fact.id, fact.revision, previous, value, now, source),
            )
        return fact, previous

    def get_fact(
        self, entity_type: str, subject: str, key: str, *, connection: sqlite3.Connection | None = None,
    ) -> Fact | None:
        scope = _scope(entity_type, subject, key)
        with self._transaction(connection=connection) as db:
            return self._find(db, scope)

    def list_facts(
        self, entity_type: str, subject: str, *, connection: sqlite3.Connection | None = None,
    ) -> list[Fact]:
        scope = (
            _text(entity_type, "Entity type", collapse_whitespace=True).casefold(),
            _text(subject, "Subject", collapse_whitespace=True).casefold(),
        )
        with self._transaction(connection=connection) as db:
            rows = db.execute(
                f"SELECT {FACT_COLUMNS} FROM memory_facts "
                "WHERE entity_type = ? AND normalized_subject = ? ORDER BY normalized_key", scope,
            )
            return [Fact(*row) for row in rows]

    def find_value(self, entity_type: str, value: str, *, connection: sqlite3.Connection | None = None) -> list[Fact]:
        with self._transaction(connection=connection) as db:
            rows = db.execute(
                f"SELECT {FACT_COLUMNS} FROM memory_facts WHERE entity_type = ? AND value = ? COLLATE NOCASE "
                "ORDER BY normalized_subject, normalized_key",
                (_text(entity_type, "Entity type", collapse_whitespace=True).casefold(), _text(value, "Value")),
            )
            return [Fact(*row) for row in rows]

    def get_history(
        self, entity_type: str, subject: str, key: str, *, connection: sqlite3.Connection | None = None,
    ) -> tuple[Fact, list[Revision]] | None:
        scope = _scope(entity_type, subject, key)
        with self._transaction(connection=connection) as db:
            fact = self._find(db, scope)
            if fact is None:
                return None
            rows = db.execute(
                """SELECT fact_id, revision, previous_value, value, created_at, source
                   FROM memory_revisions WHERE fact_id = ? ORDER BY revision""",
                (fact.id,),
            )
            return fact, [Revision(*row) for row in rows]

    def delete_fact(
        self, entity_type: str, subject: str, key: str, *, confirm: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        if confirm is not True:
            raise MemoryInputError("Deleting a fact and its revisions requires explicit confirmation.")
        scope = _scope(entity_type, subject, key)
        with self._transaction(write=True, connection=connection) as db:
            return db.execute(f"DELETE FROM memory_facts WHERE {FACT_SCOPE}", scope).rowcount == 1
