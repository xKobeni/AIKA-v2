# Ollama Transport & Metadata Cache

Date: November 19, 2026. Status: **READY FOR MANUAL REVIEW**.

Scope: the user authorized the next backend checkpoint after baseline/portability/CI. Implement connection reuse and bounded model metadata caching while preserving routing, local-model selection, HTTP safety, timeout/budget semantics, evidence rules and persistence. No context-budget, packaging/config-location, archive-index, streaming or later-phase work is included. Earlier baseline/CI changes remain uncommitted and preserved.

## Baseline and owning callers

Before editing, `python -m pytest -q` passed **1,450 tests in 35.91 s**. Inspected the current Ollama adapter, settings validation, CLI startup/session callbacks, doctor, research deadline helper, benchmark instrumentation, all direct adapter callers and affected HTTP mocks. The prior adapter called fresh tags on every generation, optionally show, then chat through top-level `httpx.request`, creating a new HTTP client per request.

Production ownership is unchanged: one ConversationSession receives ordinary/grounded/planning callbacks from the same OllamaClient; diagnostics owns a separate one-shot client. There is no new orchestrator, model selector, provider, tool, database, background worker or dependency.

## Implementation and cache policy

- **Owned transport:** each OllamaClient lazily constructs one `httpx.Client(trust_env=False, follow_redirects=False)`. Successive metadata and chat requests reuse its connection pool. No request is made merely by construction/context entry. Loopback origin validation is retained and also applied at the adapter boundary, including after settings reassignment.
- **Bounded metadata:** one successful selected-model entry and its resolved thinking control are retained per instance. The cache identity includes normalized endpoint, configured model and thinking mode. Its lifetime is **30 seconds from the last successful tags check**, measured with monotonic time; ordinary warm generations do not extend it. There is no global cache, disk cache, negative-result cache, prompt cache or cached assistant response.
- **Explicit refresh:** existing `check_model()` always performs a fresh `/api/tags` request and clears previous metadata before checking. It populates availability for the next generation; thinking controls are resolved lazily when first needed. Returned metadata is copied independently so callers cannot mutate cached state through the public return value. Expiry/explicit refresh also clears resolved thinking metadata.
- **Normal generations:** without a recent check, generation validates tags and resolves thinking as before, then calls chat. With a recent successful check/control, it calls only `/api/chat`. Every generation still validates a new, complete assistant response. Current messages, `response_format`, `num_predict`, selected model and options are constructed for that call, never reused from another conversation/request.
- **Failures/recovery:** model/client errors and interruption clear metadata. Network/HTTP/JSON failures and interrupted requests also close/drop the transport; the next user request constructs a new pool and checks availability again. Missing/remote models and unsupported thinking never become a cached success. A failed generation is **not automatically retried**. Model availability is checked again on the next attempt, including after a 404 or service-connection failure.
- **Cleanup:** `close()` is idempotent and terminal; later use returns a controlled closed-client error. Context-manager exit closes resources after success or exception. CLI wraps its entire chat session, including initialization, in this lifetime; doctor wraps its one-shot check; the benchmark closes in a finally block. No destructor, cleanup thread or background service was introduced.
- **Cookies:** response cookies are cleared between requests to preserve the old one-off adapter's lack of cross-request cookie forwarding. No auth/proxy/environment credential behavior is added by pooling.

This follows HTTPX's documented [client pooling and lifecycle](https://www.python-httpx.org/advanced/clients/). Model availability still comes from the existing [Ollama tags endpoint](https://docs.ollama.com/api/tags), not a new capability source. The original thinking parsing/schema and response validation remain intact.

### Timing, permissions and privacy preserved

Requests retain the existing per-stage timeout, connect cap and `bounded_timeout` checks before/after HTTP work. A warm cache cannot bypass an expired research/agent deadline. Redirects remain unfollowed, proxy/TLS environment settings remain ignored, and settings must identify an approved loopback origin. Model aliases marked remote are still rejected on availability checks; no cloud fallback is introduced.

Only model metadata/control state is cached, not user prompts, generated text, web-source evidence, memories, tools or successful execution claims. Ordinary/grounded/planning callbacks share transport availability while retaining their separate request messages/schema/output caps and existing generation budgets. Conversation history, resume, memory commits and tool-result verification are unchanged. The configured Ollama model remains **qwen3.5:4b**. No production database or `.env` was modified.

Metadata freshness is deliberately bounded, not instantaneous: a successful out-of-band alias/capability change may remain unknown until cache expiry or explicit `check_model()`. Changes to this instance's endpoint/model/thinking mode invalidate immediately. Local service replacement is still within the trusted loopback-service boundary; this checkpoint does not claim instant detection of arbitrary server-side changes. Actual inference errors invalidate immediately and are reported without replay.

## Files changed for this checkpoint

| File | Change |
| --- | --- |
| `src/intelligence/ollama_client.py` | Owned pooled transport, 30-second metadata/control cache, explicit refresh, identity invalidation, error cleanup and context manager |
| `src/cli.py` | Scope the existing chat client with a context manager; remaining diff is indentation |
| `src/diagnostics.py` | Close the existing one-shot doctor client |
| `scripts/benchmark_backend.py` | Close the instrumented client in finally |
| `tests/test_ollama_transport.py` | 33 new deterministic cache/lifecycle/safety/recovery and loopback pooling cases |
| `tests/conftest.py` | Mock pooled-client construction; preserve independent mocked provider transports and close clients on fixture teardown |
| `tests/test_conversation.py`, `tests/test_backend_measurements.py` | Update intentional request-count expectations; retain content/history/schema/privacy assertions and verify benchmark cleanup |
| `tests/test_research.py`, `tests/test_web_stabilization.py` | Move direct request monkeypatches to the pooled client boundary; preserve timeout/deadline/safe-error assertions |
| README, this report, `docs/benchmarks/OLLAMA_TRANSPORT_2026-11-19.json` | Usage, policy, actual results and sanitized before/after evidence |

No baseline/CI workflow, registry, executor, tool contract, database schema, routing recognizer, permission or model-setting change was needed for transport reuse. No existing test was deleted; mocked HTTP entry points and the deliberately reduced network counts were updated to the new implementation.

## Automated verification

- Pre-change full baseline: **1,450 passed in 35.91 s**.
- Focused adapter/conversation/benchmark/web-stabilization group during implementation: **134 passed in 5.07 s**, with one optional urllib3 SOCKS-dependency warning in that selected import order. No dependency was added or warning suppressed for this unrelated optional integration.
- Extended mocked provider/research/adapter group after isolating provider mocks: **344 passed in 6.63 s**.
- Final Python 3.12 complete regression: **1,483 passed in 45.63 s**, no warnings. All 1,450 earlier cases remain plus 33 new cases.
- Final Python 3.13.15 regression in a fresh isolated dependency environment: **1,483 passed in 35.66 s**, no warnings. The wheel smoke used a separate fresh non-editable installation of the same runtime code; the final test run includes the corrected HTTP fixture hooks.
- `pip check` and `python -m compileall -q aika.py src scripts` passed. `git diff --check` passed, with the repository's Windows line-ending notices only.

The new tests cover first/warm/expired/explicitly refreshed metadata; non-sliding expiry; model/endpoint/thinking-mode changes; cached False/None controls; independent returned metadata; malformed/removed/remote models; service recovery and remote alias rechecks; HTTP 404/500, connection/read/protocol/JSON failures; interrupted requests without replay; invalid generated responses; closed/lazy/context-managed ownership; doctor/CLI/benchmark cleanup; current format/token-cap messages; no cookie forwarding; invalid remote endpoint rejection; and warm-cache deadline checks. Existing agent cancellation, progress, partial results, execution budgets, source isolation, memory/persistence and routing regressions remain in the complete suite.

A synthetic local HTTP/1.1 server test records the source port of tags and two chat requests and confirms **one TCP connection**. Its resolver permits only that exact numeric loopback address/ephemeral port, and proxy environment variables point elsewhere to verify they are ignored. This is not a real Ollama/provider call or inference test. All other test HTTP/model/provider/GUI operations use existing mocks.

During the first full integration run, the shared HTTP mock collided with separately mocked provider clients and two direct request tests still patched the old top-level function. The fixture was corrected to preserve those providers' explicit MockTransport instances and the direct hooks were moved to Client.request. Their existing behavior/assertions remain unchanged; no web runtime fix or provider fallback was introduced.

## Actual live before/after trace

The same developer benchmark ran before and after against the unchanged local **qwen3.5:4b**, using only `Reply only with OK.` and `num_predict=32`. It uses temporary synthetic storage for its unrelated context measurement and never reads production conversations or memory. No model/server was forcibly stopped, started, unloaded, pulled or reconfigured. Both before and after generated two completed replies; reply text is not saved in the trace.

| Stage | Before | After |
| --- | --- | --- |
| Startup availability | tags — 1 request | tags — 1 request |
| First generation after startup | tags + show + chat — 3 requests | show + chat — 2 requests |
| Consecutive generation inside TTL | tags + show + chat — 3 requests | chat — 1 request |
| Total for startup + two generations | **7 requests** | **4 requests** |
| First generation wall time | 16,291.651 ms | 889.821 ms |
| Consecutive generation wall time | 1,353.355 ms | 332.881 ms |

The request-count reduction is the primary evidence. The first pre-change generation reported **14.361 s model-load time**; the post-change model was already warm. Ollama's measured inference time also varied between runs. These timings are observational samples, **not a controlled cold-start comparison or a claim that all latency reduction came from transport/cache changes**. In the recorded after trace, show took 13.335 ms and the consecutive chat request took 332.828 ms; no tags/show request occurred during that consecutive generation.

The [sanitized before/after JSON](../benchmarks/OLLAMA_TRANSPORT_2026-11-19.json) records routes, safe status, elapsed times and supported numeric model-duration/token-count metadata, not private prompts, secrets or generated answers. The baseline checkpoint's earlier unavailable-Ollama observation remains historical; it is not overwritten by these new successful samples.

## Installation and manual review

A new non-editable wheel was installed into a fresh Python 3.13.15 environment. `pip check` passed, and the existing isolated-import wheel smoke check passed startup/help/version/doctor, synthetic memory persistence across processes, isolated default data paths and explicit overrides with zero GUI/provider operations. Doctor was deliberately run without an Ollama service, validating both the new cleanup and existing optional-service behavior. These are local Windows environments, not a hosted GitHub run or separate-machine acceptance.

Actual source CLI startup, doctor, version and help also exited **0** against the available local service with temporary storage. A piped chat containing two short ordinary requests, `/calc 12*7`, `/capabilities`, `/history` and exit completed with no Ollama error, showed calculator **84**, the capability listing and restored-in-session message text, then exited **0**. No GUI or web-provider action was requested. No production conversation or memory database was used.

For direct backend use:

```python
from src.config import load_config
from src.intelligence.ollama_client import OllamaClient

with OllamaClient(load_config()) as client:
    client.check_model()  # always fresh; also primes availability
    first = client.generate([{"role": "user", "content": "Reply only with OK."}])
    second = client.generate([{"role": "user", "content": "Reply only with OK."}])
    # A recent successful check/control avoids metadata calls; each answer still calls chat.
```

Use an isolated `AIKA_DATA_DIR` when reviewing CLI history/memory. Run `python -m aika`, `doctor`, `--version`, `--help`, and `chat`; ordinary replies, calculator/system/memory commands and `/clear`/`resume` retain their established behavior. Normal CLI exit, EOF and Ctrl+C close the transport. Do not interpret reused metadata as proof of a new tool operation, live provider readiness or action completion. To force revalidation in the adapter, call `check_model()`; no new terminal command/config knob is needed.

Re-run the explicit live benchmark when useful:

```powershell
python -m scripts.benchmark_backend --ollama --output artifacts/ollama-transport-review.json
```

Service/model restart, alias removal and failure recovery were tested with deterministic mocked failures, not by interrupting the user's real service. Hosted Windows CI still awaits its first user publication/run. Aggregate context/output limits remain unchanged and should be the next separately scoped hardening task. No later checkpoint, Git commit, tag or push was created.

**Final status: READY FOR MANUAL REVIEW.**
