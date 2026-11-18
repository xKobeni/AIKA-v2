# AIKA V2 Phase 4B — Source Reading & Grounded Answers

**Status: READY FOR MANUAL REVIEW**  
**Date:** 2026-11-18  
**Scope:** The user-directed Phase 4B request, including bounded answer composition. No Phase 5 planning, autonomous research, commits, tags, or existing user-database changes.

## Implementation and architecture

Inspected the foundation specification, implementation phases, Phase 4A report, hybrid adapters and normalization, tool contracts/executor, configuration, Ollama client, conversation lifecycle, SQLite exchange persistence, and tests before editing. The planning baseline separated retrieval and later research conversations; this request explicitly includes selected-source answering within Phase 4B. No autonomous research workflow was added.

The existing `ConversationSession.reply` remains the only lifecycle. The registry now has six tools: the five previous tools plus `web.read`, READ_ONLY. `SearchRouter`, DDGS/Tavily mode selection, opt-in fallback, and provider error handling are unchanged. Source reading is independent of search-provider choice and cannot spend Tavily credits. Grounded synthesis uses the same configured Ollama `generate` callback, with no tool interface or independent executor.

`WebReader` holds the active search-result identities and up to three frozen `SourceEvidence` records. Its tool accepts only a source number, never a URL argument. After a verified `web.search` exchange is saved, the session installs that bounded result set. A new search attempt clears prior evidence, even if the search fails; an empty result set permits no reads. A failed storage write does not publish new search selection or read evidence. Numbers match the displayed result order, including when invalid provider rows were discarded earlier.

Commands are `/read <number>` and `/ask-web <question>`. Natural alternatives include `Read source 1.`, `Read the first result.`, and `Open and summarize source 2.`. The latter displays the same concise extracted preview; it does not initiate a model/tool loop. Invalid or missing selections produce controlled messages. Reading a source already in the active evidence set returns its previous evidence and retrieval timestamp without another network request. A fourth distinct source is rejected until a new search.

## Network gate and destination security

Both `AIKA_WEB_SEARCH_ENABLED` and the new `AIKA_WEB_READING_ENABLED` must be enabled to fetch. The new gate defaults to off and was appended, without exposing or replacing existing local credentials, to `.env` and `.env.example`. Process-environment overrides retain priority. `/web-status`, `/tools`, and doctor expose reading configuration without fetching.

The [OWASP SSRF prevention guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) informed destination and redirect controls. URL string checks alone are insufficient. This reader binds destination validation to the actual socket connection:

1. Accept only public HTTPS hostnames, on port 443, from the current verified search set. Reject direct IPv4/IPv6 literals, credentials, fragments, local/internal/single-label hostnames, malformed URLs, alternate schemes, and unexpected ports. HTTP URLs are rejected, never upgraded.
2. Resolve with `getaddrinfo` for TCP/443. Validate **every** returned address before opening a socket; a mixed public/private response is rejected. Block nonpublic, loopback, private, link-local, shared, multicast, reserved, unspecified, known special-use/transition/NAT64 ranges, and the Azure platform virtual address. A conservative explicit denylist supplements Python 3.12 `ipaddress` classifications.
3. Connect a raw socket to the validated numeric sockaddr directly. It never re-resolves the hostname, so a DNS answer changing after validation cannot redirect this connection to a newly resolved private address. Only the first validated address is attempted; no retries or automatic alternate-address attempts.
4. Wrap with `ssl.create_default_context()` using the original hostname for TLS SNI and certificate verification. Send the HTTP Host for that hostname. Verification is never disabled.

### Transport decision

HTTPX remains the search/Ollama stack. Its normal high-level transport would resolve the hostname again after a separate validation check. For the page reader, a small standard-library `HTTPSConnection` subclass pins the numeric destination while retaining normal verified TLS and bounded streaming HTTP/1.1. This avoids depending on HTTPX/httpcore private connection-pool APIs or adding a second HTTP framework. [Python's HTTPSConnection documentation](https://docs.python.org/3.12/library/http.client.html#http.client.HTTPSConnection) describes its verified TLS support. Tests check the actual numeric `socket.connect` argument, single resolution, original TLS hostname, and verified context.

There are no environment proxies, browser sessions, cookies, authorization headers, Tavily credentials, JavaScript, asset requests, recursive requests, extraction-library download calls, or redirects. All 3xx outcomes fail before reading a body; Location is never followed. Authentication failures, 403/404/429/5xx, attachment dispositions, unsupported MIME types/encodings, and ambiguous transfer framing fail with bounded fixed errors. Websites' restrictions, CAPTCHAs and paywalls are not bypassed.

## Resource limits

| Resource | Bound |
| --- | --- |
| Sources per active search | Three explicitly selected pages |
| DNS wait / TCP connect / TLS socket inactivity | 3 seconds |
| Response-read inactivity | 5 seconds |
| Network-operation budget | 15 seconds, deadline checks plus a socket-shutdown timer |
| Downloaded HTML | 1 MiB, streamed; Content-Length and observed body size checked |
| Decompression | Unsupported: require identity encoding, reject compressed responses |
| Extracted content | 12,000 characters per page, with truncation flag |
| Reading preview | 400 content characters plus bounded metadata |
| Question | 1–500 printable characters |
| Evidence sent to model | Up to 2,400 characters per source; deterministic relevance-ranked blocks |
| Model prompt / accepted draft | 15,000 / 8,000 characters |
| Answer | Up to four short supported claims and visible supporting quotes |

A timer interrupts the connected socket even when `http.client` has detached it into a response file. Byte accounting rejects streamed overflows and known-length partial responses. No partial download is substituted for a successful page. Parser work is bounded by input/text limits rather than a separate hard CPU cancellation mechanism. The DNS worker is daemonized and limited to one pending OS lookup per process: a timed-out resolver cannot connect later, and repeated requests fail closed while it remains pending. OS scheduling can delay timers; these budgets are application controls, not hard real-time guarantees.

## Extraction and provenance

Evaluated and installed Trafilatura 2.3.1; the project declares `trafilatura>=2.1,<3`. [Trafilatura's core extraction API](https://trafilatura.readthedocs.io/en/latest/corefunctions.html) accepts already retrieved HTML/parsed trees. The adapter passes only an inert lxml tree parsed with network access disabled, never a URL downloader. Scripts, styles, templates, forms, iframes, objects and executable/embed markup are removed first. It favors precision, excludes comments/images/links, and uses fast local extraction. Process-wide deduplication is disabled: it otherwise discarded repeated content when reading a second similar page. No global document cache was added. Library log text is suppressed to avoid exposing page excerpts.

Page title comes from the actual HTML title. Publication dates are accepted only from explicit publication metadata (`article:published_time`, `datePublished`); no date, author, current release, or prior search snippet is invented. Missing metadata remains unavailable. Empty/static-unreadable/extraction failures produce errors, including when JavaScript or access restrictions may be responsible. HTML text and terminal controls are sanitized; known Tavily secrets are redacted.

Frozen evidence records preserve the original selected search result as immutable JSON, source ID, requested and actual fetched URL (identical because redirects are disabled), domain, page title, bounded text, actual UTC retrieval timestamp, extraction success, optional publication date, and truncation. Output validation checks identity, URL/domain, original search attribution, timestamps, lengths, control characters, and status. Search snippets and page text remain distinct.

## Grounding and citation checks

`/ask-web` never searches, reads additional pages, changes memory, or launches an application. It receives only the current question and successful active read records. It excludes ordinary system personality/history, structured memory, archived chats, desktop measurements, keys, and unselected search snippets. Evidence is supplied as untrusted JSON data under a separate grounding instruction. At most four deterministically chosen 600-character blocks per source are retained in document order and marked as selected/truncated passages.

The configured Qwen3.5 model makes one composition attempt. It is instructed to use evidence only, distinguish page statements from independent verification, avoid treating old content as current, expose relevant disagreements with separate source claims, and return an empty claim set when evidence is insufficient. The model cannot execute tools; no model text is routed back to the executor or memory parser.

Accepted structured claims require an actually read numeric source ID and a 12–600-character exact supporting quote present both in the selected passages and the extracted document. The application rejects nonexistent IDs, missing/invented quotes, arbitrary draft URLs/citation brackets, malformed/oversized drafts, leaked credentials, action-completion claims, obviously unsupported numeric values, and clearly unrelated text by a conservative lexical check. It appends the actual source URLs and original retrieval/publication timestamps itself; no citation IDs or URLs are invented to repair a draft. Invalid drafts produce an insufficient-evidence result without a hidden correction retry. Model failure produces a controlled error; it does not fall back to pretrained guesses.

These checks validate identity, quoted support and some obvious inconsistencies. They **do not establish perfect semantic entailment, source truth, freshness, completeness, or that every source conflict was noticed**. Visible supporting quotes permit inspection. A paraphrase can pass simple checks while still being wrong; conservative checks can also reject a valid paraphrase. The output is described as source statements, never independently verified research.

## Lifecycle, privacy and persistence

Full text remains in active-session memory only. The existing SQLite transaction stores completed reading previews and answer/citation displays, not a document corpus or full extracted records. No schema, memory database, document database, embeddings or vector index was added. Read and grounded-answer exchanges are excluded from later ordinary Ollama context, including after restore. Their displayed previews and answers remain visible in history with their original URLs/timestamps.

`/history` and `/resume` perform no fetch. Resume/restart/new/clear discard full evidence and trusted active search selection; explicitly search and read again before a new grounded answer. This avoids reconstructing fetch authorization by parsing arbitrary assistant history text. A saved answer is still displayed unchanged, including its original source mapping. A storage error does not automatically retry the network/model operation or claim the exchange was saved.

Source sites receive the selected URL/path, request headers and normal connection metadata. DNS goes through the OS resolver. No chat history, memory facts, process inventory, browser authentication or Tavily key is sent to sites. Retrieved instructions such as “open Notepad”, “delete memories”, or “reveal the API key” have no execution authority. Tests confirm no app/memory operation and no secret in history/model prompts.

## Files changed

| Files | Purpose |
| --- | --- |
| `src/capabilities/web_reader.py` | Selection state, guarded pinned HTTPS fetch, web.read contracts |
| `src/capabilities/web_content.py` | Frozen evidence, local extraction, sanitation/provenance |
| `src/capabilities/web_answer.py` | Bounded passages, grounding instructions, citation/quote checks |
| `src/capabilities/web_read_intent.py` | Explicit reading/answer commands and preview formatting |
| `src/capabilities/__init__.py` | Add one READ_ONLY tool to the existing registry |
| `src/intelligence/conversation.py` | Integrate read/ask branches, post-storage active state, history isolation |
| `src/config.py`, `src/cli.py`, `src/diagnostics.py` | Disabled reading gate, commands/status, no-request diagnostics |
| `pyproject.toml`, `.env.example`, local ignored `.env` | Extraction dependency and safe reading default |
| `tests/test_web_reading.py`, `tests/conftest.py` | Reading/grounding tests and live-network blockers |
| `tests/test_tools.py`, `tests/test_runtime.py`, `tests/test_system_info.py` | Six-tool/current-phase expectations; prior behavior checks retained |
| `README.md`, this report | Setup, walkthrough, protections and actual limits/results |

## Validation

- Actual pre-edit baseline: **667 passed in 25.06 seconds**, Python 3.12.10 on Windows.
- Focused Phase 4B suite: **124 passed in 2.04 seconds** before the final evidence-output validation tightening; final results below supersede this intermediate run.
- Intermediate full suite: **765 passed in 26.71 seconds** before the final additional security cases.
- Final full suite: **791 passed, 1 warning in 33.49 seconds**. This includes all 667 prior cases and 124 new Phase 4B cases. No tests were removed; prior tool-count/current-phase assertions were updated for the one added tool.

Automated tests mock source HTTP/DNS and Ollama; autouse fixtures prevent real source connections, alongside existing DDGS/Tavily/app guards. Coverage includes tool/gates, missing/invalid selection, URL/IP/private/special-use ranges, mixed DNS, rebinding-resistant connection pinning, TLS, redirects, timeout/deadline interruption, response limits/framing/encoding/MIME, extraction errors and global-dedup regression, stable IDs and metadata, three-source limits, command routing, bounded prompts, citations/quotes, conflicts/insufficient evidence, malicious pages, no secret/memory/app side effects, no extra search, SQLite failure, no full document persistence, ordinary-context isolation, resume/history/new behavior, and all prior regression cases.

One environment warning is emitted on first Trafilatura import: urllib3's optional SOCKS support lacks PySocks. Source transport does not use urllib3 or proxies, and extraction performs no downloads; no SOCKS dependency was added merely to silence that unrelated optional capability warning.

## Actual manual acceptance performed

All runtime writes used automatically cleaned temporary directories/databases. Existing user data and the configured model were untouched.

1. A single actual DDGS search for `latest Python release` returned five ranked sources. No Tavily call or paid fallback was made.
2. Explicit `/read 1` selected `https://www.python.org/downloads/latest/`. The reader rejected its redirect and did not follow it. This was an actual controlled unsupported-source outcome.
3. Explicit `/read 2` selected `https://www.python.org/downloads/`. Verified HTTPS retrieval and local extraction succeeded. Actual title: `Download Python | Python.org`. Actual retrieved timestamp: `2026-11-18T08:12:04.626946+00:00`. The preview began with `Active Python releases`; extracted content hit the 12,000-character bound and was marked truncated. No publication date was invented. These observations are page content, not independent release verification.
4. `/ask-web` against that source returned the controlled unavailable/timed-out message using a **temporary 45-second model timeout for this smoke run**. No answer or citation was fabricated and no extra page was fetched. This does not demonstrate a completed live-page answer.
5. Resume preserved displayed history exactly, restored zero full evidence records, and `/ask-web` required reading first without another network request.
6. A separate actual Ollama check found **qwen3.5:4b** installed. Using its configured timeout and an explicitly synthetic bounded evidence record, one composition completed in **11.33 seconds**, returning an accepted claim with its exact supporting quote, `[1]`, the supplied source URL and original retrieval timestamp. This validates real model integration, not a live-web fact. No extra search or website request was made for it.
7. Actual `python -m aika`, `python -m aika doctor`, `python -m aika --version`, and `python -m aika --help` all exited **0** with isolated storage. Doctor reported six registered tools, valid SQLite schema, installed Qwen3.5, app target availability, psutil interfaces and extraction availability; it made no source/provider requests. Expected warnings remained for disabled search, unconfigured Spotify and initially absent structured-memory storage. No desktop application was launched.
8. Multi-source disagreement and injection/access/TLS/oversize/failure cases were verified with mocks. A successful live two-page comparison, fresh virtual-environment installation, live Tavily request, and actual app launch were not performed in this checkpoint.

## Manual review walkthrough and remaining limits

Install dependencies and enable `AIKA_WEB_SEARCH_ENABLED=on`, `AIKA_WEB_READING_ENABLED=on` in `.env`; leave paid fallback off. Restart chat using an isolated `AIKA_DATA_DIR`. Search with `/web --provider ddgs latest Python release`; use `/read 1` and choose another returned HTTPS source if the first redirects or is inaccessible. Inspect the preview and actual URL. Ask `/ask-web What release does the selected page identify?`; allow the configured local-model timeout and inspect the supporting quotes. Explicitly read a second source, then ask whether they agree. Finally inspect history, resume, and confirm a new grounded answer requires new reading.

Search engine uptime, site access policies, static extraction quality and model responsiveness remain external limits. An official-looking hostname is not proof of truth. JavaScript-only, compressed-only, redirected, attachment, paywalled or non-HTML results can be unsupported. DNS pinning prevents re-resolution races, but does not promise protection against a compromised OS, DNS/network administrator, public server that proxies private data, or malicious host routing. A stuck OS resolver may finish later but cannot open a connection; the process temporarily refuses more DNS work. Source selection/evidence are deliberately not restored from transcript text. Citation checks cannot guarantee every generated claim is correct.

**Next planned milestone:** Phase 5 — Controlled Agent Planning. It has not been started.

**Final status: READY FOR MANUAL REVIEW.**
