# Q1D-A — Grounded factual responses

**Status: READY FOR MANUAL REVIEW.**

## Findings and change

The existing explicit-memory route already answered “Which engine does Nova use?” and “What's Orion's frontend?” deterministically. Reproduction confirmed zero model calls. However, “Which engine is Nova using now?” fell through to generation, and a correction followed by a fact question produced an irrelevant clarification.

Reused the existing memory parser, transactional reply handler, exact-subject `get_fact` lookup and provenance records. A shared strict question matcher now covers the additional “using now” and property “of” variants using existing property aliases. Project names and answers are never hardcoded.

A supported same-message assertion/correction followed by a matching subject/property question is read-only context. The answer distinguishes the current assertion from saved memory. For example: “You just said Nova uses Godot for its engine. Saved memory still has Unity; it hasn't been changed.” Evidence retains both current-session and structured-fact sources. No memory confirmation or update is inferred from this compound question.

Ambiguous subjects clarify; absent/deleted facts report no saved value; superseded facts return only the active revision. Unsafe or analytical compound questions fall back to ordinary behavior instead of being reinterpreted as memory updates. Existing explicit save/correction/deletion flows remain intact. Replies retain existing redaction and exchange persistence.

Changed: `src/memory/intent.py`, `src/memory/chat.py`, `tests/test_grounded_fact_responses.py`, this report.

## Verification

Focused tests: **66 passed in 4.51 seconds**, covering exact subjects, aliases, current/saved conflicts, missing/deleted/superseded values, ambiguity, analysis fallback, redaction, no tools and no silent writes. Single final Python 3.12 regression: **1,756 passed in 49.44 seconds**. Compilation and whitespace checks passed.

Eight temporary-database conversational checks passed: engine, frontend, ambiguous subject, missing property, superseded fact, deleted fact, current correction and analytical fallback. The seven factual/clarification cases used **zero generations**. The analytical case used **one actual Ollama generation** with unchanged `qwen3.5:4b` configuration. Memory-table snapshots remained unchanged in every case; unrelated private facts were excluded. Complete synthetic results: `artifacts/q1da-live.json`.

## Boundaries and next step

Matching deliberately supports existing property aliases and narrow factual grammar. Unsupported wording, uncertain values, mismatched subjects/properties and broader analysis retain existing behavior; this is not general question answering.

Q1C remains **FAILED live acceptance**. Its resolver, session integration and store extension are byte-for-byte unchanged; no prompt tuning or acceptance-status promotion occurred. Q1A factual/Taglish limitations remain unresolved.

Next: manually review Q1D-A's deterministic answers. No model/configuration/schema/permission changes, production-data modifications, commits, pushes or further phases. Python 3.13, packaging and hosted CI were not rerun.
