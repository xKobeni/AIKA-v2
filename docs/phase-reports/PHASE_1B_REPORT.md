# AIKA V2 Phase 1B — Multi-turn conversation

**Status** — READY FOR MANUAL REVIEW  
**Date** — 2026-11-17  
**Approval** — Pending manual review

## What changed

Each `python -m aika chat` invocation creates a `ConversationSession`. Its `reply()` method owns the request sequence for this checkpoint. It accepts a prompt, assembles the message array, calls the existing generator, and records the result only after generation succeeds. The CLI handles terminal input, local commands, and display. The Ollama adapter still handles the API and its errors.

The request includes one system instruction, the most recent completed user/assistant pairs in chronological order, and the current user message. The session retains up to `AIKA_CONTEXT_TURNS` pairs, with a default of `10`. A limit of `0` keeps every request independent. A failed generation leaves the prior context intact, including when the history limit has been reached. Blank prompts and slash commands do not request generation.

`/history` shows the retained turns, `/clear` drops them while preserving the system instruction, and `/status` reports the configured model and retained count. `/help` lists commands. `/exit`, `exit`, Ctrl+C, and EOF end the session. Each new chat begins with empty history.

## Files changed

| Path | Change |
| --- | --- |
| `src/intelligence/conversation.py` | Added the single session request path and bounded in-memory turn storage. |
| `src/cli.py` | Wired chat through the session, added local commands, and updated the system instruction and phase status. |
| `src/config.py` | Added and validated `AIKA_CONTEXT_TURNS`. |
| `src/diagnostics.py` | Included the session module in the runtime file check. |
| `tests/test_conversation.py` | Added mocked tests for context order, isolation, eviction, clearing, history display, and failure recovery. |
| `tests/conftest.py`, `tests/test_runtime.py`, `tests/test_ollama.py` | Isolated the new setting, added its invalid-value cases, and updated the phase label and recovery test name. |
| `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, and this report | Documented the new behavior and checkpoint status. |

## Verification

- Before implementation, `python -m pytest -q` passed all **51 Phase 1A tests**.
- After implementation, `python -m pytest -q` passed **59 tests** on Windows with Python 3.12.10.
- Mocked tests verify the outbound message arrays, including a follow-up with exactly one system instruction, eviction of a complete older pair, and a cleared request containing only the system instruction and the latest user message. They also verify that blank input and local commands issue no Ollama requests after the initial model probe.
- Live CLI tests with `qwen2.5:3b` answered Orion, Next.js, PostgreSQL, and Orion again after introducing Nova. `/status` showed 7 of 10 turns retained. `/history` was empty immediately after clearing, then showed only the new exchange. The model asked for details after `/clear` and again in a separate process.
- The runtime, doctor, version, and help commands worked in PowerShell. Doctor confirmed that Ollama was reachable and `qwen2.5:3b` was installed. The missing default data directory produced the existing warning.

## Manual acceptance

From the V2 root with Ollama running, use the existing Python environment. See the [Windows setup](../../README.md#run-on-windows) if you need to create it.

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -m aika chat
```

| Check | What to enter and expect |
| --- | --- |
| A. Basic context | Enter `My project is called Orion.` Then ask `What is the name of my project?` Expect Orion. |
| B. Follow-up | Enter `Orion is a web application built with Next.js and PostgreSQL.` Ask `What frontend framework is it using?` then `And its database?` Expect Next.js and PostgreSQL. |
| C. Topic switching | Enter `I'm also developing a game called Nova.` Ask `Which project was the web application?` Expect Orion. |
| D. Clear | Enter `/clear`, then ask `What was the name of my web application?` Expect AIKA to say it lacks the information or ask for clarification. |
| E. History | Enter `/history`. Expect only the question and answer added after `/clear`. Enter `/status` to verify the retained count. |
| F. Restart | Enter `/exit`, rerun `& $python -m aika chat`, and ask `What was the name of my web application?` without providing details. Expect an answer grounded in the new session. |

Run the regression checks after exiting chat.

```powershell
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m aika --help
& $python -m pytest -q
```

## Limits and next checkpoint

The limit counts turns. Long messages may still exceed the model's effective token window. Model replies are probabilistic, while the mocked payload checks verify which information AIKA supplied. Conversation history stays in process memory and is discarded on exit. The Ollama adapter and model defaults were preserved. No Git commit or tag was created.

Phase 1C is the next planned checkpoint after manual acceptance.
