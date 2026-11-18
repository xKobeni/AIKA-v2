# AIKA V2 Phase 3B-A — Safe Windows Application Launcher

**Status:** READY FOR MANUAL REVIEW  
**Date:** 2026-11-18  
**Manual acceptance:** Pending user review. No live applications were opened during this implementation's checks.  
**Scope:** Phase 3B-A only. No commits or tags created.

## Architecture

The existing `ConversationSession` still owns each request. A bounded recognizer identifies explicit `open`, `launch`, and `start` requests or `/open`. Exact application aliases become `app.open` requests. Both natural-language and CLI requests use the same existing `ToolExecutor`; no separate orchestrator, model planner, command runner, or tool result type was introduced.

The tool registry now contains `calculator.evaluate` and `app.open`. Application definitions live in a small, code-owned `ApplicationRegistry`. It supports explicit registration, lookup, duplicate rejection, and inspection of enabled state and target availability. Model responses cannot register applications, supply functions, change launch paths, or create authorization.

The application recognizer accepts names such as Notepad, Windows Notepad, Calculator, Windows Calculator, Calc, and Spotify. `Can you open Spotify?`, `Launch the Windows Calculator`, and `Start Notepad for me` are supported. Unknown application names and command-like strings are rejected by the same argument contract without model fallback. Multiple or ambiguous targets ask which registered application is intended. Ordinary instructions such as `Start by explaining application launchers` remain conversational.

## Approved targets and execution safety

| Application ID | Display name | Approved identity | Launch method |
| --- | --- | --- | --- |
| `notepad` | Notepad | Windows system directory / `notepad.exe` | Direct executable |
| `calculator` | Windows Calculator | Windows system directory / `calc.exe` | Direct executable |
| `spotify` | Spotify | None configured | Unavailable |

The Windows system directory is obtained through `GetSystemDirectoryW`, rather than executable search through PATH or trusting a user-supplied installation path. Registered targets must match the fixed approved identity exactly. Validation rejects relative or network paths, traversal, substitutions, symlinks, and executable reparse points. Target validation and file availability are checked again immediately before launching. The working directory is the approved system directory.

Execution uses a one-element absolute argument list with `subprocess.Popen(..., shell=False)`. No executable arguments are accepted. The launcher does not run CMD, PowerShell, scripts, arbitrary files, or protocol handlers, and does not download applications or request elevation. Windows GUI applications may display their normal windows only as a consequence of the explicit user request. There is no proactive launch, background automation, keyboard/mouse control, screenshot collection, or window management.

Spotify has no audited adapter in this checkpoint and remains unavailable. Its installation is not inferred from a name, PATH entry, protocol association, or executable guess. Supporting Spotify later requires an explicitly reviewed adapter and verification method.

The approved executable location is trusted as part of the local Windows installation. This does not defend against an administrator replacing Windows binaries or a compromised operating system. A full executable signature verifier or software inventory was not added.

## Permissions and configuration

`app.open` uses the existing `LOCAL_ACTION` permission. The conversation lifecycle constructs immutable `LocalActionAuthorization` evidence only for the current explicit request, bound to both `app.open` and its exact application ID. That evidence is separate from model/tool arguments. The executor checks it before argument validation and handler invocation. Missing or mismatched authorization is denied. Application enablement and availability are checked before OS execution.

This permission exception applies only to `app.open`, requires its verification callback, and cannot enable other local tools or `SENSITIVE_ACTION`. Calculator requests retain their existing READ_ONLY behavior.

Local configuration can disable approved IDs:

```powershell
$env:AIKA_DISABLED_APPS = '["notepad", "calculator"]'
python -m aika chat
```

The default is `[]`. Configuration accepts only a JSON array of unique `notepad`, `calculator`, or `spotify` IDs. Invalid values produce a safe configuration error without echoing the input. The setting is read at startup and cannot define executables, launch methods, or extra arguments. No new dependency, application database, or schema migration was added.

## Verification and result integrity

The existing ToolResult contract gains `unavailable` and `inconclusive` statuses. Tool definitions may supply an output verification callback. Success is returned only after execution, output validation, and successful verification. Controlled execution errors can retain actual failure evidence without setting `verified=True`.

| Stage/outcome | Evidence and response |
| --- | --- |
| Launch requested | An explicit current user request is parsed into a typed tool request and authorization. No OS operation has happened yet. |
| Application unavailable | No approved usable executable or adapter exists. No OS launch occurs. |
| Disabled or permission denied | Configuration or executor policy blocks execution before the process is created. |
| Launch initiated | Windows process creation returned a process object with its actual PID. This alone is not verified success. |
| Launch verified | Waiting on the launched process for 250 ms timed out, observing that process still running at that deadline. The result contains its PID and `process_observed=True`. |
| Verification inconclusive | The launched executable exited with code zero before that deadline. The result retains the real launcher PID and exit code with `verified=False`. |
| Launch failed | Process creation raised an OS error, or the launcher exited with a nonzero code. No successful outcome is claimed. |
| Unexpected verification failure | The executor reports failure and warns that a launch may have been initiated. It does not claim the application failed to start or recommend a blind retry. |

A verified reply says that the started process was observed running and explicitly states that window readiness was not checked. It does not claim that the application UI is visible, responsive, or fully opened. Notepad and Calculator can be Store handoff launchers on some Windows installations. An early zero exit is therefore inconclusive, even when a window actually appears through a different process. This checkpoint does not correlate handoffs with an unrelated process or existing window.

The model does not generate application execution replies. Recognized requests return deterministic text from actual ToolResults. Ordinary generated replies retain an expanded guard against common fabricated tool or app completion claims. That wording guard is bounded, supplementary protection rather than a universal semantic claim verifier; it grants no execution authority.

## CLI, persistence, and diagnostics

`/apps` lists approved names and IDs, target availability, enabled/disabled state, and permission. Availability means that the approved launch executable exists and passed path checks, not that a Store package is installed or the application is ready. `/open <application>` uses the same session/executor path as natural language. Existing commands, memory handling, and calculator behavior remain available.

Completed success, failure, and inconclusive replies use the existing SQLite conversation exchange transaction. Resume restores those messages without replaying actions. Application interactions do not automatically create structured facts. If storage fails after an attempted launch, AIKA reports the actual or uncertain action outcome alongside the save failure and explains that launching cannot be rolled back. It never retries automatically. No durable tool-run audit table is introduced in this checkpoint.

Doctor checks registration, calculator execution, Windows compatibility, registered application count, per-target availability, enablement, and configuration. It never executes `app.open`. Missing optional targets produce warnings; invalid configuration or unsafe registered targets produce failures. Existing SQLite, memory, and Ollama checks remain.

Existing privacy-conscious tool traces report tool name, permission, validation, execution status, verification, and duration. They exclude application arguments, paths, PIDs, and exception details. Normal action replies and saved transcripts can contain the actual observed PID as execution evidence.

## Files changed

| File | Change |
| --- | --- |
| `src/capabilities/applications.py` | Approved application definitions/registry, Windows system-directory lookup, path checks, bounded process observation, and app tool contracts. |
| `src/capabilities/application_intent.py` | Explicit bounded request recognition, aliases, ambiguity handling, and evidence-based replies. |
| `src/capabilities/contracts.py` | Bound local-action authorization, inconclusive/unavailable statuses, verification callback, and controlled failure evidence. |
| `src/capabilities/executor.py` | Exact authorization checks for app.open, verified outcomes, and safe uncertain-launch failures. |
| `src/capabilities/registry.py` | Validation of optional verification callbacks. |
| `src/capabilities/__init__.py` | Register app.open alongside the calculator. |
| `src/capabilities/intent.py` | Unsupported-action wording, ordinary-instruction preservation, and generated-claim guard. |
| `src/intelligence/conversation.py` | Existing lifecycle integration, application authorization, and post-action storage-error reporting. |
| `src/config.py` | Validated `AIKA_DISABLED_APPS`, preserving all previous settings and the Qwen3.5 default. |
| `src/cli.py` | `/apps`, `/open`, help, prompt capability text, application configuration, and phase display. |
| `src/diagnostics.py` | Non-launching application configuration/availability diagnostics and runtime-file checks. |
| `tests/conftest.py` | Isolate the new setting and block real application launching throughout automated tests. |
| `tests/test_applications.py` | 87 focused application, security, authorization, verification, CLI, storage, and regression cases. |
| `tests/test_tools.py` | Update registry expectations and replace newly supported open requests in the unsupported-action cases with close requests; retain failure and model-fallback assertions. Adapt diagnostic mocks to the optional registry argument. |
| `tests/test_runtime.py` | Updated phase and registered tool count expectations. |
| `README.md` | Current capability, commands, configuration, verification limits, storage semantics, and report link. |
| `docs/phase-reports/PHASE_3B_A_REPORT.md` | This report. |

## Actual test results

- The user's request stated that Phase 3A manual tests passed. Before edits, the full baseline passed **256 tests** on Windows with Python 3.12.10.
- Final `python -m pytest -q`: **343 passed in 14.29 seconds**. All prior test cases remain present, with obsolete capability/phase expectations updated. The new application tests mock OS creation and do not open applications.
- Coverage includes explicit registration, duplicate/unknown rejection, disabled/missing apps, path and command substitution attacks, exact authorization, denial of other actions, safe one-element process invocation, running process evidence, zero/nonzero exit behavior, OS creation failure, post-launch verification errors, safe configuration failures, CLI commands, no model fallback, common fabricated launch claims, SQLite persistence/resume, uncertain outcomes after save failure, and memory/calculator/ordinary conversation regressions.
- Actual `python -m aika`, `doctor`, `--version`, and `--help` subprocess checks all returned **exit code 0** against temporary storage. Doctor resolved the Windows system directory, found both approved Notepad and Calculator executable targets, reported Spotify unavailable, and confirmed local Ollama connectivity with **qwen3.5:4b** installed.
- A real CLI smoke session used `/apps`, `/tools`, unavailable Spotify, unknown and injected target rejection, calculator multiplication (**4410**), explicit Orion/SvelteKit save, and current memory recall. All checks passed with exit code 0. No approved application-launch request was issued, and temporary storage was cleaned up.
- No existing user database, AIKA V1 files, model default, or dependency list was changed. No commits or tags were created.

## Manual review instructions

Use a dedicated PowerShell window in the V2 project root. Optional isolated review storage keeps test exchanges out of your normal archive:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-3ba-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_CONTEXT_DEBUG = 'roles'
python -m aika doctor
python -m aika chat
```

1. Run `/apps`. Confirm the registered targets, truthful executable availability, and enabled states.
2. Enter `Open Notepad.` Observe whether Notepad appears and compare the reply with the stated process evidence. A handoff may produce an inconclusive reply.
3. Enter `/open notepad`. Expect the same execution path and honest result; a second request can create another application instance.
4. Enter `Open Calculator.` Observe Calculator if the local Windows installation supports the approved launcher. Early successful launcher exit must remain inconclusive.
5. Enter `Open Spotify.` Expect the limitation about the unavailable audited adapter, with no launch attempt.
6. Enter `Open an application called UnknownApp123.` and `/open notepad & calc.exe`. Expect unsupported-target errors and no application launch.
7. Enter `Open an app.` Expect a question naming the registered choices, with no launch.
8. Enter `What is 245 multiplied by 18?` Expect calculator result **4410**.
9. In isolated storage, save `Remember that Orion uses SvelteKit for its frontend.` Ask `What frontend does Orion currently use?` Expect SvelteKit. Existing projects in your normal database should still return their actual saved values.
10. Exit, set `$env:AIKA_DISABLED_APPS = '["notepad"]'`, restart chat, and try `/open notepad`. Expect a disabled error and no launch. `/apps` should distinguish AVAILABLE from DISABLED.
11. Copy the session ID and resume it in a fresh process with `/resume <session_id>`. `/history` should show completed action replies without relaunching anything.
12. Run the commands below. Close the dedicated shell afterward to discard its environment overrides. Close any test application windows yourself when finished.

```powershell
python -m aika
python -m aika doctor
python -m aika --version
python -m aika --help
python -m pytest -q
```

## Limitations and next checkpoint

Live Notepad/Calculator opening and visible UI readiness remain untested in this implementation session. Manual acceptance is not claimed. No fresh virtual-environment installation was performed. Existing ordinary model generation remains covered by mocks; the real smoke session used deterministic request routes and model availability checks.

Only fixed Windows system executable targets are supported. Spotify, Store handoff correlation, new application definitions through configuration, argument passing, application closing, window management, and general desktop automation are intentionally absent. A verified process observation is time-specific and cannot guarantee that the process remains running afterward. A storage failure cannot undo a real desktop launch.

**Next checkpoint:** Phase 3B-B — System Information, as specified in the current request. It has not been implemented. Stop here for user manual review.
