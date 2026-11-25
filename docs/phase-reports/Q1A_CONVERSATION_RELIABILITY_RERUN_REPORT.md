# Q1A — Live Local-Model Rerun

Date: 2026-11-21. **Outcome: FAILED acceptance again.**

Repeated the frozen Q1A baseline/candidate comparison after confirming that the user's Ollama service was responding. All **80 fresh model replies** completed without inference errors. The candidate still fails technical accuracy, task interpretation and language requirements, so it remains rejected and undeployed. No production source or configuration changed.

## Availability and controls

The initial readiness check timed out. The existing service was allowed to initialize and then responded successfully. It was neither restarted nor stopped during this rerun, and it remains running. No model was pulled.

- Ollama **0.40.16**, existing `qwen3.5:4b`.
- Digest verified before and after: `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`.
- Thinking OFF, temperature 0.2, 1,024 output tokens, 24,000-character input budget, 10 retained turns by default.
- Same saved baseline and frozen 171-character-delta candidate instructions; no retuning.
- Same original prompts: 15 development cases / 24 turns, plus 11 reserved/regression cases / 16 turns, per condition.
- One sequential worker; baseline development → candidate development → baseline acceptance → candidate acceptance. Finite 900-second stage deadlines and existing 180-second request timeout.
- Fresh temporary case databases, disabled web, prohibited application launches and desktop/system collection. No private user history or memory was loaded.

The earlier run also completed 80 real model replies after its startup issue resolved. These fresh results are additional evidence, not replacements for that run. They use new files under [Q1A_RERUN_2026-11-21](../benchmarks/Q1A_RERUN_2026-11-21/RUN.json); original records remain intact.

## Decisive fresh findings

**Committed transactions still fail.** The baseline says “No” but then claims rollback undoes the committed UPDATE. The candidate's development opening is correct, but its correction follow-up again recommends a savepoint created before COMMIT. More decisively, its reserved answer states:

> Issuing a ROLLBACK today will undo the transaction you started and committed yesterday, reverting all changes made in that session to their state before the commit.

That is false. The independent synthetic SQLite check from the original Q1A report remains applicable: committed values survive rollback, and a pre-commit savepoint is gone after COMMIT. This failure occurred with a responsive service and a complete model response.

**Autosave still becomes acknowledgement instead of assistance.** The candidate again replies “Got it.” to the autosave request, then “Understood. The Tile Painter uses a JSON file for autosave.” after the JSON clarification. It neither asks for the missing project context nor answers the task. The fresh baseline also remains unhelpful, offering another question rather than useful guidance after the clarification.

**Atomicity remains confused.** The candidate now calls per-brush-stroke capture of a before-snapshot the “atomic” part. That does not establish consistent persistence of canvas, history and cursor across restart. Its suggested in-memory sequence does not answer the persistence-atomicity question.

**Explicit Taglish switching fails in both conditions.** Both fresh responses to the explicit request for simple Taglish are entirely English. Some other language outputs vary; for example, the malformed cache wording from the original candidate did not recur, and its laptop response is clearer this time. That variation does not establish reliable requested-language adherence.

**Missing-history denial recurs.** The candidate's export-format reply says no details were supplied in the user's previous messages, despite receiving the trusted omission notice. The earlier SVG statement was supplied but deliberately excluded by the fixture's zero-turn context setting. The correct distinction is unavailable input versus a claim about the entire conversation.

**Other results vary.** The baseline's persistent-undo and humor replies are better than its original samples without any instruction change. Both conditions retain the two-local-player correction and answer greetings/thanks briefly. Both generator explanations are coherent in this rerun; the previous candidate example-limit inconsistency did not recur. Private API replies correctly acknowledge missing implementation. The baseline's reserved concurrency explanation introduces an unsupported/confused “newer version succeeds” validation rule, while the candidate describes detecting a conflict against the same expected version.

These mixed outcomes reinforce that isolated earlier wins were not reliable evidence of a policy improvement. A serious factual failure cannot be offset by shorter answers or better performance in another case.

## Fresh measurements

| Measure | Baseline | Frozen candidate |
| --- | --- | --- |
| Matched scenarios | 26 | 26 |
| Complete final replies / model calls | 40 / 40 | 40 / 40 |
| Inference errors | 0 | 0 |
| Tool calls / launch attempts | 0 / 0 | 0 / 0 |
| Median reply latency | 8.762 s | 6.088 s |
| Latency range | 1.302–72.055 s | 1.492–52.684 s |
| Median input characters | 3,419 | 3,590 |
| Maximum input characters | 3,861 | 4,080 |
| Median output characters | 171 | 121.5 |
| Output-character range | 4–1,117 | 4–1,076 |
| Omission notices | 2 | 2 |

Latency includes existing routing, model metadata/generation and temporary persistence. Startup readiness delays are excluded. Stage order, model loading, output length and system load are uncontrolled; no causal speedup is claimed. No fixed seed was supplied. This is a repeat of the known fixtures, not a new blind acceptance set.

The unchanged claim guards produced no fixed replacement outputs or credential-redaction markers. There was one model call per turn, no classifier or rewriting generation, and no silent output-budget increase. Complete new outputs and turn-level measurements are preserved in [BASELINE.json](../benchmarks/Q1A_RERUN_2026-11-21/BASELINE.json) and [CANDIDATE.json](../benchmarks/Q1A_RERUN_2026-11-21/CANDIDATE.json). All 26 fresh scenarios have explicit provisional pass/partial/fail judgments in [AGENT_REVIEW.json](../benchmarks/Q1A_RERUN_2026-11-21/AGENT_REVIEW.json); partial is not a full pass. Independent human/native-language review remains pending.

## Preservation and conclusion

All **42 protected runtime/configuration/packaging files** match the original Q1A starting hashes. The active persona is still the original 3,320-character instruction. Model identity remains unchanged, the candidate was not deployed, and the user's Ollama service was left running. No production database, original result file, model configuration, permission, tool registry or memory behavior was changed. No commit, push or Q1B implementation occurred.

This request reran the live model comparison. Backend unit suites were not rerun here; the earlier **1,698 passing tests on each Python version** are historical regression results for the same unchanged runtime, not fresh proof of model accuracy. See [VERIFICATION.json](../benchmarks/Q1A_RERUN_2026-11-21/VERIFICATION.json), [METRICS.json](../benchmarks/Q1A_RERUN_2026-11-21/METRICS.json) and [RUN.json](../benchmarks/Q1A_RERUN_2026-11-21/RUN.json).

Q1A's acceptance failure is confirmed with Ollama available. Keep the current production policy and the original report's bounded Q1B recommendations; do not deploy this candidate based on occasional better replies.

**FAILED**
