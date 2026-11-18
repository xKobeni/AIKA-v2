# AIKA V2 Phase 0A — Foundation and V1 preservation

**Status** — READY FOR MANUAL REVIEW  
**Date** — 2026-11-17  
**Approval to proceed** — Pending

This report records the Phase 0A snapshot. The [Phase 0B report](PHASE_0B_REPORT.md) records the current runtime layout and subsequent documentation changes.

## Objective and workspace

Establish the architecture and checkpoint order, create a separate V2 workspace, and record how to recover V1. The Desktop workspace initially contained only the two primary specifications and had no Git metadata. The V1 checkout lives under `Documents\Visual Studio Blue` and has existing uncommitted work.

## Files and directories added

| Path | Purpose |
| --- | --- |
| `README.md` | Project purpose, planned technologies, structure, and checkpoint status. |
| `.gitignore` | Keep environment secrets, caches, runtime data, and backups local. |
| `docs/decisions/README.md` | Procedure for proposing and recording architectural deviations. |
| `docs/V1_PRESERVATION.md` | V1 inventory and backup and recovery procedure. |
| `docs/phase-reports/PHASE_0A_REPORT.md` | Verification evidence, limits, and manual acceptance. |
| `src/aika/`, `tests/` | Empty source and test directories for the next checkpoint. Git omits empty directories. |

Initialized a separate V2 Git repository on `main` with no commit or tag. Both original specifications retained their pre-work SHA-256 hashes.

## Architecture review

- The [foundation specification](../AIKA_V2_FOUNDATION.md) defines the contracts. The [implementation roadmap](../AIKA_V2_IMPLEMENTATION_PHASES.md) controls checkpoint order. Use the roadmap numbering when the foundation's high-level phase summary groups work differently.
- One request orchestrator owns the lifecycle. Model inference, memory, planning, tool execution, and perception have defined boundaries within the planned backend.
- SQLite is the first durable store. Structured facts have source references, scoped lookup, and atomic, traceable corrections. Memory confirmations follow a successful commit.
- The trusted executor validates typed tool proposals, checks permissions immediately before execution, and records actual outcomes. Claims of success require verification evidence.
- Sensitive perception requires explicit opt-in and scope controls. The future desktop character consumes typed, versioned events. AIKA's Windows-first, local-first backend is designed to work headlessly.
- Phase 0B introduces the Python CLI skeleton and diagnostics, Phase 1A adds Ollama, and Phase 1C introduces SQLite persistence. No architecture deviation was required for Phase 0A.

## Verification and limits

- Compared both primary specification hashes, resolved local Markdown links, inspected the file tree, and checked Git status and ignore rules. V2 is on an unborn `main` branch with untracked `.gitignore`, `README.md`, and new documentation alongside the original specifications.
- Compared V1 HEAD, Git status, and file fingerprints before and after the V2 work. The fingerprint covered tracked and nonignored untracked paths, V1 `.env`, and existing files in `backups/`. Other ignored paths were outside that comparison. Phase 0A opened no database connection and performed no migration or restore.
- The [V1 preservation inventory](../V1_PRESERVATION.md) records the discovered checkout, database configuration and uncertainty, and assets for later review. The effective database name, live schema, current backup completeness, startup, and restore are pending manual verification.
- No Python code, runtime environment, or dependencies were added. Runtime and automated application tests apply from Phase 0B onward.

## Manual acceptance

Run from PowerShell.

```powershell
Set-Location -LiteralPath 'C:\Users\johna\OneDrive\Desktop\AIKA AI'
Get-ChildItem -Force -Name
tree /F /A
git status --short --branch --untracked-files=all
git tag --list
Get-FileHash -LiteralPath @('docs/AIKA_V2_FOUNDATION.md', 'docs/AIKA_V2_IMPLEMENTATION_PHASES.md')
$v1Path = 'C:\Users\johna\OneDrive\Documents\Visual Studio Blue\AIKA AI'
git --no-optional-locks -C $v1Path rev-parse --show-toplevel HEAD
git --no-optional-locks -C $v1Path status --short --branch
```

| Specification | Expected SHA-256 |
| --- | --- |
| `AIKA_V2_FOUNDATION.md` | `7BEDDFC28E18F985B5CA94B066FB520B415D9F421AD134CD1884FF0EB291DE67` |
| `AIKA_V2_IMPLEMENTATION_PHASES.md` | `FBF1542956A8D5DA0B5A3941C225888185140635B070FC93D8BAE078F1ABE914` |

- [ ] Confirm the V2 root is separate from V1 and the tree contains only the Phase 0A scaffold and Git metadata.
- [ ] Open both specifications and confirm the single-orchestrator, memory, and permission rules. Compare the hashes above.
- [ ] Confirm there is no V2 runtime or database configuration that can connect to V1.
- [ ] Follow the V1 preservation checklist and confirm V1 is recoverable from an independent backup or that a known-good installation still runs without modifications.
- [ ] Approve Phase 0A before saving a checkpoint commit or tag and moving to Phase 0B.
