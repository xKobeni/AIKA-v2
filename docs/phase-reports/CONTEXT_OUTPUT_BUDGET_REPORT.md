# Bounded Chat Context & Output

Date: November 19, 2026. Status: **READY FOR MANUAL REVIEW**.

Scope: the user authorized the next audit checkpoint after Ollama Transport & Metadata Cache. Add a finite retained-turn maximum, a deterministic combined input-content budget and bounded ordinary output. Preserve the newest user message, system instruction, existing privacy filters, saved history, structured facts, tool authority and workflow budgets. No package/config-path migration, archive indexing, new model, streaming or later phase is included. Prior baseline/CI/transport changes remain uncommitted and preserved; CLI runtime phase remains 5E.

## Baseline and selected limits

Before editing: `python -m pytest -q` — **1,483 passed in 39.59 s**, no warnings.

The previous 16,000-character per-user-request limit and ten-turn default did not bound the combined request. Existing developer measurements produced **232,337 content characters** with ten retained synthetic exchanges, including after resume. Ordinary generation did not supply `num_predict`; grounded/planner callbacks already used 768/512.

| Setting | Default | Supported range | Behavior |
| --- | --- | --- | --- |
| `AIKA_CONTEXT_TURNS` | 10 | 0–50 | Maximum completed exchanges retained and restored; zero still saves exchanges but excludes previous turns from model input |
| `AIKA_CONTEXT_CHARS` | 24,000 | 4,096–64,000 | Shared total of model message-content characters |
| `AIKA_RESPONSE_TOKENS` | 1,024 | 64–4,096 | Ordinary output limit |

Settings are validated as whole numbers with safe errors that name the setting/range, never echo private values. Environment-over-`.env` precedence is unchanged. New Settings fields are appended with defaults for compatibility; existing positional fields/model settings remain intact. `.env.example` documents the new limits; the user's actual `.env` was not changed. Session construction enforces retained-turn/content bounds for direct callers too.

## Context assembly and overflow semantics

`src/intelligence/prompt_budget.py` is a small pure helper module, not another router or model service. ConversationSession applies its **existing model-history privacy filter and redaction first**, then builds:

```text
complete system instruction
newest eligible complete user/assistant pairs that fit
complete current user message
```

Selection walks eligible history backward, retaining a contiguous newest suffix. It stops at the first pair that cannot fit instead of skipping that pair to pull disconnected older context. The result stays chronological. No exchange is split, no message is partially shortened, and no summarization or invented context is added. The newest request/system text is preserved exactly as it existed after established privacy redaction.

If the system instruction plus current message alone exceeds the budget, the request raises a safe OllamaError naming `AIKA_CONTEXT_CHARS` and suggesting a shorter message or larger supported budget. It makes no generation call, emits no unbounded trace and saves no fabricated/partial exchange. At the default budget, the existing normal system instruction and maximum 16,000-character user request fit; lower configured budgets can reject long requests deliberately.

Trimming changes **only outgoing model context**. It does not remove records from SQLite, shorten `/history`, alter memory fact/revision semantics, reexecute old tools, change the active history anchor or rewrite saved assistant answers. Resume still loads the bounded number of completed turns using the existing store and applies the same model selection on the next request. No schema/migration or archive search change was made.

Context trace now reports the actual number of prior exchanges sent to the model. Its existing truncated flag becomes true when retained/persisted earlier exchanges are excluded by turn/content/privacy rules. Debug still respects public-text opt-in and credential filtering. `/status` retains its retained-history count and adds the configured input/output budgets, avoiding an implication that all retained turns must be sent.

## Final adapter boundary and output cap

OllamaClient validates the total content budget **before metadata or generation HTTP work**, so direct callers and source/planner workflows cannot bypass it. The supported text-message contract is a list of system/user/assistant dictionaries with role/content only, with at most 102 messages (50 complete turns plus system/current). This also bounds tiny-message overhead. Oversized or malformed input is rejected; the adapter does not silently truncate source evidence, change a planner instruction or discard a system policy.

Grounded prompts already have their own 15,000-character bound and planner tasks their existing smaller bounds, so normal defaults preserve those paths. A deliberately low global budget may reject a larger grounded prompt through its existing controlled model-error path; search/read results do not become fabricated synthesis. Source/citation selection and privacy remain in the existing workflow.

Every generation sends a finite positive `num_predict`. Ordinary calls use `AIKA_RESPONSE_TOKENS`; explicit workflow/benchmark overrides retain their own values, validated from 1 to 4,096. Grounding remains 768, planning 512, and the short developer benchmark remains 32 even when ordinary output is configured to 64. Zero, negative/unlimited, boolean, noninteger and excessive explicit overrides are rejected before HTTP work. This uses Ollama's documented [maximum generation token parameter](https://docs.ollama.com/modelfile#valid-parameters-and-values).

The previous `done_reason=length` behavior remains a controlled generation failure. No partial reply is presented or saved as a completed answer and no automatic retry occurs. Content/output validation failures before network work do not discard a healthy metadata cache unnecessarily; endpoint/model/thinking identity, 30-second expiry, forced refresh and transport-error recovery remain intact. Response formats, deadlines, model-generation budgets and selected model are unchanged.

## Files changed for this checkpoint

| Files | Purpose |
| --- | --- |
| `src/config.py`, `.env.example` | Bounded settings/constants and documented defaults |
| `src/intelligence/prompt_budget.py` | Pure whole-pair context selection and shared text-message content validation |
| `src/intelligence/conversation.py` | Apply the budget after existing privacy filtering; accurate context trace and direct-constructor limits |
| `src/intelligence/ollama_client.py` | Final input validation and finite default/explicit output caps |
| `src/cli.py` | Pass the configured content budget and show budgets in status |
| `scripts/benchmark_backend.py` | Measure bounded input, restored input and retained/persisted history independently |
| `scripts/check_installed.py` | Verify installed budget defaults as part of strict wheel smoke |
| `tests/test_prompt_budget.py` | 43 new focused cases |
| Existing config fixture/adapter/benchmark tests | Isolated defaults and intentional finite-output/bounded-measurement expectations; prior message/schema/privacy assertions preserved |
| README, this report, `docs/benchmarks/CONTEXT_BUDGET_2026-11-19.json` | Configuration, semantics and sanitized evidence |

No registered tool, executable capability, app allowlist, permission, provider policy, database schema, user data path, configured model or real user database was changed. No Git commit/tag/push was created. There is no extra model classification, tokenizer dependency, history scan, prompt-repair pass, automatic memory extraction or background work.

## Automated verification

- Baseline full suite: **1,483 passed in 39.59 s**.
- Initial existing conversation/runtime/adapter/benchmark/transport group: **160 passed in 18.35 s**. A selected-order optional urllib3 SOCKS-dependency warning was observed; no dependency was added or warning suppressed.
- Focused new budget cases plus existing developer benchmarks: **48 passed in 3.15 s** (43 new budget cases).
- Final Python 3.12 full suite: **1,526 passed in 48.33 s**, no warnings.
- Fresh Python 3.13.15 complete regression: **1,526 passed in 36.88 s**, no warnings. A freshly built non-editable wheel also passed `pip check` and the strict isolated-import smoke for startup/help/version/doctor, budget defaults, synthetic data persistence, default paths and explicit overrides. A conventional fresh venv was used after an initial uv-overlay invocation failed the strict import-origin check; the verification guard was not relaxed.
- `pip check`, `python -m compileall -q aika.py src scripts`, and `git diff --check` passed; Git emitted only existing Windows line-ending notices.

Cases cover valid/invalid/min/max configuration; direct-constructor limits; exact-boundary trimming; whole-pair/order preservation and no disconnected older context; Unicode/newest/system preservation; long/restored histories without storage changes; rejection without generation/trace/save; original 16,000-character user input; privacy filtering before selection; storage failure without retries; adapter input/role/extra-field/message-count bounds; unlimited/invalid output override rejection; finite default and independent grounded/planner limits; unchanged cache ownership; and token-limit failure without a saved partial answer. Existing routing, memory, source isolation, agent budgets/cancellation/partial results, transport recovery, persistence and resume cases remain in the complete suite.

No existing test was removed. Adapter expectations now include the deliberately added ordinary token cap, and the benchmark's old unbounded-growth expectation was replaced with a content-bound assertion plus exact retained/persisted history checks.

## Measured behavior and actual local acceptance

The same synthetic context dataset now sends **12,057 content characters** before and after resume, versus the earlier **232,337**. There is no room for even one of its deliberately large prior exchange pairs under 24,000 after reserving current/system content, so the model receives zero history pairs for this dataset. The session still retains ten exchanges and the temporary database saves all **13** submissions. Small complete recent pairs are retained in separate tests; this is not a global history-disable shortcut. Archive behavior was not changed. These size measurements used a mocked model, not a huge real inference request.

Actual unchanged **qwen3.5:4b** completed two short synthetic prompts in a temporary database. Captured chat requests had **1,937** and **1,993** content characters, both with `num_predict=1024`. The second contained one complete prior exchange and correctly recalled the synthetic marker. Resume restored history without another generation. A separate mandatory-input overflow check returned the controlled error without invoking its model callback.

Actual isolated CLI startup, doctor, version, help and a chat containing `/status`, `/calc 12*7` and exit all returned **0**. Status displayed the 24,000-character/1,024-token budgets and calculator returned **84**. No real GUI or web-provider action was requested, no paid credits were used and no production memory was used as test data. The [sanitized evidence JSON](../benchmarks/CONTEXT_BUDGET_2026-11-19.json) contains settings, counts and result summaries, never prompts, replies or private facts.

## Review and limitations

Use a dedicated PowerShell and a temporary `AIKA_DATA_DIR` for manual review. Set the new environment values or use their defaults, then restart the CLI:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-context-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_CONTEXT_TURNS = '10'
$env:AIKA_CONTEXT_CHARS = '24000'
$env:AIKA_RESPONSE_TOKENS = '1024'
$env:AIKA_WEB_SEARCH_ENABLED = 'off'
$env:AIKA_WEB_READING_ENABLED = 'off'
python -m aika doctor
python -m aika chat
```

Check short follow-ups, `/status`, explicit memory and arithmetic/system commands, then restart and `/resume` the test session. Use the developer benchmark or deterministic tests for giant transcripts and forced output-length failures instead of making the laptop generate an unnecessarily large answer:

```powershell
python -m scripts.benchmark_backend --output artifacts/context-budget.json
python -m pytest -q tests/test_prompt_budget.py
```

The content budget counts Python string characters, **not exact model tokens**, role/template overhead, response schema text, database size or process RSS. Text-only message count is also bounded, and app-owned schemas retain their existing bounds. No tokenizer, `num_ctx` change or model-specific context-window guarantee is introduced. Retained/restored history is capped by turn count but old stored answers are not destructively rewritten; unusually large historical records can still cost local read/assembly memory before model selection. Database size/archived search are separate concerns.

Omitted history can remove conversational context needed for an implicit follow-up; AIKA must use existing clarification/unknown behavior, not invent facts. Important saved facts still use deterministic structured recall. Long answers can hit the finite token cap and return the existing controlled failure; increase the supported cap deliberately if needed. Structured source prompts are never silently shortened to fit. Hosted CI, a separate Windows machine and arbitrary model/tokenizer combinations are not newly certified by these local checks.

Recommended next checkpoint, only under a new scoped instruction: portable configuration resolution and repeatable wheel-install coverage, building on the already measured installed-package `.env` coupling. No package/import rename, user-config migration or next phase was started.

**Final status: READY FOR MANUAL REVIEW.**
