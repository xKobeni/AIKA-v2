# AIKA V2 — Qwen3.5 upgrade and conversation reliability

**Status** — READY FOR MANUAL REVIEW  
**Approval** — Pending manual review

## Reported behavior and findings

AIKA reportedly denied knowing Orion's database even though the user had supplied PostgreSQL and the model later mentioned it. Before any edits, all 72 Phase 1C tests passed. A live run with `qwen2.5:3b` captured the application request immediately before Ollama. The database question had `system → user → assistant → user` in order, with the prior project statement and current question intact. The old model answered PostgreSQL and Next.js in that run. It also added generic offers of help and unsolicited explanation. The reported contradiction did not recur, so its specific cause remains unverified.

The request assembly, session IDs, turn limit, and SQLite restoration were verified by inspecting the code and testing actual payloads. This investigation found no evidence of a lost user turn or incorrectly restored session. SQLite schema and transcript storage are unchanged. The only context-path addition is a diagnostic callback inspecting the same message array before model generation.

A repeat Qwen3.5 run exposed a separate reliability issue. In a fresh Zephyr chat, the model guessed SQLite even though the trace showed zero prior turns. With the earlier prompt at temperature `1.0`, a three-seed replay reproduced that guess once. With the focused prompt and temperature `0.2`, all three seeds acknowledged missing information. The prompt and temperature were tested together, so this comparison does not isolate their individual effects.

## Changes

| File | Change |
| --- | --- |
| `src/config.py` | Set the fallback model to `qwen3.5:4b` and added opt-in thinking and context diagnostic settings. Explicit `AIKA_OLLAMA_MODEL` selections still take precedence. |
| `src/cli.py`, `src/intelligence/conversation.py` | Tightened the AIKA instruction and added an optional trace of the actual message order, model, session, completed-turn count, system instruction presence, and trimming. |
| `src/intelligence/ollama_client.py` | Consult model capability information and `/api/show` when needed, use conversation temperature `0.2`, keep reasoning separate, and reject generation-limit responses before they can be displayed or stored. |
| `tests/conftest.py`, `tests/test_ollama.py`, `tests/test_conversation.py` | Extended the Phase 1 suite for model overrides, thinking controls, trace privacy, and restoring saved context across model changes. |
| `README.md`, `docs/phase-reports/PHASE_1C_REPORT.md`, and this report | Documented the new default, optional diagnostics, and manual verification. |

The system instruction asks AIKA to answer directly from facts the user explicitly supplied, resolve references using the active transcript including restored turns, and use a focused question when a detail is missing. It tells AIKA to avoid inferring personal facts from project names, defaults, or earlier assistant guesses. It distinguishes saved transcript context from long-term fact memory.

The installed `qwen3.5:4b` reported boolean thinking controls through `/api/show`. AIKA defaults to `AIKA_OLLAMA_THINK=off`. For models that require thinking, Ollama can apply its lowest supported level. `on` uses a reported supported setting, and `default` leaves the choice to the model. The adapter returns only `message.content` after checking completion and rejecting empty or length-limited responses. Model availability, local-only validation, non-streaming generation, and the configured I/O timeout remain in effect. [Ollama model metadata](https://docs.ollama.com/api-reference/show-model-details) · [Thinking controls](https://docs.ollama.com/capabilities/thinking)

Diagnostics are off by default. `roles` reports metadata only. In `content` mode, AIKA warns that approved text appears in the terminal and prints only exact messages you list as public. Unapproved content and recognized credential-like text are withheld. The trace never reads Ollama's reasoning field.

## Verification

- Baseline `python -m pytest -q` passed **72 tests**. The expanded suite passed **86 tests** on Windows with Python 3.12.10. Model tests use mocked HTTP, and storage tests use temporary SQLite files.
- `python -m aika`, `doctor`, `--version`, and `--help` succeeded. `doctor` verified the existing SQLite database and recognized `qwen3.5:4b` as installed. With an explicit `qwen2.5:3b` override, `doctor` reported that model and passed the same storage checks.
- The final live run recalled PostgreSQL and Next.js for Orion, distinguished Orion from Nova, and acknowledged missing information in three fresh Zephyr sessions. The context trace showed the prior pair before the follow-up. After restarting under `qwen2.5:3b` and switching back to `qwen3.5:4b`, the same saved ID restored six and then seven completed turns. `/clear` emptied the active chat and retained the archive. SQLite reported `integrity_check = ok`, with 16 consecutive messages in Orion's chat.
- The nine-reply final session took 39.9 seconds end to end. This included chat startup and local model calls. The first verification script left a synthetic SQLite file in the Windows temp directory because it kept a verification connection open during cleanup. Later runs closed that connection and cleaned up their temporary databases.
- A live thinking-enabled probe during tuning returned only the final answer, `102`, in the CLI. It took about 129.5 seconds end to end on this machine before the sampling adjustment. This was a single observation rather than a benchmark.

## Manual verification

Run this from the V2 root in a dedicated PowerShell window with Ollama open. The example uses a separate data directory so the review does not add sample chats to your archive. If the model is absent, install it with `ollama pull qwen3.5:4b` before starting.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-qwen35-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_OLLAMA_MODEL = 'qwen3.5:4b'
$env:AIKA_OLLAMA_THINK = 'off'
$env:AIKA_CONTEXT_DEBUG = 'content'
$env:AIKA_CONTEXT_DEBUG_PUBLIC = '["My project Orion uses Next.js and PostgreSQL.","What database does Orion use?"]'
& $python -m aika doctor
& $python -m aika chat
```

1. Enter `My project Orion uses Next.js and PostgreSQL.` Ask `What database does Orion use?` and `And the frontend?`. Expect PostgreSQL and Next.js. The second trace should show `system`, `user`, `assistant`, `user`, with the two approved messages visible and the unapproved assistant response withheld.
2. Enter `I also have a game project called Nova, built with Godot.` Ask `Which project uses PostgreSQL?` and `Which project uses Godot?`. Expect Orion and Nova respectively.
3. Enter `/new` and ask `What database does my project Zephyr use?`. Expect an acknowledgment of missing information or a request for details. Exit chat.
4. Run `& $python -m aika chat` again. Use `/sessions` and `/resume <session_id>` to restore Orion, then verify `/history` and a follow-up. Try the same ID with `$env:AIKA_OLLAMA_MODEL = 'qwen2.5:3b'` in a subsequent invocation.
5. Turn off the trace and run regression checks. Close the dedicated PowerShell window afterward to discard its environment overrides.

```powershell
$env:AIKA_CONTEXT_DEBUG = 'off'
$env:AIKA_OLLAMA_MODEL = 'qwen3.5:4b'
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m aika --help
& $python -m pytest -q
```

## Limits

Replies remain probabilistic. The trace reports which saved turns AIKA supplied and whether the turn-count limit omitted older turns. Ollama may apply its own token window. Content inspection is intended for synthetic or confirmed public transcripts. No models were downloaded, no SQLite migration was added, and no Git commit or tag was created. Phase 2 has not started.
