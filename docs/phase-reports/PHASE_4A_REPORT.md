# AIKA V2 Phase 4A — Hybrid Web Search (DDGS + Tavily)

**Status:** READY FOR MANUAL REVIEW  
**Date:** 2026-11-18  
**Approval:** Pending user review. The DDGS reliability repair returned five real sources in one bounded auto-backend probe. External backend reliability remains variable; this repair made no live Tavily calls.  
**Scope:** Phase 4A only. No commits, tags, existing database changes, or Phase 4B work.

## Architecture

There is still exactly one registered search tool: `web.search`, classified READ_ONLY. The existing explicit network gate remains separate from local-state permissions. The tool registry still contains five tools in total. The same Tool Executor, ToolResult, conversation lifecycle, SQLite exchange transaction, and authorization rules are used.

Two independent adapters implement the same small `search(query, max_results)` boundary:

- `DDGSSearchProvider` uses the maintained `ddgs` Python library, without authentication or a paid account.
- `TavilySearchProvider` retains the official HTTPS Search API adapter and its basic, bounded request profile.

`SearchRouter` selects one adapter and, only under the documented opt-in conditions, a secondary. It does not own a conversation, call Ollama, register tools, generate a plan, or execute actions. It is a provider selector inside the existing tool handler, not another orchestrator or executor.

The maintained [DDGS package documentation](https://pypi.org/project/ddgs/) and the implementation of its search/backend/error interfaces were inspected. The project pins `ddgs==9.16.1`, installed successfully with its required dependencies. AIKA now uses the documented `backend="auto"`, with page 1 and a five-second native timeout. Readiness checks require at least one enabled text backend. DDGS can query multiple internal free engines during one adapter call; these are not additional AIKA providers and never include Tavily. No API/MCP extras, server, extraction function, or result-link fetching is used. A future DDGS version needs an adapter review before changing the pin.

The [official Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search) was also checked. Tavily keeps the fixed HTTPS endpoint and Bearer header, `basic` depth, `general` topic, and disabled answer/raw-content/image/automatic-parameter settings. The existing HTTPX dependency is reused; no new networking framework is introduced.

## Routing and paid-usage rules

| Selection | First adapter | Secondary behavior |
| --- | --- | --- |
| Configured `auto`, no per-request override | DDGS | Off by default; opt-in secondary only after a controlled unavailable, timeout, or rate-limit error. |
| Configured `ddgs` | DDGS | Never falls back. |
| Configured `tavily` | Tavily | Never falls back. |
| `/web --provider ddgs ...` | DDGS | Never falls back, regardless of configured mode or fallback setting. |
| `/web --provider tavily ...` | Tavily | Never falls back, regardless of configured mode or fallback setting. |

A Tavily key alone never authorizes automatic paid usage. Enabling web access in default auto mode makes keyless DDGS available and leaves fallback off. Tavily can consume credits only after selecting Tavily deliberately or explicitly enabling the Tavily secondary in auto mode. Enabling that secondary is an opt-in to potentially billable fallback.

Fallback is not attempted for empty results, rejected input, authentication/quota errors, malformed output, or unexpected internal failures. A secondary identical to the primary is not retried. There is at most one call to each selected provider adapter: normally one provider operation, or at most two when fallback is authorized and eligible. Results are not merged and neither adapter is automatically retried. Both-failure outcomes remain unsuccessful and retain attempted-provider metadata without fabricated sources.

Successful router output records `attempted_providers` and `fallback_used`. The reply names the provider supplying the sources and displays `ddgs -> tavily` when fallback actually supplied the result. These are provider-operation attempts, including availability checks, not a claim of a particular number of low-level DDGS transport packets.

## Configuration and setup

Search remains disabled by default. All existing environment settings, local model defaults, and offline features are preserved.

| Setting | Default | Meaning |
| --- | --- | --- |
| `AIKA_WEB_SEARCH_ENABLED` | `off` | Explicit network gate; off/on, false/true, or 0/1. |
| `AIKA_WEB_SEARCH_PROVIDER` | `auto` | auto, ddgs, or tavily. |
| `AIKA_WEB_SEARCH_FALLBACK_ENABLED` | `off` | Explicit fallback opt-in, with the same boolean syntax. A Tavily secondary can consume credits. |
| `AIKA_WEB_SEARCH_FALLBACK_PROVIDER` | `tavily` | ddgs or tavily. In auto mode the primary is DDGS, so choosing DDGS as secondary results in no second attempt. |
| `AIKA_TAVILY_API_KEY` | empty | Secret required only for Tavily. A key is not required for DDGS and is never passed as DDGS authentication. |

Keyless setup in a dedicated PowerShell window:

```powershell
python -m pip install -e '.[dev]'
$env:AIKA_WEB_SEARCH_ENABLED = 'on'
$env:AIKA_WEB_SEARCH_PROVIDER = 'auto'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
python -m aika doctor
python -m aika chat
```

To configure Tavily, enter the key through a hidden prompt rather than recording it literally in shell history:

```powershell
$apiKeyInput = Read-Host 'Tavily API key' -AsSecureString
$env:AIKA_TAVILY_API_KEY = [System.Net.NetworkCredential]::new('', $apiKeyInput).Password
$apiKeyInput.Dispose()
Remove-Variable apiKeyInput
```

Then select `AIKA_WEB_SEARCH_PROVIDER=tavily` for Tavily-only mode, or keep auto/DDGS and use `/web --provider tavily <query>` for a deliberate paid request. To authorize paid fallback, set `AIKA_WEB_SEARCH_PROVIDER=auto`, `AIKA_WEB_SEARCH_FALLBACK_ENABLED=on`, and `AIKA_WEB_SEARCH_FALLBACK_PROVIDER=tavily` before restarting chat. No billing settings or pay-as-you-go account settings are changed.

Invalid enum/boolean settings are rejected by the existing configuration system without echoing input values. Keys remain hidden from representations and redacted from chat/model/persistence boundaries. To run without any web access or credentials, leave search settings unset or set `AIKA_WEB_SEARCH_ENABLED=off`. Close the dedicated shell to discard its environment when done.

## Common data contract and validation

Both providers use one normalizer and one output contract. Each source records actual optional title, URL, domain, snippet, provider, timezone-aware UTC retrieval timestamp, optional supplied publication date, rank, and optional score. DDGS href/body/date fields are mapped to those common fields. Missing dates, titles, or excerpts remain unavailable; no research answer or missing metadata is invented. Provider and collection time are preserved in the displayed and saved result.

Queries remain bounded to 1–300 printable characters and result counts to 1–5, default five. An optional per-request provider may be ddgs or tavily; arbitrary provider names, endpoint URLs, headers, credentials, or free-form options are rejected. CLI flags select only the provider; remaining query text is search data and is never executed as code.

The shared safety checks retain HTTP(S)-only source URLs, credential/control-character rejection, obvious local/private/alternate-loopback filtering, canonical source deduplication, terminal-safe text, 200-character titles, 1,000-character snippets, and a 512 KiB normalized-input limit. Raw string lengths are checked before serialization. At most 50 provider entries are inspected, with no more than five output sources. Source URLs are never followed, fetched, or resolved by AIKA. Syntax validation is not website security or factual verification.

Tavily still has a streamed 512 KiB response cap, 3-second connection/write/pool timeouts, 5-second read inactivity, and a 15-second budget checked between reads. A blocked read can extend to its inactivity timeout; there is no hard preemption. DDGS has a five-second native per-engine timeout and uses auto backend selection/page 1, but buffers native HTTP responses within the library. This is not a five-second overall deadline: multiple engine waves and thread shutdown can extend the operation. AIKA's normalized-output cap is not a raw-wire cap on DDGS's internal transport. Transport redirects and lower-level HTTP details remain library behavior, not autonomous source crawling.

DDGS errors are converted to fixed controlled categories. Typed/nested timeout and rate-limit exceptions are recognized; other DDGS service failures are unavailable. An unexpected internal exception is a failure without paid fallback. A genuinely returned empty list remains a successful no-results outcome. The exact `No results found.` exception (also when nested) now produces a controlled `indeterminate` failure, not verified empty output. It can hide HTTP rejection or unparsed content. It is excluded from fallback eligibility, even when fallback is enabled. No original exception body is displayed.

DDGS library logging is suppressed, including later-created child loggers, to keep native exception text from exposing a query. DDGS_PROXY is rejected without displaying its value rather than silently changing the audited transport configuration. Missing/wrong DDGS versions or missing approved backends produce controlled unavailable results. Tavily retains safe authentication, quota, rate-limit, network, JSON, and HTTP error handling without exposing provider error bodies or keys.

## Privacy, untrusted results, and persistence

Only the current validated query and bounded options are provided to the selected adapter. No transcript, structured memory, system measurements, process inventory, or local files are automatically attached. Tavily keys are used for its authorization header only; DDGS receives no credential argument. The configured key can be used locally for redaction/filtering of either provider's returned data. Queries containing credentials are rejected.

All source text remains untrusted data. It is deterministically formatted, never interpreted as an instruction to mutate memory, launch apps, reconfigure the program, or execute a further search. Ordinary explanations, saved-memory questions, calculations, local system requests, and app launching retain their routes and cannot trigger an unintended provider call. The existing model instruction and bounded claim guard remain supplementary protections; actual evidence comes from tool execution.

The existing SQLite conversation transaction saves safe requests, returned source records as displayed, provider labels, and original retrieval timestamps. Resume/history display them without another search. Search exchanges remain excluded from future ordinary Ollama context, including explicit-provider commands, and are not automatically promoted into structured facts. There is no new database, migration, global result cache, or automatic replay. A storage failure does not retry the provider and can occur after a potentially billable operation.

## CLI and diagnostics

Preserved all prior commands and added provider selection to the existing `/web` command:

```text
/web <query>
/web --provider ddgs <query>
/web --provider tavily <query>
/web-status
```

Malformed/unknown provider flags are rejected without a request. Explicit natural-language searches continue through the configured mode and same executor. The recognizer remains bounded; vague references require a specific query rather than automatic context transfer. Current-information recognition remains available without turning ordinary explanations into searches.

Status and doctor report mode, primary/secondary policy, key presence, both adapters' local readiness, tool registration, and limits. They import/check interfaces without instantiating a native search client or performing a search, and do not consume credits. Local readiness does not prove authentication, connectivity, or source quality. Existing model, memory, SQLite, calculator, application, and system diagnostics remain.

## Files changed

| File | Change |
| --- | --- |
| `src/capabilities/web_search.py` | Two named adapters, shared normalizer, typed fallback categories, pinned DDGS interface checks, lightweight router, routing evidence, and common output validation. |
| `src/capabilities/web_intent.py` | Explicit CLI provider selection, malformed-flag rejection, actual provider display, and visible fallback attribution. |
| `src/config.py` | Provider mode and opt-in secondary settings with safe validation. |
| `src/capabilities/__init__.py` | Keep one web.search registration; default it to the router. |
| `src/intelligence/conversation.py` | Accept the router/adapters at the existing injection boundary; default to the disabled router without changing the lifecycle. |
| `src/cli.py` | Construct configured router, update help/provider status, and display both adapters' local readiness. |
| `src/diagnostics.py` | Hybrid mode/adapter readiness and no-request contract checks. |
| `pyproject.toml` | Add audited `ddgs==9.16.1` dependency, without optional server/MCP extras. |
| `tests/test_hybrid_search.py` | 65 new provider, routing, fallback, cost, privacy, CLI, persistence, and error tests. |
| `tests/test_web_search.py` | Rename the prior Tavily adapter imports; select Tavily explicitly for prior HTTP/CLI tests so all their existing assertions remain meaningful. |
| `tests/conftest.py` | Isolate routing/proxy environment and block live DDGS construction during automated tests, alongside the existing Tavily network guard. |
| `README.md`, this report | Hybrid setup, costs, privacy, limits, actual results, and manual review. |

The Tool Registry, Tool Executor, ToolResult, permission contracts, configured Qwen3.5 model, memory/database implementation, and existing data were not changed. No AIKA V1 files were touched.

## Original hybrid implementation validation (historical)

- Baseline: **589 passed in 18.45 seconds** before changes.
- Focused new hybrid suite: **65 passed in 1.26 seconds**.
- Final complete regression: **654 passed in 19.89 seconds**, Python 3.12.10 on Windows. All 589 prior cases remain; no tests were removed or assertions weakened.
- Automated tests mock both providers. DDGS native client creation/text requests and Tavily HTTP are blocked unless the test supplies mocks. Tests consume no live credits and do not depend on search-engine availability or current source results.
- Coverage includes keyless auto defaults, all configured modes, then-configured backend/page/timeouts, common source fields and dates, sanitation/deduplication, disabled gate, key-only non-authorization, explicit overrides/configured modes forbidding fallback, opt-in eligible fallback, rejected categories, empty results, malformed results, unavailable dependencies, no repeated primary/secondary attempts, same-provider secondary, private errors/logs, CLI flags/status, model-context boundaries, persistence/resume without replay, and prior functionality.
- Actual startup, doctor, version, and help subprocesses returned exit code **0** against a temporary database. Final actual doctor/status reported DDGS locally available without a key, Tavily unavailable without a key, and fallback off. These checks performed no search.
- One actual CLI `/web --provider ddgs official Python documentation` check completed with **no result entries**. No useful live sources or factual research answer were claimed. It did not try Tavily. The library's empty/blocked ambiguity remains a manual-review limitation rather than a reason for paid fallback.
- There is no configured Tavily key here. **No live Tavily query or paid fallback was made.** Those success/error paths were verified using mocks.
- Temporary test storage was cleaned up. No existing conversation/memory database, model configuration, Git commit, or tag was changed.

## Manual walkthrough

Use a dedicated PowerShell window and an isolated archive:

```powershell
python -m pip install -e '.[dev]'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-hybrid-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_WEB_SEARCH_ENABLED = 'on'
$env:AIKA_WEB_SEARCH_PROVIDER = 'auto'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
python -m aika doctor
python -m aika chat
```

1. Run `/web-status`. Expect auto mode, DDGS primary, fallback off, and keyless DDGS readiness if the dependency/backend is available. This must not search.
2. Enter `/web official Python documentation` and `/web --provider ddgs recent Ollama updates`. Expect DDGS sources or an honest empty/error response, with no Tavily use.
3. Ask `Search the web for recent Ollama updates.` and `Explain what web search is.` The first selects the configured search route; the second stays ordinary conversation.
4. Save a synthetic Orion/SvelteKit fact, retrieve it, calculate `245 * 18`, and ask current RAM usage. These must keep their existing local routes.
5. Configure a Tavily key with the hidden prompt above. With no fallback enabled, `/web --provider tavily official Python documentation` is a deliberate potentially billable Tavily request. It must not fall back to DDGS after an error.
6. For optional fallback review, restart with auto mode, fallback on, and Tavily as secondary. A controlled DDGS unavailable/timeout/rate-limit outcome may invoke Tavily once. A genuine empty result must not. Successful fallback must identify Tavily and show the provider transition. Automated tests exercise these conditions without artificially failing a live endpoint or spending credits.
7. Copy a session ID, exit/restart, `/resume <session_id>`, and `/history`. Earlier sources, provider, and timestamp must remain visible without search replay or insertion into ordinary model context.
8. Disable web access and restart. Both `/web --provider ddgs ...` and `/web --provider tavily ...` must report unavailable, while local features still work.
9. Run startup, doctor, version, help, and `python -m pytest -q`. Close the dedicated shell afterward to discard its temporary environment.

## Limitations and next checkpoint

User approval remains pending. The original implementation checks below are historical; the reliability repair evidence is recorded in the following section. Live Tavily and paid fallback were not exercised by this repair (the user separately reports working Tavily results). No fresh virtual-environment installation or live app launch was performed. The DDGS backend is an unofficial automated search interface and may change, block requests, or conflate empty/blocked outcomes; DDGS dependency upgrades require review. DDGS auto mode may select multiple internal engines. There is no AIKA retry or automatic paid fallback to conceal ambiguous failures.

URL validation is syntactic and does not establish website safety or source truth. Redaction covers the configured secret and recognizable Tavily tokens, not every possible credential encoding. Provider dates may be absent or estimated. Native DDGS transport buffering cannot be capped by AIKA's normalizer, and native timeouts are not a hard cancellation framework. Source snippets are not full articles or verified research conclusions.

No autonomous browsing, crawling, extraction, file management, agents, background monitors, paid feature upgrades, or new execution framework were introduced.

**Next proposed checkpoint:** Phase 4B — Source Reading & Grounded Answers. It has not been started. Stop at READY FOR MANUAL REVIEW.


## DDGS empty-results reliability repair � 2026-11-18

### Confirmed cause and investigation

The installed version is **ddgs 9.16.1**, on Python 3.12. Its actual `DDGS.text(query, **kwargs)` delegates to `_search_sync`, whose backend default is `auto`. Returned rows are dictionaries containing `title`, `href`, and `body`. AIKA already correctly maps `href` to the common URL and `body` to content/snippet; no mapping correction or replacement source data was required.

Two local defects were confirmed: AIKA forced `backend="duckduckgo"`, preventing the library's documented engine selection, and converted `DDGSException("No results found.")` into a verified empty list. Inspection of the installed `BaseSearchEngine.request` shows non-200 responses become `None`; `_search_sync` can then raise that same exception. It also raises it when parsers yield no entries. Thus an HTTP rejection was being presented as an ordinary empty search.

[Official-repository issue #498](https://github.com/deedy5/ddgs/issues/498) was inspected alongside the [version-specific API documentation](https://github.com/deedy5/ddgs/blob/v9.16.1/README.md#1-text). The issue describes similar suppressed 202/429 responses and empty parsing, but is a user report closed with a spam label, not a confirmed maintainer diagnosis or a prescribed repair. No suggested header/TLS evasion or upstream patch from that issue was adopted. The diagnosis here is supported independently by installed source and local observations.

### Bounded live evidence

Exactly two direct `DDGS(timeout=5, verify=True).text(...)` calls were made, one for each backend, for the same public query `latest Python release`, max_results=5, page=1. Each ran in a subprocess with a 35-second outer deadline; neither deadline was reached. A temporary diagnostic wrapper observed response status codes without changing requests, TLS, headers, or responses. No `.env` key was read into the probe, no Tavily request was made, and no result page was fetched.

| Direct backend | Observed result | Time |
| --- | --- | --- |
| `duckduckgo` (old adapter setting) | HTTP 202; `DDGSException("No results found.")`; no raw list returned | 0.42 seconds |
| `auto` (repaired setting) | Five raw rows; internal response statuses 200, 200, 202, 200, 200, 429, 200, 200 | 4.19 seconds |

The five raw auto rows were replayed into the existing AIKA adapter using a mocked client, without a third network search: **five normalized sources, zero discarded**. Returned URLs included `https://www.python.org/downloads/latest/`, `https://www.python.org/downloads/`, `http://devguide.python.org/versions/`, `https://docs.python.org/3/whatsnew/3.15.html`, and `https://blog.python.org/2026/10/python-31022-31117/`. These are observed provider results, not verified publication or release claims. A strict raw/normalized string comparison was false; existing whitespace/control cleanup and field bounds mean verbatim equality is not promised. Mocked contract tests establish the exact title/href/body mapping and retain sanitation. No additional live searches were made to inspect those differences or to test Ollama-specific results.

The forced DuckDuckGo failure is confirmed as a rejected automated response locally; the cause of that rejection is not established. Auto succeeded once despite some internal failures, which is evidence of restored retrieval, not a guarantee of future uptime.

### Changes and error policy

- One `web.search`, two existing provider adapters, the same router, executor, network gate, configuration, and persistence lifecycle remain.
- DDGS now receives `backend="auto"`, page 1, max_results<=5, timeout=5, verify=True. Its dependency pin remains unchanged. Readiness checks enabled text engines rather than requiring DuckDuckGo specifically.
- Literal returned `[]` is valid empty output. Ambiguous `No results found.` exceptions are controlled failures of kind `indeterminate`, with no invented results and no eligible paid fallback.
- Typed/nested timeout and rate-limit exceptions retain controlled distinct categories. Other exposed DDGS service failures remain unavailable. Unexpected internal exceptions do not authorize fallback. Upstream-hidden 202/403/429 responses cannot be assigned a known status by the production adapter; their ambiguous outcome is reported honestly rather than inferred from exception text.
- Provider modes and explicit selections are unchanged. Fallback remains off by default; explicit selection never switches. Only existing eligible unavailable/timeout/rate-limit failures can use the separately enabled secondary. Neither a returned empty list nor an ambiguous failure invokes Tavily.
- No new provider, dependency, retry, TLS bypass, engine monkeypatch in production, crawling, or Phase 4B feature was added. Existing source bounds, redaction, actual DDGS attribution, and untrusted-data handling remain.

### Automated verification

Focused hybrid suite: **72 passed in 1.59 seconds**. Tests mock network responses and cover the raw title/href/body mapping, individual invalid-row filtering with valid rows preserved, raw empty output, ambiguous direct/nested library errors, typed timeout/rate-limit handling, and real pinned-library suppression of mocked 202/403/429 responses. Existing provider mode, explicit selection, fallback, privacy, persistence, and no-unexpected-Tavily tests remain. The installed-library rejection tests perform no network requests.

Full regression result: **667 passed in 22.89 seconds**, Python 3.12.10 on Windows. All existing regression tests remain; no tests were removed. The seven additional cases supplement the 660-test pre-repair suite. Automated tests made no live provider requests.

### Manual review and remaining limits

Restart AIKA with web enabled, provider `auto`, fallback `off`; use `/web-status` and `/web --provider ddgs latest Python release` once. Expect actual DDGS sources or a controlled error, never fabricated success. `/web --provider ddgs the latest Ollama updates` can be checked manually; this repair did not repeatedly query engines for both phrases. Check ordinary calculator, memory, system, and app commands normally, then resume history without search replay.

AVAILABLE still means local dependency readiness. Individual engines can block requests, change markup, or return poor results. DDGS 9.16.1 hides some HTTP statuses, and successful rows do not identify their internal engine, so attribution is DDGS, not a guessed DuckDuckGo/other engine. Auto sends the current query to the library's free backends and can take longer than its per-engine timeout. No live Tavily usage or fresh-environment installation was tested here. No existing database was changed; no Git commits or tags were created.

**Status: READY FOR MANUAL REVIEW.** Phase 4B has not been started.
