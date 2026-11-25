# Q1D-C — Evidence-aware analysis

**Status: READY FOR MANUAL REVIEW — partial live acceptance.**

## Implementation

Reused Q1D-B's verified, immutable, session-only projection, expiry and permission checks. Added the measured RAM utilization percentage; no inferred percentage or new collection is needed. Narrow RAM/CPU analysis questions select only that metric's fields, timestamp and source. Missing/expired/disabled evidence, unavailable utilization and ambiguous metrics/snapshots clarify without generation or execution.

The single ordinary generation receives the unchanged persona plus targeted grounding instructions and a redacted user-role JSON packet. No transcript, project memory, OS details, process lists, desktop observations or other tool payloads are supplied. Evidence is data, not instructions. Optional evidence is bounded to 1,600 characters and the existing total input limit remains enforced without truncating mandatory content.

The model returns a copied measurement and natural explanation. Local validation rejects malformed replies, mismatched measurements, unsupported numeric/unit claims, action/memory claims and explicit current-state claims. Accepted prose receives an application-rendered attribution containing the actual earlier measurement, timestamp/source and “not a current measurement.” This is validated rendering, not an LLM rewrite. No retry or second generation occurs. Ordinary system-claim guards remain unchanged outside this evidence path.

Recognized analytical exchanges are excluded from later ordinary model/archive context. Q1D-B deterministic answers and explicit fresh-measurement requests remain supported.

## Verification

Focused suites: **67 passed in 2.47 seconds**. Single full Python 3.12 regression: **1,805 passed in 52.92 seconds**. Compilation and whitespace checks passed.

Eight temporary-data conversations used synthetic snapshots passed through the real executor/contracts, followed by six actual local-model generations and two zero-generation clarifications. These are not measurements of the user's laptop.

| Check | Observed outcome |
| --- | --- |
| High RAM | Correct quantities; explanation mostly descriptive |
| Low RAM | Correct historical low-utilization explanation |
| CPU | Correct draft rejected by conservative current-state guard |
| Historical versus current | Earlier values rendered; explicitly not current |
| Expired evidence | Clarified; no generation |
| Ambiguous metric | Clarified; no generation |
| Untrusted content/redaction | Hostile OS text excluded; synthetic credential redacted |
| No writes/executions | Memory snapshots unchanged; no repeated tool calls |

All six drafts copied the selected measurement correctly. A validation bug initially rejected restated source dates; it was fixed without changing prompts. The same six frozen drafts were replayed with byte-identical model inputs: **five accepted, one rejected**, zero new generations. Original inputs/outputs: `artifacts/q1dc-live.json`; final validation replay: `artifacts/q1dc-validation-replay.json`.

## Limits and next step

The remaining rejected draft used “right now” negatively; the guard conservatively rejects that wording. Some accepted prose restates quantities or speculates about possible workload causes. Interpretation is not certified, and these samples do not establish reliability. Tight budgets and unsupported wording remain limitations.

Changed: `src/capabilities/tool_followup.py`, `src/intelligence/conversation.py`, `tests/test_tool_result_analysis.py`, two Q1D-B test expectations, this report. Q1C remains **FAILED live acceptance**; its resolver/store are unchanged. No configuration/schema/model changes, commits, pushes or next checkpoint. Next: manual review. Packaging, Python 3.13 and hosted CI were not rerun.
