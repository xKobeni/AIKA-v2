# AIKA V2 Phase 2C-B — Advanced memory retrieval and contextual recall

**Status** — READY FOR MANUAL REVIEW  
**Date** — 2026-11-18  
**Approval** — Pending manual review

## Retrieval behavior

The existing conversation session coordinates retrieval before saving its completed exchange. Recognized questions receive a deterministic answer with evidence from the configured local SQLite file. Ordinary chat continues through the configured Ollama model.

| Request | Evidence and behavior |
| --- | --- |
| Explicit current value | Uses the active structured fact. A missing saved value is reported without searching old chats. |
| Saved stack or project summary | Retrieves only the selected project's active facts. |
| Previous or original value | Reads the immediately preceding or earliest saved revision. |
| `And before that?` | Uses the fact ID and revision returned by the last specific retrieval in the active session. An unrelated result clears this reference. |
| Explicit archive question | Searches user-authored statements in saved conversations. Quotes the matches with their actual session IDs, message IDs, roles, and timestamps. |
| `What did I just tell you?` | Quotes the last user message available in the retained active context. It does not search other sessions. |

Supported additions include `What's Orion built with?`, `Which frontend did I save for Orion?`, `What's the current stack for Orion?`, and `Show my saved information about Orion.` A broad historical technology question asks which property when multiple facts are possible.

## Archive search strategy

Explicit questions include `What did I mention about Atlas in my previous conversations?`, `Find where I mentioned Atlas.`, `Did I ever talk about using Vue for Atlas?`, and `What did I previously mention about PostgreSQL?` Search requires every literal term, with case folding and word boundaries. Atlas does not match Atlassian. Input is limited to eight terms and 120 characters. Ambiguous or invalid expressions ask for a narrower request. Wildcard and query-language operators are unsupported.

The implementation scans existing conversation rows through SQLite and uses parameterized SQL. It returns at most five distinct user messages, ordered by recorded timestamp descending, then actual message ID descending. Exact duplicate text keeps its newest occurrence. Recognized recall and deletion requests are excluded from evidence. Assistant text is excluded because these requests ask what the user said. Each excerpt has at most 400 content characters plus optional truncation markers. The transcript itself is left intact.

Explicit `previous conversations` queries exclude the active session before deduplication and limiting. Explicit `in this chat` queries use only the active session. Broad `previously mentioned` or `find where` queries can include both, with `current session` or `other session` beside the actual session ID.

FTS5 was considered. These requests need literal matching with bounded results, which the current tables can support directly. A separate index would add synchronization and migration work at this checkpoint. There is no new schema, migration, or search index to initialize or rebuild. The tradeoff is a full scan, which can become slow as the archive grows. SQLite read failures are reported through the existing storage-error path.

## Provenance and source boundaries

`Retrieval` is a small immutable Python record. It identifies `structured_fact`, `fact_revision`, `current_session`, or `archived_conversation`. Fact evidence includes its real fact ID, revision, source, and recorded time. Message evidence includes its real session ID, message ID, role, and timestamp. This metadata is attached to the request result. It requires no new database table.

Archive results are labeled historical user statements and quoted as data. They do not write facts or revise existing values. If Atlas was mentioned with Vue in a chat and has a saved frontend of SvelteKit, the current question returns SvelteKit while an explicit archive lookup can show the Vue statement. Deleting the structured fact removes it from active lookup while its chat mentions can remain searchable. Current-session statements can still support ordinary Phase 2C-A chat, while an explicit `currently` question requires a saved current fact.

Optional memory diagnostics print evidence source types and counts alongside the existing operation metadata. They exclude fact values and archive excerpts. Existing subject privacy controls apply. Retrieved archive excerpts are not sent to a separate model call. A later ordinary chat turn can include the displayed excerpts as part of the bounded active transcript, with the system instruction treating historical quotes as data.

## Files changed

| Path | Change |
| --- | --- |
| `src/memory/retrieval.py` | Typed evidence, literal archive search, excerpts, and active-session evidence. |
| `src/memory/intent.py` | Explicit archive and current-session questions, saved-stack variants, property aliases, and strict current-value routing. |
| `src/memory/chat.py` | Retrieval formatting, targeted provenance, and broad historical ambiguity handling. |
| `src/intelligence/conversation.py` | Supplied active session metadata within the existing request transaction. |
| `src/cli.py`, `src/diagnostics.py` | Updated phase status, source-count debug output, prompt data handling, and runtime file checks. |
| `tests/test_retrieval.py`, `tests/test_runtime.py` | Added retrieval regressions and updated the phase label. |
| `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, and this report | Documented source priorities, search behavior, and manual review. |

## Verification

- The baseline suite passed all **131 tests** before edits.
- The updated suite passed **156 tests** on Windows with Python 3.12.10, including the existing confirmation, correction, rollback, migration, model, and privacy tests.
- Automated tests use temporary SQLite databases and mocked ordinary generation. They cover cross-session search, exact attribution, deterministic ordering and deduplication, bounded excerpts, invalid and broad queries, read failures, fact and revision provenance, current-session isolation, and deletion boundaries.
- The live walkthrough uses a new temporary directory with `qwen3.5:4b` for ordinary chat. A fresh process retrieves the archived Atlas/Vue statement with its original session ID and timestamp. After saving SvelteKit, explicit current lookup returns SvelteKit. The archive remains separately labeled historical information.
- After confirmed Atlas fact deletion, current lookup reported a missing saved frontend while explicit archive search still quoted Vue and the earlier SvelteKit save statement. Current-session recall returned the preceding user request without searching another chat. Orion's current, previous, and original values were Astro, SvelteKit, and Next.js, and the relative follow-up returned Next.js. Nova's summary returned Godot independently.
- SQLite remained at schema version 2 and `integrity_check` returned `ok`. The original Atlas message was unchanged, and the deleted structured fact stayed absent. Startup, doctor, version, and help succeeded against the temporary store. The final walkthrough cleaned up its test directory. The user's actual archive was outside the tests.

## Manual acceptance

Open PowerShell in the V2 root with Ollama running. Use a dedicated shell for the temporary configuration.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-2cb-review-' + [guid]::NewGuid().ToString('N'))
& $python -m aika chat
```

1. Enter `My project Atlas uses Vue for its frontend.` Exit without saving a fact. Start `& $python -m aika chat` again and ask `What did I mention about Atlas in my previous conversations?`. Expect the quoted user statement with the earlier session ID and timestamp.
2. Enter `Remember that Atlas uses SvelteKit for its frontend.` Ask `What frontend does Atlas currently use?`, then `What did I previously mention about Atlas?`. Expect SvelteKit as the saved current value and Vue among the separately labeled historical statements.
3. Ask `What did I previously say about a project called Zephyr?`. Expect no matching evidence in this isolated archive.
4. Save Orion's frontend as Next.js, change it to SvelteKit, then Astro. Ask for its current frontend, original framework, previous frontend, and `And before that?` immediately after the previous-value answer. Expect Astro, Next.js, SvelteKit, and Next.js.
5. Save Nova with Godot. Ask `What do you remember about Nova?`, then `What frontend does Orion use?`. Each response should use the named project's facts.
6. Request `Forget Atlas's frontend.` and confirm with `yes`. Ask its current frontend and verify it is missing. `Find where I mentioned Atlas.` should still show archive evidence. No fact is recreated by the search.
7. Exit chat and run the regression commands below. Close the dedicated shell afterward to discard its environment override.

```powershell
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m aika --help
& $python -m pytest -q
```

## Limitations and next checkpoint

Search uses literal terms, without synonyms or semantic inference. Very large archives may need a measured indexing improvement. Archive output is capped, so a missing item in a returned list can also mean newer matches filled the five-result limit. The timestamp records when AIKA saved a message, not when an external event happened. Arbitrary paraphrases and unnamed ambiguous projects may require clarification. Manual acceptance is pending. The next planned checkpoint is Phase 3A, Tool Registry and Calculator.

## Reliability repair — 2026-11-18

### Findings

The baseline passed all **156 tests**. Parser inspection reproduced the failures. `Correct it to SvelteKit`, `Then correct it to Astro`, assignment notation, and the abbreviated current-value requests all returned no memory intent. They entered ordinary generation. The previous response guard applied only to recognized ordinary statements, which left these other model replies able to claim a memory change without a store operation. Direct recognized recall used SQLite, explaining why it could contradict those generated claims.

A read-only inspection of the configured database found Orion's frontend at Next.js, revision 5, with saved frontend values Next.js → SvelteKit → Next.js → SvelteKit → Next.js. This confirmed the current saved state. The database alone cannot establish the wording or execution path of every earlier reply. Automated reproduction used a fabricated model update claim and asserted the actual temporary SQLite rows.

Archive search had no session predicate. It searched all saved user messages for both `previous conversations` and broader `previously mentioned` requests. Its existing session IDs and timestamps were accurate, but the policy did not distinguish those requests.

### Applied fixes

- `src/memory/intent.py` recognizes the successive correction forms, `as its engine`, and abbreviated current-value requests. Supported corrections and questions go through the existing memory handler. Unsupported correction forms prompt for a specific target. Assignment notation gets an explicit response that it was not saved.
- `src/memory/chat.py` resolves the active subject and property, reads the current fact inside the transaction, and uses the existing revision write. A pronoun correction tied to a previous fact result checks that fact ID and revision before changing it. Existing clarification snapshots continue checking concurrent changes. Abbreviated current questions retrieve the active value even when the last answer discussed an older revision. Ambiguous subjects or properties prompt for clarification.
- `src/intelligence/conversation.py` applies the existing unverified-write-claim guard to every ordinary model reply in a memory-enabled chat. Supported writes still return their deterministic response only after both the memory change and transcript commit. Failure leaves the previous active value, revisions, and in-memory history intact.
- `src/memory/retrieval.py` applies the requested session scope before ranking, deduplication, and the five-result cap. The handler labels each result's origin while preserving its actual session ID, timestamp, role, and message ID.
- `tests/test_retrieval_reliability.py` adds database assertions for correction chains, restart recall, current/previous/original values, unsupported assignments, misleading fallback text, ambiguous questions, rollback, concurrent changes, and historical session scope. The README documents the clarified behavior.

### Actual results

The complete updated suite passed **164 tests** on Windows with Python 3.12.10. Tests used temporary databases and mocked ordinary generation. Successful-write tests observed the committed rows through a separate SQLite connection before the response was returned. Existing tests for pending-operation revision conflicts and multi-fact rollback also passed.

The live walkthrough used a separate temporary database and selected `qwen3.5:4b`. Saving Next.js followed by the two abbreviated corrections produced exactly three Orion frontend revisions, ending in Astro. Direct and abbreviated current questions returned Astro, previous returned SvelteKit, and original returned Next.js. A fresh process returned the same values without resuming the conversation. Nova's explicit engine save persisted Godot, and the unsupported assignment to Unreal Engine left Godot active.

An ordinary Atlas/Vue statement was generated through live Ollama and persisted as conversation text. In a later session, the explicit previous-conversation query returned only that earlier session. A current-chat query returned the new SvelteKit save statement, and the broad query labeled both session origins. Atlas's active saved frontend stayed SvelteKit. SQLite `integrity_check` returned `ok`. Startup, doctor, version, and help succeeded in the live test environment. The configured database was inspected read-only, and all write tests used isolated storage.

### Repair acceptance walkthrough

Use a dedicated PowerShell window at the V2 root, with Ollama running.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-2cb-fix-' + [guid]::NewGuid().ToString('N'))
& $python -m aika chat
```

1. Save `Remember that my project Orion uses Next.js for its frontend.` Enter `Correct it to SvelteKit.` and `Then correct it to Astro.` Ask `What frontend does Orion use?`, `tell me the current`, `What frontend did Orion use before?`, and `What framework did Orion originally use?`. Expect Astro, Astro, SvelteKit, and Next.js. Exit.
2. Inspect history and then start a fresh chat. Repeat the named current, previous, and original questions. The memory CLI should show exactly the three revisions.

```powershell
& $python -m aika memory history --type project --subject Orion --key frontend
& $python -m aika chat
```

3. Save `Remember that my game Nova uses Godot as its engine.` Enter `Nova.engine = Unreal Engine`. Expect an explicit unsaved response. Ask `What do you remember about Nova?` and verify Godot through the CLI after exiting.
4. In chat, enter `My project Atlas uses Vue for its frontend.` and exit. In another chat, save Atlas's frontend as SvelteKit. Ask `What did I mention about Atlas in my previous conversations?`, `What did I mention about Atlas in this chat?`, and `What did I previously mention about Atlas?`. Verify the respective other-session, current-session, and combined origin labels. Ask its current frontend and expect SvelteKit.

```powershell
& $python -m aika memory get --type project --subject Nova --key engine
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m aika --help
& $python -m pytest -q
```

Parser coverage remains bounded, and unrecognized ordinary conversation still uses the local model. The reply guard catches recognizable unverified write claims. Assignment notation intentionally remains unsupported. Manual acceptance is pending. No schema migration, model change, Git commit, or Phase 3 implementation was introduced by this repair.
