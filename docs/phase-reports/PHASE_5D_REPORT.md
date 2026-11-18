# Phase 5D — Bounded Conditional Decisions & Reliable Intent Routing

Date: 2026-11-18. Status: **READY FOR MANUAL REVIEW**. Phase 5D acceptance is pending; not PASSED.

## Workspace, baseline and scope

Read the supplied Phase 5D brief, current foundation/roadmap and Phase 5A/5B/5C reports, then inspected the actual routing, planner/dataflow contracts, executor/verification, system/calculator payloads, progress, budgets/cancellation, CLI, history and tests. Existing uncommitted earlier-phase changes were preserved; GitHub was not substituted for the local checkout. The brief's Phase 5C manual results remain user-reported historical acceptance evidence.

Baseline `python -m pytest -q`: **1,183 passed in 37.15 seconds**, no warnings.

This checkpoint adds immediate informational decisions only. The same ConversationSession owns execution and persistence; the same six registered tools and ToolExecutor remain. No new executable tool, runner, framework, provider, dependency, database/schema, background job, notification, UI or permission path was added. No user database, V1 file, secret `.env`, model configuration, Git commit, tag or push was changed/created. All write verification used temporary storage.

## Confirmed root cause and routing repair

The original sentence was outside Phase 5C's deterministic percentage vocabulary: it contains an `if` threshold and response clauses rather than a simple percentage-calculation request. The compound-agent recognizer also could not classify that whole sentence into its existing operations. ConversationSession therefore reached `_ordinary_reply` instead of `_agent_reply`. Ollama's inability disclaimer was a consequence of that route, not proof the system tool was missing. No prompt-only workaround was used.

`agent_task` now recognizes actionable local conditional candidates before ordinary fallback, including the AIKA-prefixed sentence, explicit `/agent`, prefix/context plus `if`, suffix `warn me if`, and the documented storage/RAM forms. Clearly unsupported local conditions/actions take the controlled `unsupported_condition` path before any tool or model generation. A whole request is validated, including both response clauses; unsafe action text is not discarded to make a superficially valid warning.

Manual commands beginning with `/` retain their existing routes; explicit `/agent` remains the planning entry point. Explicit memory intent is excluded from natural conditional routing. Ordinary explanatory wording, literal arithmetic, measurement-only requests, existing multi-tool plans, Phase 5C dataflow, research, source reading and provider gates retain their routes. Contextual `it` is resolved only from the explicit metric prefix in the same request, never history/memory. Unsupported/unfamiliar conditional syntax is not repaired by repeated Qwen calls.

The parser normalizes whitespace/case and common apostrophes, allows the original multiline request through the in-process Session, and accounts for every prefix/metric/operator/threshold/response token. The existing CLI is line based: paste the complete request on one line there. Other control characters, extra conditions and unknown action text are rejected. The existing 1,200-character task bound remains.

## Immutable contract and supported subset

`VerifiedCondition` is a small frozen dataclass alongside the existing dataflow helpers:

```python
VerifiedCondition(metric="storage.free_percentage", operator="lt",
                  threshold_percent=Decimal("20"),
                  true_response="warning", false_response="normal")
```

It permits one approved metric, one `lt`/`gt`/`le`/`ge` operator, one finite 0–100 Decimal threshold, and exactly those two informational response categories. Threshold input supports integers and at most three fractional digits. Negative, nonfinite, scientific, malformed, leading-zero or excessively precise threshold literals are rejected. Values are percentages, never GiB/bytes. Equality is explicitly unsupported rather than inferred.

| Metric | Exact existing field pair |
| --- | --- |
| Free system-drive percentage | `storage.free_bytes` / `storage.total_bytes` |
| Used system-drive percentage | `storage.used_bytes` / `storage.total_bytes` |
| Used RAM percentage | `memory.used_bytes` / `memory.total_bytes` |

Language aliases: below/under/less than (`lt`); above/over/greater than/exceeds (`gt`); at least/greater than or equal to (`ge`); at most/less than or equal to (`le`). Explicit C drive must match the actual system drive; other drives remain unsupported. RAM used retains the existing total-minus-available semantics.

`PercentageIntent` and `PlanStep` receive optional appended condition fields, preserving earlier constructors. The same Phase 5C typed references and required dependencies remain. A conditional plan must contain exactly the original two steps, with a matching condition on the calculator consumer and no appended action or missing decision. Mismatched metrics/thresholds, altered binding fields, extra conditional steps and model-supplied condition keys are not authorized. The small Ollama proposal schema is unchanged; no new observed values are supplied to a model.

## Two tools and exact comparison

The only actual operations remain:

1. `system.snapshot`, with the relevant storage/memory section.
2. `calculator.evaluate`, using the deterministic expression built from the verified byte counts.

The condition is a pure internal comparison, not a fake third registered tool. It occurs after both tool steps succeed and their required verification checks pass. The helper rechecks matching source identity, successful verified producer/calculator results, the existing output contracts and exact approved binding. All earlier numeric constraints remain: exact integer byte counts within unsigned 64-bit bounds, nonnegative numerator, positive total, numerator no larger than total, correct units, available fields and consistent capacities. No duplicate measurement or calculation is performed.

The calculator supplies the actual derived percentage for display/provenance. The branch uses exact integer cross-products. For threshold ratio `(threshold_numerator, threshold_denominator)`:

```text
left  = measured_numerator * 100 * threshold_denominator
right = threshold_numerator * measured_total
```

The allowlisted operator compares `left` and `right`. `Decimal.as_integer_ratio()` supplies the exact threshold ratio, independently of ambient Decimal precision or display rounding. There is no new expression evaluator, template, dynamic object traversal, JSONPath, `eval` or model judgment. Cases such as 19.995%/19.999%, exactly 20%, and 20.001% are tested against 20%; a displayed 20.00% can correctly produce a below-20 warning. The answer explicitly states that display rounding does not determine the condition.

## Branches, progress and provenance

True selects the fixed `warning` text; false selects fixed `normal` text. Omitting `otherwise` uses normal text only after a successfully verified false comparison. Accepted alternate wording includes the documented `tell me everything is fine`, `tell me it's okay`, `tell me it is okay`, and `say normal` forms. This is not an arbitrary user-string template. A normal result means the requested warning condition was not met at this snapshot, not a global system-health assessment.

`warn me` means immediate output in the current CLI. No notification, alert dialog, file cleanup, application launch, email/message, memory update, background task or permission/configuration change is available as a branch. Unsafe true **or** otherwise actions reject the entire request before measurement, not just the unsafe portion.

Progress retains the two existing tool starts/verified finishes and adds `Evaluating verified condition...`, followed by the true/false category only after evidence-based evaluation. It exposes no numeric measurement, threshold, source timestamp, expression or complete payload in callback arguments. The decision event contains only a boolean and fixed branch label. No extra tool step is displayed.

The bounded transient decision record contains metric, operator, validated threshold string, calculated percentage, actual source collection timestamp, source/calculator step IDs, boolean outcome, selected branch and verification flag. It contains no raw byte operands, unrelated system values or complete snapshots. Snapshot and calculator payload copies remain request-local evidence, not model input or persistent caches, and are captured before observer callbacks can mutate their dictionaries.

For a successful condition, final rendering replaces repetitive intermediate tool dumps with one concise measurement/threshold/condition/response/provenance answer. Existing step/tool states and total counts remain. Ordinary nonconditional agent responses remain intact. The record and final answer are derived by code; Qwen never rewrites factual execution status.

## Failures, permissions, budgets and persistence

- Failed/inconclusive/unverified source, missing values or binding mismatch block the calculator or decision as appropriate. Calculator failure never becomes a false/normal condition. The answer explicitly says neither informational branch was selected when no condition was verified.
- Existing executor permission checks, typed input/output validation, internal-error stops, duplicate prevention, one-active-request guard, output bounds and atomic final exchange are unchanged. A permission denial cannot be bypassed by the condition, an earlier success or source text.
- Checks surround condition evaluation/publication as well as tool execution. Cancellation or expiry observed before evaluation/publication preserves completed tool work but publishes no fabricated condition. If an already verified decision completed before a later observed stop, it remains a real completed result while the overall execution reports the stop; no external action is scheduled.
- Limits remain four plan steps, eight executor attempts, two generations, one planning generation and 180 seconds by default. A supported condition uses exactly two steps/two attempts, zero generations and one deterministic comparison. No automatic retry, model repair, paid provider switch or monitoring is introduced.
- Cooperative cancellation/native blocking limits remain. No hard thread/process termination is claimed. This checkpoint does not add asynchronous command reading or a fake mid-run cancellation command.
- The existing SQLite exchange stores the completed final answer, actual measurement time, threshold, branch and execution status. History/resume replay text only. A newly submitted request obtains new measurements. A save failure retains the bounded known answer in the controlled unsaved error and does not retry tools or append unsaved active history. No condition-history schema or automatic structured-memory fact was added.

## Files changed in this checkpoint

Earlier dirty files were preserved; they are not all Phase 5D changes.

| File | Purpose |
| --- | --- |
| `src/intelligence/dataflow.py` | Frozen condition contract, bounded conditional recognizer, reuse of typed dataflow, exact comparison, decision record and concise informational formatting |
| `src/intelligence/planning.py` | Natural candidate routing, memory exclusion, two-step conditional plan/preflight checks and no-model unsupported-condition rejection |
| `src/intelligence/conversation.py` | Request-local verified calculation evidence, post-tool comparison/checkpoints, safe decision progress, final decision/provenance and explicit no-branch failures |
| `src/cli.py` | Informational decision progress rendering and phase label 5D |
| `tests/test_conditions.py` (new) | 112 deterministic conditional/routing/security/boundary/failure/CLI/persistence cases |
| `tests/test_runtime.py` | Updated current-phase assertion only |
| README, roadmap, this report | Current scope, prior user-reported testing, supported wording/limits, actual verification and acceptance scenarios |

No ToolResult interface, registered capability, permission category, calculator evaluator, system measurement operation, provider setting, database schema, secret file or model configuration changed. No test was removed or weakened; earlier assertions remain, with the runtime checkpoint label updated.

## Automated verification

- Baseline: `python -m pytest -q` — **1,183 passed in 37.15 seconds**, no warnings.
- Existing focused agent/dataflow/control group during implementation — **237 passed in 6.53 seconds**.
- Focused conditional plus prior agent/dataflow/control command: `python -m pytest -q tests/test_conditions.py tests/test_dataflow.py tests/test_agent.py tests/test_agent_control.py` — **349 passed in 7.04 seconds**. The final complete-plan and unsupported-message refinements were included in the full run.
- Final `python -m pytest -q` — **1,295 passed in 36.59 seconds**, no warnings. All 1,183 baseline cases remain plus **112 new cases**.

New cases cover the exact original multiline sentence and all documented forms; contract/metric/operator/threshold/branch restrictions; strict/inclusive boundaries and 19.995/19.999/20/20.001 rounding behavior; ambient Decimal precision; free/used storage and RAM; both branches; omitted otherwise; source/calculator/binding/permission failures; no guessed normal result; cancellation and expiry after verified work; copied evidence; precise progress order/redaction; no extra tool/model/provider calls; unsafe actions and nested/combined conditions; no memory access; existing explanations/calculator/system/dataflow routes; timestamp/threshold/branch history, restore and fresh resubmission; save failure without retries; and CLI ordering without a third step. All prior registry, app, provider, source-reader, grounding, memory, budget, cancellation, lock and history regressions remain in the complete suite.

Pytest uses mocked snapshots with known integer byte counts and mocked side effects/models/providers. It does not depend on volatile live values, launch GUI applications or consume paid credits. KeyboardInterrupt/checkpoint tests are not claims of forcibly interrupting a real hung OS API.

## Actual live checks

All writes used temporary storage. Direct Session runs used an explicitly disabled SearchRouter and a generation callback that would fail if called. CLI subprocess checks forced both web gates off, DDGS mode, empty key/fallback off, temporary storage and the existing qwen3.5:4b configuration. No user database or secret file was changed.

1. Original one-line `AIKA, check my storage. If my free space is below 20%, warn me. Otherwise, tell me everything is fine.` ran both actual tools, each verified, selected **TRUE / warning** at **17.55% free**, and completed in about **93 ms**. Actual collection time: `2026-11-18T14:39:04.549604+00:00`. No ordinary generation occurred and no system-access disclaimer was returned.
2. Explicit `/agent check my storage and warn me if free space is below 20%` selected **TRUE / warning**, using two verified calls and zero generations. Collected `2026-11-18T14:39:04.561133+00:00`.
3. Opposite branch `/agent check my free storage; if below 5%, warn me, otherwise tell me it is okay` selected **FALSE / normal** at the observed **17.55%**, in about **16 ms**. Collected `2026-11-18T14:39:04.571923+00:00`.
4. RAM-above-90 request selected **TRUE / warning** at observed **94.42% used**, two verified calls/zero generations, collected `2026-11-18T14:39:04.581079+00:00`. These are time-specific measurements, not health diagnoses or future expected values.
5. For each live condition, a separate check against the captured original integer byte operands and threshold agreed with the selected decision. No extra measurement/tool call was used for that check.
6. `/agent if my free storage is below 20%, delete temporary files` returned controlled `unsupported_condition` with **zero tool calls**. No file operation or warning-only substitute was performed.
7. `/calc 15% of 800` returned **120** through the calculator. Existing used-C-drive percentage dataflow returned **82.45%**, two verified tools, no condition or model generation. Resume preserved the same history and cleared transient agent state without replay.
8. Actual `python -m aika`, `doctor`, `--version`, `--help` each exited **0**. Doctor reported six tools, successful temporary SQLite checks, local Ollama availability and unchanged agent budgets. Availability probes are not inference or provider calls.
9. Actual piped `python -m aika chat` exited **0** for the original sentence, unsafe deletion request, `/calc`, `/history` and `exit`. It showed both verified tool completions before condition progress, the real warning branch, unsupported-action status with no execution, result 120, and the original saved answer in history.

No fresh web/provider/GUI scenario, paid fallback, live hung-native cancellation or new Ollama-generated plan acceptance was required/performed for this deterministic checkpoint. Those previous contracts remain regression-tested; prior user-reported manual results are not relabeled as new implementation-time tests.

## Manual acceptance walkthrough

Use a dedicated PowerShell and isolated storage:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-5d-review-' + [guid]::NewGuid().ToString('N'))
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

Enter each request on one line:

```text
AIKA, check my storage. If my free space is below 20%, warn me. Otherwise, tell me everything is fine.
/agent check my storage and warn me if free space is below 20%
/agent check my free storage; if below 5%, warn me, otherwise tell me it is okay
/agent if my RAM usage is above 90%, warn me, otherwise say normal
/agent if my free storage is below 20%, delete temporary files
/agent if my free storage equals 20%, warn me
/calc 15% of 800
/agent calculate what percentage of my C drive is used
Explain if/else statements in Python.
/status
/history
```

Compare actual measured values with the requested threshold rather than assuming the branch from this report's old observations. To exercise the other branch, choose a valid threshold on the other side of the current measurement. Expect one snapshot/one calculator/two steps, no model-generated measurement, correct inclusive/strict comparison, and fixed informational text. Unsupported action/equality must fail before execution. Do not interpret a normal condition result as overall machine health.

Use the deterministic tests for near-threshold rounding, permission denial, missing/unverified evidence, cancellation and budget expiry instead of manipulating the live machine to force those situations. The normal explanation needs the configured local model; the supported conditions do not.

Copy the session ID, exit/restart and `/resume <id>`. The original collection time, threshold, branch and execution counts must restore with no new running progress or tool call. Resubmitting the condition should take a new snapshot. Finally run `python -m pytest -q`. User acceptance is required before marking Phase 5D passed.

## Limitations and next checkpoint

- Only one supported metric/comparison/threshold and fixed warning/normal informational branch pair is available. Equality, nested/combined conditions, arbitrary wording/branch text, other metrics/drives, scheduled monitoring and branch-triggered actions are unsupported.
- Recognition is intentionally conservative and uses same-request context only. A normal answer is scoped to the measured condition; it is not a global health assessment. Rounded display may visually equal the threshold even when exact comparison differs, which is explicitly explained.
- Native calls and cancellation retain Phase 5B's cooperative limits; already issued work cannot be rolled back. No condition can retroactively change actual executor outcomes, and storage failure cannot undo external effects.
- No new live web/GUI/paid-provider or hard-interruption acceptance was performed; mocked security/failure tests and previous user-reported acceptance remain clearly distinguished.

**Proposed next checkpoint:** user manual acceptance of Phase 5D, then only a new explicitly scoped instruction. No later phase was started.

**Final status: READY FOR MANUAL REVIEW.**
