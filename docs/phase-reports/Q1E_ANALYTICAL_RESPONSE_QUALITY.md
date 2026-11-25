# Q1E — Analytical response quality

**Status: FAILED. Candidate rejected; original runtime instructions restored.**

## Diagnosis and attempted change

Reviewed only Q1D-C evidence assembly, validation, relevant tests and recorded replies. The existing inputs contained enough verified measurements for basic interpretation. The main weaknesses were model behavior: merely restating quantities, weak next steps and speculative causal wording. Missing workload/trend evidence permits possibilities, not diagnoses. Strict JSON/date validation also rejects some otherwise cautious prose.

Tested one short analytical-instruction addition: interpret the level, distinguish observed facts from possible causes, avoid unsupported application/process/hardware assumptions, offer one conditional practical check when useful, and avoid treating low utilization alone as a problem. No validator, routing, model, persona, inference count or permission change was made.

## Actual before/after evaluation

Six previously unseen synthetic scenarios were frozen before generation: RAM 87.5%/12.5%, CPU 92%/4%, historical CPU 57.5% queried as current, and RAM 75% with unavailable availability data. Each had one independent before/after request, alternating order: **12 total local-model generations**, one per analytical request, with no retries, rewrites or retuning. Synthetic snapshots passed the real executor/contracts; they were not laptop measurements.

| Scenario | Before | Candidate |
| --- | --- | --- |
| High RAM | Correct quantities; assumes a standard desktop | More conversational; premature close/restart advice |
| Low RAM | Correct historical 12.5% interpretation | Calls 12.5% “just over one percent”; claims current conditions; rejected |
| Busy CPU | Correct high load and uncertainty | Better hypothetical explanation and activity check |
| Quiet CPU | Correct but descriptive | More natural generic low-activity interpretation |
| Current-state question | Cautious prose, invalid JSON; rejected | Cautious JSON, abbreviated source date rejected |
| Partial RAM evidence | Correct quantities, descriptive | Better conditional interpretation/check; missing value not invented |

Validated rendering fell from **5/6 to 4/6**. Rendering is not semantic certification: the candidate copied the scalar correctly while contradicting it in prose. Improvements in two cases do not compensate for that factual regression. These small samples are acceptance evidence, not statistical proof of prompt causality.

All twelve trials used only permitted evidence, made no extra tool executions and left memory facts/revisions unchanged. Complete inputs/outputs: `artifacts/q1e-live.json`; assessments: `artifacts/q1e-assessed.json`.

## Verification and disposition

Focused suites: **63 passed in 1.85 seconds**. Candidate regression passed **1,819 tests** while Ollama was unavailable. After rejection, the original instruction and runtime module were restored byte-for-byte; the final restored-runtime regression passed **1,819 tests in 50.65 seconds**. Evaluation resumed after the user started Ollama; readiness failures caused no generations.

No Q1E runtime change remains. Q1C stays **FAILED live acceptance**, and Q1A limitations remain open. Remaining problems include semantic errors in written-out quantities, variable recommendations and conservative partial-date validation. No second improvement was attempted. Packaging/Python 3.13 were not repeated: no compatibility or packaging change remained. No commits, pushes or additional checkpoint work.
