# AIKA V2 Phase 1A — Local Ollama model connection

**Status** — READY FOR MANUAL REVIEW  
**Date** — 2026-11-17  
**Approval** — Pending manual review

## Implementation

`python -m aika chat` sends an AIKA system instruction and the current message to the configured local model. The Ollama adapter checks the model list before generation, uses non-streaming `POST /api/chat`, requests `think: false`, and returns the completed assistant text. The adapter accepts a supplied message list so a future caller can use it independently of the terminal. Each CLI message starts fresh.

The original `AIKA_RUNTIME_URL` setting still works. `AIKA_OLLAMA_URL` takes precedence when set. The current checkout defaults to `qwen2.5:3b`, and the configurable generation I/O timeout defaults to 180 seconds. The adapter ignores environment proxies and does not follow redirects. It rejects explicitly cloud-marked models and installed entries marked remote by Ollama. [Ollama chat API](https://docs.ollama.com/api/chat) · [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking)

`doctor` checks the local model API and selected model. Service or model availability warnings preserve the core diagnostic exit code of `0`. Configuration and core runtime failures keep exit code `1`. Chat shows readable errors and stays open for another attempt. Diagnostics and debug logs exclude prompts, model thinking, and raw backend error bodies.

## Files

| Path | Changes |
| --- | --- |
| `src/intelligence/ollama_client.py` | Independent HTTPX adapter for model availability and generation. |
| `src/config.py` | Added local model, timeout, and URL override with legacy compatibility. |
| `src/cli.py` | Added chat, AIKA's system instruction, and Phase 1A status. |
| `src/diagnostics.py` | Added Ollama and model checks while preserving the runtime checks. |
| `pyproject.toml` | Added HTTPX and included the adapter in the package. |
| `tests/conftest.py`, `tests/test_ollama.py` | Added mocked HTTP and CLI acceptance cases. |
| `tests/test_runtime.py` | Kept the 20 prior cases. Changed expectations for the Phase 1A status text and mocked the new model check in existing doctor tests. |
| `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, and this report | Documented setup, troubleshooting, phase status, and acceptance. |

## Verification

- Installed the editable project with `python -m pip install -e '.[dev]'`. `python -m pip check` found no broken requirements.
- The original Phase 1A run passed **48 tests** on Windows with Python 3.12.10. See the test isolation fix below for current results.
- Real Ollama 0.40.16 listed the installed models. The CLI produced genuine answers to the introduction and Python function prompts using `qwen2.5:3b`, then generated a separate answer after switching to `llama3:8b` through the environment.
- At the time of the original run, `qwen3:4b` was the default and was absent on this machine. The live model list produced a warning for it. A deliberately nonexistent model produced the installation hint in `doctor` and chat, and the chat session exited cleanly.
- After stopping the temporary Ollama test instance, `doctor` reported an Ollama warning, chat reported a connection error on input, and `exit` ended the session cleanly. The regular Ollama endpoint on port `11434` still responded.
- The status, version, help, and diagnostic commands ran from PowerShell. `doctor` also resolved the editable install from outside the checkout. Python 3.11 still produced a readable compatibility error.

## Phase 1A test isolation fix

Reproduced **34 passed, 14 failed** before the fix. The model comes from the process variable `AIKA_OLLAMA_MODEL`, with `src/config.py` supplying `DEFAULT_MODEL` when the variable is absent. The model variable was unset at process, user, and machine scope during investigation. The checkout had no `.env` file, and the loader reads the process environment directly. Ollama's installed model list is used to verify availability. It does not select the model.

The old pytest fixtures removed `AIKA_OLLAMA_MODEL`, so app code and CLI subprocesses used the production fallback of `qwen2.5:3b`. The mocks and assertions still used `qwen3:4b`. The Ollama adapter correctly rejected the mismatch at the model check, which prevented many tests from reaching the generation error they were meant to exercise.

| File | Change |
| --- | --- |
| `tests/conftest.py` | A shared function-scoped fixture sets the model explicitly, clears other app overrides, and uses a temporary data path. Pytest's `monkeypatch` restores the environment after each test. The default HTTP mock lists the fixture's model. |
| `tests/test_ollama.py` | Synthetic model lists and error expectations use the chosen test model. Generation tests cover `qwen2.5:3b`, `qwen3:4b`, and the existing untagged `llama3` case. Error tests assert that the request reached `/api/chat`. |
| `tests/test_runtime.py` | CLI subprocesses inherit the fixture's environment. Startup tests verify both Qwen model names, and diagnostics assert the exact selected model. |
| `README.md` and this report | Document the actual workspace default and the test fix. |

The production loader, Ollama adapter, and `qwen2.5:3b` default were preserved. Automated Ollama requests remain mocked. The tests alter no personal settings files.

| Check | Observed result on Windows with Python 3.12.10 |
| --- | --- |
| `python -m pytest tests/test_ollama.py -q` | 30 passed |
| `python -m pytest tests/test_runtime.py -q` | 21 passed |
| `python -m pytest -q` | 51 passed, zero failures |
| Full suite with conflicting inherited model, URL, and timeout | 51 passed. The calling PowerShell session retained its original test values. |
| `python -m aika` | Core runtime `READY` with `qwen2.5:3b`. |
| `python -m aika doctor` | Ollama reachable and `qwen2.5:3b` installed locally. The missing data directory produced the expected warning. |
| `python -m aika --version` | `AIKA AI V2 0.1.0`. |

For a manual regression check, run these commands from the V2 root in a PowerShell session with your normal configuration and Ollama running. The runtime and doctor should show your configured model. With the checkout defaults, they should show `qwen2.5:3b`, and the version should be `0.1.0`.

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -m pytest tests/test_ollama.py -q
& $python -m pytest tests/test_runtime.py -q
& $python -m pytest -q
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
```

## Manual acceptance

From the V2 root, with Ollama open, use the Python created in Phase 0B. See the [README setup](../../README.md#run-on-windows) if the environment needs to be created.

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -e '.[dev]'
ollama list
$env:AIKA_OLLAMA_MODEL = 'qwen2.5:3b'
& $python -m aika chat
```

- [ ] **A. Basic conversation.** Enter `Hello AIKA. Introduce yourself.` Confirm a generated answer.
- [ ] **B. General knowledge.** Enter `Explain how a Python function works.` Confirm a sensible answer. Enter `exit` to return to PowerShell.

```powershell
# C. Switch to another installed chat model.
$env:AIKA_OLLAMA_MODEL = 'llama3:8b'
& $python -m aika doctor
& $python -m aika chat
# Ask a short question, then enter exit.

# D. Select a model that does not exist.
$env:AIKA_OLLAMA_MODEL = 'aika-phase-1a-nonexistent:latest'
& $python -m aika doctor
& $python -m aika chat
# Enter hello, then exit.

# E. Start chat with a working model. Quit the Ollama Windows app from
# its tray menu, or stop your ollama serve window, before sending a message.
$env:AIKA_OLLAMA_MODEL = 'qwen2.5:3b'
& $python -m aika chat
# Once Ollama has stopped, enter hello, then exit. Reopen Ollama after the test.

# F. Run the regression checks with Ollama running again.
& $python -m aika
& $python -m aika doctor
& $python -m aika --version
& $python -m aika --help
& $python -m pytest -q
```

- [ ] **C. Model switching.** The doctor and chat outputs identify the second model and it generates a response.
- [ ] **D. Missing model.** Doctor shows `WARN` for the model. Chat reports the missing model and shows an `ollama pull` command.
- [ ] **E. Service unavailable.** Chat reports the connection failure and returns to the input prompt.
- [ ] **F. Regression.** Runtime is `READY`, the installed model passes its probe, version is `0.1.0`, help includes `chat`, and 51 tests pass.

## Limits and next checkpoint

Prompt instructions guide identity and capability claims. Generated text can still be inaccurate. There is no conversation history, streaming, persistence, or tool execution. The test isolation fix covered `qwen3:4b` through mocks and installed no models. No Git commit or tag was created.

Phase 1B is the next planned checkpoint and adds short-lived conversation context and the single request orchestrator after manual acceptance.
