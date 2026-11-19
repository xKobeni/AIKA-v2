# Phase 6A — Basic Desktop Context Awareness

Date: 2026-11-19. Status: **READY FOR MANUAL REVIEW**.

## Result and scope

Implemented `desktop.context` as the seventh registered tool, using the existing `ToolRegistry`, `ToolExecutor`, READ_ONLY permission and single `ConversationSession`. It is OFF by default and runs only for an explicit supported request. No second orchestrator, permission system, inference pass, registry, background worker or database was introduced. Phase 6B, visual context, screenshots, GUI and voice are not implemented.

Before implementation, the actual full Python 3.12 suite passed **1,602 tests in 41.16 seconds**. Inspected the foundation/roadmap, Phase 5E, backend portability/configuration and Ollama transport reports, reasoning A/B report, owning conversation/intent/discovery/CLI/configuration/diagnostic modules, existing executor/contracts/permissions, Windows system and app capabilities, tests and installed-wheel verifier. The reasoning checkpoint remains INCONCLUSIVE; it did not authorize model or persona changes.

## Integration and consent

`Settings.desktop_context_enabled` comes from `AIKA_DESKTOP_CONTEXT_ENABLED`, default `off`. Accepted values match existing boolean gates: off/on, false/true, 0/1, ignoring case and surrounding whitespace. Blank and other values fail validation with a fixed, value-free message. Configuration uses the existing precedence: process environment > optional user configuration > verified development `.env` > defaults. The actual `.env` was not edited; only `.env.example` documents the new default.

The CLI passes the loaded setting into the existing session. The registry always includes the definition, disabled unless explicitly opted in. Disabled lookups return the executor's controlled `disabled_tool` result before any collector initialization. The executor's READ_ONLY policy, input/output contracts, bounded result handling and verifier remain authoritative. A changed permission category still fails closed. Availability consent does not authorize launching applications, controlling windows, reading files or screen content.

No configuration reload occurs per message. Change private configuration/process environment and restart to change the gate. This is a basic startup configuration gate, not a dynamic consent UI, live revocation manager or Phase 6B lifecycle implementation.

Desktop routing is narrow and deterministic, ahead of memory/ordinary inference for its exact explicit requests. Existing memory, agent, calculator, system, web and research routes retain their behavior. The planner's existing operation parser does not accept desktop observations: model-generated plan text cannot acquire this capability. No broad desktop tool was added to agent workflows.

## Commands and natural-language boundary

Inside `python -m aika chat`:

```text
/desktop-context --status
/desktop-context
Aika, what application am I using right now?
What's my active window's application?
What is my screen resolution?
How many monitors are connected?
Show my desktop information.
```

The explicit command observes both scopes; foreground questions collect only foreground identity; resolution/count questions collect only display metadata. Invalid command options return usage without collection. No arbitrary trailing instructions are stripped to manufacture an accepted observation request.

`Can you tell what app I'm using?`, `Are you able to see my desktop?`, `Do you support screen awareness?` and `Can you take screenshots?` return capability/availability information without collection or generation. `How does Windows detect the active window?` remains ordinary informational chat without a desktop observation. Ambiguous, compound, memory-related and unsupported screenshot requests do not match the observation recognizer. Supported wording is intentionally limited; this is not general desktop-language understanding.

`--status`, `/capabilities`, startup, doctor and tool listings never inspect foreground state or sample displays. Readiness text explicitly says API availability was not tested. Doctor reports the configured gate and seven registered tools. CLI help includes the command; startup now identifies phase 6A. Observation replies use the actual executable basename without an unverified friendly-name mapping. They describe the foreground application rather than asserting what the user is actively doing. A terminal being foreground is normal; no previous-focus guess or global tracking exists.

## Native implementation and data contract

The new adapter is `src/capabilities/desktop_context.py`; routing/presentation is in `src/capabilities/desktop_intent.py`. Only Python's standard-library `ctypes` is added to the implementation; there is no new dependency. DLL bindings are created only after an enabled explicit observation. Unsupported platforms import safely and return controlled unavailable behavior.

| Scope | APIs and verification | Returned metadata |
| --- | --- | --- |
| Foreground | `GetForegroundWindow`, `GetWindowThreadProcessId`, `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`, `QueryFullProcessImageNameW`, `CloseHandle` | Executable basename and PID only when verified; fixed unavailable reason otherwise |
| Displays | `EnumDisplayMonitors`, `GetMonitorInfoW`, `EnumDisplaySettingsW(ENUM_CURRENT_SETTINGS)` | Enumerated Windows display count, primary mode resolution, per-display mode resolution and primary marker |

Process access uses only the limited query right, never injection, elevated privileges or a full process-list scan. Full executable paths exist only in the bounded native query buffer; the basename is extracted before return. Handles close in a `finally` block, including query failure/interruption. A second foreground HWND/PID check rejects a detected focus/identity change. No accessible process is assumed when there is no window, access is denied, the process disappears, a name is invalid, or APIs are missing. [Microsoft's process-image API documentation](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew) specifies the supported query rights; [foreground-window documentation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow) also documents a possible null handle.

Display enumeration is bounded to 64 monitors. An additional enumeration checks for changed monitor handles; it is a finite consistency check within one request, not polling. Disconnection, missing modes, absent/ambiguous primary identity or invalid dimensions produce partial/unavailable data, with no logical-coordinate fallback. Width/height come from the current display mode in physical pixels, not the DPI-virtualized monitor rectangle; there is no process/thread DPI-setting call. The Windows native structures measured 104 bytes (`MONITORINFOEXW`) and 220 bytes (`DEVMODEW`) on this environment. [Microsoft documents the physical-pixel semantics of EnumDisplaySettingsW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaysettingsw).

These are current display-mode dimensions, not panel native-resolution, physical size or physical panel-count guarantees. Windows can expose virtual, remote and mirror/pseudo monitors through enumeration. The result is labeled “Active Windows displays”; [EnumDisplayMonitors documentation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors) describes the pseudo-monitor caveat. Display IDs are ordinal within one request, not stable hardware identifiers; device names, handles, layout coordinates and hardware serial numbers are not returned. Foreground/display collections are point-in-time observations, not an atomic desktop snapshot; rapid changes that evade the consistency checks remain possible. Nothing is cached as current state.

`DesktopContext` is a TypedDict with strict runtime tool contracts:

- `capability`, `scope` (`all`, `foreground`, `displays`), collection `status` (`complete`, `partial`, `unavailable`).
- Requested `foreground`: status, executable basename/PID or null, fixed safe error code. Unrequested scope is null.
- Requested `displays`: status, count or null, primary resolution or null, bounded monitor entries (ordinal, primary marker, physical pixel width/height or null, safe error code).
- Timezone-aware `collected_at` and fixed local Win32 `source`.

Unexpected fields, full paths, invalid timestamps, impossible counts/dimensions, and inconsistent claimed completeness fail output validation. Complete output alone can become verified SUCCESS. Partial/all-unavailable collections carry typed data under the existing INCONCLUSIVE result, verified=false; presentation names the limitation and only displays available validated fields. Missing OS/APIs return UNAVAILABLE without fabricated observations; disabled access returns DISABLED without initializing native APIs. A failed verifier cannot present a complete result as verified success. Native errors are fixed codes/messages rather than raw exception strings or paths.

## Privacy and persistence

Desktop responses are formatted deterministically and returned before conversation persistence, history append or memory handling. Neither the observation nor its request/reply exchange is archived. No desktop evidence is supplied to ordinary/grounded/planning generation or later model history. Context-free follow-up messages cannot silently reuse a previous foreground observation; a fresh explicit request is required.

Existing CLI tool traces include only tool name, permission, validation/outcome, verification flag and elapsed time. They do not print observation payloads. Human-facing command output can show the requested basename and display modes; detailed structured results also contain PID, timestamp and source. The implementation never reads titles, window text, tab URLs, clipboard, documents, screenshots, audio or input activity. No activity-log table, automatic memory, tracking hook, cloud transmission or external-provider request is added. The acceptance artifact intentionally omits foreground basenames and PIDs.

## Actual Windows acceptance

Live checks used temporary `AIKA_DATA_DIR` and profile paths, a process-local OFF/ON override and fresh session after opt-in. No real configuration file was changed; no user history was loaded. No elevation request, new application launch, window manipulation, screenshot, title read, model generation or provider call occurred.

| Check | Actual result |
| --- | --- |
| OFF: explicit command and foreground question | Controlled disabled responses; native initializer mocked to fail if reached, **0 calls** |
| OFF/ON status; ON capability questions | Controlled capability/status answers, **0 native initializer calls**, **0 model calls** |
| ON foreground request | Native success with validated identifier/PID, timestamp/source; identity deliberately omitted from saved artifact |
| ON display request | Native success; **2 active Windows displays**, **1920 × 1080 primary current mode**; per-display fields passed the output contract |
| ON explicit combined request | Native foreground/display success; no retained observation history |
| Source CLI startup, doctor, version, help | All four exited **0**, isolated paths and disabled web; no desktop collection by these commands |
| Observation persistence / inference | **0 retained observation turns**, **0 Ollama generations** |

Measured once per distinct request, including session routing and executor validation: foreground **0.759 ms**, displays **0.408 ms**, combined **0.524 ms**. Executor-only times were 0.685, 0.360 and 0.498 ms respectively. These three different-scope samples are not throughput, tail-latency or worst-case guarantees. Native calls are synchronous and cooperative; there is no new worker or hard preemption of an in-flight Windows API call. Ctrl+C cleanup/no-persistence is covered by deterministic tests.

The APIs enumerated two Windows display regions; **physical multi-monitor acceptance is not claimed**. Settings UI comparison, switching existing applications interactively, human confirmation of terminal foreground behavior, actual DPI/orientation changes, Remote Desktop, real protected-process denial and physical disconnect/reconnect remain unperformed. Those branches have mocked coverage. No additional application was launched or screen/title inspected to simulate manual acceptance. The safe automated/live checks above are distinct from the remaining human walkthrough.

Sanitized records: [Windows checks](../benchmarks/PHASE_6A_WINDOWS_ACCEPTANCE_2026-11-19.json), [fresh installed wheel](../benchmarks/PHASE_6A_INSTALLED_WHEEL_2026-11-19.json).

## Regression and packaging

| Verification | Result |
| --- | --- |
| Initial full regression, Python 3.12.10 | **1,602 passed**, 41.16 s |
| New deterministic desktop tests | **57 passed**, 2.23 s |
| Final full regression, Python 3.12.10 | **1,659 passed**, 43.04 s |
| Final full regression, Python 3.13.15 | **1,659 passed**, 40.54 s |
| Dependency checks | No broken requirements, 3.12 source environment, 3.13 environment and fresh wheel environment |
| Compilation | `compileall` passed for entry point, runtime and developer scripts under both interpreters |
| Fresh non-editable wheel | Built and installed into new temporary 3.12 venv; isolated `-I` imports proven inside venv; smoke passed |
| Installed desktop gate | Default OFF with native initialization forbidden; seven tools; user opt-in and process-OFF precedence passed |
| Installed portability/history | Startup/help/version/doctor, synthetic cross-process memory, default/override paths, Unicode profile, config precedence, malformed/unreadable config, verified source fallback all passed |
| Whitespace | `git diff --check` passed; Windows line-ending warnings only |
| Hosted CI | Unverified; not dispatched or claimed |

The 3.13 environment has no standalone `pip` module; its dependency check succeeded via `py -3.12 -m pip --python .venv-naturalness/Scripts/python.exe check`. No pip upgrade was required. Local logs are under `artifacts/phase6a-*`.

New offline tests use synthetic native bindings/foreground identities. They cover default/explicit gates and existing configuration precedence, exact versus nonrequest intents, success and Unicode, no foreground, denied/terminated processes, HWND/PID races, handle cleanup/minimum rights, multi-monitor and portrait modes, logical-versus-physical dimensions, display changes/missing modes, unknown OS/APIs, strict provenance and result completeness, existing executor permissions, agent refusal, interruption cleanup, CLI dispatch/redacted traces, no archive/memory/model writes, and capability/status non-collection. Existing regression coverage continues to verify memory/conversation, system info, launch safety, research/citations, context/output budgets and planning limits. Test registry/doctor expectations intentionally changed from six to seven; no safeguard was weakened to satisfy a test.

## Preservation and changed surfaces

The actual `.env`, active persona, Ollama adapter, planner/dataflow, packaging dependencies and all memory/storage Python modules match their starting hashes (**13 protected files**). Current loaded settings remain `qwen3.5:4b`, thinking OFF, 1,024 output tokens, 24,000 input characters, 10 retained turns, desktop context OFF. No production database, schema migration, V1 file, commit, tag or push was touched. Existing permission classes/executor, six prior tools, launch semantics, research verification, metadata-cache policy and workflow limits were not edited.

New runtime modules contain the native collector/typed contract and narrow intent/presentation. Small integration changes are limited to configuration, registry construction, discovery, the existing conversation early-return, CLI and diagnostic declarations. `.env.example`, README, foundation/roadmap, installed smoke and regression expectations document the intentional seventh-tool change. No new model or dependency is installed into the application.

## Remaining review

With isolated storage, first verify OFF command/question/status behavior. Enable only in that isolated process, restart, and compare explicit results with Windows Display Settings and existing foreground applications. Move focus manually between already-open applications and the terminal, issuing a fresh explicit request each time. Review unavailable/partial responses without granting elevation. Do not infer visual access from executable identity.

Phase 6B's broader consent lifecycle, event-driven context, screenshot/vision/OCR, browser/document context, graphical embodiment and voice remain outside this implementation. The current phase stops here for manual review.

**READY FOR MANUAL REVIEW**
