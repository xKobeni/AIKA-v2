# AIKA V2 Phase 1C — Persistent conversation history

**Status** — READY FOR MANUAL REVIEW  
**Date** — 2026-11-17  
**Approval** — Pending manual review

The [Qwen3.5 reliability report](MODEL_UPGRADE_QWEN35_REPORT.md) records later model and prompt changes and verifies that saved chats still resume with the same schema.

## Behavior

Chat uses `AIKA_DATA_DIR/conversations.sqlite3`. On Windows the default directory is `%LOCALAPPDATA%\AIKA AI V2\data`. Each launch begins with an empty active chat. A stable session ID appears in `/status` and enters the saved list after the first completed exchange. `/sessions` shows saved IDs alongside a short preview of the first message. `/resume <session_id>` restores the most recent completed turns, up to `AIKA_CONTEXT_TURNS`, in chronological order. `/new` and `/clear` switch to a fresh ID and keep the previous chat in the archive.

The model generates a reply first. The store then commits the user and assistant messages together, including the session update. Only after commit does AIKA update its active context and show the reply. Generation errors, interruption, and storage failures leave the previous history intact. If another terminal writes to the same chat first, the stale write is rejected and the user is prompted to resume again.

## Database schema

| Table | Columns and constraints |
| --- | --- |
| `conversation_sessions` | Stable text `id` primary key, UTC `created_at` and `updated_at`, optional `title`. The last-update and ID index supports the saved-chat list. |
| `conversation_messages` | Integer `id` primary key, `session_id` foreign key, `role`, `content`, positive `sequence`, and UTC `created_at`. A unique `(session_id, sequence)` index supports ordered retrieval. Odd sequences are user messages and even sequences are assistant messages. |

SQLite `application_id` and `user_version` identify AIKA's version 1 schema. Initialization creates missing tables only in an empty, unversioned database and refuses incompatible files. Connections enable foreign keys and a three-second lock wait. Parameterized SQL writes run in explicit transactions. This checkpoint follows the Phase 1C brief's two-table design and commits only completed exchanges. Persisting individual request attempts is outside this checkpoint. [SQLite transactions](https://sqlite.org/lang_transaction.html)

Doctor checks the existing schema, runs SQLite `quick_check` and `foreign_key_check`, and rolls back a write probe. With no database yet, it checks a temporary database in the configured directory or its closest existing parent. The production database is created by chat. Storage errors include useful next steps without printing conversation content or raw database errors. [SQLite PRAGMA reference](https://sqlite.org/pragma.html)

## Files changed

| Path | Change |
| --- | --- |
| `src/storage/conversation_store.py` | Added schema initialization, session listing and restoration, transactional saves, and storage verification. |
| `src/intelligence/conversation.py` | Connected the existing request flow to the store and restored bounded context by session ID. |
| `src/cli.py`, `src/diagnostics.py` | Added session commands, storage errors, and the SQLite doctor check. |
| `pyproject.toml` | Included `src.storage` in the package. SQLite uses Python's standard library. |
| `tests/test_conversation_store.py`, `tests/test_conversation.py`, `tests/test_runtime.py` | Covered the schema, rollback and crash recovery, resume, input isolation, and previous CLI behavior using temporary databases. |
| `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, and this report | Documented session commands, storage, troubleshooting, and checkpoint scope. |

## Verification

- Before implementation, all **59** Phase 1B tests passed. The final `python -m pytest -q` run passed **72 tests** on Windows with Python 3.12.10. Automated tests used temporary databases and mocked generation. A child process exited abruptly after its first insert, and reopening the database preserved the previous exchange and rolled back the interrupted one.
- Live CLI runs used the installed `qwen2.5:3b` model and a temporary database. Orion's database answer was PostgreSQL. After a process restart and resume, the frontend answer was Next.js. With `AIKA_CONTEXT_TURNS=2`, the resumed history showed two turns. The original chat retained its earlier turns, and a fresh chat asked for more information about the project. `/clear` emptied the active context and left Orion available to resume again.
- After repeated starts, SQLite `integrity_check` returned `ok`. The temporary archive contained two saved sessions and ten messages, including eight consecutively numbered messages in Orion's chat. Doctor passed both its fresh-directory and existing-database probes without adding sessions or messages.
- The editable install and `pip check` passed. Runtime status, `--version`, and `--help` worked from outside the checkout.

## Manual acceptance

Use a temporary data directory for the walkthrough so example chats are separate from your regular history. These commands are intended for a dedicated PowerShell window from the V2 root. Ollama should already be running.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-1c-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_CONTEXT_TURNS = '2'
& $python -m aika doctor
& $python -m aika chat
```

1. Enter `My project Orion uses Next.js and PostgreSQL.` Then ask `What database does Orion use?` Expect PostgreSQL. Ask `Which of those technologies is its frontend?` This gives the chat three completed exchanges. Enter `/exit`.
2. Rerun `& $python -m aika chat`. Use `/sessions` to find Orion's ID, then enter `/resume <session_id>` with the full copied ID. `/history` should show the two latest completed turns. Ask `What frontend framework did Orion use?` Expect Next.js.
3. Enter `/new`, then ask `What database does my project use?` The fresh chat has no Orion history. Use `/sessions` and `/resume <session_id>` to return to Orion.
4. Enter `/clear` and `/history`. The active context should be empty. `/sessions` should still list Orion. Quit and resume the chat again to confirm the saved history remains in order.
5. Run the regression checks after exiting chat. Close the dedicated PowerShell window to discard its environment overrides.

```powershell
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m pytest -q
```

## Limits and next checkpoint

`/history` displays bounded context rather than the entire archive. The limit counts turns and does not guarantee a token budget. The database contains local conversation text, and copying or deleting the file affects saved chats. Permanent chat deletion and structured fact memory are outside this checkpoint. No V1 database was used. No Git commit or tag was created.

The next planned checkpoint is Phase 2A, structured fact storage, after manual approval.
