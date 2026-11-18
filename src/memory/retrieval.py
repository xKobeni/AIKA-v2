import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from src.memory.store import Fact, MemoryInputError, Revision
from src.memory.intent import parse_intent


MAX_MATCHES = 5
MAX_EXCERPT = 400


@dataclass(frozen=True)
class Retrieval:
    source_type: Literal["structured_fact", "fact_revision", "current_session", "archived_conversation"]
    value: str
    subject: str | None = None
    key: str | None = None
    fact_id: str | None = None
    revision: int | None = None
    source: str | None = None
    session_id: str | None = None
    message_id: int | None = None
    role: str | None = None
    created_at: str | None = None


def fact_evidence(fact: Fact, revision: Revision | None = None) -> Retrieval:
    return Retrieval(
        "fact_revision" if revision else "structured_fact",
        revision.value if revision else fact.value,
        subject=fact.subject, key=fact.key, fact_id=fact.id,
        revision=revision.revision if revision else fact.revision,
        source=revision.source if revision else fact.source,
        created_at=revision.created_at if revision else fact.updated_at,
    )


def search_archive(
    db: sqlite3.Connection, terms: tuple[str, ...], *, limit: int = MAX_MATCHES,
    session_id: str | None = None, scope: Literal["all", "other", "current"] = "all",
) -> tuple[Retrieval, ...]:
    """Find literal terms in user-authored messages, keeping the newest duplicate."""
    if not terms or len(terms) > 8 or not 1 <= limit <= MAX_MATCHES:
        raise MemoryInputError("Use one to eight specific search terms and at most five results.")
    if scope not in {"all", "other", "current"} or (scope != "all" and session_id is None):
        raise MemoryInputError("A scoped conversation search needs an active session.")
    normalized = tuple(" ".join(term.casefold().split()) for term in terms)
    if any(not re.fullmatch(r"[\w .+#/-]+", term) or len(term) < 2 for term in normalized) or sum(map(len, normalized)) > 120:
        raise MemoryInputError("Use specific printable search terms, up to 120 characters in total.")
    patterns = [re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)") for term in normalized]

    def matches(content: str) -> bool:
        text = " ".join(content.casefold().split())
        if not all(pattern.search(text) for pattern in patterns):
            return False
        intent = parse_intent(content)
        return intent is None or intent.action in {"save", "statement", "correct"}

    db.create_function("aika_archive_match", 1, matches, deterministic=True)
    try:
        # Existing archives are small. A bounded literal scan avoids a second index lifecycle.
        rows = db.execute(
            """WITH matches AS (
                SELECT id, session_id, role, content, created_at,
                       ROW_NUMBER() OVER (PARTITION BY content ORDER BY created_at DESC, id DESC) AS duplicate
                FROM conversation_messages WHERE role = 'user' AND aika_archive_match(content)
                    AND (? = 'all' OR (? = 'other' AND session_id != ?) OR (? = 'current' AND session_id = ?))
            ) SELECT id, session_id, role, content, created_at FROM matches
              WHERE duplicate = 1 ORDER BY created_at DESC, id DESC LIMIT ?""",
            (scope, scope, session_id, scope, session_id, limit),
        ).fetchall()
    finally:
        db.create_function("aika_archive_match", 1, None)

    results = []
    for message_id, session_id, role, content, timestamp in rows:
        text = " ".join(content.split())
        position = text.casefold().find(normalized[0])
        start = max(0, position - 80) if len(text) > MAX_EXCERPT else 0
        excerpt = text[start:start + MAX_EXCERPT]
        if start:
            excerpt = "…" + excerpt
        if start + MAX_EXCERPT < len(text):
            excerpt += "…"
        results.append(Retrieval("archived_conversation", excerpt, session_id=session_id, message_id=message_id,
                                 role=role, created_at=timestamp))
    return tuple(results)


def last_session_statement(
    db: sqlite3.Connection, session_id: str, sequence: int,
) -> Retrieval | None:
    if sequence == 0:
        return None
    row = db.execute(
        """SELECT id, role, content, created_at FROM conversation_messages
           WHERE session_id = ? AND sequence = ? AND role = 'user'""",
        (session_id, sequence - 1),
    ).fetchone()
    if row is None:
        return None
    message_id, role, content, timestamp = row
    excerpt = content[:MAX_EXCERPT] + ("…" if len(content) > MAX_EXCERPT else "")
    return Retrieval("current_session", excerpt, session_id=session_id, message_id=message_id,
                     role=role, created_at=timestamp)
