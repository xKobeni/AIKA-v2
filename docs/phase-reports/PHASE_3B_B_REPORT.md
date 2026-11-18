# AIKA V2 Phase 3B-B — Windows System Information & Awareness

**Status:** READY FOR MANUAL REVIEW  
**Date:** 2026-11-18  
**Approval:** Pending user manual review. Scripted live checks are recorded below, not a claim of final manual acceptance.  
**Scope:** Phase 3B-B only. No Git commits or tags created.

## Purpose and architecture

AIKA can now collect explicit, read-only Windows measurements through two registered tools:

| Tool | Permission | Input contract |
| --- | --- | --- |
| `system.snapshot` | READ_ONLY | Optional `section`: `all` (default), `cpu`, `memory`, `storage`, or `os`. No paths, intervals, or extra arguments. |
| `system.processes` | READ_ONLY | Optional integer `limit` from 1 through 25 (default 10), and `sort`: `pid` (default) or `memory`. No additional metadata flags. |

The registry now contains four tools: the calculator, application launcher, snapshot, and process snapshot. The existing executor validates their arguments and output and supplies the existing typed ToolResult. There is no new result type, orchestrator, permission category, command runner, or agent system. Existing application authorization and higher-risk permission denials are unchanged.

`system_info.py` owns measurement and output validation. `system_intent.py` owns bounded natural-language recognition and presentation. The existing `ConversationSession.reply` selects the registered tool, executes it, formats actual results, and saves the completed exchange using the existing SQLite transaction. Recognized failures never fall through to Ollama. Calculator and app requests retain their earlier routes. Generic RAM explanations remain conversational.

The foundation's illustrative system-status capability is realized here as the two tool names required by the current checkpoint. Restricted file access is not implemented, and the next checkpoint follows the current request: Phase 4A — Web Search Foundation.

## Measurement dependency and sources

`psutil>=7,<8` is the single justified new dependency. It was absent in the active Python environment before this implementation. Installation with `python -m pip install 'psutil>=7,<8'` succeeded and installed **psutil 7.2.2**. The project dependency list now installs it automatically. There are no additional overlapping system-information packages.

All retrieval is in-process. CPU, physical memory, system-drive disk usage, and process attributes use psutil's Windows interfaces. OS version and architecture use Python `platform` and `sys.getwindowsversion`. The actual Windows system drive is derived from the existing `GetSystemDirectoryW` adapter, without a hardcoded drive or a user-controlled path. No PowerShell, CMD, WMI subprocess, web API, or administrator elevation is used.

The dependency is loaded lazily. Missing psutil or an unsupported platform returns a controlled unavailable ToolResult rather than inventing data or breaking normal calculator, memory, or app operations. Doctor reports readiness accurately.

## Snapshot semantics and verification

Snapshot results contain a requested section, measured groups, an actual timezone-aware UTC collection timestamp, source description, and unavailable-field paths. Values remain bytes, counts, and numeric percentages internally. The presentation layer consistently uses GiB (`1024^3` bytes).

- **CPU:** `cpu_percent(interval=0.1)` performs a fresh blocking sample with a fixed short interval. It does not display an uninitialized nonblocking first reading. Logical and physical core counts are read separately. A legitimately measured zero-percent utilization is valid; a missing value is `None`, never a substituted zero. The usage represents a momentary sample, not a permanent property or health diagnosis.
- **RAM:** Read total and available physical RAM once. Used RAM is `total - available`; percent used is derived from those measured bytes and rounded to one decimal place. This matches the installed Windows psutil implementation, which was inspected during implementation. Available memory means memory Windows can allocate/reuse, including reclaimable pages where applicable. Windows psutil exposes its `free` value using the same underlying available physical memory value; AIKA labels the measurement available and does not invent a distinct strictly-free-RAM metric.
- **Storage:** Inspect only the Windows system drive, determined from the system-directory API. Total, used, free, and percent used come from one psutil disk-usage result. No network shares, external drives, directory scans, or caller-specified paths are inspected.
- **OS:** Return reported Windows name/version, Windows build where available, and architecture. Fields that cannot be retrieved remain unavailable rather than inferred.

Focused questions collect only their section. `/system` collects those four sections but never a process inventory. Each request obtains fresh values; changing metrics are not cached across requests. A snapshot's fields are sampled sequentially, not as an atomic hardware-wide instant, and the timestamp records collection completion.

Per-field failures preserve valid measurements elsewhere. Missing fields are listed explicitly and displayed as unavailable. Output validation checks known fields, numeric ranges/types, reasonable integer bounds, capacity consistency, metadata, and timezone awareness. A result with no valid requested measurement is a failure with `verified=False`. A partially available successful result verifies only the actual fields it contains, not the availability of missing fields or the health of the machine.

`Why is my PC slow?` can return the available snapshot, with an explicit explanation that one sample cannot diagnose the cause. CPU temperature requests receive a deterministic statement that temperature monitoring is not implemented and overheating cannot be inferred from utilization.

## Process snapshots and privacy

Process enumeration requests exactly `pid`, `name`, and `memory_info`, with psutil's inaccessible-field fallback. Only PID, sanitized basename, and resident-memory bytes leave the measurement layer as process rows. The code does not request command-line arguments, environment variables, usernames, open files, window contents, authentication material, or histories.

Default order is ascending PID. Memory ranking sorts measured resident memory descending, then PID; unavailable memory sorts last. A bounded heap retains at most the requested limit, with a maximum of 25 rows. Computing a memory ranking can inspect all current processes, but it does not retain or return an unlimited inventory. The enumeration cache is cleared before and after collection.

Resident memory is the Windows resident set/working set. It can include shared pages, so it is not an exclusive allocation and cannot be summed as an exact account of physical RAM consumption. Per-process CPU utilization is omitted because this checkpoint does not perform reliable per-process interval sampling.

Protected processes, inaccessible fields, and processes exiting during iteration or attribute inspection are handled without elevation. A known PID can remain in the result with unavailable name or memory. Counts explain partial access and process exits. A successfully completed empty enumeration is labeled empty; an entirely failed inspection due to access denial or process exits is not marked verified. Process names are reduced to basenames, stripped of terminal controls, and limited to 120 display characters.

The reply explicitly states that a process is not proof of a visible or responsive application window. There is no process termination, application closing, continuous monitor, background inventory, window inspection, or other write capability.

## Conversation persistence and model-context boundaries

Completed system replies, including bounded process rows, are saved in the existing SQLite conversation history. This can store process names, PIDs, and memory values; it is documented rather than hidden. Nothing is automatically promoted into structured long-term facts. There is no new schema, migration, database, or persistent metric cache.

`/history` and `/resume` preserve the displayed exchanges. Ordinary model context excludes prior system-measurement request/reply pairs, including after loading a saved session. The filter recognizes the original supported request deterministically without collecting anything again. This prevents automatic transmission of process inventories and prevents treating earlier measurements as fresh. User-authored text still follows ordinary conversation rules. Restoring history does not rerun tools.

Storage failures propagate through the existing storage-error path; the uncommitted response is not appended to active history. System tools have no external side effects to roll back. The existing application-launch storage warning remains unchanged.

The system instruction forbids invented host measurements. A bounded response guard catches common unverified personalized numbers, metric tables, OS claims, and process claims in ordinary generated replies. It is supplementary wording protection, not a universal semantic verifier. Measurement execution and data provenance come from the trusted tools, not model text.

## CLI and diagnostics

Added `/system` and `/processes [limit]`, routed through the registered tools. `/system` accepts no arguments; `/processes` accepts a single integer from 1 through 25. Unsupported flags, malformed arguments, booleans, and out-of-range limits are rejected without measurement or model fallback. The existing help, history, session, memory, calculator, and application commands are preserved.

Natural-language examples include all CPU, RAM, storage, OS, summary, and process questions in the current request. `AIKA, how much RAM is my computer using?` is supported. `Open Calculator` and `Open Notepad` continue to use `app.open`, and arithmetic continues to use the trusted calculator.

Doctor checks supported platform, psutil availability and required callable interfaces, registration, READ_ONLY permissions, and input-contract initialization. It does not call CPU, RAM, disk, or process measurement APIs. Missing measurement dependencies are reported as FAIL on Windows; unsupported operating systems are WARN in diagnostics and unavailable at execution. Existing model, SQLite, memory, calculator, and application checks remain.

Tool debug traces reuse the existing debug setting and show only recognition/execution metadata such as selected tool, permission, validation, verified status, and elapsed duration. Measurement values and process inventories are not included in tool traces or ordinary context traces. Normal CLI replies and saved history contain the requested measurements.

## Files changed

| File | Change |
| --- | --- |
| `src/capabilities/system_info.py` | Lazy Windows measurement interfaces, focused snapshot collection, bounded process collection, input/output validation, metadata, partial failures, and two tool definitions. |
| `src/capabilities/system_intent.py` | Bounded request recognition, strict command arguments, temperature limitation, GiB formatting, truthful replies, and common unverified-claim guard. |
| `src/capabilities/__init__.py` | Register both new system tools with the existing tools. |
| `src/intelligence/conversation.py` | Existing lifecycle integration, deterministic formatting, unsupported-temperature response, and model-context exclusion while preserving full history. |
| `src/cli.py` | New commands/help, capability and phase text, model instructions, and system diagnostics integration. |
| `src/diagnostics.py` | Runtime-file checks and non-measuring system-tool/dependency diagnostics. |
| `pyproject.toml` | Add the single `psutil>=7,<8` dependency. |
| `tests/test_system_info.py` | 110 focused measurement, privacy, intent, CLI, error, persistence, and regression cases. |
| `tests/conftest.py` | Prevent real measurement calls during automated tests; new measurement tests provide mocked APIs. Existing app-launch prevention remains. |
| `tests/test_tools.py` | Extend the expected registered tool set to all four tools. |
| `tests/test_runtime.py` | Update current phase, tool count, and remaining unimplemented component expectations. |
| `README.md` | Commands, sources, privacy and persistence, measurement semantics, limits, and report link. |
| `docs/phase-reports/PHASE_3B_B_REPORT.md` | This report. |

Configuration defaults, the existing ToolResult/executor/permission contracts, application launch code, and memory/database implementation were not changed. No AIKA V1 files, Git commits, or tags were touched.

## Automated verification

- Before changes, `python -m pytest -q` passed **343 tests in 14.42 seconds** on Windows with Python 3.12.10.
- Final `python -m pytest -q`: **453 passed in 15.55 seconds**.
- All 343 previous cases remain; obsolete phase/tool-count expectations were updated without removing failure assertions or tests. The new cases use mocked psutil/platform APIs, temporary databases, and mocked application launches. They do not depend on host CPU load, specifications, or running processes.
- Coverage includes all metric groups, physical/logical counts, a legitimate zero CPU sample, optional and partially unavailable fields, full failure, strict units, timestamp awareness, source metadata, process limits and sorting, protected/exiting processes, iterator races, cache cleanup, basename/control-character privacy, output rejection, malformed arguments, every requested natural-language example, CLI commands, failure without model fallback, unsupported temperature, context privacy after resume, storage failure, and calculator/app/memory regressions.

## Actual live checks performed

The live checks used a temporary data directory and the real Windows/psutil backend. Process names and inventories were captured only as needed for assertions and were not printed in the development transcript.

| Check | Observed result |
| --- | --- |
| Executor `system.snapshot` with default arguments | Verified success; OS/CPU/RAM/storage groups passed output validation. |
| Executor `system.processes`, memory order, limit 25 | Verified success; at most 25 results, measured memory ordered descending, and only the three allowed process fields present. |
| `python -m aika` | Exit code 0; current phase 3B-B. |
| `python -m aika doctor` | Exit code 0; psutil 7.2.2 interfaces, registered READ_ONLY tools, and locally installed qwen3.5:4b reported accurately. |
| `python -m aika --version` | Exit code 0. |
| `python -m aika --help` | Exit code 0. |
| Actual CLI `/system`, CPU, RAM, system-drive, and Windows-version requests | Expected measured sections and source metadata returned, without measurement errors. |
| Actual CLI `/processes`, `/processes 15`, and largest-RAM-process question | Bounded process replies and requested memory ordering returned. |
| Actual CLI CPU-temperature question | Explicit unsupported-temperature response, without a fabricated reading. |
| Actual CLI `/processes --all` | Controlled validation error. |
| Actual CLI calculator multiplication | 4410. |
| Synthetic Orion/SvelteKit save, `/new`, current frontend recall | Saved structured fact correctly retrieved in the new conversation. |

All live subprocess checks returned exit code 0 and temporary storage was cleaned up. Existing user data was not modified. No live application was reopened; app-launch regression was tested with mocked OS launching. Process data was not sent to Ollama. Live checks are implementation verification, not user manual acceptance or a comparison against Task Manager.

## Manual acceptance walkthrough

Use a dedicated PowerShell window in the V2 root. Install the updated dependency first if using another Python environment.

```powershell
python -m pip install -e '.[dev]'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-3bb-review-' + [guid]::NewGuid().ToString('N'))
python -m aika doctor
python -m aika chat
```

1. Enter `/system`. Compare OS/version and approximate RAM/disk capacities against Windows. Live CPU and available memory can vary between observations.
2. Ask `What's my CPU usage?`. Expect a measured momentary percentage and core counts, not a permanent load estimate.
3. Ask `How much RAM am I using?`. Expect used/total/available physical memory in GiB with availability semantics stated.
4. Ask `How much free space is on my system drive?`. Expect free/used/total and the actual Windows system drive.
5. Enter `/processes`, then `/processes 15`. Expect at most 10 and 15 process rows respectively, names/PIDs/resident memory only. Protected fields can be unavailable.
6. Ask `Which processes are using the most RAM?`. Expect descending measured resident-memory values, with missing values last. Compare approximately to Windows' working-set view rather than private/exclusive memory columns.
7. Ask `What Windows version am I using?`. Expect OS metadata only, with unavailable fields labeled if necessary.
8. Ask `What's my CPU temperature?` or `Is my CPU overheating?`. Expect an explicit limitation, without inferring temperature from utilization.
9. Enter `Open Notepad.` or `Open Calculator`. This is an actual authorized app launch; verify the earlier launcher behavior and its honest process/window distinction.
10. Ask `What is 245 multiplied by 18?`. Expect 4410 from the calculator.
11. Save `Remember that Orion uses SvelteKit for its frontend.`, enter `/new`, and ask `What frontend does Orion currently use?`. Expect the saved SvelteKit value. Exit and restart to confirm persistence as well.
12. Enter `/processes 26`, `/processes --all`, and `/system extra`. Expect controlled validation errors without invented results.
13. Use `/history` and `/resume <session_id>` to inspect saved measurement exchanges. They must remain visible without automatically collecting new data or including old inventories in ordinary Ollama context.

Exit and run:

```powershell
python -m aika
python -m aika doctor
python -m aika --version
python -m aika --help
python -m pytest -q
```

Close the dedicated shell afterward to discard its environment overrides. Close any application windows opened during review yourself.

## Known limitations and next checkpoint

The tools target Windows only and use bounded deterministic request phrasing. CPU temperature and per-process CPU utilization are unavailable. Snapshots vary with load, process exits, permissions, and the Windows API's reporting. Physical cores can be unavailable. Process ranking can examine the full current inventory but only returns the bounded selection. Shared working-set memory is not exclusive allocation, and process presence is not window readiness.

User manual acceptance, fresh-environment installation, and visual Task Manager comparisons remain pending. Application opening was not repeated live during this checkpoint; mocked regressions passed. Ordinary generation is covered by mocks and model availability checks, rather than a new live conversational benchmark. The wording guard is bounded; only actual tool outputs establish measured evidence.

No background monitor, process termination, filesystem tool, network monitoring, screen/window perception, web search, agent planning, or frontend has been implemented.

**Next checkpoint:** Phase 4A — Web Search Foundation. Do not begin it automatically; stop for manual review of Phase 3B-B.

## System intent routing reliability repair — 2026-11-18

**Status:** READY FOR MANUAL REVIEW. The latest complete regression suite passes **468 tests**. This is a focused Phase 3B-B repair, not the start of another checkpoint.

### Root cause and reproduction

The pre-repair baseline passed **453 tests in 15.45 seconds**. Direct parser inspection returned `None` for `How much free storage do I have?`, `How much disk space is available?`, and `How full is my system drive?`. The storage branch recognized only three narrow sentence forms. Consequently, the existing conversation lifecycle treated the first question as ordinary conversation and called Ollama rather than the working Windows measurement tool. The generated refusal contained no numerical claim, so the existing unverified-number guard did not intercept it. The issue was intent coverage, not system-drive detection or measurement freshness.

New regression cases were run before the repair: **11 failed and 4 passed**, including seven newly requested storage phrasings, the exact summary/follow-up dialogue, failure after an earlier successful measurement, and unsupported-target limitations. The existing system-drive phrasing and the three educational negatives already passed.

### Exact fix and changed files

- `src/capabilities/system_intent.py`: Replaced the narrow storage branch with a small shared grammar. It combines storage/disk-space/space nouns, free/available/remaining qualifiers, current quantity/state questions, check/show requests, and explicit PC/computer/system-drive scopes. All eight expressions in the repair request select `system.snapshot` with `section=storage`. Full-string matching prevents an external-drive or Google Drive suffix from accidentally being treated as the Windows system drive.
- The same file adds controlled limitation replies for explicit storage-measurement questions about unsupported locations. Cloud-account measurements explain that the integration is unimplemented; other drive/location requests explain that only the Windows system drive is supported. Educational questions remain ordinary model requests. There is no new drive scanner or external integration.
- `tests/test_system_info.py`: Added **15 regression cases**. All eight storage phrasings assert the exact ToolRequest, execution through the existing executor, the actual mocked free/used/total/percentage values, no unrelated measurements, and no Ollama call. Three educational negatives exercise ordinary generation. The exact `/system` → `How much free storage do I have?` dialogue changes the mocked disk reading from 400 GiB free to 350 GiB free and verifies two real backend/executor calls, the new saved reply, and exclusion of both measurement exchanges from ordinary model context. A failure on the second reading verifies that neither the earlier success nor a fabricated model answer is reused. Google Drive and external-drive requests verify limitations without tool execution or model generation.
- `docs/phase-reports/PHASE_3B_B_REPORT.md`: This repair record, actual results, and remaining review limitations.

The measurement code, executor, request lifecycle, tool contracts, permission checks, system-drive detection, model configuration, and memory/database code were unchanged. Freshness remains provided by the existing collector executing on every recognized request. No commits or tags were created.

### Actual verification results

- Focused system suite after the fix: **125 passed in 1.78 seconds**.
- Complete regression suite: **468 passed in 25.71 seconds**, retaining all 453 prior cases. Measurements and ordinary model responses are mocked in the new automated tests; temporary SQLite storage is used.
- A separate temporary-data walkthrough ran the actual CLI with debug roles enabled. `/system`, `How much free storage do I have?`, `How much disk space is available?`, and `How full is my system drive?` each produced an actual successful verified `system.snapshot` execution and a storage reply. The trace recorded exactly four such tool executions.
- `What is cloud storage?` used the ordinary Ollama route exactly once in that walkthrough and completed without an Ollama or measurement error. The walkthrough returned exit code **0**. Live storage values need not differ between closely spaced requests; fresh collection is demonstrated by the tool execution trace and the changing-value regression test, rather than by assuming free space must change.
- Actual `python -m aika doctor` returned exit code **0**. Temporary test storage was cleaned up. Existing user conversation/memory data and the configured model were not modified, and no applications were opened.

### Manual review and remaining limitations

For user review, use the temporary data-directory setup above and enter `/system`, `How much free storage do I have?`, `How much disk space is available?`, `How full is my system drive?`, and `What is cloud storage?`. The first four must collect current local measurements; the last must remain an explanation. Then run `python -m aika doctor` and `python -m pytest -q`.

Scripted live verification passed; user manual acceptance remains pending. Recognition is deliberately bounded, not a general language-understanding system. The supported storage tool still measures only the Windows system drive. Arbitrary drives, network locations, cloud quotas, and unsupported paraphrases are not newly implemented. Explicit unsupported target forms covered by the limitation grammar are refused accurately; the parser does not promise to recognize every possible phrasing. No old measurements are copied as current results, no failed measurement falls back to Ollama, and educational storage questions are kept separate from live retrieval.
