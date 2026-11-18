# AIKA V2 Phase 0B — Python runtime and diagnostics

**Status** — READY FOR MANUAL REVIEW  
**Date** — 2026-11-17  
**Approval** — Pending manual review

## Implementation

- `python -m aika` shows runtime status after checking the environment and configuration. `--version` shows the application version and `--help` describes usage.
- `doctor` checks Python compatibility, project location, runtime files, platform, environment configuration, and the data path. It exits `1` on a failed check and `0` on success or warnings. Invalid command syntax exits `2`.
- Configuration reads five optional environment variables. Errors identify the variable or requirement without echoing its value. Debug logging includes an invocation correlation ID. The local runtime URL is validated without a connection attempt.

## Files and layout decision

The approved layout uses root `aika.py` and modules directly under `src/`. The previous `src/aika/` directory was verified empty and removed. setuptools explicitly installs the `aika` module and the `src` package so `python -m aika` works after installation as well as from the source checkout.

| Path | Purpose |
| --- | --- |
| `aika.py` | Starts the command-line program and returns its exit code. |
| `src/__init__.py` | Defines the package and its default release version. |
| `src/cli.py` | Parses commands and prints status, diagnostics, and errors. |
| `src/config.py` | Loads environment settings and validates their values. |
| `src/diagnostics.py` | Performs local checks and records their outcomes. |
| `tests/test_runtime.py` | Exercises commands, configuration, and failure cases. |
| `pyproject.toml` | Declares Python 3.12+, packaging, and the pytest development dependency. |
| `README.md` | Documents setup, commands, results, configuration, and layout. |
| `docs/AIKA_V2_FOUNDATION.md` and `docs/AIKA_V2_IMPLEMENTATION_PHASES.md` | Reflect the approved layout and current setup commands. |
| `docs/phase-reports/PHASE_0A_REPORT.md` | Points readers to this report for the current layout and retains the 0A evidence. |
| `docs/phase-reports/PHASE_0B_REPORT.md` | Records this checkpoint and its verification. |

## Commands and results

| Command or check | Observed result |
| --- | --- |
| `py -3.12 -m venv .venv` and `& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'` | Installed `aika-ai-v2` 0.1.0 and pytest 9.2.0 in the Python 3.12.10 environment. |
| `& .\.venv\Scripts\python.exe -m pip check` | No broken requirements found. |
| `& .\.venv\Scripts\python.exe -m aika` | Reported `READY`, `LOADED`, and Phase `0B`. Model, memory, tools, and desktop showed `NOT IMPLEMENTED`. |
| `& .\.venv\Scripts\python.exe -m aika --version` and `--help` | Printed `AIKA AI V2 0.1.0` and displayed the command help, respectively. |
| `& .\.venv\Scripts\python.exe -m aika doctor` | Exit `0` from the repository and from `%TEMP%` using the installed environment. The absent default data directory produced a `WARN` and remained absent. |
| `doctor` with invalid `AIKA_LOG_LEVEL` | Configuration `FAIL` and exit `1` without a traceback. |
| `py -V:Astral/CPython3.11.16 -m aika doctor` and `py -3.14 -m aika doctor` | Python 3.11.16 reported `FAIL` and exit `1`. Python 3.14.6 reported `PASS` and exit `0` with valid configuration. A reserved Windows data path on 3.14 returned configuration `FAIL` and exit `1`. |
| `& .\.venv\Scripts\python.exe -m pytest -q` | **20 passed** on Windows with Python 3.12.10. Tests used no model, network, or database. |
| V1 file and status fingerprint | V1 HEAD, status, and the Phase 0A fingerprint of 264 paths matched. No database connection was opened. |

## Manual verification

Run the [PowerShell setup and commands](../../README.md#run-on-windows) from the V2 root. Review the README's expected output, then run this failure check. The prior value is restored afterward.

```powershell
$python = '.\.venv\Scripts\python.exe'
$previousLogLevel = $env:AIKA_LOG_LEVEL
try {
    $env:AIKA_LOG_LEVEL = 'invalid-level'
    & $python -m aika doctor
    $LASTEXITCODE
} finally {
    $env:AIKA_LOG_LEVEL = $previousLogLevel
}
```

- [ ] Verify startup status, version, and help match the README.
- [ ] Run `doctor` with valid configuration and review every reported check. An absent data directory is an expected warning when an existing parent is found.
- [ ] Confirm the invalid log level prints a configuration `FAIL` and exit code `1`, then rerun `doctor` with valid settings.
- [ ] Run `pytest` and confirm the suite passes.
- [ ] Approve Phase 0B before creating a checkpoint commit or tag and moving to Phase 1A.

## Limits and next checkpoint

Data path diagnostics are read-only. They verify path validity and directory or parent existence. Write permissions and database creation are outside this checkpoint. V1 startup, live database, and backup recovery remain unverified. No new runtime dependency, Git commit, or tag was added.

Phase 1A is the next planned checkpoint and will connect the CLI to a local Ollama model.
