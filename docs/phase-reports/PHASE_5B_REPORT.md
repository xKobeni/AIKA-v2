# Phase 5B — Agent Reliability & Execution Control

**Date:** 2026-11-18  
**Status:** READY FOR MANUAL REVIEW. User acceptance of Phase 5B is pending; not PASSED.

## Scope and baseline

Read the supplied Phase 5B brief, current foundation/roadmap, Phase 5A and relevant Phase 4C reports, actual planning/execution/permission contracts, CLI, tool adapters, research, persistence and tests. The local checkout already contained uncommitted earlier-phase work. It was preserved; GitHub was not substituted for the workspace. The brief reports completed user manual testing of Phase 5A and authorization of 5B; its original report remains historical.

Baseline command: `python -m pytest -q` — **1,034 passed in 37.85 seconds**, no warnings.

This checkpoint extends the existing ConversationSession, planning records, ToolExecutor and CLI callbacks. It adds no runner, executor, framework, tool, dependency, database, migration, worker, scheduling system or event bus. No V1 file, existing user database, secret `.env`, configured model, Git commit, tag or push was changed/created. All write verification used temporary storage.

## Confirmed gaps and changes

1. Phase 5A step records lacked start/finish times, dependencies, verification flags and real per-operation provenance. Existing dictionaries now contain those fields, with bounded fixed summaries and nested executor-attempt records for research. No alternate execution model was introduced.
2. Progress reported starts but lacked verified terminal statuses, planning/validated stages and skip/cancellation visibility. An optional structured `agent_progress` callback supplements the existing research/legacy callback. CLI rendering uses fixed labels and categories only.
3. Unstarted work after cancellation was marked skipped. It is now cancelled; uncertain in-flight work remains inconclusive. Verified work observed before interruption is preserved. A trace callback interruption after a returned result no longer discards that result. Cancellation noticed at a research progress boundary prevents the next provider/read operation.
4. Unexpected local handler/contract errors were indistinguishable from ordinary execution failures, allowing the independent-step continuation policy to apply after an internal error despite the intended stop policy. The executor now supplies safe categories for internal/input/contract errors and exposed timeouts. Internal/contract/output-limit failures latch the agent stop condition; normal controlled failures retain dependency-aware continuation.
5. Tool-specific schemas bounded normal output but there was no shared retention limit. The same executor now bounds JSON-compatible data before output validation and again before result retention, including controlled-error data. Oversized payloads are discarded, not silently truncated and verified.
6. Final responses lacked explicit derived totals and could say dependencies were skipped when no step had been skipped. Final provenance, status/counts and conditional wording now reflect the actual records. A mismatched tool identity cannot publish another tool's result as a verified calculation.
7. SQLite save failure suppressed already-known agent results. The controlled storage error now includes the bounded execution answer and an explicit unsaved/not-rolled-back warning. It never retries or appends an unsaved history turn.
8. The foundation's one-active-request policy lacked a guard for programmatic overlap/reentrancy. A nonblocking per-Session lock rejects overlapping `reply()` calls without another plan, tool call or history write, and releases in `finally`. The CLI remains synchronous; no queue or parallel execution was added. Direct `new`/`resume` calls still belong to the idle lifecycle owner.

## State and record contract

Existing lowercase names remain: `pending`, `running`, `succeeded`, `failed`, `skipped`, `inconclusive`. `cancelled` identifies work cancelled before invocation. This is not a redundant new state machine.

| State | Evidence/meaning |
| --- | --- |
| pending | Validated operation awaiting its execution decision |
| running | Local workflow or invocation has entered its execution phase; no success claim |
| succeeded | Matching ToolResult with success, verified flag and data, or accepted existing grounded research output |
| failed | Controlled failure/unavailability/denial/timeout, or failed workflow with no verified answer |
| skipped | Required dependency failed or a scheduling/budget requirement prevented the next operation |
| cancelled | Cancellation observed before the operation was invoked; no claimed external termination |
| inconclusive | An invocation may have occurred but its result cannot be verified, including interrupted calls and uncertain app launches |

Per-step dictionaries retain `number`, `tool`, `state`, `category`, `attempts` and add `depends_on`, `verified`, `started_at`, `finished_at`, `duration_ms`, `result_summary`, `operations`. Each actual ToolExecutor attempt has its real requested tool name, status/category/verification and timing. A `research` step therefore records actual `web.search` and `web.read` attempts rather than pretending research is a seventh tool. A denied executor attempt does not establish that its handler or an OS action ran.

UTC timestamps use the actual wall clock; durations use monotonic time. Unstarted skipped/cancelled steps have no fabricated invocation timestamp. A workflow can begin its local checks without issuing a tool; the nested invocation record and attempt count make this distinction explicit. `finished_at` marks the local terminal observation, not proof an external interrupted process/network operation finished. Time resolution can legitimately yield zero duration for very fast work.

`result_summary` contains a short fixed phrase, not raw output. At most four steps/eight invocation records are retained. Metadata/progress excludes arguments, queries, source URLs/content, calculations, system/process data, keys, private prompts and raw exceptions/model responses. Actual bounded user-requested results appear only in the normal final answer/error display and existing saved exchange, not progress logging or planner input.

## Progress and final report

CLI output separates `Planning request...` and `Plan validated: N steps`. It then renders `[index/total] RUNNING/SUCCEEDED/FAILED/SKIPPED/CANCELLED/INCONCLUSIVE tool-name`, with safe categories where applicable. No terminal success appears before verification. Research tool attempts identify the actual search/read tool; the final research step requires accepted grounded evidence. There are no full payload dumps. Progress callback errors cannot turn an actual verified result into a failed tool operation; a callback KeyboardInterrupt is honored at the next safe checkpoint.

Final replies retain each available result and explicitly list step/tool states, actual research-operation provenance, execution status and all five terminal counts. Full success, partial success, no-success failure, interruption/budget stops and inconclusive outcomes remain distinct. No model is called to invent or rewrite execution status. Counts come directly from records; final summaries do not claim skipped work when the count is zero.

Temporary progress is not persisted as separate turns. The existing atomic SQLite exchange stores one final answer, including partial/cancelled results where saving succeeds. Resume displays historical results without planner/provider/tool replay and clears transient full evidence/agent records. Storage failure can occur after an external action; it cannot roll that action back. Completed results are displayed with the explicit save failure; no duplicate exchange or automatic action retry is performed. There is no execution-history database or durable job journal.

## Budgets, dependencies and permissions

- Existing limits remain **4 steps, 8 executor attempts, 2 model generations, at most 1 planning generation, 1 research workflow**, and **180 seconds** overall (`AIKA_AGENT_TIMEOUT`, finite 30–300). Research retains its one-search/five-read-attempt/three-successful-page caps. Plans reserve the worst-case six executor slots for it. Identical normalized calls are rejected before execution and again at runtime, even after failed attempts. No extra per-tool settings duplicate those bounds.
- Added fixed data limit: **128 KiB of UTF-8 JSON** at the executor boundary, before the output contract and again before retaining data. Non-JSON/cyclic/invalid data is rejected safely. The bound applies to all existing tools, including manual use and error payloads. It does not stop allocations already performed inside a trusted handler, replace network byte limits, or preempt native work.
- Final per-step content is limited to **16,000 characters**, plus an explicit truncation notice when needed. Safe status/provenance/count lines remain available. These fixed limits add no environment switches and do not silently increase existing timeouts.
- Missing/self/forward/cyclic/duplicate dependencies fail full-plan validation before side effects; step numbers must be actual integers. Runtime dependencies require predecessor `succeeded`, not an attempt or missing evidence. Independent steps may continue after ordinary controlled failure. Global limit/internal/contract errors and cancellation stop further scheduling. No output substitution/model guessing supplies missing predecessor values.
- The same executor remains the permission authority. The same exact trusted app authorization, allowlist, input/output checks, process verification, network gates, DDGS/Tavily modes and explicit paid-fallback opt-ins remain. Neither Ollama nor retrieved data can grant permissions, alter provider/budget settings or append actions. No arbitrary executable, shell, files or automatic memory writes were introduced.

## Cancellation and timeout guarantees

Ctrl+C/KeyboardInterrupt and the existing optional cancellation predicate are cooperative. They stop new scheduling when observed and preserve known completed results. Unstarted work is cancelled; uncertain in-flight work is inconclusive and never retried. A completed verified local result returned before a stop check remains a real result even if the overall deadline is now exhausted; the final run still reports budget exhaustion and never full success. Research/model late-answer rejection is preserved.

Built-in `TimeoutError` and provider-exposed timeout categories are reported distinctly from internal/ordinary failures. An app timeout or uncertain launch is inconclusive; it cannot unlock a dependent step or establish window readiness. No process is killed or declared terminated. Missing reliable timeout evidence is not invented from a generic exception.

There is no hard interruption of arbitrary Python/native code. DDGS engine waves/thread shutdown, OS/DNS calls, HTTP read-inactivity behavior, extraction and already issued launches retain their existing limits. A cancellation predicate cannot preempt a synchronous blocking handler; execution waits for a safe return/observable interrupt. No fake `/agent cancel`, polling, job workers or thread-kill claim was added. Timing/stop records describe local observation and cannot prove an uncertain side effect was undone. Expanded interactive approval/recovery infrastructure remains deferred under the supplied narrowed Phase 5B brief.

## Files changed in this checkpoint

Earlier dirty files are not all Phase 5B changes. This checkpoint touched:

| File | Purpose |
| --- | --- |
| `src/intelligence/conversation.py` | Existing lifecycle records/timing/progress, honest states/counts, latched stops, safe observers, result retention on save failure, one-active-reply guard |
| `src/intelligence/planning.py` | Fixed result/display bounds, outcome/count/fixed-summary helpers, exact numeric step/dependency checks; no runner |
| `src/capabilities/executor.py` | Same executor: shared bounded data retention, safe timeout/internal/contract categories; unchanged permissions/ToolResult interface |
| `src/cli.py` | Structured agent-progress rendering and callback wiring; current phase 5B |
| `tests/test_agent_control.py` | 38 new deterministic execution-control/security/persistence/CLI regressions |
| `tests/test_agent.py` | Preserve old assertions while updating explicitly changed cancellation/pre-execution-skip states, exact final-summary expectation and verified CLI progress checks |
| `tests/test_runtime.py` | Current checkpoint label 5A → 5B |
| README, roadmap, this report | Controls, limits, scope clarification, actual verification and manual walkthrough |

No `ToolResult` field, registry entry, permission category, model configuration, dependency, database schema, secret file or user data changed. The existing agent constructor/configuration defaults and all earlier manual commands remain available.

## Automated verification

- Baseline: **1,034 passed in 37.85 s**, no warnings.
- First extended agent/control focus: **118 passed in 3.18 s**.
- Final focused command: `python -m pytest -q tests/test_agent_control.py tests/test_agent.py` — **126 passed in 2.19 s**; the subsequent pre-execution-budget state refinement was included in the final full run.
- Final full command: `python -m pytest -q` — **1,072 passed in 30.64 s**, no warnings. All 1,034 previous cases remain, plus 38 new cases.

Coverage includes ordered planning/execution events; real timestamp/duration/step IDs; verified versus missing/mismatched/unverified output; dependency success/failure/missing/self/cyclic references; independent continuation; output/overall/runtime execution/model/duplicate caps; timeout/private exceptions; permission recheck; exact approved launch and uncertain launch behavior; no paid provider switch; malicious page/tool text; redacted progress; partial/final counts; storage failure with visible completed results and no retry; atomic history/resume without replay; natural/manual routing; and all prior memory/system/calculator/launcher/web/source/research/doctor/help/version regressions.

Cancellation tests use Events to hold/release a controlled synchronous mocked handler, not sleep-based timing. They prove cancellation does not forcibly terminate that handler, no subsequent call occurs, and its verified result is preserved after release. KeyboardInterrupt is also injected through the actual chat loop: it displays inconclusive/cancelled states, then accepts `/calc 9*9` and returns 81 without exiting prematurely. These are deterministic mocked interrupt tests, not a claim that a real hung OS call was forcibly interrupted. Pytest launched no GUI or real providers and consumed no Tavily credits.

## Actual live manual verification

All writes used `TemporaryDirectory` storage and the existing **qwen3.5:4b** model configuration. Live web used `SearchRouter(True, '', 'ddgs', False)` with reading enabled: no Tavily key and no fallback. No existing user database or secret `.env` was modified. No GUI app was launched.

1. `/agent calculate 12*7 then show my system information`: actual arithmetic result **84**, actual local Windows snapshot, two verified steps/two executor calls/zero model generations, about **219 ms**. Progress appeared in start/verified-finish order. Private system values are not copied into this report.
2. `/agent calculate 15% of 800 then calculate 9*9`: **120** and **81**, two verified steps, correct counts, zero model generations.
3. `/agent calculate 5/0 then calculate 2+2`: controlled division-by-zero failure, no second tool call, dependent step skipped; counts **0 succeeded / 1 failed / 1 skipped**.
4. `/agent calculate 12*7 then research latest Python release`: actual result **84** retained; DDGS returned its controlled **indeterminate** failure. Two executor attempts total, zero read/model calls, **1 succeeded / 1 failed / 0 skipped**, partial status in about **4.110 s**. No retry or Tavily fallback occurred. No current web fact or citation was fabricated. A successful new live search/read/grounded agent chain was not demonstrated.
5. Resume restored exactly the same saved answers; `last_agent` reset and no actions replayed. Final small guard/summary refinements after the web smoke were regression tested rather than querying DDGS repeatedly.
6. Actual isolated `python -m aika`, `python -m aika doctor`, `python -m aika --version`, and `python -m aika --help` each exited **0**. Doctor reported six tools, successful temporary SQLite checks, local Ollama availability and unchanged configured agent limits. No diagnostic provider/source call occurred.
7. Actual piped `python -m aika chat` exited **0** for the percentage/calculation and failure/dependency scenarios, `/history`, and `exit`. Planning, validated count, running/verified terminal events and saved final status/counts were visible. No extra progress turns were written.

No new live Ollama plan-generation acceptance was necessary for these deterministic tasks (zero generations); the previous real Phase 5A model acceptance is historical, not relabeled as a fresh 5B test. A real GUI launch, real external hung-operation interruption, live Ctrl+C signal, successful new live research chain, paid Tavily/provider fallback and crash recovery remain unverified/deferred. Mocked tests cover their specified boundaries where described.

## Manual acceptance walkthrough

Use a dedicated PowerShell with isolated storage:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-5b-review-' + [guid]::NewGuid().ToString('N'))
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
/agent calculate 12*7 then show my system information
/agent calculate 15% of 800 then calculate 9*9
/agent calculate 5/0 then calculate 2+2
/agent calculate 5/0; calculate 9*9
/agent calculate 2+2; calculate 2 + 2
/agent open powershell
/agent research latest Python release then calculate 2+2
/status
/history
```

Check real values, ordered verified progress, failed-versus-skipped/independent states, duplicate/unauthorized-target rejection before side effects, disabled web with no request, and one saved summary per turn. Verify normal conversation, memory, `/calc`, `/system`, `/web`, `/read`, `/ask-web` and `/research` retain established behavior.

For deliberate app acceptance, enter `/agent open notepad` **once**, inspect the actual app and compare process evidence. Expect verified process status or an explicit inconclusive/unavailable result, never a claim of window readiness or a retry. Arbitrary paths/executables remain unavailable. This real launch was not performed by the implementation tests.

Exit, set the two web gates to `on` deliberately, keep `provider=ddgs` and `fallback=off`, and restart chat. Try `/agent calculate 12*7 then research latest Python release`. Inspect actual provider, source/final URLs, retrieval timestamps and supporting claims, or an honest bounded provider/evidence failure. This configuration prevents Tavily usage even if a local key exists. Do not count a snippet or failed retrieval as read-page verification.

Test Ctrl+C during a controlled request and inspect which work was verified, never-started or uncertain. Allow for a synchronous native call to take time to return; do not infer external process termination. After a handled stop, enter `/calc 9*9` and verify chat remains usable. The automated Event/KeyboardInterrupt tests provide deterministic cancellation coverage without creating an intentionally hung live external service.

Copy the session ID from `/status`, exit/restart and `/resume <id>`. Saved results/counts must restore without new tool/provider calls or fresh running progress. Finally run `python -m pytest -q`. User review is required before changing the checkpoint's acceptance status.

## Remaining limitations and next checkpoint

- Hard preemption, process termination, automatic retry, background jobs, durable execution journals and resumable plans remain outside scope. SQLite cannot roll back external effects or record results if storage is unavailable.
- Programmatic overlap of `reply()` is rejected; there is no queue, multi-client API or concurrent lifecycle editing support. Do not call `new`/`resume` during active work.
- Internal/contract/oversized outputs stop the run even when an independent later action would otherwise have been permitted. This intentionally favors reliable control after uncertain output; ordinary controlled failures retain existing independent continuation.
- Byte/character limits may reject/truncate unusually large otherwise useful tool output; final display reports truncation. Payload allocation inside a handler is not hard-memory-limited.
- Existing narrow natural-language plan grammar, no dynamic argument/dataflow substitution, single research workflow, source-format/security constraints, conservative grounding validation and DDGS intermittency remain.
- Live GUI, real hung native cancellation, fresh live grounded web-agent success and paid-provider acceptance remain pending. No claim of live validation is made for mocked scenarios.

**Suggested next checkpoint:** user manual acceptance of Phase 5B. A later user-defined checkpoint needs a new scoped instruction; Phase 5C or later work was not started.

**Final status: READY FOR MANUAL REVIEW.**
