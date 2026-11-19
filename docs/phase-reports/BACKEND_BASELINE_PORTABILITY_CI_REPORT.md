# Backend Baseline, Portability Measurements & Windows CI

Date: November 19, 2026. Status: **READY FOR MANUAL REVIEW**.

Scope selected by the user: the audit's first checkpoint, baseline/portability measurements and Windows CI. Production base: `5830087bdec6b61a29eb7773683eb68a87c7d8b8`, matching the supplied audit. This checkpoint adds verification infrastructure; it does not implement the later transport, context-budget, packaging/config-resolution, archive-indexing or refactoring recommendations. CLI runtime phase remains 5E. No Phase 5F/6A work was started.

## Baseline and files changed

Before editing, `python -m pytest -q --durations=20` passed **1,445 tests in 35.57 s**. `python -m pip check` reported no broken requirements. `python -m compileall -q aika.py src` passed. The slowest existing cases were subprocess-based runtime/configuration tests (approximately 0.8–0.9 s each), not measurements of ordinary inference latency.

| File | Purpose |
| --- | --- |
| `.github/workflows/backend.yml` | Windows 3.12/3.13 matrix, isolated checkout venv, mocked tests, optional-Ollama diagnostics, wheel venv smoke check, synthetic baseline and dependency artifacts |
| `scripts/benchmark_backend.py` | Synthetic archive/context measurements, explicit opt-in local Ollama request tracing and sanitized JSON output |
| `scripts/check_installed.py` | Non-editable wheel verification using isolated imports, unrelated working directory and synthetic default/override data paths |
| `tests/test_backend_measurements.py` | Five focused tests for benchmark semantics, restoration, offline default, trace counting and safe failure reporting |
| `docs/benchmarks/BACKEND_BASELINE_2026-11-19.json` | Sanitized measurements and portability evidence from this checkpoint |
| `.gitignore` | Ignore build outputs, temporary CI environments and generated artifacts |
| README and this report | Scope, reproduction, actual results and remaining limitations |

No `src/` runtime module, `aika.py`, packaging metadata, configured model, permission, registry identity, production database, secret file or existing test was changed. No dependencies were added to the application. The five new tests supplement the 1,445 existing cases. No Git commit/tag/push or remote CI dispatch was performed.

## Repeatable measurements

Run from the checkout with project dependencies installed:

```powershell
python -m pip check
python -m compileall -q aika.py src scripts
python -m pytest -q --durations=20
python -m scripts.benchmark_backend --output artifacts/baseline.json
```

The benchmark defaults to no Ollama, network provider, GUI action, production history or user-memory access. Archive rows are synthetic and live in an in-memory SQLite database. Context measurements use a temporary conversation database and a mocked generation callback, including save/resume. Timings are observational; no machine-dependent timing thresholds are asserted in tests.

### Archive-search baseline

Six repetitions per case; first sample is recorded separately and the table uses the median of the remaining five. Every row has unique synthetic user content; the many-match case parses matching statements and returns the existing maximum five results. These are in-memory search timings, not disk I/O or a profile of the user's actual archive.

| Archived user rows | No-match warm median | Many-match warm median |
| --- | --- | --- |
| 100 | 0.333 ms | 3.723 ms |
| 1,000 | 2.724 ms | 35.520 ms |
| 10,000 | 26.112 ms | 347.568 ms |

The measurements confirm scan growth and a higher cost when matches invoke intent parsing. They do not establish a migration threshold or justify changing the schema in this checkpoint. Exact matching, provenance and current archive behavior are preserved. FTS5/indexing remains a later, separately scoped decision; no embeddings were added.

### Combined model-context baseline

At the existing ten-turn limit, twelve synthetic submissions of 12,028 retained user characters and 10,000 assistant characters produced **232,337 content characters** in the assembled model request. The initial request had 12,057 content characters. A restored session produced the same 232,337-character request on the next submission. The generation callback was mocked; no large prompt was sent to Ollama.

This is a character measurement, not a tokenizer count or a claim that the selected model accepts the entire request. The existing per-user-request 16,000-character bound remains; there is still no aggregate ordinary-chat context budget or ordinary-generation output cap. Fixing that is the separately authorized context-budget checkpoint.

### Ollama request tracing and unavailable live timings

Explicit opt-in command:

```powershell
python -m scripts.benchmark_backend --ollama --output artifacts/baseline-with-ollama.json
```

This reads the existing validated local configuration, retains the configured model, caps measurement timeout at 45 s and requests only two short synthetic responses with `num_predict=32`. It records route/method, elapsed time, safe outcome categories and supported numeric duration/token-count metadata; it does not record replies, private prompts, secrets or conversation history. It does not start a server, pull/unload/restart a model or change configuration. The first measured call is explicitly not described as a guaranteed cold model.

Actual live attempt: `qwen3.5:4b` startup `GET /api/tags` returned a controlled **connection** failure after **2,724.649 ms**. No generation was attempted after the failed startup check. Therefore **live first/consecutive-generation timings are unavailable**, and no speedup or before/after performance claim is made.

A focused test exercises the actual unchanged OllamaClient with mocked HTTP responses. It records startup tags followed by tags/show/chat for each of two generations when thinking metadata requires show. This verifies trace counting and confirms the repeated-request path, but is not a live HTTP benchmark. Transport pooling/caching remains unchanged and deferred.

## Clean-environment and installed-wheel verification

Two fresh virtual environments were created without system-site-packages. Source was copied to unrelated temporary checkout paths using only tracked/nonignored task files; no `.env`, database, original `.venv` or local runtime data was copied. A non-editable `py3-none-any` wheel was built from the exported source and installed with its declared runtime/dev dependencies into each fresh environment. Dependency acquisition used pip against the package index; the test and smoke scenarios themselves made no web-provider or paid-service requests.

Python 3.12 used the existing 3.12.10 interpreter with a fresh venv. Python 3.13.15 used an isolated temporary interpreter obtained through the already installed uv tool with `--no-bin`; it was not registered as a new default interpreter. The temporary interpreter and venv were removed after verification. An initial local harness assumed the wrong managed-interpreter directory layout and stopped before testing; resolving it with `uv python find` allowed the complete run below. No product code change was made for that harness assumption.

| Verification | Python 3.12.10 | Python 3.13.15 |
| --- | --- | --- |
| Wheel installation with fresh dependency resolution | Passed | Passed |
| `pip check` | Passed | Passed |
| `compileall` for launcher/runtime/developer scripts | Passed | Passed |
| Full exported-checkout pytest suite | **1,450 passed in 35.56 s** | **1,450 passed in 34.21 s** |
| Installed-wheel startup/help/version/doctor | All exit 0 | All exit 0 |
| Unrelated cwd and `python -I`; actual launcher under venv | Passed | Passed |
| Isolated default data path and synthetic memory save/get across processes | Passed | Passed |
| Explicit `AIKA_DATA_DIR` override | Passed | Passed |
| Process environment override | Passed | Passed |
| GUI/provider operations during smoke | 0 | 0 |

The installed smoke check redirects `LOCALAPPDATA`, home/profile and all AIKA state into a temporary tree, strips inherited AIKA/Python path settings, and uses a deliberately unavailable loopback Ollama URL. Doctor exits successfully with the expected Ollama warning. No default data directory is created merely by startup/doctor; an explicit synthetic memory save creates the database at the isolated OS-default location, then a new process retrieves the saved fact. A second synthetic save verifies the explicit data override. Actual import paths are checked to be inside the fresh venv, so an editable installation or checkout import cannot satisfy the wheel smoke accidentally.

### Observed packaging/configuration limits

The wheel works for these offline/default-path operations. Its `.env` location still resolves beside the installed package; a `.env` placed in the unrelated working directory is **not loaded**. Process environment settings work. Existing `.env` precedence/validation tests remain in the full suite. This checkpoint records the config-location issue without installing a new user-config scheme or changing packaging/import names. Generic top-level `src` package coexistence with another package of the same name was not tested.

These are local tests on the same Windows host with fresh environments, exported source paths and synthetic profile roots. They are **not a separate Windows account, clean Windows VM or second physical machine acceptance**. No claim of universal installation portability is made.

## Windows CI gate

The workflow runs on push, pull request or manual dispatch, with `contents: read`, no deployment/publishing step and no persisted checkout credentials. Both Windows Python 3.12 and 3.13 jobs:

1. Create a checkout venv and install the existing development dependencies.
2. Run `pip check`, compileall, startup/help/version/doctor with temporary data paths and an intentionally absent Ollama service.
3. Run the full mocked regression suite with slow-test reporting.
4. Generate the synthetic archive/context baseline with **no `--ollama` flag**.
5. Build a wheel, install it into a separate non-editable venv and run the isolated installed-wheel check.
6. Save baseline and resolved dependency JSON as uniquely named per-Python artifacts, retained for 14 days.

The workflow follows GitHub's [Python matrix guidance](https://docs.github.com/en/actions/tutorials/build-and-test-code/python), [context availability rules](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability) and the official [artifact action](https://github.com/actions/upload-artifact). Wheel construction/installation uses pip's [wheel](https://pip.pypa.io/en/stable/cli/pip_wheel/) and [installation](https://pip.pypa.io/en/stable/cli/pip_install/) interfaces. Artifact uploads contain measurement/version metadata, not a dump of environment variables, app data, credentials or raw generation replies.

Local workflow validation: YAML parsed, every PowerShell run block passed AST syntax checks, and **actionlint 1.7.12 passed**. The linter was taken from its [official release](https://github.com/rhysd/actionlint/releases/tag/v1.7.12), its release-archive SHA-256 checked against the published checksum, and the executable used only from a temporary directory. It is not an application or CI runtime dependency. `git diff --check` passed.

**The GitHub-hosted workflow has not run yet.** It remains a locally prepared gate until the user commits/pushes it. Local interpreter/environment results and lint success are not relabeled as a green hosted Actions run.

## Dependency evidence and reproducibility

Baseline direct versions: HTTPX 0.28.1, psutil 7.2.2, DDGS 9.16.1, python-dotenv 1.2.2, Trafilatura 2.3.1. Fresh Python 3.12 resolution selected python-dotenv 1.2.4 and pytest 9.2.0 and still passed the entire suite. The resolved versions for both environments are saved under the ignored `artifacts/` directory; CI records equivalent dependency inventories.

No dependency constraints were widened, tightened or locked. Captured versions document this baseline; **they are not a reproducible deployment lockfile**. Selecting and maintaining that lock strategy remains a separate packaging/deployment task. The CI gate intentionally detects future compatibility changes within current declared ranges.

## Reproduction and review

For the installed smoke check, build and install a wheel into a fresh venv, then invoke the script with that venv's interpreter and `-I`:

```powershell
python -m pip wheel --no-deps --wheel-dir artifacts/wheels .
python -m venv .venv-wheel
$aikaWheel = @(Get-ChildItem -LiteralPath artifacts/wheels -Filter '*.whl')
if ($aikaWheel.Count -ne 1) { throw 'Expected exactly one application wheel.' }
$aikaWheelPath = $aikaWheel[0].FullName
& .venv-wheel/Scripts/python -m pip install $aikaWheelPath
& .venv-wheel/Scripts/python -m pip check
& .venv-wheel/Scripts/python -I scripts/check_installed.py
```

The script is safe to invoke from the checkout because `-I` excludes that checkout from application imports and the smoke subprocesses use an unrelated cwd. Run it only with a fresh environment; it rejects a non-venv/nonisolated invocation. Package installation may require network access; no provider credits or Ollama inference are required for wheel checks.

The committed [sanitized JSON evidence](../benchmarks/BACKEND_BASELINE_2026-11-19.json) contains baseline measurements and both smoke summaries. Local ignored artifacts additionally include full fresh test output and dependency inventories. Timing observations vary with host load and dataset shape; do not turn these samples into brittle CI pass/fail latency limits.

Remaining review items: first hosted Windows Actions run after publication; separate-account/VM acceptance; live first/consecutive Ollama timings when the local service is available. Recommended next implementation checkpoint, only under new scope: Ollama transport reuse and bounded metadata caching with explicit refresh/invalidation. Aggregate context limits should follow promptly. No later remediation was implemented here.

**Final status: READY FOR MANUAL REVIEW.**
