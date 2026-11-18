# Phase 5C — Controlled Tool Dataflow & Contextual Execution

Date: 2026-11-18. Status: **READY FOR MANUAL REVIEW**. Phase 5C user acceptance is pending; not PASSED.

## Baseline and architecture

Read the supplied Phase 5C brief, current foundation/roadmap, Phase 5A/5B reports, and actual planning, registry/executor, ToolResult, system/calculator contracts, execution controls, CLI and persistence code/tests. The checkout contained uncommitted earlier work and was inspected locally rather than replaced from GitHub. The user's new brief explicitly approves Phase 5B and reports its subsequent manual app/web/history acceptance; those are user-reported results, not new 5C implementation tests.

Baseline: `python -m pytest -q` — **1,072 passed in 30.05 seconds**, no warnings.

The existing single ConversationSession owns the complete lifecycle. The existing planner produces two typed steps; the same executor executes both. No new executable tool, runner, framework, dependency, database, schema, worker, provider, async flow or permission path was added. The registry remains six tools. No V1 file, existing user database, secret `.env`, configured model, Git commit, tag or push was changed/created. All write verification used temporary storage.

## Binding representation and allowlist

New `src/intelligence/dataflow.py` contains small immutable contracts and pure validation/projection/formatting helpers. It does not execute tools:

```python
VerifiedBinding(source_step=1, source_field="storage.free_bytes",
                expected_type="number", unit="bytes")
PercentageCalculation(numerator=..., denominator=..., operation="percentage")
```

`PlanStep.calculation` is an optional appended field; existing step constructors remain compatible. A bound consumer carries `ToolRequest("calculator.evaluate", {})` as a structurally validated deferred input, not an executable empty call. Only after runtime resolution is it replaced with a real expression and passed through the existing calculator input/output contracts and executor permissions.

Allowed producer: **system.snapshot**. Allowed consumer: **calculator.evaluate**. Operation: **percentage** only. Both references must identify the same earlier snapshot and be declared dependencies. The source section must contain the selected group. Self/forward/missing/noninteger references, unknown fields, incompatible types/units, other producers/consumers, literal substituted measurements, extra transformations and reversed operands fail full-plan validation before any handler runs.

| Percentage | Numerator | Denominator | Bound unit |
| --- | --- | --- | --- |
| System drive free | `storage.free_bytes` | `storage.total_bytes` | bytes / bytes |
| System drive used | `storage.used_bytes` | `storage.total_bytes` | bytes / bytes |
| RAM used | `memory.used_bytes` | `memory.total_bytes` | bytes / bytes |

These are short approved projection IDs, not general dictionary paths. Implementation reads fixed dictionary keys after validation; no JSONPath, dynamic attribute traversal, `getattr`, `eval`, `exec`, templated functions or arbitrary output piping was introduced. No process names, memory facts, chat history, app output, webpage/snippet/error text or configuration/secrets can supply bindings.

## Runtime numeric verification

Existing `system.snapshot` already supplies bounded integer byte counts, actual collection time and source identity. Its ordinary schema/output is unchanged; no strings are parsed back into measurements and no second psutil call or duplicated snapshot is taken. RAM used retains the existing definition **total minus available**, rather than inventing a different OS memory metric.

Only a matching successful, verified ToolResult from this run is retained in a private request-local evidence map. A bounded snapshot copy is made before observer callbacks, so a mutable callback payload cannot change the operands after verification. This map is neither planner metadata nor persisted/cached evidence. Other requests and restored history cannot provide values.

Before binding, code requires the source step to be succeeded and the matching ToolResult to remain verified, revalidates the existing snapshot contract/provenance, checks field availability and then selects only approved numeric fields. Missing fields, values explicitly reported unavailable, booleans, numeric strings, floats (including NaN/infinity), negative or oversized quantities are rejected. Bound values must be exact integers within the existing unsigned 64-bit byte contract. Total must be positive, numerator cannot exceed total, and known used/remaining quantities must add up consistently. No zero/null/model estimate is substituted on failure. Zero **numerator** is valid; zero denominator is not.

Code constructs exactly `(numerator / denominator) * 100` from those bounded integer literals. It does not evaluate a planner template or calculate the percentage itself. The existing calculator parses and computes the expression with its 50-digit Decimal context and returns its actual verified result. Both tools still execute through the same executor. Existing limits remain four steps/eight executor attempts/two model generations/180 seconds by default, with existing timeout clipping, duplicate guards and output bounds. Common dataflow requests use two executor attempts and zero generations.

References declare bytes, not rounded GiB. Final formatting converts measured quantities to GiB for display, includes exact byte counts, displays the actual calculator result to two decimal places, and explicitly explains rounding. Decimal display uses its own fixed precision/rounding context; it does not depend on ambient float formatting. An explicit C-drive request must match the measured system drive. The workflow does not silently measure another drive or authorize other local/cloud storage targets.

## Planner, routing and execution controls

A conservative vocabulary/intent check recognizes the requested storage/RAM percentage examples and creates a deterministic snapshot-plus-calculator plan. It handles explicit `/agent` first and clear natural wording. Simple `/system` and measurement-only questions retain their ordinary route. Existing literal percentage calculations followed by a separate system request also retain their original independent/dependent semantics; unsupported-dataflow detection does not swallow that valid old workflow.

The small Ollama planning schema is unchanged. It still proposes original user-text spans/dependencies; arbitrary binding/value keys are rejected. New binding objects and measurement arguments are constructed only by trusted deterministic code. Unsupported or ambiguous dataflow fails closed with a controlled category, not guessed source fields or repeated model repairs. There is no model call to calculate or rephrase a derived answer. General dataflow, arbitrary conditionals, cross-request reuse, multi-derived-value macros and user-supplied binding syntax remain unsupported.

After producer success, one safe progress event says `Resolving verified numeric inputs...`. It contains no values, raw payload, expression or private source details. It precedes the calculator's running event and does not claim binding success. Cancellation/budget checks remain before and after resolution and before tool invocation. If a binding fails, the consumer is skipped with zero attempts and no running/success claim; previous real results remain available. Failed/inconclusive/unverified producers cannot unlock the consumer. A calculator failure cannot produce a verified percentage answer.

The same Phase 5B dictionaries record execution timing, verification, counts and actual calls. Successful calculation metadata adds approved field/type/unit/source-step references, actual collection time, calculator step and verification flags; it contains no numeric operands or full snapshot. Input verification and overall calculation verification remain distinct. Final summaries use real records, without a model rewriting status.

Existing one-active-request lock, exact app authorization, network/billing gates, safe internal-error stops, bounded outputs, cooperative interruption and SQLite atomic exchange behavior remain. No binding can target an app launch, web tool, memory operation, shell or configuration. History stores the final answer and provenance, not live binding evidence. Resume never remeasures or recalculates. A save failure retains the bounded known answer in the controlled error display and never repeats tools or appends unsaved history.

## Local presentation repairs

- A one-step plan now displays `Plan validated: 1 step`.
- Research provenance now says e.g. `Research operations for step 2 (4 calls)`, explicitly distinguishing the parent step ID from invocation count. The test verifies the actual count rather than the ambiguous former label.
- A run with no successes and an inconclusive operation now has an **inconclusive** final status rather than calling an uncertain launch failed. Actual failed/skipped/successful step semantics and process/window verification rules remain intact.

## Files changed in this checkpoint

Earlier dirty files were preserved; they are not all Phase 5C changes.

| File | Change |
| --- | --- |
| `src/intelligence/dataflow.py` (new) | Typed references, fixed numeric projections, narrow intent, runtime validation, safe provenance and deterministic percentage display |
| `src/intelligence/planning.py` | Optional calculation field, deterministic two-step plans, binding preflight/identity checks, unsupported-plan control while retaining ordinary literal percentages |
| `src/intelligence/conversation.py` | Private verified evidence map, runtime resolution/dependency skip, existing executor invocation, safe binding event/provenance and presentation fixes |
| `src/cli.py` | Binding progress rendering, singular step wording, current phase 5C |
| `tests/test_dataflow.py` (new) | 111 deterministic mocked dataflow and regression cases |
| `tests/test_agent_control.py` | Updated exact research provenance wording assertion |
| `tests/test_runtime.py` | Current-phase label expectation |
| README, roadmap, this report | Scope, allowlist, limits, user-reported prior approval, current verification and walkthrough |

No system producer, calculator evaluator, registry entry, ToolResult interface, executor permission, model setting, config default, database schema or secret file changed.

## Automated verification

- Baseline full suite: **1,072 passed in 30.05 s**, no warnings.
- First dataflow-only suite: **96 passed in 2.64 s**.
- Final focused command: `python -m pytest -q tests/test_dataflow.py tests/test_agent.py tests/test_agent_control.py tests/test_system_info.py` — **362 passed in 5.64 s**.
- Final full command: `python -m pytest -q` — **1,183 passed in 31.33 s**, no warnings. All 1,072 baseline cases remain, plus 111 new cases. Existing assertions were retained, with explicitly requested phase-label and research-label expectations updated.

Tests cover schema/field/type/unit/source/consumer/operation restrictions; self/forward/missing dependencies; exact raw byte operands and ordering; free/used storage and RAM; Decimal precision/rounding and zero numerator; missing/declared-unavailable/nonfinite/bool/string/oversized numbers; zero/inconsistent total; current matching verified evidence; producer/consumer failures; no literal/model measurement replacement; one snapshot/no unnecessary model/web call; progress order and privacy; copied evidence and provenance; no history reuse/replay; storage failure; cancellation before/during a controlled Event-blocked producer or before the consumer; expired budgets; permission recheck/disabled tools; unsupported app/web binding; the three presentation changes; and all prior memory/calculator/system/app/web/research/CLI regressions.

System values/models/providers/GUI side effects are mocked in pytest. Exact arithmetic assertions use known synthetic measurements, never volatile live percentages. No paid request or real GUI launch occurred in tests. Blocking cancellation uses Events and bounded joins, not sleep-heavy tests or fake thread termination.

## Actual live verification

All writes used temporary databases. The direct Session used an explicitly disabled SearchRouter and a generation callback that would fail if called, proving the common workflows did not need model inference. CLI checks retained configured `qwen3.5:4b`, forced both web gates off, DDGS mode, no key/fallback, and temporary storage. The configured user model and databases were untouched.

1. `/agent check my system storage and calculate the percentage of free disk space`: actual system byte measurements → actual calculator; both verified, one call each, zero generations. Observed **17.55% free**, about **78 ms**, with actual source timestamp `2026-11-18T13:35:46.246473+00:00`.
2. `/agent calculate what percentage of my C drive is used`: verified `storage.used_bytes` / `storage.total_bytes`, **82.45% used**, one call each, zero generations; collected `2026-11-18T13:35:46.259244+00:00`.
3. `/agent get my RAM information and calculate the percentage currently used`: verified memory used/total, **87.85%** at that observation, one call each, zero generations; collected `2026-11-18T13:35:46.267245+00:00`.
4. Existing `/agent calculate 12*7 then show my system information`: two verified ordinary operations, zero generations, about **141 ms**, without forced binding.
5. Direct resume restored the same saved measurement/answer text, cleared transient agent state and performed no new calls.
6. Actual `python -m aika`, `doctor`, `--version`, `--help` each exited **0**. Doctor reported six tools, successful temporary SQLite checks, local Ollama availability and unchanged agent limits. Local availability probes are not generation or provider requests.
7. Actual piped `python -m aika chat` exited **0** for free-storage and RAM-derived requests, `/history`, then `exit`. It displayed ordered resolving/running/verified completion, final percentages and two-success counts. The later RAM reading was **85.78%**, demonstrating volatile live measurements rather than a fixed expected value. History displayed the original saved results without executing them again.

These numbers are time-specific observations, not production constants or future acceptance targets. The final ordinary-literal-percentage routing refinement was regression-tested rather than repeating live measurements. No fresh web-agent, paid provider, live GUI launch, actual Ctrl+C against a hung native API, or new Ollama plan-generation acceptance was performed in this phase. Their existing automated boundaries remain covered; the prior web/app acceptance in the brief is explicitly user-reported.

## Manual acceptance walkthrough

In a dedicated PowerShell, use isolated storage and keep external services off:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-5c-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_WEB_SEARCH_ENABLED = 'off'
$env:AIKA_WEB_READING_ENABLED = 'off'
$env:AIKA_WEB_SEARCH_PROVIDER = 'ddgs'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
$env:AIKA_AGENT_TIMEOUT = '180'
python -m aika
python -m aika doctor
python -m aika --version
python -m aika --help
python -m aika chat
```

Enter:

```text
/agent check my system storage and calculate the percentage of free disk space
/agent calculate what percentage of my C drive is used
/agent get my RAM information and calculate the percentage currently used
Check my available storage, calculate what percent is free, and explain it.
/agent calculate 12*7 then show my system information
/agent calculate 15% of 800 then check my storage
/agent calculate free disk percentage using 12345 bytes
/agent calculate what percentage of my D drive is free
/system
/calc 15% of 800
/status
/history
```

Check one snapshot/one calculator per derived value, actual measured byte quantities and units, mathematically correct percentage, honest rounding explanation, timestamp/provenance and two verified outcomes. Explicit C must match the actual system drive; another-drive request must not cause another-drive measurement. Literal arithmetic/system requests must remain independent of dataflow. Unsupported fields/guessed supplied bytes/dynamic chaining should be rejected before execution, without a model repair or app launch.

The automated tests provide controlled producer failure, unverified/missing/nonnumeric inputs, permission denial, budget expiry, storage errors and cancellation of an Event-blocked producer. In every such scenario verify no dependent calculator call with guessed values. Do not intentionally hang a live OS service to test hard cancellation: it is not promised.

Copy the session ID, exit/restart and `/resume <id>`. Measurements, collection times and derived answer must remain the original saved values; no new running progress or measurement/calculation may occur. Ordinary chat/memory and manual web controls retain their established behavior under their own gates. Run `python -m pytest -q` after review. No paid/GUIs are needed for this checkpoint's acceptance.

## Limitations and next checkpoint

- Only the three fixed percentage workflows and approved byte-field pairs are supported, normally as a two-step plan. No generic user binding syntax, model-generated reference/value schema, arbitrary transformations, broader tool chaining, multiple derived quantities in one new macro or cross-request/context substitutions were implemented.
- Natural recognition is conservative. Unknown wording may produce a controlled unsupported result; it is never repaired by guessing measurements. Explicit examples above are the supported path.
- RAM uses total minus available; storage uses the actual Windows system drive. Percentages and rounded displays are observations from one snapshot, not predictions or proof of future capacity/availability.
- Existing cooperative cancellation/native timeout limitations remain. Already issued work cannot be retroactively undone; SQLite cannot roll back external effects. No tool retry, background job or durable recovery was added.
- Fixed output/precision and existing conservative web/grounding/permission boundaries remain. Metadata does not retain numeric operands/full snapshots; the final answer retains the user-visible original measurement provenance without replay.

**Proposed next checkpoint:** user manual acceptance of Phase 5C, followed only by a new explicitly scoped instruction. No Phase 5D or later feature was started.

**Final status: READY FOR MANUAL REVIEW.**
