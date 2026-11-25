# Q1A — Conversation Accuracy & Natural Response Reliability

Date: 2026-11-21. **Outcome: FAILED acceptance.**

The compact instruction candidate produced some development improvements, but it did not resolve committed-transaction recovery and regressed on reserved task interpretation, atomicity guidance and language quality. It was **rejected, not deployed**. The starting runtime persona and every other runtime source remained unchanged throughout; no production rollback was necessary. Passing backend tests does not establish improved model answers.

**Live rerun:** At the user's request, the same frozen comparison was repeated with their Ollama service confirmed responsive. All 80 fresh replies completed without inference errors; serious factual and conversational failures remained. Original evidence is retained. See [the separate rerun report](Q1A_CONVERSATION_RELIABILITY_RERUN_REPORT.md) for new outputs, measurements and case assessments. The candidate remains rejected.

## Baseline and inspection

Verified the checkout's origin is `https://github.com/xKobeni/AIKA-v2.git`. Before any file changes, the complete Python 3.12.10 suite passed **1,698 tests in 46.32 seconds**. Inspected the foundation/roadmap and the actual conversation assembly, persona, Ollama transport/validation, prompt budgeting, memory/action/system/web claim guards, evaluation script, quality tests/fixtures, failed Quality 2.0 report and reasoning A/B report.

The active starting instruction was the restored **3,320-character** persona, not the rejected Quality 2.0 candidate. The existing 1,742-character evidence policy and conditional 135-character history-omission notice remained intact. The earlier broad rewrite's factuality, fabricated-documentation, generator and language failures informed the regression selection; it was not reactivated. The A/B result remains INCONCLUSIVE and did not authorize thinking ON.

Actual settings: `qwen3.5:4b`, thinking OFF, temperature 0.2, 1,024 ordinary output tokens, 24,000 input-content characters and 10 retained turns. Explicit omitted-history fixtures retain their original zero-turn override. Ollama **0.40.16** served the existing model with digest:

`d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`

Ollama was initially stopped. The first model check failed before generation. The installed service was started on the existing validated loopback endpoint; tags/version probes, including a direct socket probe, then timed out during startup. One restart affected only that task-owned process. The last visible startup stage was GPU discovery, but its role as the cause was not established. A final bounded probe eventually succeeded, so live evaluation proceeded. No model was pulled and no permanent server/configuration setting was changed. These startup delays are separate from the successful-generation measurements. After evaluation, only the verified task-owned server/descendants were stopped, restoring the initial stopped-service state; the task startup log was redacted.

## Confirmed defects and root-cause analysis

The first reproduction used six development scenarios and nine actual model calls:

- **Committed SQLite edits:** the opening “No” was followed by a claim that rollback undoes the UPDATE, and advice to revert a prior commit/use a pre-update savepoint. That does not fit the stated UPDATE → COMMIT → ROLLBACK sequence.
- **Persistent undo:** the initial reply proposed storing forward SQL and re-executing it to restore the previous state. Forward replay is not an undo-history design. The follow-up improved, but did not remove the earlier misleading advice.
- **Private API:** the model admitted it had not seen the code, then invented specific possible internals and added a generic offer. It did not fabricate supplied documentation in this run.
- **Contention:** the model rejected guaranteed optimistic superiority, although broad no-locks/locking-overhead language still needed implementation qualifications.
- **Venting in Taglish:** the reply shifted into an unnatural story/flow metaphor rather than acknowledging coding fatigue.
- **Humor:** “Got it. That's a new development. What do you plan to do about them?” missed the joke and imposed an unnecessary task question.

The broader baseline also falsely said an omitted mode list “wasn't provided in our chat,” despite receiving the omission notice; suggested that a canvas explicitly described as saved might not be persisted; and overstated crash safety of a temporary-file/rename pattern.

These are model interpretation, knowledge and instruction-adherence failures in the observed samples. The required current prompts were intact, recent history was retained where configured, and no ordinary input exceeded **4,105 characters** in either condition. Only the two deliberately missing-history follow-ups had omission notices per condition. There is no evidence here of a transport truncation, wrong memory lookup or lost required history causing the technical failures. The broad “acknowledge simple facts” style rule also appears to compete with task requests: the candidate's autosave exchange became acknowledgements instead of useful clarification/analysis. This is a supported interpretation of outputs, not proof of an internal model mechanism.

An independent in-memory SQLite check confirmed that COMMIT retained the updated value after rollback, and `ROLLBACK TO` a pre-commit savepoint failed because that savepoint no longer existed. An independent Python check confirmed generator invocation does not execute its body until iteration. Both reviewed generated code examples ran; valid code did not excuse inconsistent explanation text. No production data was used. See [fact checks](../benchmarks/Q1A_FACT_CHECK_2026-11-21.json).

## Small change tested

One experimental candidate changed four short style fragments, adding **171 characters** overall: 3,491 total, with a 1,749-character style section. It was tested through the existing evaluator's `instruction=` parameter. No runtime change or second generation was used.

| Target | Experimental wording |
| --- | --- |
| Requested language | “Follow the user's requested language, including natural Filipino-English, without forced slang.” |
| Speech act | “Recognize jokes as jokes. For venting, acknowledge without advice; give a practical step only when help is requested.” |
| Technical reliability | “For technical tasks, respect the stated sequence and preconditions. Don't invent unseen code/docs or promise mechanisms without their prerequisites.” |
| Corrections | Replace “accept corrections” with “reconcile corrections with the actual supplied turns” |

The rest of the persona and **entire evidence policy were unchanged**. No benchmark-specific SQL answer, API behavior or other technical answer was embedded in the instruction. Candidate text/hash and exact replacements are preserved in the [rejected-candidate manifest](../benchmarks/Q1A_CANDIDATE_MANIFEST_2026-11-21.json). It was frozen before Q1A acceptance outputs were inspected and was not tuned afterward.

## Evaluation design and completeness

Reused original fixture wording, IDs, categories and user-turn sequences: **15 development cases**, the **10 existing held-out cases**, and the legacy generator case as an acceptance regression. That is **26 matched cases / 40 turns per condition**, **80 total model calls**, all with complete final answers and zero Ollama errors.

The existing held-out fixtures and their historical findings were already known from earlier checkpoints; this was a reserved-output check, not an independently authored blind benchmark. The generator regression was selected before reserved Q1A outputs were collected. No acceptance result was used to revise this candidate.

Execution was sequential: baseline reproduction → candidate development → baseline development supplement → baseline reserved/regression → candidate reserved/regression. Each stage used the same model/options and unchanged client pooling/cache policy. First-turn inputs differed only by the **171-character instruction delta**; subsequent inputs used each condition's real earlier generated replies. Starting synthetic context and requested retention settings were equivalent; histories were not swapped or leaked across cases. No fixed seed or independent repetitions were used, so isolated wins are observations, not reliable causal estimates.

Each case had a fresh temporary conversation/memory database. Evaluation settings used temporary data paths, disabled search/reading and empty provider credentials. The existing harness blocked application launches; additional guards prohibited desktop/system collection. There were **zero tool calls, launch attempts, external-provider calls or private-data inputs** in the selected cases. Production user history and memory were not opened.

There was one ordinary generation per turn, no classifier, no second agent and no response-rewriting pass. The unchanged client rejected incomplete/output-limited responses; none occurred. Per-stage deadlines were finite (600 or 900 seconds), with the unchanged 180-second model timeout clamped by the existing shared request budget. Total selected generation requests were bounded to the 80 executed turns. No retry with a larger output cap or thinking mode was introduced.

The existing evaluator stores the complete final assistant text. An audit of the unchanged deterministic claim guards found no fixed replacement outputs or credential-redaction markers in these records, so those guards did not substitute the observed model final texts. The raw API final field was not separately duplicated, and private thinking was never logged. Complete prompts/answers, latency, input sizes and call counts are in the combined [baseline](../benchmarks/Q1A_BASELINE_2026-11-21.json) and [rejected candidate](../benchmarks/Q1A_CANDIDATE_2026-11-21.json) records; original stage files are retained as provenance.

## Before/after findings

These are provisional implementation-agent reviews of complete exchanges, not independent human/native-speaker acceptance. `Partial` is **not** a full pass. Serious regressions reject the candidate regardless of an aggregate score. All 26 scenarios have explicit per-condition `passed` flags and rationales in [the case review](../benchmarks/Q1A_AGENT_REVIEW_2026-11-21.json); existing human-score slots remain empty.

| Scenario(s) | Baseline | Candidate | Finding |
| --- | --- | --- | --- |
| Greeting, thanks, acknowledgement | Pass | Pass | Brief replies without service pitches; no improvement needed in these samples. |
| Coding frustration | Pass | Pass | Both give a focused debugging next step; candidate is more verbose. |
| Correcting player count | Pass | Pass | Both answer two local players from supplied correction. |
| Explain, then simplify | Pass with caveat | Pass with caveat | Same topic retained and simplified; no-locks language still needs implementation qualifications. |
| Missing mode history | Fail | Partial | Baseline falsely denies earlier provision. Candidate admits a gap, but its first reply changes ownership to “My puzzle modes.” |
| Committed rollback | Fail | Fail | Both still offer invalid savepoint recovery after COMMIT. Candidate follow-up also suggests INSERT for an existing row. |
| Persistent undo | Fail | Pass | Candidate drops misleading forward-SQL replay and explains separate snapshots/diffs; limited observed improvement. |
| Hot-row concurrency | Pass with caveat | Pass with caveat | Both reject a universal speed guarantee; broad internal-lock assumptions remain. |
| Unknown `cache.persist_all()` | Partial | Pass | Candidate stays more general about missing evidence, although it still starts with “Got it.” |
| Tired Taglish | Fail | Fail | Baseline metaphor is unnatural; candidate gives unsolicited rest-before-work advice despite coding already underway. |
| Bug joke | Fail | Pass | Candidate recognizes the joke without a task question, but remains generic. |
| English → Taglish | Fail | Fail | Both attempt the switch; fluency/technical translation remain unreliable. |
| User-reported 250 FPS | Pass | Partial | Both deny independent verification. Candidate adds unsupported positive appraisal and does not supply the requested careful formulation. |
| Generator regression | Pass | Partial | Core timing and runnable code are correct in both; candidate introduces a 10-versus-20 example-description inconsistency. |
| Committed versus uncommitted paraphrase | Pass | Pass | Correct distinction in this reserved sample does not cancel the failed development exchange. |
| Undo after reopen | Partial | Fail | Candidate narrows atomicity to “the history stack itself,” failing to account for canvas/history/cursor consistency. |
| “Optimistic must always win” | Pass with caveat | Pass with caveat | Both reject the premise and describe conflict validation. |
| Unseen `layoutpack.render_transaction()` | Pass | Pass | Neither invents supplied documentation or claims browsing in this run. |
| Autosave request, then JSON correction | Fail | Fail, regression in usefulness | Baseline asks for context and offers a pattern, but overclaims crash safety. Candidate only acknowledges and repeats JSON facts. |
| Rubber-duck joke | Pass | Pass, flatter | Both recognize a joke; “That's a classic joke” is not a naturalness gain. |
| Done tonight, just venting | Partial | Fail | Baseline adds a question; candidate directs “Take a break.” |
| Taglish color correction | Partial | Pass | Both keep blue/purple; candidate's correction turn is clearer Taglish. |
| Slow laptop, usage unknown | Partial | Fail | Candidate uses malformed/invented “cache na gumupok” and a weak display-workload hypothesis. No measurements were performed or claimed. |
| Missing older export format | Partial | Partial | Both avoid guessing SVG, but ask poorly focused follow-ups; candidate's session-versus-visible-context wording remains ambiguous. |

### Representative complete short outputs and technical excerpts

**Humor, limited improvement**

- Before: “Got it. That's a new development. What do you plan to do about them?”
- Candidate: “That's a funny twist on the usual \"bug\" definition.”

**Autosave, reserved task-interpretation regression**

For “Add safe autosave to the project we discussed,” candidate: **“Got it.”** After the user specifies the tile painter and JSON, candidate: **“Understood. The Tile Painter uses a JSON file for autosave.”** These are complete outputs, not truncated summaries. They do not clarify the missing project context or answer the task.

**Atomicity, reserved technical regression**

Baseline's follow-up recommends saving current canvas and history together. Candidate instead says: **“The atomic unit here is the history stack itself.”** Persisted canvas, history and cursor must remain consistent, or current state must be safely derived from a consistent persisted representation; merely serializing the history array does not establish that contract. The implementation was not supplied, so narrowing the atomic unit this way was unjustified.

**Committed edit, unresolved factual failure**

Candidate opens with the correct COMMIT/ROLLBACK distinction, then says: **“To restore the old level, you would need to revert to a previous savepoint…”** The synthetic SQLite check disproves that recommendation for the stated committed sequence. A correct first sentence is not a pass for the exchange.

## Performance measurements

All values describe the same 40-turn selection per condition. Latency includes existing conversation handling, model metadata/generation and temporary persistence, not only generation compute.

| Measure | Baseline | Rejected candidate |
| --- | --- | --- |
| Complete final responses / model calls | 40 / 40 | 40 / 40 |
| Extra classification/rewriting generations | 0 | 0 |
| Inference errors / tool calls | 0 / 0 | 0 / 0 |
| Median latency | 7.728 s | 5.448 s |
| Latency range | 1.279–51.084 s | 1.133–40.072 s |
| Median input characters | 3,419 | 3,590 |
| Input-character range | 3,327–3,944 | 3,498–4,105 |
| Median final-output characters | 181 | 109 |
| Final-output length range | 4–1,009 | 4–873 |
| History-omission notices | 2 | 2 |

Shorter replies, including unhelpful acknowledgements, contribute to candidate latency. Stage order, first model loading, generated-history length and OS/model residency were not controlled; no warm request is labeled a true cold start and no causal speedup is claimed. Startup service delays are excluded. Separate generation-token counts/load durations were not captured by this evaluator. Exact turn metrics and matching-input checks are in [metrics](../benchmarks/Q1A_METRICS_2026-11-21.json).

## Verification and files

| Check | Actual result |
| --- | --- |
| Initial full Python 3.12.10 regression | **1,698 passed**, 46.32 s |
| Final full Python 3.12.10 regression | **1,698 passed**, 50.31 s |
| Final full Python 3.13.15 regression | **1,698 passed**, 45.05 s |
| Runtime/configuration preservation | All **42 protected files** match starting hashes: every existing runtime Python source, actual `.env` and `pyproject.toml` |
| Model identity | Existing digest verified before/after inference; no model/configuration/thinking change |
| Live completeness | 26 matched scenarios, 80 complete model replies, one generation per turn, zero inference errors |
| Guard/output audit | No deterministic claim-guard substitutions or credential-redaction markers detected |
| Production data, tools, memory | No production DB access; existing seven tools, permissions, memory/storage, research, agent and inference contracts unchanged |
| Hosted CI | Not run or claimed |

No production code, existing evaluation script, original fixture or test was modified. There is no retained response-policy implementation change. Existing tests already cover the relevant assembly, one-call behavior, omission/privacy and deterministic routes; mocked tests are not cited as proof of output-quality improvement. The [verification record](../benchmarks/Q1A_VERIFICATION_2026-11-21.json) captures final regression and preservation results.

Deliverables are this report and `docs/benchmarks/Q1A_*`: complete condition/stage outputs, original-fixture selection copies, experimental/baseline instruction text, rejected manifest, per-case review, performance metrics, independent fact checks and startup diagnostics. Reproduction/review helper scripts and local test logs are under ignored `artifacts/q1a_*`; no new application dependency or framework was introduced. No V1 changes, schema migrations, production database edits, commits or pushes occurred.

For a bounded rerun using the existing evaluator, load one saved case-selection JSON, use a fresh output filename and pass the chosen saved instruction explicitly. Do not install the rejected instruction as the runtime default:

```python
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts.evaluate_conversation import evaluate, load_cases
from src.config import load_config
from src.capabilities.web_budget import request_budget

with TemporaryDirectory() as root, request_budget(900):
    settings = replace(load_config(), data_dir=Path(root), web_search_enabled=False,
                       web_reading_enabled=False, tavily_api_key="")
    evaluate(settings, load_cases([Path("docs/benchmarks/Q1A_ACCEPTANCE_CASES_2026-11-21.json")]),
             Path("artifacts/q1a-new-review.json"),
             instruction=Path("docs/benchmarks/Q1A_BASELINE_INSTRUCTION_2026-11-21.txt").read_text(encoding="utf-8"))
```

The selected cases contain no system/desktop collection requests. The actual experiment additionally prohibited those collectors at the adapter and used the existing launch-blocking harness. Re-running is an explicit new inference experiment; it is not automatic continuation of this checkpoint.

## Remaining limits and recommended Q1B scope

Q1A has **not** demonstrated a safe general response improvement to deploy. The active baseline still has factuality, omitted-history, task-interpretation and Taglish weaknesses. The candidate's small gains do not satisfy the no-serious-new-regression gate. Scores here are agent assessments; independent technical and native-language review remains incomplete. There were no repetitions or statistical reliability estimates, and 38 of the original 64 fixture cases were not sampled in this checkpoint.

For a separately scoped Q1B, first add independently authored technical/intent paraphrases and repeated paired trials, with technical errors as hard rejection gates. Investigate explicit, evidence-backed technical verification using existing approved research/execution contracts, rather than another broad persona rewrite. Any additional model calls, automatic source use or product behavior would need separate justification/approval; none was implemented here. Preserve the distinction between user assertions, verified evidence and unknown implementation, and assess useful task completion separately from shorter or friendlier replies.

The checkpoint stops with the rejected experiment, completed evidence and unchanged production behavior. Q1B was not started.

**FAILED**
