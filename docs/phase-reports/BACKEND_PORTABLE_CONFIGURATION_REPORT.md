# Backend Hardening Checkpoint 4: Portable Configuration

Date: November 19, 2026. Status: **READY FOR MANUAL REVIEW**.

## Baseline and scope

The checkout was clean at `e54df09` before this checkpoint. Before editing, Python 3.12.10 passed **1,526 tests in 37.87 seconds**, `pip check` reported no broken requirements, and doctor exited zero with the installed local `qwen3.5:4b` model available. Doctor used an overridden temporary data directory, disabled web gates and an empty Tavily key. Its SQLite probe used temporary storage; production conversations and memory were not opened for testing.

This implements only portable configuration and installation reliability. ConversationSession, six executable tools, permissions, agent limits, database name/schema, retained-turn limit, 24,000-character context default, 1,024-token output default, pooled Ollama transport and its 30-second metadata cache are preserved. No dependency, model, framework, executable capability, migration, V1 change or next checkpoint is included. No commit, tag or push was made.

## Defects and configuration policy

Previously the only file source was `Path(__file__).resolve().parents[1] / '.env'`. That accidentally selected `site-packages/.env` for a wheel and supplied no supported independent per-user configuration location. The old dotenv convenience reader could also log malformed syntax and silently continue. Installed doctor warned about absent source metadata even when the runtime files were complete.

The shared configuration loader now merges sources in this order, highest priority first:

1. Process environment, including explicitly blank values.
2. Optional user configuration: `%LOCALAPPDATA%\AIKA AI V2\config\.env` on Windows; `~/.aika-v2/config/.env` when local application data is unavailable.
3. Development root `.env` only for the executing verified source tree.
4. Existing validated defaults.

The same source resolution serves `load_config`, `load_version` and `load_data_dir`; internal calls pass the already merged mapping to avoid duplicate discovery. No explicit configuration-file override, search path, registry operation or config watcher is added. Configuration is loaded at the existing initialization boundary, never for each ordinary message or generation.

Source compatibility checks the executing module's root for `src/config.py`, `aika.py` and a `pyproject.toml` with project name `aika-ai-v2`. If installed distribution RECORD ownership identifies that actual module as a wheel file, development fallback is disabled first. Egg-info source lists are not wheel RECORD ownership. This deliberately supports both direct source execution and pip-editable installation; it does not claim that filesystem markers alone prove pip-editable installation. Working-directory markers and `.env` files are never consulted. Source-copy compatibility is additionally checked inside the installed smoke script; actual pip-editable installation is checked separately in the local clean-environment matrix.

## User setup and data independence

After installing a wheel in a dedicated venv, deliberately create your configuration directory and edit your own UTF-8 `.env`:

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\AIKA AI V2\config"
# In your editor, create .env inside that directory, using .env.example as reference.
python -m aika
python -m aika doctor
```

For example, the file can contain `AIKA_MODEL_TIMEOUT=180`. A PowerShell process override such as `$env:AIKA_MODEL_TIMEOUT='90'` wins until removed from that shell. Existing supported variables are unchanged. A new source checkout may deliberately copy `.env.example` to its root `.env`; AIKA performs no automatic copy.

Configuration location comes from the OS profile, independently of `AIKA_DATA_DIR`. An existing explicit data override still selects exactly the same directory. A user config that does not set a data-location variable leaves the existing data location intact. Deliberately configuring `AIKA_DATA_DIR` still works; no database is moved or copied. Database naming remains `conversations.sqlite3`, with existing conversations, memory, revision and migration behavior unchanged. Configuration loading performs no database I/O. A test hashes a synthetic database containing conversation and memory records before and after config loading and verifies identical bytes.

No startup creates a config file or directory. Missing optional files are normal. A regular existing file that is inaccessible, malformed, non-UTF-8 or larger than 64 KiB fails with a fixed source label, without input values, private paths, parser logging or fallback to another file. UTF-8 BOM, quoted strings and comments remain supported; interpolation remains disabled. File/parent symlinks and Windows reparse points are rejected, and opened-file identity is checked against the pre-open file identity. These bounded checks do not claim to sandbox a compromised OS or protect against all concurrent filesystem mutations. Profiles using junctions or other reparse indirections must use process environment configuration instead. There is no permission/ACL modification.

Doctor reports mode, low-to-high source labels, whether user config is present, whether development `.env` was loaded, and existing data-directory validation. It never prints config contents or profile paths. Malformed config stops before storage diagnostics. Missing source metadata is normal for a complete installed runtime. Runtime-file checks now include the planning, dataflow, prompt-budget, capability discovery and language modules already shipped by the existing package declarations.

## Portability and packaging audit

Inspected all production Python modules, launcher and packaging/verification scripts, including callers of config helpers. Searches covered developer names, OneDrive, fixed user/profile/desktop/download locations, drive literals, interpreters/venvs, `Path.cwd`, `os.getcwd`, `sys.path`, resources and relative file access.

| Finding | Classification and outcome |
| --- | --- |
| Module-relative `.env` as sole source | Actual portability defect; fixed with OS-derived user configuration and verified development compatibility. |
| Required source metadata warning in wheel doctor | Installed-runtime diagnostic defect; complete installed files now pass without source metadata. |
| `__file__`-anchored runtime module presence checks | Intentional package-resource checks; work with the actual wheel layout. |
| `C:\\` literals in numeric dataflow | Intentional explicit natural-language C-drive request, checked against verified snapshot identity; not the default system-drive discovery. Preserved. |
| Approved `notepad.exe` / `calc.exe` names | Intentional Windows behavior; resolved using `GetSystemDirectoryW`, not a fixed C drive or PATH search. Preserved. |
| `%LOCALAPPDATA%`, home fallback, validated `AIKA_DATA_DIR` | Safe existing OS-derived defaults; no fixed username, OneDrive dependency or default Python-install database path. Preserved. |
| Synthetic drive/profile/user-directory examples in tests | Test-only fixtures; include a Z-drive resolution assertion, spaces and Unicode. No real alternate Windows drive installation was tested. |
| `.venv-ci` / `.venv-wheel` and relative commands in CI/setup | Documentation/build-workspace examples with explicit checkout base; not production discovery. |
| Temporary benchmark databases and explicit benchmark output paths | Intentional developer script behavior; no runtime configuration authority. |
| Top-level package named `src` | Existing import-collision risk; use a dedicated venv. Package/import rename deliberately deferred. |

No developer username, OneDrive requirement, hardcoded private profile path, absolute Python executable, manual runtime `sys.path` modification, or current-directory-based production configuration discovery was found. `pyproject.toml` already includes `aika` and every runtime subpackage, declares Python >=3.12 and existing runtime dependencies, and derives wheel version from `src.__version__`; no metadata/framework correction was necessary. Version environment override remains an application display setting, not a wheel metadata rewrite. No hidden shell dependency was added; CI uses its existing explicit PowerShell shell and runtime subprocesses retain argument arrays.

## Changed files

| File | Change |
| --- | --- |
| `src/config.py` | One source resolver, strict bounded dotenv parsing, per-user discovery, source/wheel policy, safe source provenance on existing Settings. |
| `src/diagnostics.py` | Safe config labels and complete installed-runtime file checks. |
| `tests/conftest.py` | Redirect config-profile roots as well as data during tests. |
| `tests/test_portable_configuration.py` | 25 focused precedence, installation policy, safety, path and data-preservation cases. |
| `scripts/check_installed.py` | Expanded installed smoke: source ownership, Unicode/spaces, user config, env priority, missing/malformed/unreadable files and synthetic persistence. |
| `.github/workflows/backend.yml` | Redirect configuration profile to runner-temporary storage in the existing Windows matrix. |
| `README.md`, `.env.example`, this report | Setup, precedence, limits, evidence and manual review boundary. |

## Verification

| Verification | Python 3.12.10 | Python 3.13.15 |
| --- | --- | --- |
| Fresh-environment full regression | 1,551 passed in 38.08 s | 1,551 passed in 40.27 s |
| Wheel installation and `pip check` | Passed | Passed |
| Compileall: launcher, runtime and scripts | Passed | Passed |
| Fresh non-editable wheel smoke (`-I`) | Passed | Passed |
| Actual `pip install -e` and unrelated-directory startup/doctor/version/help (`-I`) | Passed | Passed |

Each environment was a new standard virtual environment with no system site packages. The wheel was built from a temporary copy containing the current runtime, launcher and packaging metadata; no developer `.env` was copied. Full tests ran against the copied source with fresh installed dependencies. Wheel subprocesses verified both `aika` and `src.config` origins under the fresh venv, using isolated Python imports and an unrelated working directory. Only after wheel checks did each environment switch to an actual pip-editable install of the temporary source copy, whose deliberately created synthetic development `.env` was verified from outside that copy. Python 3.13 was provisioned under the temporary test root; all test environments and synthetic files were removed on exit.

Both fresh environments resolved HTTPX 0.28.1, python-dotenv 1.2.4 and pytest 9.2.0. These are observed versions, not new pins or changes to application dependency declarations.

The first fresh Python 3.12 run found a test-isolation error: the synthetic `os.fstat` mock also affected pytest output capture during test cleanup (1 failed, 1,550 passed). The mock is now scoped within the loader assertion and restored before pytest cleanup. A subsequent wheel-smoke assertion also expected an invalid file URL to beat the deliberately valid process URL; that expectation contradicted the required precedence. The smoke now checks an invalid, unshadowed timeout instead. No production validation was loosened. Subsequent results are recorded below.

Focused configuration/dotenv/runtime checks passed **55 tests**; the 25 configuration cases also passed separately after narrowing that mock. Current-checkout pip check and compileall passed. YAML and all eight workflow PowerShell step bodies parsed successfully. Hosted GitHub CI has **not** been executed for these unpublished changes; local validation is not a hosted result.

Live current-checkout startup, doctor, version and help each exited zero using temporary data/profile overrides with web disabled. Live doctor confirmed the real local Ollama API and installed `qwen3.5:4b`; it performed no model generation, system sampling, process enumeration, GUI launch or provider request, and left the target data directory absent.

Automated regression uses the existing mocked model/provider/tool patterns. Installed smoke runs actual subprocesses, installed imports and temporary SQLite persistence, with Ollama deliberately unavailable on loopback port 1. Permission denial, reparse flags and concurrent file identity replacement are mocked failure checks, not live ACL, junction or concurrent-race demonstrations. The alternate Z-drive check verifies Windows path semantics, not another physical drive. No claim of a different physical account, clean OS, GUI, paid-provider or manual chat acceptance is made.

## Performance and remaining boundaries

On this machine, 31 read-only source config loads of the original HEAD loader and updated loader yielded first samples **2.709 / 3.731 ms**, and warm medians over the other 30 of **0.913 / 2.415 ms** respectively. This is initialization-only overhead (about 1.5 ms warm), with bounded file checks and package metadata reads, not an inference benchmark or performance guarantee. No per-message config lookup, filesystem scan, database scan, watcher, synchronization, background polling, extra Ollama classifier or HTTP client creation was introduced.

The existing transport/cache, prompt budgets, web billing gates, secret redaction, permissions, Phase 5E routing, archive retrieval, conversation resume and structured memory remain covered by full regressions. Existing local `.env` was read for source compatibility but never edited or migrated. No production database, memory record or V1 file was changed; all write verification used synthetic temporary data. Dependencies/interpreters for clean checks were installed only under temporary directories, not system-wide.

Remaining boundaries: `src` import naming, conservative rejection of reparse config paths, no ACL provisioning or packaged-desktop installer validation, no actual second Windows account/drive, and hosted CI pending publication. No new desktop/voice/context phase is started. The next audit recommendation is targeted modularity: consider extracting one pure routing/formatting concern from ConversationSession with behavior-preserving tests, only after this manual review and separate authorization. No extraction or archive indexing was started.

## Manual acceptance gate

In your own isolated venv, check startup/doctor/version/help from a directory outside the checkout. Deliberately create a user config with a harmless public display name, restart, and confirm doctor labels it present without printing its path or contents. Override that name in the current shell and confirm the environment wins. Remove that shell override before testing source `.env` compatibility. Use synthetic data overrides for persistence testing; do not move or rewrite existing production databases. Automated checks above do not constitute this user acceptance. Stop at Checkpoint 4 for review.
