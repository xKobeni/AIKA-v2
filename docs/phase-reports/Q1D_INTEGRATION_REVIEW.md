# Q1D integration review

**Status: READY FOR MANUAL REVIEW.**

**Recommendation:** Q1D-A/B/C can be accepted together for their narrowly tested scope, with the analytical-quality limitations below. This does not accept Q1C or claim that Q1A is resolved.

## Findings and narrow fix

Reviewed the shared session routing, memory parser/replies, retained tool evidence, analytical validation and affected tests. No conflicting routing, unintended tool execution or memory mutation was found in the tested flows.

- A answers exact structured facts and distinguishes a current-message Godot assertion from saved Unity without modifying the saved fact.
- B answers historical tool questions from validated transient results. Calculator ambiguity, expired evidence, session resume and disabled results cannot silently supply a value. A memory reply does not become a calculator result.
- C receives only the requested verified metric and provenance, excluding saved project facts and raw tool payloads. Its replies remain explicitly historical. Pending memory deletion is canceled by an intervening tool follow-up, without deleting anything.

The rejected CPU draft stated that the snapshot “does not confirm whether … right now.” That is an uncertainty statement, not a claim about current measurements. Added a bounded grammatical exception for this specific epistemic-denial form. It exempts only the time phrase during temporal validation; original numbers, units, cross-metric claims, source checks and action/memory guards remain enforced. Affirmative current-state claims elsewhere still reject. No prompt/persona change or output rewriting was made.

## Verification

Focused unit/integration suites: **81 passed in 3.67 seconds**. Final regression: **1,819 passed on Python 3.12 (62.20 s) and 3.13 (58.70 s)**. Both environments passed dependency consistency and compilation checks; whitespace checks passed.

Five temporary-data conversational checks passed: combined memory/assertion/system/analysis, competing tool results, expired/resumed evidence, pending-memory cancellation and adversarial current claims. **Zero fresh model calls.** The actual previously generated CPU draft was replayed through the complete session with an identical model input and now validates; unsupported positive claims still reject. Snapshot fixtures passed the real executor/contracts. Query flows left saved facts/revisions unchanged, and follow-ups caused no extra executions.

Packaging passed: wheel runtime bytes matched source; a non-editable temporary installation passed `python -I scripts/check_installed.py`, isolated profile/configuration/SQLite restart checks and `pip check`. Existing system-site dependencies were reused with `--no-deps`; this was not a fresh dependency resolution.

Available hosted [Backend verification](https://github.com/xKobeni/AIKA-v2/actions/runs/44547126489) is successful for committed base `d5105c8`. It does **not** validate the uncommitted Q1D working tree. No workflow was dispatched.

## Limits and next development

Grammar and evidence lifetime remain deliberately narrow. Other uncertainty forms may still be conservatively rejected. Model explanations can be descriptive or speculate about causes; numeric grounding is not proof of sound reasoning. Replayed drafts establish integration, not fresh model reliability.

Q1C remains **FAILED live acceptance** and Q1A factual/Taglish limitations remain open. Next recommended work, only when separately authorized: improve analytical usefulness and cautious causal wording using a small held-out evaluation. No new phase was started.

This review changes only temporal validation, integration tests and this report. No model, persona, architecture, schema, permission changes, commits or pushes.
