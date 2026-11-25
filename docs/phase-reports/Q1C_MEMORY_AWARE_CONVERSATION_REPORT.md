# Q1C — Memory-aware conversation

**Status: FAILED — live acceptance.** The read-only implementation remains in the working tree for review. Retrieval works, but generated replies do not consistently use it. The first implementation was evaluated once, without prompt retuning or baseline/candidate repetitions.

## Implementation

Ordinary conversation now passes its existing `MemoryStore` into the Q1B resolver. Indexed, read-only SQL matches exact project subjects before falling back to a single established session project. Property names and existing technology aliases determine relevance. No other conversation archive is searched.

Only active `memory_facts` rows qualify; revisions and deleted facts are excluded. At most three complete facts fit within a 1,600-character optional packet and the existing total input budget. Mandatory instructions, newest input and Q1B-selected exchanges remain intact. Oversized facts are skipped, not truncated. API-key redaction applies before model input.

Existing fact evidence supplies subject, property, value, ID, revision, source and timestamp. Instructions distinguish saved state from current assertions, forbid executing quoted data and prohibit silently changing memory. Diagnostics retain IDs/revisions/status only. Explicit save/correction/deletion routing remains unchanged; retrieval adds no writes, model calls, schema changes or permissions.

Changed: `src/memory/store.py`, `src/intelligence/context.py`, `src/intelligence/conversation.py`, `tests/test_memory_aware_context.py`, this report. Earlier Q1A/Q1B work was preserved.

## Verification

Starting reference: Q1B's recorded 1,723 tests; no repeated baseline suite. Focused memory/context suites: **85 passed in 5.58 seconds**. Single final Python 3.12 regression: **1,738 passed in 44.33 seconds**. Compilation and `git diff --check` passed.

Eight temporary-database live scenarios used seven generations of existing `qwen3.5:4b`, thinking OFF, unchanged persona and budgets:

| Scenario | Actual result |
| --- | --- |
| Nova/Unity versus Godot | Unity selected; reply ignored saved engine: FAIL |
| Cross-session | Used Unity; unverified blanket migration claim: PARTIAL |
| Multiple projects | Orion's React selected and used; Nova excluded: PASS |
| Current Godot versus saved Unity | Used Godot; saved Unity unchanged; discrepancy not explained: PARTIAL |
| Superseded/deleted | Only active Godot selected; deleted SQLite excluded; reply ignored Godot: PARTIAL |
| Ambiguous reference | Clarification, zero generations: PASS |
| Unrelated question | No saved facts injected: PASS |
| Malicious/private data | Redacted; unrelated memories absent; no actions/writes: PASS |

All eight memory-table snapshots remained unchanged. Complete synthetic outputs and assessments: `artifacts/q1c-live.json`. Generated input sizes were 3,356–4,049 characters; reply wall times were 6.8–22.2 seconds. These are observations, not speed benchmarks.

## Limits and next step

Matching currently supports project facts, exact subject phrases up to four words within the first 64 question words, and lexical property/technology clues. Vague requests can miss facts; competing matches clarify conservatively. Zero-turn chat history stays disabled; independently saved facts remain available by explicit name. Concurrent updates after retrieval and stale statements already present in chat are not resolved here.

The model's selective evidence use remains a limitation; Q1A factual and Taglish failures remain open. Next: manually review these changes and evidence-policy compatibility before another separately authorized attempt. No Q1D, commits, pushes, model changes or production-data modifications. Python 3.13, packaging and hosted CI were not rerun.
