import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


DATABASE_NAME = "conversations.sqlite3"
APPLICATION_ID = 0x41494B41
CONVERSATION_SCHEMA = (
    """CREATE TABLE conversation_sessions (
        id TEXT PRIMARY KEY NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        title TEXT
    )""",
    """CREATE TABLE conversation_messages (
        id INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES conversation_sessions(id),
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        created_at TEXT NOT NULL,
        CHECK ((sequence % 2 = 1 AND role = 'user') OR (sequence % 2 = 0 AND role = 'assistant')),
        UNIQUE (session_id, sequence)
    )""",
    """CREATE INDEX conversation_sessions_recent ON conversation_sessions(updated_at DESC, id)""",
)
MEMORY_SCHEMA = (
    """CREATE TABLE memory_facts (
        id TEXT PRIMARY KEY NOT NULL,
        entity_type TEXT NOT NULL CHECK (length(trim(entity_type)) > 0),
        subject TEXT NOT NULL CHECK (length(trim(subject)) > 0),
        normalized_subject TEXT NOT NULL CHECK (length(normalized_subject) > 0),
        key TEXT NOT NULL CHECK (length(trim(key)) > 0),
        normalized_key TEXT NOT NULL CHECK (length(normalized_key) > 0),
        value TEXT NOT NULL CHECK (length(trim(value)) > 0),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        UNIQUE (entity_type, normalized_subject, normalized_key)
    )""",
    """CREATE TABLE memory_revisions (
        fact_id TEXT NOT NULL REFERENCES memory_facts(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL CHECK (revision > 0),
        previous_value TEXT,
        value TEXT NOT NULL CHECK (length(trim(value)) > 0),
        created_at TEXT NOT NULL,
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        CHECK ((revision = 1 AND previous_value IS NULL) OR (revision > 1 AND previous_value IS NOT NULL)),
        PRIMARY KEY (fact_id, revision)
    )""",
)
MIGRATIONS = (CONVERSATION_SCHEMA, MEMORY_SCHEMA)
SCHEMA_VERSION = len(MIGRATIONS)


class StorageError(Exception):
    """A storage failure safe to show without a path or conversation content."""


class Database:
    def __init__(self, data_dir: Path, *, create: bool = True):
        self.path = data_dir / DATABASE_NAME
        if create:
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise StorageError("Cannot create the database directory. Check AIKA_DATA_DIR and its permissions.") from None

        with self._transaction(write=create, create=create) as db:
            application_id = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            definitions = {" ".join(sql.split()) for (sql,) in db.execute(
                "SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL AND name NOT GLOB 'sqlite_*'"
            )}
            is_new = create and application_id == version == 0 and not definitions
            if not is_new and (application_id != APPLICATION_ID or not 1 <= version <= SCHEMA_VERSION):
                raise StorageError("Incompatible AIKA database or schema version. The database was left in place.")
            expected = {" ".join(statement.split()) for migration in MIGRATIONS[:version] for statement in migration}
            if definitions != expected:
                raise StorageError("The database schema does not match this version of AIKA.")

            if create and version < SCHEMA_VERSION:
                for migration in MIGRATIONS[version:]:
                    for statement in migration:
                        db.execute(statement)
                db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                version = SCHEMA_VERSION
            self.schema_version = version

    @contextmanager
    def _transaction(
        self, *, write: bool = False, create: bool = False, probe: bool = False,
        connection: sqlite3.Connection | None = None,
    ):
        if connection is not None:
            yield connection
            return
        mode = "rwc" if create else "rw"
        try:
            with closing(sqlite3.connect(f"{self.path.as_uri()}?mode={mode}", uri=True, timeout=3, isolation_level=None)) as db:
                db.execute("PRAGMA foreign_keys = ON")
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db
                if probe:
                    db.rollback()
                else:
                    db.commit()
        except sqlite3.Error as exc:
            code = getattr(exc, "sqlite_errorcode", 0) & 0xff
            if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
                raise StorageError("The AIKA database is corrupt or is not a SQLite database.") from None
            if code in {sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM, sqlite3.SQLITE_CANTOPEN}:
                raise StorageError("Cannot write to or open the AIKA database. Check AIKA_DATA_DIR and its permissions.") from None
            if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise StorageError("The AIKA database is busy. Wait for the other operation and try again.") from None
            if code == sqlite3.SQLITE_FULL:
                raise StorageError("The AIKA database ran out of disk space.") from None
            raise StorageError("The AIKA database operation failed. Run doctor to check storage.") from None
