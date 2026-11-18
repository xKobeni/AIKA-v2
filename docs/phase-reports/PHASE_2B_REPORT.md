# AIKA V2 Phase 2B — Natural-language persistent memory

**Status** — READY FOR MANUAL REVIEW  
**Approval** — Pending manual review

## Memory flow

The existing conversation session still owns each request. It parses supported memory phrasing into a typed intent, resolves the target from explicit names or recent user messages, and calls the existing SQLite fact store. Python formats answers from the selected rows. The language model receives regular chat as before and has no direct access to the database. The bounded parser replaces the need to trust a model-generated operation or SQL statement.

Explicit `remember` and `save` instructions can create project facts. A clear correction can update an existing fact. An ordinary statement that would introduce a new fact stays in the conversation alone. Multi-fact writes, revisions, and the corresponding transcript pair share one transaction. AIKA displays confirmation only after commit, and errors leave prior data and in-memory context intact. Write provenance includes the session ID and user message sequence.

Targeted questions can use the active value, summarize one project's facts, find projects by an exact saved value, or retrieve a previous value from that fact's revisions. A fresh chat can recall saved facts by explicit project name without restoring any prior transcript. Ambiguous pronouns or properties prompt for clarification. For an ordinary recall question with no matching saved fact, an explicit matching statement already in the active transcript can still go through normal chat. An unknown fact in a fresh chat produces a clear missing-memory response.

`Forget Orion's frontend` asks for confirmation. `yes` or `confirm` applies only to the displayed fact ID and revision in the active chat. `cancel`, `no`, a different message, a chat switch, or restart discards the pending confirmation. A changed fact must be requested again. Deletion removes the fact and revisions from the active database. Past transcripts and backups may still contain the information.

The database remains at schema 2. The default/configured Ollama model, legacy session commands, and explicit Phase 2A memory CLI remain available. Optional context diagnostics reuse `AIKA_CONTEXT_DEBUG` and report operation, recognized keys, retrieval, committed write, revision, and validation. Subject names require approved public text in `content` mode. Stored values and reasoning traces are excluded from memory diagnostics.

## Files changed

| Path | Change |
| --- | --- |
| `src/memory/intent.py`, `src/memory/chat.py` | Typed intent parsing, reference resolution, and replies grounded in the store. |
| `src/memory/store.py`, `src/storage/database.py`, `src/storage/conversation_store.py` | Reused the surrounding transaction for memory and transcript writes and added exact value lookup. |
| `src/intelligence/conversation.py`, `src/cli.py`, `src/diagnostics.py` | Integrated the existing request path, session-bound confirmation, private traces, and doctor status. |
| `tests/test_chat_memory.py`, `tests/test_memory.py`, `tests/test_runtime.py` | Added conversational tests and updated the expected phase and ordinary-chat fixture. |
| `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, and this report | Documented supported language, limitations, and the review workflow. |

## Verification

- Before changes, all **98** tests passed, including the Phase 2A revision, deletion, reopen, schema migration, and rollback cases.
- After implementation, all **112 tests passed** on Windows with Python 3.12.10. Injected failures in a multi-fact write and in the transcript insert each rolled back the whole request. The CLI showed a storage error without a success message in the failed write test.
- The live walkthrough used separate CLI processes, real `qwen3.5:4b` for ordinary chat, and one temporary SQLite database. Orion's frontend and database saved together. Its corrected frontend was SvelteKit, its previous value was Next.js, and PostgreSQL stayed active. A fresh process recalled both current and previous values.
- Live reverse lookup returned Orion for PostgreSQL and Nova for Godot. A fresh chat reported no saved database for Zephyr. Chat responded to the statement about Ember, and `memory list` confirmed it had created no facts. `memory history` showed exactly two frontend revisions before deletion. An intervening question left the requested fact intact, and a subsequent confirmed deletion removed only the frontend.
- A final live check recalled Orion's database with a possessive question, then asked which project the user meant after a second project was mentioned in ordinary chat. The first project's frontend remained Next.js.
- Startup, doctor, version, and help worked. Doctor reported conversational memory ready without displaying fact values. Verification left the production archive outside all write tests.

## Manual acceptance

Open PowerShell at the V2 root with Ollama running. This example uses a separate data directory for review.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-2b-review-' + [guid]::NewGuid().ToString('N'))
& $python -m aika chat
```

1. Enter `Remember that my project Orion uses Next.js for its frontend and PostgreSQL for its database.` Verify both facts are confirmed. Ask `What frontend does Orion use?`, then `And its database?`.
2. Enter `I'm changing Orion's frontend to SvelteKit.` Ask `What did I use before?` Expect Next.js. Exit and run `& $python -m aika chat` again. Ask `What frontend does Orion currently use?` and `What was its previous frontend?`. Expect SvelteKit then Next.js.
3. Enter `Remember that my game Nova uses Godot.` Ask `Which project uses PostgreSQL?` and `Which one uses Godot?`. Expect Orion and Nova. Enter `/new`, ask `What database does Zephyr use?`, then enter `My project Ember uses SQLite.` as an ordinary statement. Exit.
4. Inspect the result from PowerShell. Expect two frontend revisions and no stored facts for Ember.

```powershell
& $python -m aika memory history --type project --subject Orion --key frontend
& $python -m aika memory list --type project --subject Ember
& $python -m aika chat
```

5. Enter `Forget Orion's frontend.` and reply `cancel`. Verify it is still retrievable. Repeat the forget request and reply `yes`. Verify frontend is missing and `What database does Orion use?` still returns PostgreSQL. Exit chat.
6. Run the regression commands. Close the dedicated PowerShell window when finished to discard its environment override.

```powershell
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m aika --help
& $python -m pytest -q
```

## Limits and next checkpoint

The parser recognizes a bounded set of project question and assignment forms. Give the property explicitly for an unfamiliar technology. Ambiguous or unsupported requests can require rephrasing. The memory CLI supports broader keys and entity types. Contextual references depend on the retained transcript window. Confirmed deletion does not erase old chat text or backups. Phase 2C is the next planned checkpoint after manual approval. No Git commits or tags were created.
