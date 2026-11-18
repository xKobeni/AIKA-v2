# AIKA V2 Phase 2C-A — Flexible memory understanding

**Status** — READY FOR MANUAL REVIEW  
**Approval** — Pending manual review

## Scope

This checkpoint expands language handling and clarification within the existing Phase 2C roadmap. The roadmap also calls for broader history and deletion semantics. Those remain later work. The SQLite schema, revision store, deletion confirmation, and configured Ollama model are preserved.

## Supported phrasing

| Intent | Examples |
| --- | --- |
| Explicit save | `Keep in mind that Eclipse uses Astro` and `Make a note that Eclipse's database is PostgreSQL` |
| Correction | `I've replaced Eclipse's frontend with SvelteKit`, `I switched Eclipse from Astro to SvelteKit`, and `By the way, Eclipse uses MySQL now` |
| Current or previous value | `What does Eclipse use for its frontend?`, `What's the framework for Eclipse?`, `What did I use before?`, and `The previous one?` |
| Original value | `What framework was Eclipse originally using?` and `What framework did I originally use for Eclipse?` |
| Summary or reverse lookup | `Tell me everything you've saved about Eclipse` and `Which of my projects uses PostgreSQL?` |

The existing parser emits typed operations. The existing conversation session owns the request and transaction. A correction with an explicit `from` value checks it against the active stored value before editing. The original-value question reads the first saved revision. Previous-value questions still read the preceding revision. A pronoun replacement such as `I'm replacing it with SvelteKit` needs an identifiable project and property.

## Clarification and confirmations

- When multiple projects or properties remain plausible, AIKA asks one focused question. A recognized project or property reply applies only to that pending request. A different chat message replaces the pending request.
- An ordinary statement creates conversation context. If a later correction targets an unsaved property, AIKA can explain that the earlier value was mentioned in the current transcript and offer to save the new value. It searches only the retained active or explicitly resumed transcript for this explanation. On confirmation, the new value starts at revision 1. The earlier chat value remains transcript text.
- Pending saves and clarifications are in memory for the active session. `cancel`, switching chats, or restarting discards them. If the fact is created elsewhere while confirmation is pending, AIKA asks for a new correction. Existing deletion confirmations still bind the fact ID and revision.
- As before, the memory update and its transcript commit together. The live test exposed a model-generated claim that it had saved a fact during ordinary chat even though no fact existed. The generation instruction now reserves write confirmations for the application, and the ordinary-statement path replaces recognizable unverified write claims with a chat-only acknowledgment.

## Files changed

| Path | Change |
| --- | --- |
| `src/memory/intent.py` | Expanded the bounded save, correction, current/original/previous value, summary, and reverse-lookup grammar. |
| `src/memory/chat.py` | Resolved references, introduced scoped clarification and first-save confirmation, and guarded ordinary-statement write claims. |
| `src/intelligence/conversation.py`, `src/cli.py` | Reused the existing session for pending operations and updated the phase label and model instruction. |
| `tests/test_chat_memory.py`, `tests/test_runtime.py` | Added coverage for the new behavior, pending-state isolation, and rollback. Updated the phase expectation. |
| `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, and this report | Documented supported forms, checkpoint boundaries, and manual review. |

## Verification

- All **112 baseline tests** passed before editing on Windows with Python 3.12.10.
- The full updated suite passed **120 tests**.
- Automated tests use temporary databases and mocked model responses. They cover alternative phrasing, ambiguous project and property references, session isolation, cancellation, concurrent fact creation before confirmation, SQL write failure, and the misleading model reply.
- The final live walkthrough used `qwen3.5:4b` and a temporary SQLite database. Eclipse's original frontend was Astro after changing it to SvelteKit. The reverse lookup and summary returned its saved facts. The ambiguity prompt allowed a project to be selected without editing either project prematurely.
- The ordinary Nebula statement produced a chat-only acknowledgment, and `memory list` showed no facts after cancellation. A fresh chat offered to save React without claiming it had seen Vue. After confirmation, React was the only revision. The Orion regression restored SvelteKit and PostgreSQL after restart and confirmed Next.js as the earlier frontend. Doctor passed against the temporary database.

## Manual acceptance

Open a PowerShell window at the V2 root with Ollama running. Use an isolated database for the walkthrough.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-2ca-review-' + [guid]::NewGuid().ToString('N'))
& $python -m aika chat
```

1. Enter `Keep in mind that my project Eclipse uses Astro for its frontend.` Then enter `I've replaced Eclipse's frontend with SvelteKit.` Ask `What framework was Eclipse originally using?` Expect Astro.
2. Enter `Make a note that Eclipse's database is PostgreSQL.` Ask `Which of my projects uses PostgreSQL?` and `Tell me everything you've saved about Eclipse.` Expect Eclipse and its two facts.
3. Enter `My project Nebula uses Vue.` Then enter `Change its frontend to React.` AIKA should ask which project. Reply `Nebula`. Expect a first-save offer. Reply `cancel` and exit.
4. Confirm `memory list` finds no facts for Nebula. Start another chat, enter `Change Nebula's frontend to React.`, and reply `yes`. Ask `What was its previous frontend?` AIKA should report no earlier saved value. Exit and inspect history. Only React should appear as revision 1.

```powershell
& $python -m aika memory history --type project --subject Nebula --key frontend
& $python -m aika chat
```

5. In chat, save Orion with Next.js and PostgreSQL. Recall its frontend, then say `I'm replacing it with SvelteKit.` Ask `What did I use before?` Exit and restart. Verify Orion's current frontend is SvelteKit, its database is PostgreSQL, and frontend revisions are Next.js and SvelteKit.
6. Exit chat and run `& $python -m aika doctor` and `& $python -m pytest -q`. Close this PowerShell window to discard its environment override.

## Limits

Language support is bounded. Arbitrary paraphrases, cross-project bulk corrections, and open-ended property descriptions may require a clearer request or the memory CLI. Retained transcript limits affect reference resolution and earlier chat observations. Broader deletion semantics and Phase 2C-B remain pending. Manual approval is pending, and no Git commit or tag was created.

## Reliability repair

The baseline passed all **120 tests** before the repair. Both reported failures were reproduced on a temporary SQLite database with a mocked model response.

- The pending correction still held Orion and SvelteKit, but its property matcher accepted only exact forms. `hmm the frontend` cleared the request and went through ordinary model generation. The model promise had no corresponding SQLite write. The existing write path already committed a recognized correction and its transcript together, then updated memory in the active session.
- `What frontend did Orion use before?` did not match a historical grammar rule. The request went to Ollama without reading the revision table. SQLite had Next.js, SvelteKit, and Next.js in order. The model's AngularJS answer came from the generation path rather than a wrong stored revision.

`src/memory/chat.py` now recognizes bounded filler and possessive forms in property clarifications, including `frontend`, `the frontend`, `hmm the frontend`, and `I mean its frontend`. A recognized reply completes the pending correction without asking for another confirmation. Within the write transaction, AIKA compares the selected fact with the snapshot taken when clarification began. A changed or replaced fact needs review, even if a later revision restored the same text. The correction, revision, and exchange commit before the result is displayed. If storage fails, the transaction rolls back, the pending request is consumed, and the previous history stays intact.

`src/memory/intent.py` routes the missing historical forms to the existing store. **Current** is the active value. **Previous** is the revision immediately before the active one. **Original** is the earliest saved revision. `And before that?` can step backward from the fact ID and revision most recently returned by the memory path. `src/intelligence/conversation.py` keeps that reference in the active session and clears it on a switch or restart. Missing or ambiguous history prompts for a clearer request or reports the missing value. The schema and Ollama configuration were preserved.

`tests/test_chat_memory.py` covers the four clarification forms, commit visibility from a separate database connection, revision conflicts, failure rollback and CLI error output, session switching, repeated historical values, and facts with only one revision.

The full regression suite passed **131 tests**, including **11 new cases**. Tests used isolated SQLite databases and mocked generation.

The live CLI walkthrough used `qwen3.5:4b` and a temporary database. `hmm the frontend` committed revision 2, SvelteKit, and a later correction recorded Astro as revision 3. The fresh-chat answers matched the SQLite rows for previous, relative, original, and current lookup. The unrelated database fact stayed PostgreSQL.

### Reliability acceptance

Start from the V2 root with Ollama running. Use a separate PowerShell window and a new temporary database.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-2ca-fix-' + [guid]::NewGuid().ToString('N'))
& $python -m aika chat
```

1. Enter `Remember that Orion uses Next.js for its frontend and PostgreSQL for its database.` Then enter `I'm replacing it with SvelteKit.` When asked which property, reply `hmm the frontend`. Expect confirmation that AIKA updated the frontend from Next.js to SvelteKit. Exit chat.
2. Run the history command below. Expect revision 1 Next.js and revision 2 SvelteKit. Open chat again, enter `Change Orion's frontend to Astro.`, and exit. Rerun the history command and confirm revision 3 is Astro.
3. Open a fresh chat and ask `What frontend did Orion use before?`, `And before that?`, `What framework was Orion originally using?`, and `What frontend does Orion currently use?` Expect SvelteKit, Next.js, Next.js, and Astro in that order. Orion's database should still be PostgreSQL.

```powershell
& $python -m aika memory history --type project --subject Orion --key frontend
& $python -m aika memory get --type project --subject Orion --key database
& $python -m pytest -q
```

The parser still recognizes a bounded set of replies and question forms. A relative historical question requires a specific revision in the current session. The user's existing database was outside the repair tests. Phase 2C-B remains pending.
