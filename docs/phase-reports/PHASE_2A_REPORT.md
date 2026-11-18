# AIKA V2 Phase 2A — Structured memory storage

**Status** — READY FOR MANUAL REVIEW  
**Approval** — Pending manual review

## Implementation

`python -m aika memory` manages facts through `set`, `get`, `list`, `history`, and `delete`. The commands use a typed Python store and work without model inference. Regular chat still receives its conversation transcript alone. The selected Ollama model and configuration behavior were preserved.

Facts are scoped by entity type, subject, and key. Lookup uses Unicode case folding and collapses identifier whitespace to single spaces. The stored display spelling of the subject and key comes from creation. Values are printable text with outer whitespace trimmed. Each new fact gets a stable ID and revision 1. Updating a value keeps the ID and atomically records the previous value, new value, source, and next revision in UTC. Repeating the same normalized input value leaves the fact and its history intact.

Deletion requires `--confirm` in the CLI and `confirm=True` in the Python API. It removes the selected fact and its revisions from the active database. This operation leaves conversation transcripts and unrelated facts intact. Copies in backups or residual SQLite data may still exist. [SQLite foreign-key actions](https://sqlite.org/foreignkeys.html#fk_actions)

## Migration and schema

Both stores use `AIKA_DATA_DIR/conversations.sqlite3`. An empty database is initialized to schema 2. Opening a compatible Phase 1C database through `chat` or `memory` adds two tables in one transaction and sets `user_version` to 2. The original conversation schema, IDs, and rows are preserved. A failed migration rolls back the new tables and version change. Unknown application IDs, versions, and unexpected schemas are rejected. A version 1 binary can reject the upgraded file. [SQLite transactions](https://sqlite.org/lang_transaction.html)

| Table | Purpose and constraints |
| --- | --- |
| `memory_facts` | One active text value per unique normalized entity type, subject, and key. Stores the stable ID, display subject and key, source, timestamps, and current revision number. |
| `memory_revisions` | Ordered revisions keyed by `(fact_id, revision)`. Stores previous and new values, source, and UTC time. The fact foreign key cascades on confirmed deletion. |

`doctor` checks schema compatibility, SQLite quick and foreign-key integrity, and writability with a rolled-back probe. It checks access to the fact and revision tables and reports structured memory as ready once the configured database is on schema 2. It warns about pending migration without upgrading the configured database. It does not display stored facts.

## Files changed

| File | Change |
| --- | --- |
| `src/storage/database.py`, `src/storage/conversation_store.py` | Shared SQLite initialization and transaction handling, additive migration, and storage checks. |
| `src/memory/store.py`, `src/memory/cli.py` | Typed fact and revision operations plus explicit command formatting and deletion confirmation. |
| `src/cli.py`, `src/diagnostics.py`, `pyproject.toml` | Registered the command, diagnostics, and package. |
| `tests/test_memory.py`, `tests/test_conversation_store.py`, `tests/test_runtime.py` | Added memory and migration tests and updated schema and phase expectations. |
| `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, and this report | Documented the commands, scope, storage, and verification. |

## Verification

- **86 baseline tests passed** before editing. **98 tests passed** after implementation on Windows with Python 3.12.10.
- Automated tests covered normalization, missing and invalid facts, repeated updates, subject and entity type isolation, confirmed deletion, revision rollback, and a failed migration that could be retried. A mocked chat checked that saved facts were absent from its model request.
- Separate live CLI processes saved Orion's Next.js and MySQL facts and Nova's Godot fact, revised Next.js to SvelteKit, and read both revisions. Repeating SvelteKit preserved revision 2. An unconfirmed deletion was refused. Confirmed deletion removed only the frontend fact and its revisions.
- The live walkthrough used a temporary Phase 1C database. After upgrading it, a fresh chat listed and resumed the existing Atlas session and `qwen3.5:4b` answered PostgreSQL from its transcript. The two original message rows matched exactly, SQLite `integrity_check` returned `ok`, and doctor reported structured memory ready without disclosing stored values.
- Runtime status, doctor, version, and help succeeded. Verification used synthetic or temporary databases. The user's actual archive and V1 data were outside these migration tests.
- The editable install and `pip check` passed, and `python -m aika memory --help` worked from outside the checkout.

## Manual acceptance

From the V2 root, use a dedicated PowerShell window and a temporary data directory. Keep Ollama open for the chat check.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-2a-review-' + [guid]::NewGuid().ToString('N'))

& $python -m aika memory set --type project --subject Orion --key frontend --value Next.js
& $python -m aika memory set --type project --subject Orion --key database --value MySQL
& $python -m aika memory set --type project --subject Nova --key engine --value Godot
& $python -m aika memory set --type project --subject Orion --key frontend --value SvelteKit
& $python -m aika memory history --type project --subject Orion --key frontend
& $python -m aika memory list --type project --subject Orion
& $python -m aika memory get --type project --subject Nova --key engine

& $python -m aika memory delete --type project --subject Orion --key frontend
& $python -m aika memory delete --type project --subject Orion --key frontend --confirm
& $python -m aika memory get --type project --subject Orion --key frontend
& $python -m aika memory list --type project --subject Orion
```

- [ ] History shows revision 1 as Next.js, revision 2 as SvelteKit, and SvelteKit as current. Each command is a separate process.
- [ ] Orion's database is MySQL and Nova's engine is Godot after the update. The unconfirmed deletion is refused. After confirmation, frontend is absent and database still exists.
- [ ] Run `& $python -m aika chat`, enter `My project Atlas uses PostgreSQL.`, and exit. Start chat again, run `/sessions`, and `/resume <session_id>` with Atlas's full ID. Ask `What database does Atlas use?` and expect PostgreSQL from the restored transcript.
- [ ] Exit chat, then run the regression commands below. Doctor should show `Structured Memory: READY` and `Automatic Memory: NOT IMPLEMENTED`.

```powershell
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m aika --help
& $python -m pytest -q
```

## Limits and next checkpoint

This checkpoint supports single-valued text facts through explicit commands. Chat does not automatically extract or retrieve them. Manual acceptance is pending. Phase 2B is the next checkpoint after approval. No Git commit or tag was created.
