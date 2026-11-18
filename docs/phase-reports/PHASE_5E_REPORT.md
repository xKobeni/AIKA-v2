# Phase 5E — Capability-Aware Intent Routing & Agent Usability

Date: 2026-11-18. Status: **READY FOR MANUAL REVIEW** after the manual-acceptance repair below. Phase 5E has not been user-approved. The supplied Phase 5E brief explicitly approves Phase 5D; historical reports are retained.

## Baseline and confirmed gaps

Inspected the foundation, implementation roadmap, Phase 5A–5D reports, actual ConversationSession lifecycle, memory recognizer/transaction/provenance, calculator, approved applications, system measurements, search/source/research recognizers, planner/dataflow/conditions, registry/executor, configuration, diagnostics, CLI and tests. The checkout was clean before this checkpoint.

Baseline `python -m pytest -q`: **1,295 passed in 40.81 seconds**.

Confirmed source-level gaps: calculator did not accept `work out` or spelled-out `percent of`; local measurement recognition missed common polite/possessive/current-RAM/available-memory wording; `Search online for` fell outside existing research recognition and natural search was not used at that fallback entry; source-finding research wording and the requested memory revision wording were absent. Capability questions depended on ordinary generation. Existing app wording already covered most examples, while sharing normalization adds consistent punctuation/AIKA-prefix handling. Existing latest-release questions already enter bounded research and were deliberately preserved.

## Changes and routing priority

The existing ConversationSession remains the only request orchestrator. The existing registry still has six executable tools. No executor, permission, schema, model setting, dependency, provider or workflow budget changed.

1. Validate the raw request before trimming: 16,000-character overall bound; reject nonprintable controls except CR/LF/tab. Existing 1,200-character agent, 512-character calculator and narrower web/source bounds still apply. Rejected raw requests do not run tools, generate text or append history.
2. Explicit slash commands keep their existing CLI/Session handlers. `/capabilities` is the only new command; `/help` lists it. Explicit command arguments retain their validation and are not rewritten by natural-language normalization.
3. Recognized memory operations stay ahead of natural action planning. Ordinary project statements retain their established behavior and cannot override a calculator command. Pending memory handling, committed writes, revision history, evidence and ambiguity resolution stay in the existing memory implementation.
4. Capability questions, narrowly supported clarification patterns and clear unsupported requests use deterministic answers. They do not generate or execute tools. Any pending memory confirmation is cleared when a separate deterministic capability/action response takes over.
5. Clear existing agent/dataflow/conditional requests still use the same planner/executor. Simple arithmetic and measurements retain single-tool routes. Existing source-answer/read, research and explicit `/web` priorities remain. The new natural search fallback reuses `web_request`, including a guard against personal/project/history queries bypassing the existing research privacy boundary.
6. Ordinary explanations fall through to the same Ollama conversation. No global capability-disclaimer replacement, model classifier, additional model context injection, new dialogue state machine or model repair loop was added.

Harmless normalization is shared across calculator, application, system, web and research recognizers: common whitespace, curly apostrophe, AIKA salutation, polite request prefixes and terminal punctuation. It does not discard arbitrary suffix instructions, executable arguments or unsupported actions to manufacture an accepted task.

## Exact wording improvements

| Area | Accepted examples / behavior |
| --- | --- |
| Calculator | `What's 245 multiplied by 18?`, `Calculate 245 times 18.`, `What's 15 percent of 800?`, `Calculate 15 percent of 800.`, `Can you work out 12 times 7?` → existing safe calculator |
| System | `How much storage do I have left?`, `Can you check my disk space?`, `How full is my C drive?`, `What's my current RAM usage?`, `How much memory is available on my computer?`, `Check my laptop's system information.`, `Show me my PC specs.`, `Can you check my laptop's RAM usage?`, `Check my computer's RAM usage.`, `Show me my PC system information.` |
| Drive identity | C-drive wording requests the existing system-drive snapshot; a non-C or missing measured identity produces an unavailable explanation, never relabeled C-drive values |
| Apps | Existing `Open Notepad.`, `Launch Calculator.`, `Start Notepad.`, `Can you open Notepad for me?`; shared salutation/spacing/punctuation. Actual allowlist and exact authorization still apply |
| Search | `Search online for Python release notes.` uses `web.search`; existing look-up/official-documentation/latest-release wording retains its previous search or bounded research route |
| Research | Existing `Research the latest Python release.` and citation phrasing; new `Find sources and explain what they say about Python 3.15.` reuses bounded research |
| Memory | Existing save/correct/current/list forms; new `What was the previous frontend I recorded for Orion?` uses existing history intent. `What about my project?` uses existing subject resolution or clarification |
| Multiple tools | `Calculate 12 times 7, then show my RAM usage.`, `Check my system information and calculate 9 times 9.`, `Research the latest Python release, then calculate 12 times 7.` use existing planning, preflight and budgets |
| Conditions | `Check whether my free storage is below 20%.`, `Tell me if my RAM usage exceeds 90%.`, `Warn me when my disk usage is above 85%.` normalize to the existing strict Phase 5D condition parser |
| Dataflow | `Calculate the percentage of free space on my system drive.` retains existing verified Phase 5C dataflow |

`Warn me when` means an immediate snapshot and response. No monitoring, scheduled task, alert service or conditional side effect exists. Unsafe suffixes remain part of the parsed request and fail closed. The original Phase 5D sentence and explicit `/agent` routes remain regression-covered.

Explanations such as `Explain how multiplication works.`, `What is a percentage?`, `What is cloud storage?`, `Explain RAM.`, `How does Windows manage memory?`, `How do I open Notepad?` and `What is a search engine?` do not request tools.

## Capability discovery and honest status

`src/capabilities/discovery.py` renders the existing registry definitions and actual session adapters; it is not another tool registry or execution authority. It shows registered names, enabled/disabled state, existing permission categories, descriptions and command examples. Local system readiness uses the existing interface initializer without sampling. Approved app readiness uses the existing target validation/availability checks. Search uses the existing adapter's local `unavailable_reason`; reading shows the independent reading/network gate and selected-source prerequisite. Research depends on registered/enabled search/read tools and their gates/readiness. Agent/dataflow descriptions state their prerequisites and existing limits.

Conversation and memory are described as configured, not proven live. Listings explicitly distinguish local readiness from live inference, provider authentication/connectivity/credits, measurement collection, window readiness and committed database writes. They do not probe Ollama, search providers, sample metrics, enumerate processes, launch apps or expose keys. The listing does perform bounded local readiness checks such as imports and approved-target metadata checks; it is not a filesystem scan. The response itself is saved through the existing conversation exchange, like other answers.

`What can you do?`, `What tools do you have?`, `Can you check my system?`, `Can you access my system information?`, `Can you browse the web?`, `Can you remember information?`, `Can you control my computer?`, `Can you open applications?` and `Can you delete files?` are answered without generation. Broad `Can you check my system?` describes capability; `/system` or a specific metric request collects data. No GPU/temperature measurement, unrestricted desktop control or automatic memory is claimed.

`Open it.`, `Check the latest version.` and `Show me the information.` ask a focused target question without tools. Project ambiguity stays in existing memory context resolution. General file deletion, shell commands/installation, private-file sweeping, all-window control and screen recording receive deterministic limitations. Unsupported application paths/PowerShell still fail the actual app contract without launching. Mixed supported/unsupported plans must pass complete preflight before any execution; no approved step grants authority to another action.

## Evidence, privacy and performance safeguards

Actual handlers still supply ToolResult status, verification and bounded errors. Calculator values come from actual safe arithmetic; snapshots come from system.snapshot; launch uncertainty remains explicit; research requires real source evidence; memory success requires transaction commit. No deterministic capability response fabricates execution. No model can choose a new tool or permission through these changes.

Existing external-source isolation, source selection and citations, request lock, deadlines, four-step/eight-attempt limits, cancellation, partial results, exact conditional comparison, copied binding evidence, SQLite failure semantics and history/resume without replay remain in the complete regression suite. No user facts or conversation history are automatically sent to web providers. Natural personal/project search phrasing cannot bypass the previous guard. Explicit commands remain deliberate user requests subject to the original contracts and gates.

Common arithmetic/system/app requests add zero model calls; capabilities/clarifications/unsupported replies use zero model or tool calls. Conditions/dataflow use two existing executor calls and zero generations. No extra classifier pass, speculative operation, background process, network readiness check, paid fallback switch or additional history scan was introduced. Existing research may generate only after evidence retrieval under its original budget.

## Files changed

| Files | Purpose |
| --- | --- |
| `src/capabilities/language.py` (new) | Shared bounded language normalization |
| `src/capabilities/discovery.py` (new) | Read-only capability presentation, deterministic status, clarification and unsupported wording |
| `src/capabilities/intent.py`, `application_intent.py`, `system_intent.py`, `web_intent.py`, `research.py` | Reuse normalization, add small wording aliases, preserve actual contracts and privacy guards |
| `src/intelligence/conversation.py` | Existing lifecycle integration, memory/command priority and raw input validation |
| `src/intelligence/dataflow.py` | Normalize three immediate-condition aliases into the same strict parser |
| `src/memory/intent.py` | Existing history/subject intent aliases |
| `src/cli.py` | `/capabilities`, help and current phase label |
| `tests/test_capability_routing.py` (new) | Focused Phase 5E tests |
| `tests/test_runtime.py` | Current phase assertion only |
| `README.md`, implementation roadmap, this report | Supported scope, verification, limitations and review instructions |

## Automated verification

- Baseline: **1,295 passed in 40.81 s**.
- Routing/conditional/research/app regression group: **461 passed in 9.92 s**.
- Initial complete regression: **1,408 passed in 42.86 s** (113 new tests at that point).
- Final focused `python -m pytest -q tests/test_capability_routing.py`: **114 passed in 3.29 s**, including an additional trailing-control-character boundary case.
- Final `python -m pytest -q`, including raw-input and final capability-status refinements: **1,409 passed in 44.51 s**, no warnings. All 1,295 baseline cases remain, plus **114 new cases**. `git diff --check` passed.

The new tests verify the requested wording families, selected tool/result attribution, deterministic status and live-readiness wording, command/memory priority, disabled registrations, permissions, allowlist/path rejection, independent web/reading gates, no provider/model/launch requests during discovery, no paid fallback, unsafe multi-action/conditional suffix rejection, external snippet isolation, memory provenance/revisions/no automatic new facts/rollback, input bounds, history/resume and storage failure. Existing agent progress, cancellation, budgets, partial results, source injection/SSRF, provider policy, startup/doctor/help/version and database cases remain in the full suite. No test was removed or weakened; only the runtime phase-label expectation changed.

Pytest uses mocked model/provider/measurement/GUI boundaries and synthetic memory. It makes no live provider calls, GUI launches or paid requests. The separate live checks below are not pytest results.

## Actual live checks

All storage writes used TemporaryDirectory databases. No existing user database, V1 file, secret file or configured model was changed. No GUI was launched. No Git commit, tag or push was created.

1. Actual Windows snapshots succeeded and were verified for storage-left, polite laptop RAM and PC system-information requests, each with one `system.snapshot` call and zero model calls.
2. Real calculator returned **4410**, **120** and CLI **84** through existing validated execution.
3. `/capabilities`, general discovery and system/app capability questions used zero tool/model calls. Actual listing showed Windows tools and approved targets locally ready, and disabled web/search reading in the isolated offline session.
4. Downloads deletion returned the controlled limitation with no tool. `Open PowerShell and run a command.` reached the existing app contract and returned `invalid_input`, unverified, with no launch.
5. Original Phase 5D storage sentence executed snapshot + calculator, both verified, and selected TRUE at that moment. New check-whether free-storage also selected TRUE; RAM-above-90 and used-disk-above-85 selected FALSE at those moments. Each used exactly two verified tools and no generations. These are time-specific decisions, not fixed future expectations or ongoing monitoring.
6. Explicit C-drive percentage dataflow and `/agent calculate 12*7 then show my system information` each completed with two verified tools and no generation. No measurements were guessed or reused from history.
7. Synthetic project `Phase Five Synthetic` was explicitly saved as SvelteKit, recalled, corrected to Next.js, and previous SvelteKit recalled. The fact had revision 2. Resume restored identical history and cleared transient agent state without replay.
8. Actual unchanged **qwen3.5:4b** produced ordinary answers to `What is cloud storage?`, `Explain how RAM works.` and `What is a search engine?`: one model call each, zero tool calls. No new classification pass was used.
9. Live DDGS-only search (`SearchRouter(True, '', 'ddgs', False)`) for official Python documentation returned controlled **timeout**. Live research of the latest Python release returned controlled **indeterminate** search failure. Both made only `web.search`; neither fabricated current facts/citations nor silently used Tavily. No successful fresh live source-reading/grounded research chain was demonstrated.
10. Actual isolated `python -m aika`, `doctor`, `--version`, `--help` each exited **0**. Doctor reported six tools, temporary SQLite success, local Ollama/model availability, unchanged agent limits and disabled web gates. A piped CLI chat containing `/capabilities`, `What can you do?`, arithmetic, ambiguity, unsupported deletion and `/history` exited **0** and displayed saved answers.

The first standalone acceptance harness attempt stopped before any request because it supplied a string rather than Path to the existing store constructor. The harness was corrected and the full live sequence above completed. No production change was made for that harness error.

## Safe manual review walkthrough

Use a dedicated PowerShell with isolated storage:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-5e-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_WEB_SEARCH_ENABLED = 'off'
$env:AIKA_WEB_READING_ENABLED = 'off'
$env:AIKA_WEB_SEARCH_PROVIDER = 'ddgs'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
$env:AIKA_TAVILY_API_KEY = ''
python -m aika
python -m aika doctor
python -m aika --version
python -m aika --help
python -m aika chat
```

Try the wording table, `/help`, `/capabilities`, explanatory questions, `Open it.`, `Check the latest version.`, `What about my project?`, Downloads deletion, and the original one-line Phase 5D sentence. Check actual verification/source timestamps instead of expecting the old TRUE/FALSE observations. `/agent calculate the percentage of free storage on my C drive` and `/agent calculate 12*7 then show my system information` must preserve two verified operations. Use synthetic memory, for example:

```text
Remember that Review Synthetic uses SvelteKit.
What frontend did I save for Review Synthetic?
Correct Review Synthetic's frontend to Next.js.
What was the previous frontend I recorded for Review Synthetic?
/history
```

Resume that saved session using `/sessions` and `/resume <id>` after restarting. Expect restored text and no replayed operations. No production facts are required. For optional live web review, exit chat, explicitly enable both web gates in that same dedicated shell, keep DDGS selected/key empty/fallback off, and try the search/research examples. Accept an honest provider/evidence error when the network fails; do not interpret it as a grounded result. Pytest covers denial, malformed source data, missing fields, cancellation and budget failures without changing the live machine.

## Limitations and next checkpoint

Recognition remains deliberately bounded. Unlisted paraphrases and vague references may still need an explicit command or ordinary conversation. No general coreference engine was added. Natural personal/project/history searches are conservatively excluded; explicit `/web` stays the deliberate route. Existing app-only combinations without supported sequencing may retain the existing ambiguity response. No arbitrary drive, GPU/temperature measurement, file management, shell, desktop vision/control, voice, autonomous planning, automatic memory extraction or monitoring was added.

The listing reports current local readiness, not cached previous success; it cannot establish provider credit balance, future connectivity or model quality. Native blocking/cancellation limitations and uncertain application outcomes remain as documented in earlier phases. GUI launch and a successful fresh live research/source chain were not newly demonstrated here; mocks and existing regression tests cover their boundaries.

Recommended next checkpoint: **manual review of Phase 5E**, then a separately authorized scope. No subsequent phase has started.

## Manual acceptance findings and repair

The user reported two failed manual scenarios after the initial implementation: `How much space is left on my laptop?` was incorrectly treated as an unsupported drive/location, and `Can you open Notepad?` unexpectedly launched Notepad. These are confirmed Phase 5E defects; the initial verification above did not establish that these exact phrases worked. The user did not approve Phase 5E.

Repair baseline before editing: `python -m pytest -q` — **1,409 passed in 41.54 s**.

### Actual causes and targeted fixes

- `_storage_request` recognized general PC/computer/system-drive scope but omitted laptop. Its separate unsupported-location fallback therefore rejected the laptop sentence. The shared bounded device scope now includes laptop/desktop/notebook and applies to both “is left/available/free” and “do I have [left]” forms. `unsupported_measurement` uses that same recognized scope before rejecting other locations, which also keeps the agent preflight consistent. Explicit unsupported drive/location requests remain rejected. Aggregate all-drive/combined requests receive a deterministic limitation before measurement or model generation.
- Every rendered storage snapshot now says `Scope: Windows system drive only; not aggregate storage across all drives.` Existing actual drive identity, free/used/total capacity, collection time and source are retained. C is displayed only when the measured system drive is C. No tool, drive enumeration or all-drive arithmetic was added.
- App recognition previously removed `Can you` as politeness before determining the speech act. New `application_question` preserves bounded ability wording before that normalization. It is shared by capability presentation and the existing app recognizer, so a capability question cannot become a launch merely by reaching planner operation recognition.
- `Can/Could/Would you open/launch/start <target>`, `Are you able to launch/open/start <target>` and `Do you support opening/launching/starting <target>` are nonexecuting ability questions unless the recognized polite-action form explicitly contains `for me` (optionally `now`/`please`). Known targets are described using the actual registry, app enabled state and existing target readiness. Unsupported, disabled and locally unavailable targets receive truthful limitations, without launch or model generation. The response does not claim a running process or ready window.
- Existing imperatives, `/open`, and polite action forms such as `Can you open Notepad for me now?` retain actual validated executor launch handling. `Open Notepad now.` is supported by stripping only the terminal immediate-action qualifier; arbitrary paths/arguments/other suffixes remain subject to the existing strict allowlist contract. Bare ability wording ending in `now` asks for clarification instead of launching.
- Removed the redundant standalone `RAM` line from conditional rendering. RAM title, used percentage, threshold, branch, exact-comparison explanation, tool evidence and timestamps remain. Storage conditions retain their drive line.

No application allowlist, permission, process-verification, execution budget, cancellation, source policy, database schema, dependency, configured model or orchestrator was changed. No Phase 5F work was started.

### Repair tests and verification

Added `tests/test_5e_acceptance_repair.py`: **36 tests** for general-device wording/scope, other drives, aggregate exclusions, ordinary storage explanations, zero-side-effect ability questions, explicit and polite action launches, unauthorized targets, disabled apps, permission denial, agent-route rejection, RAM presentation and resume without replay. Launches in pytest use the existing mocked OS adapter. The old `Can you open Spotify?` launch-intent case was intentionally changed to `Can you open Spotify for me?` to match the corrected contract; new tests assert that the original bare question returns no launch request. No other existing expectation was relaxed.

- Focused new repair file: **36 passed in 2.64 s**.
- Existing routing/app/system/conditional/execution-control group plus repair cases before the final two device-wording cases: **511 passed in 10.56 s**.
- Full repair `python -m pytest -q`: **1,445 passed in 44.27 s**, no warnings. All 1,409 pre-repair cases remain, plus 36 new cases; the one changed Spotify test preserves launch coverage under the corrected action wording.

Safe local acceptance used one TemporaryDirectory database, the unchanged `qwen3.5:4b`, disabled web gates, DDGS mode, empty key and fallback off. A launch-adapter guard would fail if invoked; it remained unused throughout. The six exact requests from the repair brief produced:

| Request | Actual result |
| --- | --- |
| `How much space is left on my laptop?` | One successful verified `system.snapshot`; actual C: drive free/total capacity, explicit Windows system-drive-only scope, timestamp `2026-11-18T15:37:01.488669+00:00` and local API provenance. Zero model/launch calls. |
| `Can you open Notepad?` | Exact support/explanation response with `Open Notepad` example and window-readiness caveat. Zero tool/model/launch calls. |
| `Are you able to launch Notepad?` | Same deterministic support response. Zero tool/model/launch calls. |
| `What is cloud storage?` | Actual ordinary Ollama explanation; one model generation, zero tools/launches. |
| `What's 245 multiplied by 18?` | Actual verified calculator result **4410**; zero model/launch calls. |
| `Check whether my RAM usage exceeds 90%.` | Verified snapshot + calculator, **88.90%**, FALSE/normal at that moment, two successful steps, zero generations. Collection time `2026-11-18T15:37:28.445153+00:00`. Title followed directly by `RAM used`, with no redundant standalone `RAM` line. |

Actual `python -m aika`, `python -m aika doctor`, `python -m aika --version` and `python -m aika --help` each exited **0**, using the same isolated storage. Doctor confirmed six tools, compatible temporary conversation/memory storage, installed local model and unchanged budgets; optional web remained disabled. No live GUI launch or provider request was made. Actual explicit-launch behavior is tested through the real adapter with mocked OS process creation, not claimed as a new live GUI test. `git diff --check` passed (only the existing Windows line-ending normalization notice).

Changed for this repair: `src/capabilities/system_intent.py`, `src/capabilities/application_intent.py`, `src/capabilities/discovery.py`, `src/intelligence/dataflow.py`, the new repair test file, the one corrected app-intent test case, README wording and this report. Earlier Phase 5E changes remain uncommitted and preserved. No production database, V1 file, model configuration, commit, tag or push was changed.

### Remaining ambiguity and review

Natural language remains bounded. The documented distinction is intentional: a bare `Can you open Notepad?` asks ability; `Open Notepad` performs an action; `Can you open Notepad for me [now]?` explicitly asks action; bare ability-plus-`now` requests clarification. Use `/open <approved-id>` when action intent should be unambiguous. Capability status is local readiness, never proof of successful execution or window readiness. General device storage reports only the Windows system drive, never total capacity across all physical/logical drives.

Repeat the six exact sentences from the repair brief in an isolated review database. Only the storage, arithmetic and RAM-condition sentences should request tools; the two Notepad questions must make no launch request, and the cloud-storage explanation must stay in ordinary conversation. A real GUI launch was not needed for this safe repair acceptance; explicit launch behavior is regression-tested with mocked process creation. Stop for another manual review.

**Final status: READY FOR MANUAL REVIEW.**
