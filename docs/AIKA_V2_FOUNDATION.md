# AIKA AI V2 — Foundation & Architecture Specification

**Document ID:** AIKA-V2-FOUNDATION  
**Version:** 0.1.0 — baseline proposal  
**Date:** 2026-11-17  
**Target:** Windows-first, local-first personal desktop AI companion  
**Status:** Planning baseline, not a claim of implementation  
**Role:** Source of truth for AIKA V2 architecture and phased implementation

> **Product principle:** Build the intelligence, memory, safe agency, and event contracts of a desktop-embodied character *before* building its visual body.

## 0. How to use this document

This document sets the architecture, invariants, boundaries, contracts, acceptance scenarios, and phase gates for AIKA V2. Codex and other coding assistants must read it before a phase implementation. When implementation needs to diverge, propose a short Architecture Decision Record (ADR); do not silently introduce another orchestrator, database, permission path, or agent framework.

**Priority order:** security and verified behavior > documented contracts > milestone acceptance > implementation convenience. Model names, providers, libraries, and directory details are configurable choices; contracts and safety invariants are not.

**Meaning of “local-first”:** conversation, memory, orchestration, and baseline inference can operate locally. Web search, external APIs, and cloud models (if separately enabled) are optional outbound integrations. Local-first does not mean every feature works offline.

## 1. Product definition

AIKA is a locally running desktop AI companion designed to evolve into an **embodied AI character**. Its eventual character can inhabit the desktop, react to permitted environment signals, move, animate, speak, and assist. Unlike a conventional chat window with an avatar, AIKA's character will express a persistent intelligence system with memory, task execution, and behavioral state.

### Core product capabilities

1. **Conversational intelligence:** natural dialogue and follow-ups, consistent handling of uncertainty.
2. **Persistent, correct memory:** explicit facts, updates, superseded values, and recall across restart.
3. **Agentic task execution:** bounded plans, typed tool calls, permissions, checked outcomes.
4. **Web intelligence:** source-backed searches and synthesis when online.
5. **Desktop capabilities:** allowlisted app launching, restricted system/file access, later controlled GUI actions.
6. **Contextual perception:** signals from enabled sources only; no ambient monitoring by default.
7. **Character personality and behavior:** stable identity and event-driven state; later animated embodiment.

### First usable milestone

A CLI AIKA that can converse, remember/update/retrieve facts across restarts, launch a permitted app while reporting genuine status, and later perform source-backed web research. The CLI is a **development interface**, not the long-term product interface.

### Explicit non-goals before the backend stabilizes

- A multi-agent swarm, separate action model, self-rewriting code, general shell execution, or fully autonomous control.
- Always-on microphone/camera/screen capture; unconsented access to private windows or files.
- PostgreSQL, a vector database, or RAG framework as prerequisites for exact memory recall.
- Avatar animation, desktop movement, speech synthesis, cursor interaction, and graphical polish in early phases.
- Claiming action completion solely from an LLM response, without execution evidence.

## 2. Decisions and rationale (ADRs)

| ID | Baseline decision | Rationale / review trigger |
|---|---|---|
| ADR-001 | **One request orchestrator** owns all user request lifecycles. | Prevent competing routers/agents. Revisit only after reproducible bottleneck. |
| ADR-002 | **Python 3.12+ modular monolith** for initial backend. | Minimal deployment and simple local debugging. |
| ADR-003 | **Ollama through a model-provider interface.** | Local inference, replaceable model, benchmark rather than blindly hardcode. |
| ADR-004 | **SQLite with migrations** stores chat, requests, structured memory, and audit records. | Durable, low-setup local storage. Consider other stores only for measured need. |
| ADR-005 | **Deterministic memory lookup first; optional FTS5, then semantic retrieval.** | Fix V1's claimed-but-unavailable memory failure. |
| ADR-006 | **Trusted executor owns tool execution and policies.** | Model outputs are suggestions, not direct OS permissions. |
| ADR-007 | **Localhost API + typed event stream** is the future UI boundary. | Enables CLI now and desktop UI later without moving brain logic into frontend. |
| ADR-008 | **Character consumes events; never bypasses the orchestrator.** | Independent embodiment development. |
| ADR-009 | **Windows-first with platform adapters.** | Narrow early scope; avoid fake cross-platform guarantees. |
| ADR-010 | **No new feature before real-app acceptance passes.** | Prevent V1-style scope drift. |

**Candidates, not immutable commitments:** a small Qwen model for baseline Ollama tests; FastAPI when an HTTP boundary is necessary; SearXNG or a managed search API for online research; React + TypeScript + Tauri 2 for the eventual desktop UI. Benchmark performance and integration before adopting each.

## 3. Logical architecture

```text
[CLI now]      [Desktop UI later]      [Authorized system event]
    \                  |                         /
     +------ Local API / in-process adapter -----+
                           |
                    Request Orchestrator
                     (single authority)
                           |
           +---------------+----------------+
           |               |                |
     Context/Memory     Model Adapter   Agent Planner
           |               |                |
     SQLite + FTS5     Ollama/other      Tool Registry
           |               |                |
           +---------------+----------- Policy Gate
                                           |
                                      Tool Executor
                                           |
                               OS / Files / Web adapters
                                           |
                                 Verified tool outcomes
                                           |
                                     Event Bus
                                           |
                     CLI stream / logs / future avatar states
```

### The crucial separation

- **Core orchestrator:** lifecycle and routing authority; does not directly access the OS or SQL tables.
- **Intelligence/model adapter:** language understanding, replies, optional structured planning; **cannot execute** tools.
- **Memory:** durable data, transactional revisions, provenance; **cannot independently initiate** desktop actions.
- **Agent planner:** suggests next bounded tool calls; **does not grant permissions**.
- **Capability registry/executor:** validated operations, trusted authorization, timeouts, verification, idempotency handling.
- **Perception:** normalizes permitted environmental observations into events; no direct execution rights.
- **Character state/behavior:** maps events into expression/behavior state; proactive proposals must re-enter orchestrator.
- **Interface adapter:** renders results/events; no application/business logic or model-specific knowledge.

Keep one process and one SQLite file initially. Internal modules are **not** independent microservices. Do not create one class per diagram box unless implementation needs it.

## 4. Request lifecycle contract

Each user request has a UUID, session ID, origin, timestamp, content, and optional target scope. Every tool operation and emitted event references that request ID.

### Lifecycle

```text
RECEIVED
  -> CONTEXT_READY
  -> REASONING
  -> (WAITING_APPROVAL)?
  -> (EXECUTING -> VERIFYING -> REASONING)*
  -> COMPLETED | FAILED | CANCELLED
```

Rules:

1. Persist the user turn and request state before starting model generation.
2. Resolve follow-up references from active session context; retrieve structured knowledge selectively by subject and predicate.
3. If a request is conversational, generate without tools. If a tool is needed, ask the model/planner for **typed** intent; it is not executable code.
4. Validate tool name/arguments against registry, check scope/permissions, require approval where needed, execute, then record verifiable outcome.
5. Return a final answer based only on known memory evidence, model output framed as inference, or verified tool/web evidence.
6. Commit assistant messages and final request state. Stream progress events with request correlation IDs.
7. Bound the loop: configurable maximum tool steps, timeouts, and cancellation. On failure, report what completed and what did not.
8. For non-idempotent actions, never blindly retry after an uncertain result. Use operation IDs and reconciliation.
9. Start with **one active request per session**; queue or reject additional requests explicitly. Improve concurrency only after correctness.

### Illustrative request envelope

```json
{
  "schema_version": "1.0",
  "request_id": "<uuid>",
  "session_id": "<uuid>",
  "origin": "user_text",
  "content": "Open Spotify",
  "created_at": "<ISO-8601 UTC timestamp>",
  "context": {"active_project_id": null},
  "idempotency_key": "<optional-client-generated-key>"
}
```

Origin values begin as `user_text`, `system_event`, and `scheduled_event`; only `user_text` is enabled initially. System/scheduled events are **not trusted user instructions**.

### Failure semantics

- `COMPLETED`: the request was handled and claims are supported. Can include an explicit "not found" answer.
- `FAILED`: infrastructure/model/tool execution failed and prevents the goal.
- `CANCELLED`: user or policy stopped the request.
- A tool's own status is `success`, `failure`, `denied`, `cancelled`, or `unknown`. Unknown means verification was inconclusive, **not** success.

## 5. Persistent memory contract

### Memory types

| Type | Purpose | Storage / retrieval |
|---|---|---|
| Working context | Recent turns, unresolved references | Request/session assembly; bounded size |
| Conversation history | User/assistant messages and evidence | SQLite; time- and session-based lookup |
| Structured facts | Current project/person/preferences facts | SQLite key-based lookup; subject-scoped |
| Historical revisions | Former fact values, corrections, sources | Immutable revision history + status |
| Episodic summaries | Meaningful multi-turn events | Deferred; explicit provenance |
| Semantic retrieval | Fuzzy discovery across longer content | Deferred; optional index |

### Canonical structured fact

```json
{
  "fact_id": "<uuid>",
  "subject": {"type": "project", "key": "orion", "display_name": "Orion"},
  "predicate": "frontend_framework",
  "value": "SvelteKit",
  "status": "active",
  "revision": 2,
  "supersedes_fact_id": "<uuid-of-nextjs-fact>",
  "source_message_id": "<uuid>",
  "recorded_at": "<ISO-8601 UTC timestamp>"
}
```

### Write and revision rules

- On **explicit** "remember" commands, parse to typed fact candidates, validate subject/predicate/value, commit transaction, and only then say "remembered".
- When the subject or update intent is ambiguous, clarify rather than overwrite unrelated facts.
- An update atomically supersedes the former active fact and inserts a revision. Do not overwrite old value in place.
- For an ordinary question, retrieve existing active facts; do **not** create a fact by guessing what the answer should be.
- Store source identifiers and timestamps. Distinguish *user-supplied assertion* from externally verified information.
- For "what did I use before?", look up the prior revision of the **same subject and predicate**, not a general chat guess.
- For "forget/delete", distinguish deleting an active preference from purging history. Implement semantics that really remove/disable the requested records and associated derived indexes; do not claim full purge while copies persist in backups.
- Avoid automatic storage of sensitive observations in v2 baseline. Personalization requires explicit opt-in and scope controls.
- Maintain separate conversation logs and memory records. Memory is not merely a synthesized chat summary.

### Minimal relational layout

Required tables by milestone:

- `sessions(id, created_at, updated_at, active_project_id)`
- `messages(id, session_id, role, content, created_at, request_id)`
- `requests(id, session_id, origin, state, created_at, completed_at, error_code)`
- `memory_facts(id, subject_type, subject_key, predicate, value_json, status, revision, supersedes_id, source_message_id, created_at)`
- `memory_events(id, fact_id, operation, request_id, created_at)`
- `tool_runs(id, request_id, operation_id, tool_name, args_redacted_json, status, verified, result_redacted_json, created_at)`

Later as required: `approvals`, `research_sources`, `perception_preferences`, `scheduled_jobs`.

Constraint: there should be **no more than one active fact** for a normalized `(subject_type, subject_key, predicate)` triple. Use a partial unique index or equivalent DB constraint. Schema migrations are versioned and tested; never rely on destructive `drop/create` startup logic.

Storage configuration: enable SQLite foreign keys, sensible busy timeout, atomic transactions, and backups. Consider WAL after checking actual access patterns and backup strategy. FTS5 is optional for searching conversations but not required for exact fact retrieval.

### Memory acceptance sequence (must survive process restart)

1. "Remember that my project Orion uses Next.js and MySQL." → two structured facts persisted.
2. "What frontend am I using for Orion?" → Next.js, via retrieved record.
3. "I'm switching Orion to SvelteKit." → old frontend superseded, MySQL untouched.
4. "What did I use before?" → Next.js, via revision history.
5. Restart AIKA and ask #2 and #4 again → same answers.
6. Repeat with **another project** using conflicting technologies → no cross-project leakage.
7. Attempt correction with unclear subject → ask which project, do not mutate silently.
8. Delete requested fact/history through defined semantics, restart, verify it no longer appears in active recall.

## 6. Agent and tool execution contract

### Agent rules

- A single orchestrator manages a bounded tool-use loop. The planner may use the current conversation model; **no separate action model by default**.
- Each tool call must use a registered name and schema-valid parameters; unknown tools fail closed.
- A plan can decompose a multi-step request but cannot invent new capabilities or elevate permissions.
- No external webpage, downloaded document, search snippet, or OS signal may inject instructions into system policy or tool arguments without trusted validation.
- No unrestricted `shell.exec`, `eval`, arbitrary Python execution, persistence daemon creation, or silent installation in MVP.

### Tool specification (illustrative)

```json
{
  "name": "app.open",
  "version": "1.0",
  "description": "Open one of the user's explicitly allowlisted applications",
  "permission": "execute_allowlisted_app",
  "risk": "low",
  "arguments_schema": {
    "type": "object",
    "properties": {"application_id": {"type": "string"}},
    "required": ["application_id"],
    "additionalProperties": false
  },
  "requires_confirmation": false,
  "timeout_seconds": 15,
  "can_retry_automatically": false
}
```

### Execution result

```json
{
  "request_id": "<uuid>",
  "operation_id": "<uuid>",
  "tool": "app.open",
  "status": "success",
  "verified": true,
  "evidence": {"process_observed": true},
  "data": {"application_id": "spotify"},
  "error": null,
  "elapsed_ms": 850
}
```

**Verification nuance:** observing a process does not prove the application UI is usable. Describe the actual check in the evidence and word the reply accordingly. An unverified start request should not become "Spotify opened successfully."

### Permission classes

| Class | Examples | Policy |
|---|---|---|
| Read-only, bounded | Calculator, approved system metrics | Allowed when enabled |
| Scoped action | Open allowlisted app, open approved URL | Explicit allowlist / scoped permission |
| Sensitive read | Read personal documents, screen/window content | Folder/window scope and consent |
| Modify | Move/rename/edit files, browser form actions | Per-action approval and recovery path |
| High impact | Delete, purchases, communications, account/security changes | Strong approval; many excluded initially |
| Unbounded/unsafe | Raw terminal commands from model, arbitrary executable download | Disabled by default |

The policy check happens **immediately before execution**, even if an earlier plan or UI already approved a related action. Approval decisions must bind to the exact tool, arguments, and scope. Audit decisions without logging secrets.

### Initial registry

1. `math.calculate` — deterministic arithmetic with constrained input.
2. `app.open` — Windows application launcher, fixed allowlist of IDs to trusted commands/paths.
3. `system.status` — read-only permitted metrics.
4. `file.read_text` — limited folders, file size/type bounds, no symlink escape.

`web.search` and `web.fetch` are added in the web-intelligence milestone. GUI click/type and file writes are later milestones, not MVP defaults.

## 7. Web intelligence contract

Web research follows `search -> select sources -> fetch -> extract -> assess freshness/source quality -> synthesize -> cite`. Separate **search result snippets** from **retrieved primary pages**; do not invent browsing or citations.

Store for each used result: normalized URL, title, provider, retrieved timestamp, optional publication timestamp, excerpt/claim anchors, fetch status, and request ID. Cite URLs in final responses and disclose when only a snippet was available. Recent-version questions must use fresh evidence; old documentation cannot establish today's latest release.

**Provider boundary:** `SearchProvider.search(query, options)` and `PageFetcher.fetch(url, limits)` permit changing from SearXNG to a managed search API without touching orchestration. SearXNG JSON mode may require configuration and public instances may disable it. Web queries necessarily leave the computer when submitted to an online engine.

Security: protect against SSRF to localhost, LAN/private endpoints, metadata services, `file:`/unsupported schemes, redirect bypass, huge responses, malicious markup, untrusted content/prompt injection, and credential-bearing URLs. Limit download size, redirects, total time, and concurrency. Respect website access restrictions where applicable.

Offline rule: if provider/network unavailable, explain that live verification cannot be performed; do not substitute stale recalled model knowledge as if current.

## 8. Perception, character state, and embodiment contract

### Two coordinated loops

**Task loop** processes explicit user requests and approved tool work. **Behavior loop** interprets enabled signals and chooses presentation/proactive *suggestions*. The behavior loop cannot directly execute tools, remember sensitive observations, or send messages without entering the policy-controlled orchestrator.

### Initial normalized perception events (future phase)

- `system.app_foreground_changed` — only app identity when enabled; avoid raw window titles by default.
- `system.resource_sampled` — bounded system metrics.
- `system.time_context_changed` — local time/day and optionally configured routine.
- `system.permission_changed` — visible permission state.

Later opt-in: pointer proximity, screen region observation, microphone, camera, UI Automation, and explicit access to active document content.

### Character state machine

`idle`, `listening`, `thinking`, `acting`, `speaking`, `success`, `error`.

Character state is a **UI/behavioral representation**, not a claim of subjective emotions. Priority rules prevent contradictory states: e.g., a pending approval overrides `acting`; a failed action leads to `error` rather than `success`. Keep idle behavior subtle and throttle reactions.

### Event envelope

```json
{
  "schema_version": "1.0",
  "event_id": "<uuid>",
  "request_id": "<uuid-or-null>",
  "source": "orchestrator",
  "type": "character.state_changed",
  "timestamp": "<ISO-8601 UTC timestamp>",
  "payload": {"state": "thinking", "reason": "processing_request"}
}
```

Additional typed events: `request.started`, `request.completed`, `tool.started`, `tool.completed`, `approval.requested`, `memory.updated`, `response.chunk`, `response.completed`, `perception.observed`. Define schema versions and redact sensitive payloads before broadcasting.

**Future UI rule:** The desktop character subscribes to events; it never calls Ollama, writes memory, or executes an OS tool on its own. A UI action submits a new request to the same orchestrator.

## 9. Model integration and response grounding

Interface `ModelProvider.generate(messages, tools?, response_schema?, cancellation?)` hides provider-specific formats. Record model ID, configuration, generation times, errors, and tokens where supported. Keep prompts versioned and narrow: system/persona, safety/policy, retrieved memory evidence, tool descriptions, recent dialogue, and current user message.

**Context priority:** explicit current request and applicable policy -> exact structured facts for identified subject -> relevant recent messages -> verified tool/web evidence -> optional fuzzy retrieval. Never let a web snippet or stale chat memory override an explicit current correction without reconciliation.

For small models, test schema conformance, tool selection, argument precision, refusal of nonexistent tools, follow-up resolution, hallucination, and latency on the target device. Candidate model size is not evidence of quality. Support a non-model path for deterministic memory lookup and arithmetic.

If the local model fails, report a clear degraded state. Never silently switch to a paid/cloud provider without explicit configuration and permission.

## 10. Local runtime and interface boundaries

Start with an in-process CLI adapter to avoid unnecessary HTTP complexity. When the desktop shell or separate client is introduced, expose a versioned local API, e.g. `POST /v1/requests`, `GET /v1/requests/{id}`, `POST /v1/approvals/{id}`, `GET /v1/events` (stream), and `GET /v1/health`.

Safety for the future local API: bind to loopback only (`127.0.0.1`), authenticate client calls using a per-install/session secret, restrict CORS, validate request origins and request bodies, do not expose permissive OS-action endpoints, and avoid writing secrets to logs. Tauri capabilities are a second permission boundary, **not** a replacement for backend policy enforcement.

### Logging and diagnostics

Structured logs contain correlation IDs, event types, elapsed time, tool status, and safe error codes. Raw prompts, file contents, page bodies, private window titles, credentials, and memory values are **not** logged by default. Provide a deliberate diagnostic export with review/redaction and easy local deletion.

## 11. Proposed repository layout

```text
aika-ai-v2/
├── aika.py                      # python -m aika entry point
├── apps/
│   ├── cli/                     # Current development entrypoint
│   └── desktop/                 # Future React/Tauri application
├── src/
│   ├── __init__.py              # Runtime package and release version
│   ├── cli.py                   # Command-line adapter
│   ├── config.py                # Environment configuration
│   ├── diagnostics.py           # Runtime inspection
│   ├── core/                    # Orchestrator, contracts, context, events, policies
│   ├── intelligence/            # Model adapter, conversation, planner, persona
│   ├── memory/                  # Store, retrieval, atomic revisions, migrations
│   ├── capabilities/            # Registry, executor, Windows/file/web adapters
│   ├── perception/              # Authorized signal providers
│   ├── character/               # State machine and behavior proposals
│   ├── api/                     # Local transport boundary (when needed)
│   └── storage/                 # SQLite connection and migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── acceptance/
├── docs/
│   ├── AIKA_V2_FOUNDATION.md
│   ├── decisions/               # Short architecture decision records
│   └── phase-reports/           # Acceptance and decisions per phase
├── config/                      # Example configs; never secrets
├── data/                        # Optional repo-local data override (gitignored)
└── pyproject.toml
```

Phase 0B uses root `aika.py` and the `src/` package directly. Only scaffold files used in the current milestone. The default local data path is outside the checkout.

## 12. Development phases and exit gates

| Phase | Build | Must demonstrate before proceeding |
|---|---|---|
| **0 — Foundation** | This specification, ADRs, acceptance fixtures, V1 preservation plan | Contracts are coherent; planned test cases and permissions are explicit; no V1 destructive migration |
| **1 — Conversation core** | CLI + SQLite sessions/messages + Ollama adapter + orchestrator | Natural follow-up dialogue; restart preserves history; model failure is explicit |
| **2 — Structured memory** | Exact fact store, revision history, retrieval, deletion | Entire Orion scenario and conflicting-project scenario pass after restart |
| **3 — Safe agency/tools** | Registry, policy/approvals, executor, first tool set | App launch checked; denied operations blocked; no false completion or arbitrary shell |
| **4 — Web intelligence** | Search adapter, fetcher, citations, offline states | Sources/URLs verifiable; current claims use fetched data; injection and SSRF defenses tested |
| **5 — Perception** | Optional signal providers and consent UI/CLI | Sensors default off; context correct; consent revocation stops observation |
| **6 — Character brain** | Event/state/behavior loop | Consistent character event sequence; no unsolicited tool execution |
| **7 — Embodiment** | Desktop UI, avatar, animations, cursor, voice as separate features | Backend still operates headless; UI mirrors real task and permission state |
| **8 — Advanced agency** | Scoped GUI actions, schedules, richer integrations | Each additional capability has its own safety and end-to-end acceptance gate |

Phases can be split into smaller implementation steps, but **cannot skip exit gates**. Later features may be reprioritized if an independent, justified need emerges.

## 13. Concrete acceptance test catalogue

| ID | Scenario | Required result |
|---|---|---|
| AC-01 | "sup AIKA" | Natural response without unintended tool calls |
| AC-02 | Discuss a project then ask "what about its database?" | Proper subject resolution or clarification |
| AC-03 | Explicitly remember Orion frontend/database | Persist both as independently queryable facts |
| AC-04 | Ask "What frontend am I using?" with Orion active | Answer from structured memory, cite internal fact provenance in debug trace |
| AC-05 | Switch Orion from Next.js to SvelteKit | Atomic revision; MySQL unchanged |
| AC-06 | Ask "What did I use before?" | Answer Next.js using history |
| AC-07 | Restart and repeat AC-04/06 | Identical correct recall |
| AC-08 | Create Solar Finch with different stack | No mixing of Orion/Solar Finch values |
| AC-09 | Ask to forget a specific stored fact | Apply defined deletion behavior, verify no active recall after restart |
| AC-10 | "Open Spotify" when allowed/installed | Tool executes and reports specifically verified status |
| AC-11 | "Open nonexistent app" | Report failure, no invented successful launch |
| AC-12 | Attempt unregistered tool / unsafe shell | Denied before OS access |
| AC-13 | Request current release information while online | Search/fetch with attributable URLs and timestamp |
| AC-14 | Same request with internet disabled | Clearly say live verification unavailable |
| AC-15 | Webpage includes prompt-injection instruction | Ignore external instruction; enforce registered-tool permission |
| AC-16 | Cancel a running request | Stop or safely mark in-flight work; no false success |
| AC-17 | Two simultaneous requests in one session | Defined queue/rejection; no state corruption |
| AC-18 | Disabled desktop perception | No observation and no sensitive event payloads |
| AC-19 | Character task sequence | `thinking -> acting -> speaking/idle` events correspond to actual lifecycle |
| AC-20 | Restart after DB write | No corruption; accepted transactions preserved |

Each phase should run applicable automated tests **and** a documented CLI walkthrough against a real Ollama runtime and permitted OS tools. Use simulated failures for negative paths. Unit tests alone are never a release gate.

## 14. V1 preservation and migration plan

1. Treat V1 repository, database, assets, prompts, and test fixtures as **read-only reference**, not as code to overwrite.
2. Back up V1 data before migration; record current DB technology, schema, source version, and whether export is complete.
3. Identify reusable *behavioral contracts* rather than copying all existing abstractions.
4. Define a separate V1-to-V2 import command, preview/dry-run mode, schema mapping, validation report, and rollback strategy.
5. Do not mutate or delete V1 source data during import. Prefer copy/import into a new V2 database.
6. Import only once migration tests and duplicate/conflict semantics are verified. Old data stays accessible independently.

## 15. Codex working agreement

Every implementation request must include:

- **Reference:** this exact document version and applicable ADRs.
- **Scope:** one milestone or a tightly bounded sub-step, with explicit exclusions.
- **Contracts:** touched interfaces/schema/event formats and compatibility expectations.
- **Safety:** tool permissions, data handling, rollback behavior, no silent destructive changes.
- **Acceptance:** relevant AC IDs plus one manual end-to-end scenario.
- **Output:** changed files, design decisions, tests run/results, known limitations, and how to reproduce.

Codex must **not** introduce separate decision routers, agent frameworks, databases, vector stacks, hidden prompts-as-state, arbitrary shell tools, or redesign the frontend without explicit architectural approval. No giant refactor to solve a single acceptance failure. Make the smallest coherent change, add regression tests, and verify the actual application.

### Phase report template

```text
Milestone:
Scope completed:
Contracts changed (and ADRs):
Tests run / results:
Manual acceptance run / result:
Data migration impact:
Security/permissions reviewed:
Known limitations:
Ready for next phase? yes/no + reason:
```

## 16. Open questions to resolve empirically

These choices are **not** reasons to block Phase 1; keep interfaces replaceable and measure when needed:

- Actual target PC specs (RAM, GPU/VRAM), acceptable generation latency, and local model benchmark.
- Exact Ollama model choice and whether specialized tool model outperforms using the single model.
- Preferred search provider and willingness to run a SearXNG service versus using a paid API.
- Which folders/apps should be allowlisted for personal use.
- Which opt-in perception signals provide enough value without invasive monitoring.
- Later avatar rendering technology and animation asset pipeline.

## 17. Reference documentation (checked 2026-11-17)

- Ollama tool calling: https://docs.ollama.com/capabilities/tool-calling
- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs
- SQLite FTS5: https://www.sqlite.org/fts5.html
- Tauri v2 capabilities: https://v2.tauri.app/security/capabilities/
- Tauri v2 window config: https://v2.tauri.app/reference/config/
- SearXNG search API: https://docs.searxng.org/dev/search_api.html

**Foundation freeze criterion:** This document can be treated as the V2 baseline once its major decisions and acceptance gates are accepted. Future changes should be versioned, not silently assumed. **Next implementation task after Phase 0:** Phase 1, reliable conversation core—not memory, web, tools, and character animation all at once.
