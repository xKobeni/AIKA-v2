# AIKA V2 Phase 3A — Tool Registry and Calculator

**Status:** READY FOR MANUAL REVIEW  
**Date:** 2026-11-18  
**Approval:** Pending user review; no commits or tags created.

## Implemented behavior

AIKA executes exactly one registered tool: `calculator.evaluate`. Both natural-language arithmetic and `/calc` enter the existing `ConversationSession.reply` lifecycle. They use one registry, executor, and trusted Python evaluator. No model call selects or computes these results. Recognized calculator failures return controlled errors without falling through to Ollama.

Explicit calculator requests take precedence over memory parsing, so calculator input cannot accidentally become a memory update. Other memory requests retain the existing transaction and confirmation behavior. Ordinary conversation still uses the configured model, whose default remains `qwen3.5:4b`. Recognized unsupported action requests such as `Open Spotify` return an honest capability explanation. The system instruction prohibits invented execution claims, and an additional bounded response guard catches common unverified tool and desktop completion claims in ordinary generated replies.

The foundation's illustrative `math.calculate` name is implemented as `calculator.evaluate`, as required by this checkpoint's request. This is a static Python registration, without model-provided functions or a plugin loader.

## Registry, contracts, and execution

`ToolDefinition` holds the name, description, input and output validators, permission classification, trusted handler, and enabled flag. The registry validates definitions, rejects duplicates, lists definitions including disabled entries, and rejects unknown or disabled lookups.

`ToolRequest` contains a tool name and arguments. The executor resolves that name, checks permission before validation or execution, validates the argument object, invokes the registered handler, and validates its output. Only a completed handler with valid output returns a verified successful `ToolResult`. Unexpected handler and contract exceptions become generic errors without leaking their text.

`ToolResult` keeps execution independent of CLI formatting. It contains the tool name, status, data, verified flag, safe error, permission, input-validation status, and elapsed milliseconds. Statuses distinguish `success`, `invalid_input`, `denied`, `execution_failed`, `unknown_tool`, and `disabled_tool`. Every failure has no successful data and `verified=False`.

The permission enum defines `READ_ONLY`, `LOCAL_ACTION`, and `SENSITIVE_ACTION`. Only `READ_ONLY` can execute. Both higher-risk categories fail closed, even when a registered handler exists. There is no approval workflow, shell tool, filesystem tool, or application launcher in this phase. Future scoped authorization must be added at the executor boundary before enabling those categories.

## Calculator safety and numerical behavior

The calculator parses an expression with Python's AST parser and explicitly allows only numeric constants, addition, subtraction, multiplication, division, and unary signs. Parentheses group those operations. A full-match normalizer supports simple percentages such as `15% of 800`. It never uses Python `eval` or `exec` and never launches external processes.

Constants are converted from their original source text into `Decimal`, avoiding a float-to-Decimal conversion. The arithmetic context is independently set to 50 significant digits and half-even rounding, regardless of the caller's Decimal context. Output is ordinary decimal text without unnecessary trailing fractional zeros, and negative zero becomes `0`.

Limits are enforced before or during evaluation:

| Limit | Value |
| --- | --- |
| Expression length | 512 characters |
| AST node count | 128 |
| AST depth and parenthesis nesting | 16 |
| Digits in each decimal literal | 50 |
| Nonzero intermediate/final magnitude | `1e-100` through `1e100` inclusive |
| Result text length | 128 characters |

Names, calls, attributes, imports, lists, arbitrary Python syntax, powers, floor division, modulo, scientific notation, and numeric underscores are rejected. Division by zero and numerical-size violations are controlled execution failures. Repeating divisions are rounded; this is bounded decimal arithmetic rather than arbitrary-precision symbolic mathematics.

## CLI, diagnostics, and storage

`/tools` lists the actual registered definitions and enabled status. `/calc <expression>` calls the same session method and executor as natural language. Existing help, history, session, resume, clear, new, status, and exit commands remain available.

The existing `AIKA_CONTEXT_DEBUG` setting enables tool diagnostics in `roles` and `content` modes. Tool traces show recognized intent, selected tool, permission, input validation, execution status, verification, and elapsed milliseconds. They exclude input values, result values, and unexpected exception text. Normal CLI replies and transcripts still contain the request and answer as expected.

Doctor builds the real registry and executes `0.1 + 0.2` through its executor. It checks both verified success and the actual result `0.3`, reports the registration count, and returns failure when registration or the calculation probe fails. Existing Python, configuration, SQLite, memory, and Ollama checks remain. Desktop Actions is explicitly reported as NOT IMPLEMENTED.

Successful calculations, controlled calculator errors, and unsupported-action explanations use the existing completed-exchange SQLite transaction. A save failure propagates through the existing storage-error path before the reply is displayed or appended to active context. Restart and `/resume` restore these exchanges. Calculations do not create structured memory facts. There is no schema change, migration, second database, or durable tool-run audit table in this checkpoint; structured execution results are transient, with optional redacted terminal diagnostics and the existing saved transcript.

## Actual files changed

| File | Change |
| --- | --- |
| `src/capabilities/__init__.py` | Static registry construction with calculator registration. |
| `src/capabilities/contracts.py` | Typed requests, definitions, results, permissions, and controlled errors. |
| `src/capabilities/registry.py` | Registration validation, lookup, availability, duplicate rejection, listing. |
| `src/capabilities/executor.py` | Permission gate, input/output validation, execution, verification, safe failures, timing. |
| `src/capabilities/calculator.py` | Restricted AST arithmetic, Decimal evaluation, size bounds, percentage support. |
| `src/capabilities/intent.py` | Bounded calculator recognition, result formatting, unsupported-action handling, generated-claim guard. |
| `src/intelligence/conversation.py` | Calculator and unsupported-action branches in the existing request lifecycle. |
| `src/cli.py` | `/tools`, `/calc`, help, privacy-conscious tool traces, current phase and capability text. |
| `src/diagnostics.py` | Runtime file checks and actual registry/calculator probe. |
| `pyproject.toml` | Include `src.capabilities` in packaged modules; no dependency changes. |
| `tests/test_tools.py` | 92 focused tool, parser, chat, storage, privacy, memory, CLI, and doctor tests. |
| `tests/test_runtime.py` | Update obsolete phase/capability assertions and assert actual tool diagnostic output. |
| `README.md` | Current phase, commands, supported arithmetic, safety limits, diagnostic behavior, report link. |
| `docs/phase-reports/PHASE_3A_REPORT.md` | This report. |

## Actual verification results

- Baseline: `python -m pytest -q` — **164 passed** before implementation.
- Final: `python -m pytest -q` — **256 passed in 12.46 seconds**, Python 3.12.10 on Windows. All 164 existing cases remain present; only the obsolete runtime phase and unavailable-tool counts were updated.
- Automated tests use mocked generation and temporary SQLite storage, without requiring Ollama or internet. They verify registry rejection, argument and output contracts, permission denials before handler invocation, arithmetic and Decimal precision, unsafe syntax and size limits, error statuses, no model fallback, natural-language routing, `/calc`, `/tools`, privacy, storage failure, restart persistence, memory coexistence, and failed doctor probes.
- A subprocess-driven walkthrough ran the actual `python -m aika chat` CLI with a separate temporary data directory. Natural-language multiplication, parentheses via `/calc`, decimals, and percentages produced **4410**, **50**, **0.3**, and **120**. Division by zero and the supplied `__import__` payload returned errors. `/tools` reported one available READ_ONLY calculator. `Open Spotify` reported that actions are not implemented.
- In that isolated active database, explicit Orion/SvelteKit save and current frontend recall succeeded. A fresh chat process resumed the calculator session and restored its results. SQLite `integrity_check` returned `ok`; exactly one structured fact existed, from the explicit Orion save. The user's configured memory and conversation database were not modified.
- `python -m aika`, `doctor`, `--version`, and `--help` all returned exit code **0** in the isolated walkthrough. Doctor confirmed live Ollama connectivity and installed **qwen3.5:4b**, and the actual calculator probe passed. The calculator walkthrough made no inference calls; ordinary model generation regression coverage is mocked.
- The initial walkthrough's checks passed, but its test harness left a SQLite inspection connection open during temporary-directory cleanup. The connection handling was corrected in the harness, the isolated artifact was removed, and the complete walkthrough reran with exit code **0** and successful cleanup. This did not require an application storage change.
- No V1 files, model configuration, existing databases, commits, or tags were changed. No Phase 3B work was implemented.

## Manual acceptance instructions

Use a dedicated PowerShell window in the V2 project root. To avoid changing your existing archive during review, use fresh temporary storage:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-3a-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_CONTEXT_DEBUG = 'roles'
python -m aika chat
```

1. Enter `What is 245 multiplied by 18?` — expect `4410` and a verified successful calculator trace.
2. Enter `/calc (125 + 75) / 4` — expect `50`.
3. Enter `What is 0.1 + 0.2?` — expect `0.3`.
4. Enter `What is 15% of 800?` — expect `120`.
5. Enter `/calc 100 / 0` — expect a division-by-zero error and `verified=no`.
6. Enter `/calc __import__("os").system("echo unsafe")` — expect an invalid-expression error, with no code execution.
7. Enter `/tools` — expect `calculator.evaluate`, `READ_ONLY`, and `AVAILABLE`.
8. In this temporary database, first save `Remember that Orion uses SvelteKit for its frontend.` Ask `What frontend does Orion currently use?` — expect the saved SvelteKit value. For the existing-memory acceptance test instead, open a separate shell without the temporary override and ask the same question against your existing data; it must reflect your actual saved value.
9. Enter `Open Spotify.` — expect an explanation that actions are not implemented, without launching it.
10. Copy the session ID, exit, restart `python -m aika chat`, run `/resume <session_id>` and `/history` — expect completed calculator replies and errors to remain.
11. Run the regression commands below. Close the dedicated shell to discard its environment overrides.

```powershell
python -m aika
python -m aika doctor
python -m aika --version
python -m aika --help
python -m pytest -q
```

## Known limitations and future integration

Natural-language recognition is deliberately bounded. Units, variables, implicit multiplication, contextual values such as `my income`, and multi-step instructions are unsupported; use an explicit numeric `/calc` expression. Explicit calculation commands with unsupported text return an error. Ambiguous ordinary questions can still use conversational generation, which is not a verified calculator result.

Unsupported-action recognition and ordinary-response claim filtering cover common phrasings rather than every possible paraphrase. They are supplementary honesty safeguards, not authorization mechanisms. No model response has an execution path outside the trusted executor, regardless of wording. A general-purpose planner, universal semantic claim verifier, durable tool-run audit log, and scoped action approvals remain future work. The synchronous calculator is bounded by input/operation limits; no generic timeout or cancellation framework has been added.

No fresh virtual-environment installation or GUI-driven manual typing was performed. CLI acceptance used actual subprocesses and scripted stdin. User manual acceptance remains pending.

**Next planned checkpoint:** Phase 3B — Desktop Actions. Do not begin it until the user reviews this checkpoint.
