# Phase 4B-R — Web Reliability & Stabilization

**Status: READY FOR MANUAL REVIEW. User acceptance is pending; this checkpoint is not marked PASSED.**


**Grounded-answer reliability follow-up:** The latest local implementation has accepted real-page `/ask-web` answers with qwen3.5:4b in 29.61 and 40.47 seconds, with source-limited freshness wording. See the follow-up section below. Earlier failed smoke outcomes remain historical evidence; they are not the final grounding result. A fresh live DDGS search in this follow-up failed, so the supplied Python.org URL was fetched explicitly by the diagnostic harness rather than fabricating a search result.

Date: 2026-11-18. Scope: stabilize the existing manual search/read/answer pipeline only. No automatic research, Phase 4C/5 implementation, new database, browser automation, desktop UI, Git commit or push.

## Inspection and preserved architecture

Read the foundation and implementation roadmap, Phase 4A/4B reports, relevant adapters, normalizer/output contracts, guarded reader, extraction, answer validation, Ollama client, configuration, ConversationSession, ToolExecutor, CLI, and tests. The actual pre-edit baseline was **791 passed, 1 warning in 31.66 seconds**, Python 3.12.10 on Windows.

There is still one ConversationSession, ToolExecutor, registry and SQLite/memory lifecycle. The registry retains its six tools. `/web`, `/read`, `/ask-web`, manual source selection, ephemeral full-text evidence, transcript persistence, history/resume isolation, explicit network gates, source limits and permission rules remain. Neither source text nor model output can initiate a tool, memory operation, search or desktop action. Tavily mode/fallback safeguards are unchanged. No existing user database was opened for manual acceptance; all runtime writes used automatically cleaned temporary directories.

## Findings, root causes and repairs

| Observation | Evidence and cause | Repair / remaining uncertainty |
| --- | --- | --- |
| Generic execution/validation failure | The executor evaluated `output_contract(handler(arguments))` in one try block, so unexpected handler errors and contract errors received the same message. Search normalization serialized native optional metadata before validating its types, and passed huge integers to `math.isfinite`; deterministic regression fixtures reproduce TypeError/overflow paths. | Separate handler and output-contract phases for web tools. Normalize supported scalar fields before serialization, ignore malformed optional metadata, and check score range before finite conversion. Invalid lists/oversized/unusable results fail specifically as normalization errors. The exact cause of the user's original valid-query failure was **not reproduced live**, so these are confirmed code defects and diagnostic improvements, not proof that every original occurrence had the same cause. |
| Ambiguous DDGS failure | Live probes reproduced the existing `No results found.` ambiguity. DDGS still hides some engine rejection/parser outcomes. | Retain an unsuccessful indeterminate outcome, no fabricated empty success, no automatic retry and no billable fallback for that ambiguity. External DDGS reliability is not claimed fixed. |
| Wikipedia extraction failure | The checked public Python Wikipedia page downloaded **1,031,609 bytes** and primary Trafilatura extraction produced **75,191 characters** before the 12,000-character evidence cap. Its reported failure was not reproduced. The previous extraction wrapper collapsed import, parse/sanitization and primary-extractor exceptions into one generic message. | Distinguish dependency, parsing, primary/fallback and no-readable-text failures. Keep Trafilatura primary and use a bounded local HTML fallback after primary failure/empty output. Do not claim an established Wikipedia-specific root cause. |
| Redirecting sources rejected | Phase 4B deliberately rejected every redirect; the real Python `/downloads/latest/` URL redirects to a release-specific page on the same hostname. | Support at most two manually handled same-host HTTPS redirects with fresh address validation/pinning and verified TLS for every connection, one deadline and body budget, loop detection, accurate requested/final URLs and immutable chain provenance. |
| Model timeout / no accepted answer | An actual cold completion took **74.38 seconds**, including approximately **14.17 seconds** loading and **57.59 seconds** decoding 266 tokens. The earlier temporary 45-second smoke timeout was shorter than that workload. A later schema-constrained warm completion took **35.26 seconds** and was rejected for `numeric_support`, rather than timing out. | Preserve the configured **180-second** model timeout. Distinguish timeout/unavailability; add fixed-label timing/rejection diagnostics. Grounded CLI calls use Ollama JSON schema output and a 768-token output cap, with quote-first composition instructions and unchanged quote/citation/numeric checks. No hidden repair retry or guessed answer. A complete accepted live answer remains **unverified**. |

## Search failures and safe opt-in diagnostics

`AIKA_WEB_DEBUG=off` is the default. Enable it explicitly in `.env` or the process environment and restart to receive fixed stage, outcome, rejection-reason and elapsed-time labels through the `aika.web` logger. `/web-status` shows this setting. Accepted stage labels include provider, normalization, contract, internal, retrieval, extraction and grounding. Grounded rejection reasons are fixed categories such as numeric support, claim support, schema shape and JSON syntax.

Logs never contain query text, source URLs, HTML, snippets, credentials, headers, exception messages, stack traces, model drafts, memory or desktop data. Provider library request logs remain suppressed. No raw body or exception text is inserted into a debug event. Diagnostics are not sent to Ollama or stored as conversation content. Failures remain unsuccessful ToolResults with the existing status/data behavior; typed exceptions carry internal stage information without changing the ToolResult schema. Normalization/contract/internal errors never trigger a paid secondary.

DDGS remains keyless and primary in auto mode. Tavily remains optional, explicitly selected or separately opted into as fallback for the existing identifiable eligible failure categories. An empty list is a real no-results response; indeterminate DDGS failures are not successful empty lists. Status/doctor still make no provider/source requests. No provider upgrade, added provider, retry loop or anti-bot workaround was introduced.

## Guarded redirects, budgets and provenance

The redirect policy follows the existing pinned HTTPS mechanism and [OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html). It supports only 301/302/303/307/308, no more than **two redirects / three total connections**. Relative Locations are resolved against the current URL, then canonicalized and checked again. Each hop must use HTTPS, port 443, the same exact canonical hostname, no credentials, no fragment, no direct IP literal and no unsupported/local hostname. Cross-host transitions, malformed or missing Locations, credential-bearing locations, loops and excess hops stop before connecting to the target. The configured Tavily secret is also checked against decoded redirect URLs.

Every connection resolves DNS again, validates **all** returned addresses, and rejects mixed/nonpublic/private/link-local/special-use answers. It connects directly to the validated numeric sockaddr, checks the connected peer IP/port matches that destination, and verifies TLS/SNI against the original hostname. It does not perform a second hostname lookup during connection. A public-to-private DNS change at a redirect is rejected; tests exercise this explicitly. Cookies, authorization and Referer are never forwarded; environment proxies are ignored. No authentication, CAPTCHA, paywall or website restriction is bypassed.

All hops share the same **15-second** deadline and socket-shutdown timer; remaining time is checked before opening/using the next connection. DNS/connect and read inactivity limits remain 3/5 seconds. Redirect bodies are **not downloaded**, so intermediate responses cannot reset or multiply the single **1 MiB HTML body budget**. Final bodies retain size, transfer-framing, encoding, MIME, attachment and incomplete-response checks. Compression is rejected rather than decompressed. The standard library separately bounds HTTP headers; the body cap is not a claim of an exact raw-wire byte cap including headers/TLS overhead. Native OS scheduling and a stuck daemon resolver remain documented limits; at most one OS DNS lookup can remain pending, and it cannot connect later.

Evidence now records the original requested URL, actual final URL, validated redirect chain (up to three distinct URLs), original selected result, source ID, retrieval timestamp and extraction method. The output contract checks all chain endpoints, exact same-host HTTPS policy, original search attribution, allowed extraction methods, bounds and metadata. Grounded citations use the **final fetched URL**; the preview also shows the requested URL. Existing nonredirected evidence remains valid. Full evidence is still active-session state only; saved displays retain their original metadata without refetching on history/resume.

## Extraction fallback

Trafilatura remains primary. No dependency or downloader was added. The [Trafilatura extraction API](https://trafilatura.readthedocs.io/en/latest/corefunctions.html) receives only already retrieved, sanitized lxml HTML parsed with network access disabled. Metadata extraction and executable-element removal remain separate from the primary call.

The primary operates on a copy: a failed or mutating extractor cannot damage the clean tree used by fallback. Fallback is a deterministic traversal of semantic main/article content or document paragraphs/headings/list items, with navigation/header/footer/aside/dialog/banner removal. Navigation-only fragments, empty/too-short text and obvious challenge titles are rejected. Fallback stops collecting near the existing **12,000-character** limit, then applies the same control-character sanitation, credential redaction and truncation indicators. It does not use a search snippet, fetch assets, execute markup, call another website or infer missing publication dates. `extraction_method` distinguishes `trafilatura` and `html_fallback` in previews and evidence.

Fallback is intentionally conservative. It can include incidental static page text or reject a useful unconventional layout. A successful extraction is evidence of page text, not that an article is complete, trustworthy or semantically relevant. Access-denied HTTP responses are rejected before extraction; fallback cannot bypass server-side restrictions.

## Grounding and local-model behavior

The same configured Ollama client handles both ordinary and grounded chat. Only grounded CLI composition adds a bounded JSON response schema and `num_predict=768`, through an injected callback to the existing session. Ordinary requests retain their prior options. [Ollama's structured output API](https://docs.ollama.com/capabilities/structured-outputs) supports the schema in the `format` field. No model, thinking policy, configured timeout or architecture was silently replaced.

Source IDs, actual quotations, numeric support, bounded prompts and visible citations remain mandatory. A JSON-only fenced response may be parsed, but surrounding prose, invented IDs/URLs/quotes and unsupported numeric strings remain failures. The prompt asks for a quote first and requires version/date strings to occur unchanged in that same quote. There is exactly one model call per `/ask-web`; no automatic correction attempt, fetch or search follows a rejected draft. The actual latest prompt change could not be live-validated because the subsequent DDGS searches failed before source selection/model generation.

The checks establish traceability and catch specific inconsistencies, **not perfect semantic entailment**. They may reject a valid date paraphrase, and a weak claim can still pass simple lexical checks. A completed model response is not an accepted grounded answer until validation passes. The observed numeric-support rejection is reported as such, not converted into success or a timeout.

## Files modified

| Files | Change |
| --- | --- |
| `src/capabilities/web_diagnostics.py` | New fixed-label opt-in recorder and typed web failure categories |
| `src/capabilities/executor.py` | Separate web execution and output-contract failure handling; opt-in diagnostics |
| `src/capabilities/web_search.py` | Safe optional metadata normalization and categorized provider/normalization failures |
| `src/capabilities/web_reader.py` | Bounded same-host redirects, shared budgets, peer checks and provenance validation |
| `src/capabilities/web_content.py` | Immutable method/chain metadata, stage-specific errors and safe local fallback |
| `src/capabilities/web_answer.py` | Schema, quote-first prompt, fixed rejection diagnostics, bounded fenced-JSON parsing |
| `src/capabilities/web_read_intent.py` | Show requested/final URLs, redirect count and extraction method |
| `src/intelligence/conversation.py` | Reuse the same session with optional grounded-generation callback/debug wiring |
| `src/intelligence/ollama_client.py` | Safe timeout category and optional grounded format/output cap |
| `src/config.py`, `src/cli.py`, `src/diagnostics.py` | Explicit debug gate, status, runtime inventory and existing-client wiring |
| `tests/test_web_stabilization.py` | New reliability, SSRF/redirect, fallback, privacy and adapter regression cases |
| `tests/test_web_reading.py`, `tests/conftest.py` | Preserve prior cases with updated provenance/error/fallback expectations and debug isolation |
| `.env.example`, `README.md`, `docs/AIKA_V2_IMPLEMENTATION_PHASES.md`, this report | Setup, policy, accurate review status and actual outcomes |

The ignored local `.env`, configured model/timeouts, existing user databases, foundation specification, permission categories and registry tool count were not changed by this checkpoint.

## Automated verification

- Baseline: **791 passed, 1 warning in 31.66 seconds**.
- Focused existing provider/reader suite after core changes: **317 passed, 1 warning in 4.63 seconds**.
- Focused stabilization/reader/model/executor suite: **301 passed, 1 warning in 4.51 seconds** before the final navigation-fragment case.
- Intermediate full suite: **836 passed, 1 warning in 24.26 seconds**.
- Final complete suite: **837 passed, 1 warning in 29.89 seconds**. All 791 pre-existing cases remain, plus 46 stabilization regression cases.

The warning is the existing optional urllib3 SOCKS/PySocks capability warning during Trafilatura import. The reader uses no proxy or urllib3 downloader. No dependency was added to silence it.

All pytest HTTP/DNS/Ollama/provider operations are mocked or blocked by the existing autouse fixtures. Tests consume no Tavily credits. Previous cases were retained; prior extraction-failure tests now explicitly make both primary and fallback fail, while new cases verify fallback success. Tests cover malformed/native optional metadata, huge numeric scores, execution versus contract errors, opt-in/private diagnostics, provider isolation, relative/absolute same-host redirects, cross-host/HTTP/port/IP/credential rejection, loops/hop limits, per-hop DNS rebinding and peer matching, one time/size budget, fallback sanitization and mutation isolation, challenge/navigation rejection, timestamps/source identity, numeric/citation failures, configured timeouts and ordinary-model isolation. The earlier memory, calculator, Windows apps/system information and persistence regressions remain in the complete suite.

## Actual live checks and remaining acceptance gap

Live testing was limited to public diagnostic queries and pages, with **no Tavily requests or paid fallback**. There were six deliberate DDGS operations across diagnosis and changed-code smoke checks: three returned usable results and three returned controlled indeterminate errors. These were manual test invocations, not application retry logic. After the final two ambiguous failures, live engine queries were stopped.

1. The checked Python Wikipedia page downloaded within the byte limit and extracted using Trafilatura. The reported Wikipedia-specific failure was not reproduced.
2. Actual `latest Python release` search returned five sources. `/read 1` followed the one same-host redirect from `https://www.python.org/downloads/latest/` to `https://www.python.org/downloads/release/python-3152/`, verified TLS and extracted static page content. Requested/final URLs and source identity were displayed correctly. The observed release text is a page statement, not an independent assertion about current releases.
3. One actual answer-generation run completed in 74.38 seconds but did not pass grounding. An actual CLI run with JSON schema output completed in 35.26 seconds and was rejected specifically for numeric support. Neither draft was printed as a valid answer. The configured timeout was 180 seconds throughout these checks.
4. After the quote-first prompt refinement, both subsequent search attempts failed indeterminately. `/read` required a successful active search and `/ask-web` required read evidence. They made no extra provider, page or model requests. A complete successful **live search → read → accepted grounded answer** has therefore **not been demonstrated** in this checkpoint.
5. Resume/history preserved the displayed exchanges and cleared extracted evidence without network replay. The actual CLI was also exercised with explicit commands; no automatic research command was introduced.
6. Actual startup, doctor, version and help subprocesses all exited **0** against isolated temporary storage. Doctor confirmed six tools, SQLite probe validity, installed `qwen3.5:4b`, and reader/extraction readiness without source/provider calls.

No live cross-host/private-network attack, certificate failure, oversize stream, paywall bypass, desktop app launch, Tavily authentication, fresh virtual-environment install or successful live multi-source answer was attempted. Security/failure and multi-source cases use mocks. No raw model draft or HTML was written to logs or this report. Temporary stores were cleaned automatically.

## Manual acceptance commands

Install the existing declared dependencies, enable both network gates in the project `.env`, and optionally enable `AIKA_WEB_DEBUG=on`. Leave paid fallback off. Use isolated storage:

```powershell
$env:AIKA_DATA_DIR = Join-Path ([IO.Path]::GetTempPath()) ('aika-4br-review-' + [guid]::NewGuid().ToString('N'))
$env:AIKA_WEB_SEARCH_ENABLED = 'on'
$env:AIKA_WEB_READING_ENABLED = 'on'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
$env:AIKA_WEB_DEBUG = 'on'
python -m aika doctor
python -m aika chat
```

```text
/web-status
/web --provider ddgs latest Python release
/read 1
/ask-web What release does the selected page identify?
/history
```

Inspect the requested/final URL and extraction method. If DDGS fails, expect an honest failure and no paid request. If the result is cross-host/inaccessible/unsupported, explicitly select another returned source; the application must not do it automatically. An accepted answer must have a real read-source ID, inspectable exact supporting quote and final URL. A rejected draft or model timeout is not acceptance. Resume and verify that old displays remain unchanged but new grounded answers require explicit fresh search/read evidence. Recheck calculator, memory, system information and approved application commands as desired, then run the complete suite.

**Remaining risks:** external DDGS blocking/parser ambiguity; unconfirmed original generic-query and Wikipedia-specific triggers; unsupported cross-host/compressed/JavaScript/access-restricted pages; conservative or imperfect extraction/claim validation; OS/network trust and timing limits; and the outstanding full live grounded-answer acceptance. The configured inference budget was not increased to conceal slow local decoding.

**READY FOR MANUAL REVIEW — not PASSED.** Phase 4C and Phase 5 remain unimplemented.


## Grounded-answer reliability follow-up — 2026-11-18

**Status: READY FOR MANUAL REVIEW, not PASSED.** This follow-up changes grounding reliability only and preserves the local redirect/extraction improvements. The actual workspace, reports and tests were inspected; no GitHub checkout/reset was used. All pre-existing local work was retained.

### Precise reproduced failure

Baseline before this follow-up: **837 passed, 1 warning in 26.84 seconds**.

A live DDGS `/web --provider ddgs latest Python release` attempt failed indeterminately. The application correctly rejected `/read 1` without an active successful search and did not spend Tavily credits or call Ollama. To investigate the reported answer failure independently, a diagnostic harness explicitly fetched the exact public URL supplied in the user's observed test through the existing guarded HTTPS fetcher:

```text
https://www.python.org/downloads/release/python-3152/
```

Trafilatura extracted **2,778 characters**, containing `Python 3.15.2`. The resulting bounded public evidence and temporary conversation database were used only for this isolated diagnostic; no new search result/provider attribution was invented. This is a live page-and-model acceptance check, not a claim that a new DDGS search succeeded. The production app still accepts reading only from its active verified search set.

The pre-fix qwen3.5:4b completion took **33.06 seconds**. Privacy-safe inspection of its structure established:

- It returned two claims with existing numeric source IDs.
- Both quotes occurred in the read page and in the selected evidence.
- The first claim contained one numeric string absent from its own supporting quote, although present elsewhere in the page.
- The second claim had no numeric mismatch. The old early return never reached its remaining validation.
- The rejection was `numeric_support`, not malformed JSON, absent `Python 3.15.2`, failed extraction, source-ID mismatch, or a timeout.

The root reliability defect was **all-or-nothing validation**: one unsupported claim immediately discarded the whole draft. The unsupported first claim should still be rejected; it should not prevent independently supported claims from being evaluated. Related confirmed code defects were arbitrary 600-character chunk boundaries and a final `[:2400]` slice that could cut evidence mid-word/sentence, generic rejection labels, and a lexical rule that rejected concise version-only paraphrases lacking the same filler words as the source. The exact raw model draft was not logged or persisted.

### Implementation

1. **Independent claim validation.** Validate every claim against its own real read-source ID, actual selected quotation, numbers/versions and content. Omit invalid claims; display only those that pass. If all claims fail, return controlled insufficient evidence. A partial answer says only supported statements are shown. This is not a correction attempt, a new model call or acceptance of unsupported numeric detail.
2. **Original-text passage selection.** Rank original paragraph/sentence spans by question topic, exact requested versions, release/version indicators and dates. Preserve offsets and whitespace, merge adjacent selected spans using the actual source substring, and select only complete units that fit the 2,400-character budget. Overlong units are split at word boundaries; an overlong individual token is skipped. No final blind slice truncates the last selected passage. Four units and the existing 15,000-character overall prompt cap remain.
3. **Conservative topic isolation.** Exclude sources with no topic-word overlap when the question names a topic; an unrelated Philippines-news question cannot use the Python release page. Generic follow-ups such as `Which version?` can use active evidence. Claim support is still checked against its own source, not a merged pool. This lexical filter is deliberately small and may reject synonyms or translated topic names; no embedding/RAG system was introduced.
4. **Exact quote resolution.** Require a quote from both the read document and selected passages. Whitespace-only copying differences may resolve back to an actual verbatim source substring; punctuation, words, version strings and unsupported ellipses are not repaired. Rendering uses that resolved original quotation. A real but unselected quote remains rejected as `quote_not_selected`.
5. **Supported paraphrases and numeric/status safety.** Generic reporting words do not cause rejection of a concise `Version 3.15.2` paraphrase. Numeric strings and complete version identifiers, including prerelease suffixes, must occur in that claim's supporting quote. Clearly unrelated predicates and status assertions such as stable/beta/security/maintenance absent from the quote are rejected. Explicit negative status wording cannot be summarized as positive. These remain conservative checks, not a general proof of semantic entailment.
6. **Freshness scope.** The prompt and rendered answer distinguish a page's release statement from globally latest/current facts. An unsupported global freshness inference is replaced by the validated source passage, and freshness questions receive an explicit qualification. A page identifying a maintenance release is not automatically proof of current stable status or global freshness.
7. **Stable citations.** IDs are never renumbered after relevance filtering. Final URLs and retrieval/publication timestamps are attached by code from the immutable evidence snapshot supplied to the model. Draft URLs and invented IDs are rejected. Existing `source`, `quote`, `text` JSON schema, configured qwen3.5 model, token cap and 180-second configured timeout remain unchanged. Ordinary chat uses its existing model path.
8. **Explicit formatting and diagnostic errors.** Malformed JSON produces a controlled `[malformed_json]` message without exposing draft content or an internal exception. Other model-format/claim failures use fixed categories. The opt-in `aika.web` log distinguishes individual `claim_rejected` events from complete `draft_rejected` and successful answers. There are no hidden model retries, provider calls, page fetches, memory writes or desktop actions during `/ask-web`.

### Machine-readable categories and privacy

With `AIKA_WEB_DEBUG=on`, logs include fixed `stage`, `outcome`, `reason`, and elapsed milliseconds. Current grounding reasons include:

```text
malformed_json
missing_quote
quote_not_found
quote_not_selected
unsupported_number
source_mismatch
insufficient_evidence
model_timeout
model_unavailable
invalid_claim
unsupported_claim
```

No prompt, page content, quote text, URL, private question, raw model response, configured credential, numeric value from the draft, traceback or exception message is placed in diagnostic logs. Malformed JSON handling and model timeout/unavailability remain controlled. Debug remains off by default. Model prompts receive only the question and selected read-source metadata/passages; unrelated chat, structured memory and desktop measurements remain excluded. Successful/failed web exchanges are still excluded from future ordinary model context. Citation validation does not establish perfect semantic entailment or independent factual verification.

### Optional urllib3 warning

Inspection of the installed `urllib3.contrib.socks` module confirmed the known `DependencyWarning` is emitted when its optional `socks` import is unavailable; that module then raises ImportError, which the extraction dependency's optional downloader import handles. AIKA's reader does not use that downloader or SOCKS transport.

Only the known warning is suppressed, and only around the lazy Trafilatura import, by matching all three of: `DependencyWarning` category, exact optional-PySocks message prefix, and module `urllib3.contrib.socks`. A test verifies that a different dependency warning in the same module and the same message in another module still surface. No global warning suppression, PySocks dependency or proxy support was added. A fresh process with `PYTHONWARNINGS=always` successfully extracted HTML with **no PySocks warning and no other stderr**.

### Tests and actual live acceptance

- Baseline: **837 passed, 1 warning in 26.84 seconds**.
- Focused grounding/reader/stabilization intermediate suite: **199 passed in 9.70 seconds**, before six additional predicate/snapshot cases.
- Complete intermediate regression: **872 passed in 26.33 seconds**, no warning summary.
- Final complete regression: **872 passed in 35.33 seconds, with no warnings**. All 837 prior cases remain, plus 35 new cases.

All 837 prior cases remain, plus **35 new grounding/warning cases**. The existing malformed-output test now expects its explicit controlled JSON-format message. Redirect, DNS pinning, SSRF, TLS, extraction fallback, DDGS/Tavily, calculator, memory, app/system, persistence and injection regression cases are preserved. Tests mock model/network operations and consume no credits.

The live model checks reused the bounded public evidence from the guarded diagnostic fetch; no additional website search or fetch was performed per question. The real configured model adapter, its structured-output schema and the existing `ConversationSession.reply` lifecycle handled these commands:

```text
/ask-web What is the latest Python version?
/ask-web What is the latest Philippines news?
```

First accepted real-model run: **29.61 seconds**. Final accepted run after the added status/predicate guards: **40.47 seconds**. Both displayed this supported statement:

> The page identifies Python 3.15.2 as a maintenance release of Python 3.15.

Both attached source **[1]**, the final Python.org URL, the actual retrieval timestamp **2026-11-18T09:19:03.017094+00:00**, and the original supporting page passage. Both explicitly stated that the read pages do not independently establish the latest version/current state today. No publication date was invented. The quotation in the rendered answer comes from extracted evidence, not the earlier search snippet or pretrained model knowledge.

The Philippines-news question returned insufficient evidence with `reason=insufficient_evidence` **before calling Ollama**. History/resume preserved the completed displays and cleared active full-text evidence without refetching. Actual startup, doctor, version and help subprocesses exited **0** with isolated temporary storage. Source-data/model-draft logs were never enabled. Temporary diagnostic evidence and SQLite files were removed after verification; existing user data was not modified.

### Files changed in this follow-up

- `src/capabilities/web_answer.py`: span selection, topic isolation, independently validated partial claims, exact quote resolution, version/status checks, qualified freshness, snapshot citations and controlled errors.
- `src/capabilities/web_diagnostics.py`: explicit safe grounding categories and individual-claim rejection outcome.
- `src/capabilities/web_content.py`: narrowly scoped optional warning suppression only; redirect and extraction logic preserved.
- `tests/test_grounded_reliability.py`: 35 new cases covering the requested release/news, formatting, citation, version, status, passage, privacy, warning and snapshot scenarios.
- `tests/test_web_reading.py`: explicit malformed-JSON message assertion, with all prior failure cases retained.
- `README.md`, this report: current behavior, diagnostics, verification evidence and remaining limits.

### User walkthrough and remaining limits

Enable the existing search/reading gates, optionally `AIKA_WEB_DEBUG=on`, and leave paid fallback off. In an isolated conversation:

```text
/web latest Python release
/read 1
/ask-web What is the latest Python version?
/ask-web What is the latest Philippines news?
/history
```

Expect a source-limited version statement with real quotation, URL and retrieval time when supported. Expect insufficient evidence for the unrelated news question; no implicit search should follow it. An invalid claim must never become an accepted citation. After resume, explicitly search/read again before a new grounded answer.

External DDGS intermittency remains. This follow-up's new DDGS search failed, so a fresh successful search/read/answer chain was not claimed; the accepted `/ask-web` checks used a real guarded fetch of the user's supplied previously read URL. No live Tavily request, paid fallback, successful multi-source live comparison, fresh dependency installation or desktop launch was performed. Topic/lexical/status checks remain conservative and cannot guarantee all natural-language implications are supported. A model can still return no usable claim; the app must fail honestly rather than guess or retry silently. Exact date reformatting, paraphrases with no shared content terms, and translated topic names may be rejected.

**READY FOR MANUAL REVIEW — user acceptance is still pending. No Phase 4C/5, commits or pushes.**
