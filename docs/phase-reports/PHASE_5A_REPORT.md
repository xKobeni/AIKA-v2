# Phase 5A — Controlled AI Agent Planning

**Date:** 2026-11-18  
**Status:** READY FOR MANUAL REVIEW — user acceptance pending, not PASSED.  
**Scope:** bounded planning and verified multi-tool work inside the existing conversation lifecycle. Phase 5B and later features were not implemented.

## Workspace and baseline

Inspected the actual local checkout, foundation, roadmap, Phase 4C report, registry/executor/contracts, intent parsers, app/system adapters, Ollama, research, reader/evidence contracts, configuration, CLI, SQLite history and relevant regression tests. The checkout already contained uncommitted Phase 4B-R/4C work; it was preserved rather than replaced with GitHub versions. The baseline was **945 passed in 33.12 seconds**.

No commit, tag, push, Git reset, user-database operation, secret `.env` edit or new dependency was performed. Temporary databases were used for automated and live acceptance. No schema migration, database, agent framework, alternate executor, desktop UI or personality system was added.

## Architecture and trust boundary

`src/intelligence/planning.py` contains inert plan proposals and validation, not a runner. `ConversationSession` remains the sole lifecycle owner. It builds and validates the entire plan before executing anything, then iterates the fixed validated steps using its existing `ToolExecutor`. Registry membership, input contracts and permissions are checked before execution; the executor rechecks the real permission and output contracts at execution time.

Supported operations are existing constrained arithmetic, explicit allowlisted app launches, system snapshot/process inventory, and public web research. Research is a workflow reference to the existing `_research_reply`, not a new tool or copied search/read/synthesis loop. The registry still contains exactly six tools: `calculator.evaluate`, `app.open`, `system.snapshot`, `system.processes`, `web.search`, `web.read`. Raw search/read/ask commands remain separate manual controls; plans do not provide arbitrary URL fetching or a second web orchestration path.

Clear requests separated by `;`, `then`, `and then`, or `and` followed by another recognized request verb use deterministic planning with zero planning generations. Other explicit `/agent` tasks may use one structured Ollama call. Simple conversation, single-tool requests, arithmetic, memory recall, manual commands and single Phase 4C research requests retain their existing routes. Natural multi-tool routing requires an explicit compound boundary and a recognized first operation; unfamiliar wording can use `/agent`.

The model's minimal schema proposes only original user-text instructions and dependencies. It does not supply tool names, executable code, permissions or generated arguments. Every proposed instruction must resolve in original order to an actual current user-text span, allowing only case/whitespace differences. Code uses that original span, runs the existing intent parser and validates its registered tool input. Gaps may contain only a small sequencing/punctuation vocabulary: omitting `do not`, conditions, restrictions or other requested actions fails closed. Unrecognized operations, extra schema keys, invented spans, missing coverage, unknown/disabled tools, invalid inputs, unsupported permission categories, forward/cyclic/self dependencies and repeated calls reject the complete plan before any handler runs.

Planning receives only the current task and fixed policy/schema guidance. It receives no conversation history, system measurements, personal memory, search snippets, page text, prior tool results or API key. There is no observation-driven replanning and no substitution of earlier tool/source text into later action arguments. Malicious webpage/tool/model text therefore cannot create a new action or authorization. The fixed final summary uses existing tool formatters and validated research output, with no extra free-form synthesis call or pretrained fallback.

No architecture ADR is needed: this is the already documented planner role under ADR-001/ADR-006, with ConversationSession retaining execution authority. The phase roadmap is the detailed checkpoint numbering; the older foundation's high-level phase numbering remains historical.

## Limits, dependencies and outcomes

| Boundary | Enforced policy |
| --- | --- |
| User task | 1–1,200 printable characters |
| Plan | At most 4 steps, original order, no dynamic additions |
| Executor | At most 8 invocation attempts, including denied/failed nested calls |
| Generations | At most 2: optional planning plus at most one research grounding call; no final-generation call |
| Research | At most one workflow; existing one search / five read attempts / three successful pages |
| Overall time | 180 seconds by default; `AIKA_AGENT_TIMEOUT` finite 30–300 seconds |
| Planner output | At most 4,096 characters; Ollama structured schema with 512 prediction-token cap |
| Retries | None; no automatic replanning, tool retry or query expansion |
| Duplicate guard | Preflight normalized tool/arguments, plus runtime call identity guard, including failed attempts |

Plans reserve the worst-case six executor slots for research. Research plus at most two other operations fits the eight-call cap; larger plans are rejected rather than partially guessed or truncated. Local model availability/thinking probes are existing adapter requests, not extra generation calls. DDGS internal engine waves and explicitly authorized provider fallback remain the existing provider behavior, not agent retries or counted low-level HTTP packets.

`then` requires verified success of the preceding step. Model dependencies must reference distinct earlier numeric step IDs; explicit `then`/`afterwards` cannot be erased. A failed/inconclusive/skipped dependency skips its descendants. Independent `and`/`;` steps can continue after an ordinary controlled tool failure. Invalid plans, global budget exhaustion, interruption and unexpected internal errors stop further execution, including independent remaining work. A limit failure encountered inside nested research stays latched at the outer boundary even if the existing research layer returns a controlled failure.

Each step records `pending`, `running`, `succeeded`, `failed`, `inconclusive` or `skipped`. Success requires a successful, verified ToolResult with real data, or an accepted existing grounded research outcome. Executor attempts are counted honestly; a denied validation attempt is not proof a tool handler ran. In-flight interruption/uncertainty is inconclusive, not success. Known completed local results are preserved in a partial answer even when time expires afterward. A late research/model answer is discarded by existing deadline checks.

Application launches still require an exact user-requested approved app ID, trusted `LocalActionAuthorization`, fixed targets and existing process verification. Process observation does not establish window readiness. An inconclusive launch cannot unlock a required next step; no launch is retried. A handler error that carries evidence of an attempted launch adds a check-before-retry warning. No general desktop automation, shell, file access/editing or memory operations are available through planning. Existing memory commands remain separate.

## Shared budget, cancellation and persistence

The existing request deadline now nests using the smaller parent/child deadline, so Phase 4C research cannot reset or extend the agent budget. Existing provider, DNS-pinned reader and Ollama adapters keep their clipping/checks. Scope tokens reset in `finally`; later normal chat is unaffected. Existing TLS, DNS pinning, SSRF/private-IP blocking, peer validation, two same-host HTTPS redirects, byte/time limits, extraction fallback and grounding quote/source/version/status verification are preserved.

Cancellation uses Ctrl+C/KeyboardInterrupt or an optional in-process cancellation predicate at safe checkpoints. There is **no hard process preemption**: native DDGS work, HTTP read-inactivity semantics, extraction or an already started process can outlive a nominal deadline. Already issued actions cannot be undone. After a known stop, no further AIKA operation starts and no uncertain result is described as verified success. Expanded approval UI, background jobs, durable cancellation and partial recovery are Phase 5B exclusions.

`last_agent` holds safe transient metadata: generated request ID, outcome, executor/model counts, elapsed time, step number/tool/state/category and attempt count. It contains no instructions, arguments, results, queries, URLs, page content, private prompts, memory values, credentials or raw model response. `/status` shows configured limits and a short last outcome. No raw planner logging or debug response dump was introduced.

The final user/assistant exchange uses the existing atomic SQLite save. Full plan/result state is transient; `/new` and `/resume` clear it and active source evidence. Restoring saved citation-bearing text never reruns planning, tools, searches or model generation. Storage failure does not retry actions, append an unsaved active-history turn or pretend to roll back a launch. After any executor attempt, the controlled storage error states that operations were not rolled back and actual app state should be checked before resubmission. Crash recovery/job journals are not claimed.

## Files changed in this checkpoint

This list distinguishes Phase 5A work from the many earlier uncommitted files already present at baseline.

| File | Change |
| --- | --- |
| `src/intelligence/planning.py` (new) | Conservative routing, typed steps, structured schema, original-text resolution, registry/input/permission/dependency/duplicate validation |
| `src/intelligence/conversation.py` | Sole-owner agent branch, bounded execution/model calls, verified outcomes, partial summaries, history isolation, cancellation and storage handling; injectable existing research callbacks |
| `src/capabilities/web_budget.py` | Nested scopes cannot extend an outer deadline |
| `src/config.py`, `.env.example` | Validated optional `AIKA_AGENT_TIMEOUT`, default 180 seconds |
| `src/cli.py` | `/agent`, progress, help/status limits, structured local planner callback, current phase 5A |
| `src/diagnostics.py` | Agent configuration check with no tool/provider activity |
| `tests/test_agent.py` (new) | Deterministic/mocked planning, execution, trust boundaries, research integration, budgets, interruptions, privacy and persistence |
| `tests/test_applications.py` | Preserve compound-target rejection for manual `/open`; add two-explicit-app natural task verification |
| `tests/test_runtime.py`, `tests/conftest.py` | Current-phase expectation and isolated agent environment configuration |
| README, roadmap, this report | Setup, safe limits, accurate implementation/review status, actual results and walkthrough |

No permission category, ToolExecutor, registered tool, SQLite schema, existing secret file or configured model was changed in this phase. The single-launch injection case remains tested as `/open Notepad; launch Calculator`; the formerly rejected natural phrase is now intentionally accepted as two independently scoped explicit app requests. Other injection, ambiguous target, arbitrary path/arguments and shell-denial tests remain.

## Automated verification

- Baseline: `python -m pytest -q` — **945 passed in 33.12 seconds**.
- Focused agent/application/research suite before the final two planner-format regressions: **247 passed in 4.37 seconds**.
- Full suite before the final schema wording clarification: **1034 passed in 28.07 seconds**, no warnings.
- Final `python -m pytest -q`: **1034 passed in 28.46 seconds**, no warnings. This retains the 945 baseline cases (with the documented intentional routing/phase expectations updated) and adds 89 cases: 88 agent tests and one compound-app test.

The added cases exercise deterministic planning without models/handlers; exact original-text resolution; legitimate spacing/case changes; malformed/oversized JSON; invented tools/actions/arguments; omitted restrictions/operation verbs; full-plan validation before side effects; duplicate/cyclic/invalid dependencies; unknown and changed permissions; exact launch authorization; actual/inconclusive outcomes; dependent skipping and independent continuation; failed reads within the eight-call cap; runtime execution/model/duplicate caps; model timeout and budget expiry; no deadline extension; cancellation before/during/between work; malicious model/page text; no private results sent into a web query or planner; no unexpected Tavily requests; one atomic history exchange; storage failure without retry; resume without replay; CLI help/progress; and invalid timeout settings.

Automated provider, network, launch and model responses are mocked. Previous memory, calculator, application, system, provider billing/fallback, redirects, DNS rebinding/SSRF, extraction, citations and conversation tests remain in the full suite. No live Tavily credits were consumed.

## Actual live smoke tests

All runs used `TemporaryDirectory` storage, configured **qwen3.5:4b**, web search disabled and no Tavily key passed to the Session. No existing user database was read or changed. No desktop application was launched.

1. `/agent calculate 12*7 then show my system information` completed **two verified executor operations, zero model generations, 203 ms**. Arithmetic returned 84 and actual local Windows/psutil snapshot data was returned. Private measurement values are not reproduced in this report. Resume restored the same history without execution.
2. The initial free-form sentence task exposed local-model schema reliability issues. The original offset-based proposal was safely rejected with zero executions. The simpler copied-instruction schema also rejected a proposal; fixed metadata inspection showed two four-character instructions, consistent with expressions without their required operation verbs. A dedicated regression rejects this omission. No raw model responses were logged or used to authorize anything. These were separate developer smoke invocations after code changes, not automatic application retries.
3. After replacing offsets with original-text resolution, retaining case/whitespace-only tolerance, and adding an explicit operation-verb/schema example, `/agent First calculate 12*7. Afterwards calculate 20/4.` completed with **84 and 5**, **one structured planning generation, two successful executor calls, 8.890 seconds**. No extra answer generation was used. This demonstrates one successful real qwen3.5:4b planning case, not deterministic success for every free-form wording. The final wording cleanup removed an obsolete “zero-based” phrase and made the unsupported empty-plan schema consistent; that small cleanup was regression tested, not repeatedly live-generated.
4. Actual `python -m aika`, `python -m aika doctor`, `python -m aika --version`, and `python -m aika --help` each exited **0** against isolated storage. Doctor reported six tools, successful temporary SQLite checks, local Ollama availability and the agent limits. Diagnostics made no web/source/provider requests.
5. Actual piped `python -m aika chat` exited **0** with these inputs: two arithmetic operations; a division-by-zero followed by a required arithmetic step and an independent arithmetic step; disabled research followed by a required arithmetic step; `/history`; `exit`. Observed results were 84/5, a correctly skipped dependent step plus independent result 8, an explicit disabled-web response with no provider call and a skipped dependent step, and saved history. Progress occurred only for attempted operations; skipped steps had no running message.

No final-code live DDGS/Tavily research-agent chain, application launch, malicious public site, hard process cancellation, crash recovery, fresh dependency installation or Phase 5B approval was exercised. Mocked tests verify integration/security boundaries and the prior Phase 4C report records its actual live web chain; those are not presented as a new live Phase 5A web acceptance. DDGS's existing intermittent upstream failures remain.

## Manual acceptance

Open a dedicated PowerShell in the checkout. Use isolated storage and keep web/paid fallback disabled initially:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-5a-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_WEB_SEARCH_ENABLED = 'off'
$env:AIKA_WEB_READING_ENABLED = 'off'
$env:AIKA_WEB_SEARCH_PROVIDER = 'ddgs'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
$env:AIKA_AGENT_TIMEOUT = '180'
python -m aika doctor
python -m aika chat
```

Enter these scenarios, checking actual states rather than assuming overall completion:

```text
/agent calculate 12*7 then show my system information
calculate 2+2 and calculate 3+3
/agent calculate 1/0 then calculate 3+3; calculate 4+4
/agent calculate 2+2; calculate 2 + 2
/agent calculate 2+2 then run powershell
/agent First calculate 12*7. Afterwards calculate 20/4.
/agent research latest Python release then calculate 2+2
/status
/history
```

Expect two verified local results; then partial failure with one dependency skipped and independent result 8; duplicate and shell requests rejected before any execution; a bounded structured model plan or an honest controlled rejection; and disabled research with no network call or dependent calculation. Ordinary `hello`, `2+2`, saved-memory recall and `/calc`, `/system` should keep their existing routes. Use existing explicit memory commands separately and verify their usual behavior.

To test a real launch deliberately, enter `/agent open Notepad then calculate 2+2`. Check the actual application. Only a verified running process permits the dependent calculation; window readiness is not claimed. If the launcher is unavailable/inconclusive, expect failure/inconclusive state and a skipped calculation, not a retry. `/open Notepad; launch Calculator` remains an invalid manual target.

Exit chat, deliberately enable only the existing web gates, and restart:

```powershell
$env:AIKA_WEB_SEARCH_ENABLED = 'on'
$env:AIKA_WEB_READING_ENABLED = 'on'
# Keep provider=ddgs and fallback=off to prevent Tavily usage.
python -m aika chat
```

Try `/agent calculate 12*7 then research latest Python release`, and the roadmap scenario `Open Notepad and find the official Python download page.` Inspect actual provider, URLs, retrieval timestamps and claims. Accept an honest bounded failure if sources/provider/model cannot verify the question; never treat the search snippet as a read page. Check that only explicitly requested apps launch and webpage instructions never become operations. Compare a standalone `/research` and the manual `/web` → `/read` → `/ask-web` path. Provider modes/fallback opt-ins retain the existing documented behavior; no paid review is required here.

At a safe point during a long model/research operation, use Ctrl+C and inspect the interrupted/partial reply, skipped work and subsequent chat usability. It may wait for the current native operation; this is not a hard-stop guarantee. Copy the `/status` session ID, exit, start again and `/resume <id>`; saved answers must restore without tool/provider/model replay. Finally run `python -m pytest -q`.

## Remaining limitations

- Natural language and original-text matching are deliberately narrow. Model paraphrases, unsupported conditionals, references such as “use that result,” generated arguments, omitted qualifiers, repeated work and multiple research workflows fail closed. Use explicit supported clauses; no model expansion or automatic repair loop is provided.
- Dependencies are control-flow prerequisites, not general dataflow or semantic task planning. Independent operations may continue after ordinary failures because the user requested them; use `then` when a prerequisite is required.
- Exact span/input verification prevents invented operations, but does not prove that every safely parsed task captures every human nuance. Model/source semantic grounding retains its existing conservative limits and false negatives.
- Deadlines/cancellation are cooperative, and already issued actions cannot be undone. Native overrun, abrupt termination between an action and final history save, and process/window uncertainty remain possible. There is no durable job journal or automatic recovery/retry.
- Transient metadata/active evidence are cleared on resume; history preserves the final summary and citations, not a resumable plan. SQLite cannot roll back external actions.
- No fresh live web-agent or app-launch acceptance was performed in this phase. DDGS availability and qwen3.5:4b generation remain variable. No paid fallback was enabled to make verification succeed.

**Final status: READY FOR MANUAL REVIEW.** Stop at Phase 5A. Phase 5B requires a new instruction and user acceptance is not assumed.
