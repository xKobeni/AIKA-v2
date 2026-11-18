# Phase 4C — Intelligent Automated Web Research

**Status: READY FOR MANUAL REVIEW. User acceptance is pending; this checkpoint is not marked PASSED.**

Date: 2026-11-18. Scope: fixed, bounded automatic research through the existing conversation lifecycle. No Phase 5 planning, general agents, new database, browser automation, desktop UI, commits or pushes.

## Inspection and baseline

Inspected the actual local workspace, foundation, implementation roadmap, Phase 4A/4B/4B-R reports, search providers/router, normalizer, secure reader, extraction, grounding/quote validators, Ollama adapter, configuration, conversation storage, CLI and tests. Existing local modifications were preserved; no older GitHub checkout/reset was used. The recent redirects, fallback extraction, optional-warning handling, per-claim validation, prompt isolation and source provenance improvements remain.

Actual pre-edit baseline: **872 passed in 28.15 seconds**, Python 3.12.10 on Windows.

The gap was coordination: natural search/current-information requests previously returned search snippets, while secure reading and grounded composition required separate commands. DDGS ambiguity, occasional normalization contract errors, source accessibility, conservative grounding and local inference latency remained operational limits.

## Architecture and implemented sequence

`ConversationSession` remains the sole lifecycle owner. Its bounded `_research_reply` branch executes the existing tools and existing grounding callback. The small `research.py` module contains deterministic intent/query/ranking/date/diagnostic helpers; it cannot execute tools or run an independent conversation. The new `web_budget.py` shares a request deadline with existing adapters. There is still one ToolExecutor, one registry and **six tools**. No new research tool, planner, agent runtime, document store or migration was introduced.

The workflow is:

1. Recognize explicit `/research <question>` or a sufficiently specific research/current-information phrase. Resolve existing calculator/app/system/memory intents first. Manual `/web`, `/read`, `/ask-web` remain their original operations.
2. Validate a printable question of 1–300 characters. Ask for a specific query when a reference such as “this” or “here” supplies no subject. Do not infer a subject from private prior turns.
3. Require **both** existing search and reading gates. Disabled research makes no network request and does not fall back to model guesses.
4. Prepare one bounded query from the current question only. Add a requested relative date where it fits, using the local/configured timezone.
5. Execute one `web.search` ToolRequest. Preserve actual provider and eligible explicitly enabled fallback behavior. Do not automatically retry or expand the query.
6. Rank the returned five-or-fewer candidates; bind the verified result set to the existing WebReader.
7. Attempt at most **five eligible source reads**, stopping after **three successful reads**. Each read is a `web.read` ToolRequest. A successfully retrieved page later excluded for date suitability still consumes a success slot. Failed/unsupported pages are skipped, not replaced by snippets.
8. If suitable extracted evidence remains, perform **one** local grounded-generation call, then apply the existing source/quote/numeric/version/status/claim checks. Model output cannot select more tools. No formatting correction or inference retry loop was added.
9. Save one completed user/assistant exchange using the existing SQLite transaction. Include validated citations, original retrieval/publication metadata and actual provider attribution in the displayed answer. On storage failure, clear uncommitted active evidence and do not repeat operations.

Natural examples supported include “AIKA, what's the latest stable Python version?”, “What's happening in the Philippines today?”, “Search for recent AI developments”, “Find the latest information about Ollama”, and “Compare the newest releases of Python and Node.js”. Other wording can use `/research` explicitly. This is bounded pattern recognition, not unrestricted language understanding.

## Routing and privacy boundaries

The existing memory intent parser takes priority over natural research recognition, including current-value/project questions and pronoun follow-ups. An initial regression caught a collision with “What's Orion's current frontend?”; the implementation was fixed without changing those memory tests. Personal/history markers and local measurement patterns are excluded from natural research. The legacy natural-search parser cannot bypass this exclusion: ConversationSession now uses it only for explicit `/web`; natural research belongs to the new guarded path.

Ordinary conversation, calculations, approved desktop launches, local system information, saved memory and archive queries keep their previous routes. `/research` explicitly authorizes researching its supplied text, but never attaches related saved facts, old messages, system measurements, private files or user documents. Queries containing recognized credentials are rejected by the existing search input boundary. Relative-date context is derived from the configured clock/timezone, not inferred personal location or conversation history.

Page text remains untrusted quoted data. A page asking to open Notepad, delete projects, reveal credentials or search elsewhere has no execution authority. The research branch can construct only the fixed search/read requests. Model output is validated answer data, never a ToolRequest or a memory instruction. No filesystem-management or desktop-action capability is added to research. Normal conversation persistence is the only application write associated with a research answer.

Research exchanges are excluded from future ordinary Ollama context, including after resume. Full extracted text remains bounded active-session state; it is not promoted to structured memory. `/history` and `/resume` never research, refetch or regenerate. Resume/new/clear discard full evidence and the transient last-run summary. Existing displayed answers retain their original URLs, provider label and timestamps.

## Source ranking and evidence suitability

Candidates must pass public HTTPS syntax/port/credential restrictions before a read attempt. Ranking does not perform DNS or fetch any page. It considers:

- Topic overlap in the supplied title, snippet and URL path, without using a snippet as answer evidence.
- Direct release/download paths and subject-specific publisher hints for Python, Node.js and Ollama; the canonical publisher's pages can outrank an unrelated first result.
- Available publication dates, a bounded recent-date preference, explicit requested-day matches and rejection of future-timestamp freshness bonuses.
- Small news publisher hints for AP and PNA, checked against their [AP topic page](https://apnews.com/hub/philippines) and [PNA landing page](https://www.pna.gov.ph/). These are nonexclusive ranking preferences, not an assertion of editorial truth or a network allowlist.
- Duplicate canonical paths/semantic query parameters, ignoring tracking-only differences. Requested URLs themselves are not rewritten for fetching.
- Supported formats and publisher diversity for news/comparisons, so three similar pages from one publisher need not displace another requested subject.

Owner-like domains such as `python.org.evil.example` receive no owner bonus. **No domain hint establishes trust or factual correctness.** Every selected URL still undergoes the existing real destination validation and exact quote/claim checks. Broad topics, synonyms and unconventional source layouts can remain difficult for these small deterministic heuristics; there is no vector index or hidden model planner.

In a comparison, subject coverage is checked against the actual read evidence; incomplete coverage receives a qualification rather than an invented comparison. Existing grounding instructions require separate source identities and acknowledgment of relevant disagreements. Programmatic citation/quote checks do not guarantee that the model noticed every disagreement or that all implications are entailed.

## Relative dates and news freshness

`AIKA_TIMEZONE=local` uses the operating system timezone. An explicit available IANA zone, such as `Asia/Manila`, is also supported. Windows declares a `tzdata` dependency; the tested installation already had **tzdata 2026.6**. Dates are computed at request time without hardcoded current dates. The temporal snapshot includes the local date, as-of timestamp, target day where relevant, timezone and a publication-versus-event reminder. It is supplied separately from the question so it does not contaminate topic matching.

For **today/yesterday news and events**, usable page evidence requires actual extracted publication metadata with a timezone, matching the requested local day and no later than the request's as-of time. Search-result publication hints cannot replace missing page metadata. Date-only, timezone-free, missing, old or future metadata cannot establish the requested local publication day. A UTC publication can cross midnight correctly when converted to the user's configured timezone. This policy may conservatively decline a useful site that omits suitable metadata.

Publication date is **not event date**, and retrieval time is **not publication time**. Even a matching article date cannot independently establish that the event occurred that day. Grounding instructions and final date qualifications state this. Software release/documentation questions may use undated pages, but their statements and recency are qualified rather than treated as independent proof of the globally latest/stable release. No dates, authors or freshness labels are invented.

## Security and finite resource policy

The guarded reader and extraction policy from Phase 4B-R are preserved: validated DNS answers, direct numeric connection pinning and peer matching, verified TLS/SNI, HTTPS/443 only, no IP literals/local/private/metadata-service destinations, at most two revalidated same-host redirects, no environment proxies, cookies, browser authentication, redirects across hosts, executable downloads, JavaScript, assets, crawler or auth/CAPTCHA/paywall bypass.

Limits remain 1 MiB HTML, identity encoding only, 12,000 extracted characters per page, bounded primary/fallback extraction, and the existing per-read DNS/connect/read inactivity and 15-second network budget. A single research request adds an overall **180-second default**, configurable from **30 to 300 seconds** with `AIKA_RESEARCH_TIMEOUT`. The existing model timeout still applies; each call uses the smaller remaining workflow allowance where appropriate.

The shared deadline is propagated through search client timeouts, guarded fetch budgets, provider fallback checks and the Ollama HTTP adapter. Checks occur before/after operations. No next AIKA tool/provider/model operation begins after expiry, and a model/native result returned too late is not published as a valid answer. The deadline scope resets on every completion, failure or interruption; later ordinary chat is unaffected.

This is **not hard process-level preemption**. DDGS's internal engine waves and thread shutdown can outlive the nominal deadline despite finite native timeouts; ContextVar state is not injected into the library's internal worker threads. HTTPX read-inactivity limits are not an absolute wall-clock interrupt against a trickling response, and parsing/extraction are input-size bounded rather than run in cancellable CPU workers. The reader retains its socket-shutdown timer; a stalled OS resolver can remain as at most one daemon lookup that cannot later connect. Those limitations are reported rather than hidden behind an exact-deadline guarantee. No new operation or billable secondary is initiated after the budget is known exhausted.

There are at most **six executor operations**: one search and five read attempts, plus at most one model-generation operation and its existing local availability/thinking probes. A search-router fallback can invoke a second provider only under the existing explicit opt-in; DDGS can contact several internal free engines during one provider operation. These are not claims of six low-level HTTP packets. No application retry, automatic query expansion or automatic paid retry was introduced.

KeyboardInterrupt ends the research attempt, clears active evidence and returns a controlled interrupted result while keeping chat usable. An already issued native request cannot be retroactively undone. No additional step follows interruption. SQLite failures do not retry the search, reads or generation.

## Provider/billing policy and failure diagnostics

DDGS remains the default keyless primary in auto mode. Tavily remains optional and uses its existing basic API profile. Its configured key alone never enables paid fallback. Configured explicit modes retain their no-switch behavior. Auto-mode fallback is still disabled by default and only eligible after the existing identifiable unavailable/timeout/rate-limit failures, with user opt-in. Ambiguous DDGS failures, literal empty responses, invalid input, malformed normalization and contract errors cannot silently trigger Tavily. Expired workflow budgets prevent a secondary request even when fallback was enabled.

The accepted answer records the **actual** search provider. When an explicitly enabled secondary supplies sources, the final reply identifies the transition instead of hiding potential paid usage. A `failure_category` optional field was appended to ToolResult for safe failure attribution; existing statuses/data and old constructor defaults remain compatible.

`last_research` is a bounded active-session summary: generated request ID, attempted/actual provider, candidates evaluated, attempted/successful/failed reads, usable evidence count, fixed failure categories, validation outcome, final outcome and elapsed milliseconds. `/web-status` displays a short last-run status. With `AIKA_WEB_DEBUG=on`, the terminal/logger receives the bounded summary after the conversation save succeeds or fails; storage failure is recorded accurately. No query, URL, source text, API key, memory fact, measurement, raw response, header or exception text appears in this diagnostic metadata. Full ToolResults/drafts are not logged.

The summary is intentionally transient, with optional logs; it is not a new persistent research database. Citation-bearing answers, provider labels and original timestamps persist through the existing exchange storage. Empty results, no eligible candidates, no usable evidence, model timeout/format rejection, budget exhaustion, interruption and storage failure have distinguishable outcomes. Failed or insufficient workflows never become pretrained guesses.

## Additional reliability repair found during Phase 4C

The first live attempt failed the search output contract. Investigation confirmed an independent deterministic defect: `_clean(value, limit)` normalized whitespace **before** truncation. If character 200 of a title or character 1,000 of a snippet was a space, slicing left trailing whitespace. The output validator applied `_clean` again, removed it, and rejected the normalizer's own output.

`_clean` now strips trailing whitespace after slicing, preserving the exact existing bounds and making normalization idempotent. Two regression cases reproduce the title/snippet boundaries and verify the real output contract. The first live raw provider response was not retained, so the precise row/field from that attempt is not retrospectively proven; the class of defect is confirmed and the next full live attempt succeeded. Other DDGS backend ambiguity is not claimed fixed.

## Files changed

| File(s) | Purpose |
| --- | --- |
| `src/capabilities/research.py` | Deterministic intent, query preparation, temporal rules, ranking, category filtering and safe summaries; no tool runner |
| `src/capabilities/web_budget.py` | Per-request shared deadline with guaranteed context reset |
| `src/intelligence/conversation.py` | Existing lifecycle owns the bounded research branch, state, progress and atomic final exchange |
| `src/capabilities/web_search.py` | Remaining-time client/fallback checks and truncation idempotency fix |
| `src/capabilities/web_reader.py` | Reuse existing guarded reads with a clipped shared budget; prior security/provenance retained |
| `src/capabilities/web_answer.py` | Separate temporal context, concise research rendering, literal AI/Philippine topic normalization; existing verification retained |
| `src/capabilities/contracts.py`, `src/capabilities/executor.py` | Optional safe failure category on the same ToolResult/ToolExecutor |
| `src/intelligence/ollama_client.py` | Clip existing local model/probe timeout to remaining research time |
| `src/config.py`, `src/cli.py`, `src/diagnostics.py` | New timeout/timezone configuration, `/research`, progress/status, phase label and no-request diagnostics |
| `pyproject.toml`, `.env.example` | Windows timezone data dependency and safe optional defaults |
| `tests/test_research.py` | New complete workflow, routing, ranking, privacy, dates, billing, limits, cancellation, persistence and contract regression cases |
| `tests/test_web_search.py` | Preserve legacy intent-query parsing and manual `/web` single-search behavior while natural requests now research |
| `tests/test_runtime.py`, `tests/conftest.py` | Current-phase assertion and isolated new environment settings |
| `README.md`, implementation roadmap, this report | Setup, accurate review status, design, walkthrough, evidence and limitations |

No existing user database, local secret `.env`, configured Ollama model, Phase 4B-R report or V1 file was changed. No new permissions or schema migrations were introduced.

## Automated verification

- Baseline: **872 passed in 28.15 seconds**.
- Focused memory/manual-web regressions after the routing correction: **154 passed in 3.39 seconds**.
- Intermediate full suite: **941 passed in 25.96 seconds** before final reference/privacy/outcome cases.
- Final focused research suite: **73 passed in 2.15 seconds**.
- Final full regression: **945 passed in 26.59 seconds, with no warnings**. All 872 pre-existing cases remain, plus 73 Phase 4C cases.

All 872 prior cases remain. The intentional behavior change is covered explicitly: natural research requests now use the workflow, while `/web` retains one search and no model/read call. Old natural-query parser cases are retained and their extracted queries are tested through manual `/web`; no memory regression tests were removed or weakened. All provider, HTTP, DNS, model and app boundaries in pytest are mocked or blocked by autouse fixtures. Tests consume no Tavily credits and depend on no live engine or current release.

New coverage includes the requested natural examples and `/research`; local memory/history/arithmetic/system/app/ordinary bypasses; both network gates; vague queries and private-context exclusion; DDGS indeterminate/empty/transient handling; opt-in paid fallback, explicit modes and expiry-before-paid-fallback; owner and deceptive-domain ranking; directness, diversity, freshness, tracking deduplication, unsupported formats; automatic guarded reads and final redirect URLs; private DNS with no socket connection; failures and alternate candidates; timezone midnight/yesterday/future and mixed publication metadata; missing dates preventing same-day model calls; conflicts and incomplete comparisons; strict citations/quotes/injection isolation; bounded steps, model timeouts and late results; keyboard interruption and context cleanup; transient diagnostics, SQLite failures and no resume/history replay; CLI progress; and the newly reproduced truncation contract defect.

## Actual live/CLI outcomes

All runtime writes used automatically cleaned temporary databases. Test sessions explicitly selected DDGS-only with paid fallback off and an empty Tavily configuration, regardless of local optional key presence. No live Tavily request, credit use or paid fallback occurred.

1. **First Python attempt:** `What's the latest stable Python version?` reached search but stopped on an output-contract failure, with no page/model operation. The truncation defect above was reproduced and repaired.
2. **Successful full automatic run after that repair:** the same single natural-language question searched DDGS, evaluated **five** candidates, securely read **three** pages and composed a validated answer using **qwen3.5:4b**. Search took about **1.83 seconds**; model/validation about **82.77 seconds**; total workflow **85.797 seconds**, within the 180-second budget. There was one search ToolRequest, three read ToolRequests, and one model generation, with no user-issued `/read` or `/ask-web`.
3. The answer attributed a security/maintenance-release statement to the actual Python release page and a release-list/date statement to the actual downloads page. One unsupported model claim was omitted. It did **not** assert that the sources independently proved today's globally latest stable version.
4. Actual cited final URLs were `https://www.python.org/downloads/release/python-3152/` and `https://www.python.org/downloads/`, with retrieval timestamps **2026-11-18T10:34:20.481920+00:00** and **2026-11-18T10:34:20.718635+00:00**. Publication metadata was unavailable and was reported as such. The release page's same-host redirect was handled by the preserved guarded reader. These are observed page statements, not independent current-release verification.
5. Resume preserved the displayed answer/history exactly and restored **zero** active full-text evidence records without any repeated search/read/model operation.
6. **Philippines news smoke:** `What's happening in the Philippines today?` prepared the local-date query but DDGS returned a controlled **indeterminate** provider error. The workflow stopped in **4.344 seconds**: zero reads, zero model calls, no retry or paid fallback. No current news answer was fabricated. A successful live same-day news answer is still unverified.
7. Actual `python -m aika`, `python -m aika doctor`, `python -m aika --version` and `python -m aika --help` each exited **0** against temporary storage. Doctor confirmed six registered tools, valid SQLite probing, installed qwen3.5:4b and research budget/timezone configuration. It made no source/provider requests. No desktop application was launched.

The final date/ranking/summary/privacy refinements after the successful Python smoke were covered by regression tests rather than repeatedly querying engines. The successful model run therefore demonstrates the implemented sequence and preserved validation; it is not a promise of deterministic answers or engine uptime for every future request. No final-code live comparison, live Ollama-updates/AI-news answer, fresh virtual-environment installation, paid fallback, source attack or desktop launch was attempted. Those execution/security/error cases use mocked tests or remain manual review items as stated.

## PowerShell manual acceptance

Use a dedicated shell and isolated storage; install the declared dependencies first. These variables are session-local examples and do not modify a user's existing database:

```powershell
python -m pip install -e '.[dev]'
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-4c-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_WEB_SEARCH_ENABLED = 'on'
$env:AIKA_WEB_READING_ENABLED = 'on'
$env:AIKA_WEB_SEARCH_PROVIDER = 'auto'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
$env:AIKA_RESEARCH_TIMEOUT = '180'
$env:AIKA_TIMEZONE = 'Asia/Manila'
python -m aika doctor
python -m aika chat
```

Enter:

```text
What's the latest stable Python version?
What's happening in the Philippines today?
Search for recent Ollama updates.
/research latest Python release
Explain how a Python dictionary works.
Remember that Orion uses SvelteKit for its frontend.
What's Orion's current frontend?
/web-status
/history
```

Research questions should show truthful progress and one final cited answer or a controlled verification limit. The ordinary explanation and saved fact must not invoke web research. Inspect final URLs, publication/retrieval distinctions and actual quotations using manual `/web`/`/read`/`/ask-web` as needed. A valid citation is not proof of perfect semantic support. Test a comparison with `Compare the newest releases of Python and Node.js.` and check separate source identities or an explicit coverage limitation.

Exit, then disable network access and restart:

```powershell
$env:AIKA_WEB_SEARCH_ENABLED = 'off'
python -m aika chat
```

Repeat the current-events question. Expect an explicit disabled/unverified response with no provider, page or model guess. Restore the gate only deliberately. A naturally occurring DDGS ambiguity or inaccessible source must produce a bounded failure/recovery, not an unlimited retry. Deterministic tests cover forced source/search failures without making artificial live failure traffic or consuming credits. `/web --provider tavily ...` remains a deliberate potentially billable manual choice only after configuring a key; no live paid acceptance was performed here.

Finally run `python -m pytest -q`. User review is required before changing checkpoint status.

## Remaining limitations and next checkpoint

- DDGS remains intermittently blocked/unparsed; exact upstream HTTP status is sometimes unavailable. Indeterminate failure is not an empty success or a paid-fallback trigger.
- Native deadline overrun limits described above remain; this is a bounded synchronous workflow, not a cancellation/process-isolation framework.
- Only five search results and three successful pages can contribute. Date failures can consume success slots; unsupported/cross-host/compressed/JavaScript/access-restricted pages are skipped honestly.
- Same-day news publication checks are deliberately strict. Missing/timezone-free dates and event/publication ambiguity may prevent a useful answer even when the topic is real.
- Small static ranking hints, keyword/topic matching and source diversity are heuristic, nonexhaustive and not trust certification. Natural intent patterns are conservative; ambiguous or unfamiliar wording can use `/research` explicitly.
- Exact quote, version, numeric, status and lexical validation improve traceability but cannot prove all semantic implications or detect every source disagreement; valid paraphrases can still be rejected. Source assertions are not independent factual verification or global freshness proof.
- Full source text and run summaries do not survive restore; saved citation-bearing answers do, without network replay. Storage failure can occur after an authorized provider operation and is never silently retried.
- Live same-day news, multi-source software comparison and optional Tavily/fallback acceptance remain pending. Existing data and paid settings were not altered to make a smoke test pass.

**Next planned milestone:** Phase 5 — Controlled Agent Planning, only on a new instruction. It has not been started.

**Final status: READY FOR MANUAL REVIEW.**
