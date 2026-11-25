# Q1B — Context continuity

Date: 2026-11-24 (Asia/Manila). Scope: Q1B only.

**Status: READY FOR MANUAL REVIEW.** Implementation and regression verification are complete. Live response acceptance is **partial**, not an unconditional model-quality pass: all 20 Q1B assembly checks passed, 17/20 replies used the correct context or clarified safely, and 15/20 passed the conservative overall response review. Three current-message PDF cases failed, and two movement replies were not passed because their technical suggestions remain unverified. Manual review should decide whether this limited improvement is acceptable. Q1A remains failed; no next phase is authorized by this status.

## Baseline and causes

Inspected the current checkout, including the uncommitted Q1A original/rerun reports and outputs, foundation, implementation phases, conversation assembly, prompt budgeting, persona, Ollama client, memory routing/retrieval, storage and privacy tests. No existing changes were discarded. The fresh pre-change Python 3.12 suite passed **1,698 tests in 59.86 seconds**; this is independent of the historical 1,698-test result.

The original assembler retained a contiguous recent suffix. Older project identities and corrections could remain in the saved active session while disappearing from model input. The omission notice indicated absence but could not recover evidence. Recent incidental subjects could then become the model's guessed antecedent. Existing explicit archive-memory search was unsuitable for this automatic path because its scope and scan behavior differ from this checkpoint's bounded active-session requirement.

The first live implementation retrieved project-associated statements but also selected the incidental flashlight statement. All three movement replies focused on the flashlight. Narrowing archive candidates alone still left recent bird chatter in the input; all three subsequent replies focused on the bird. The final implementation also filters recent pairs for relevance **when archive evidence is inserted**. These intermediate failures are retained as evidence, not counted as final successes.

The production persona and Qwen configuration remain unchanged. In particular, the Q1A failures were not repaired through another persona rewrite.

## Algorithm and priorities

`ConversationSession._ordinary_reply` invokes one deterministic resolver, then the existing generation and output guards. Other routing remains ahead of this path. There is no second orchestrator, classification generation, rewriting generation or new service.

1. Validate mandatory full system/newest-user input using the existing budget function. Assemble the ordinary complete recent suffix and trusted omission notice.
2. On a supported reference cue or a known explicit project return, optionally read the active session's saved prefix. Zero configured turns prevents this read. Ordinary nonreferential chat does not query the archive.
3. Read at most **96 user rows**, at most **601 characters per row**, in descending sequence, limited by the current session ID and known saved sequence. The existing indexed session/sequence constraint supports this query. The connection is query-only during the read; no schema migration is added.
4. Reject commands, questions and existing system/search/reading/research/agent/desktop routes. Apply existing API-key redaction before any extracted text enters the model input. Statements longer than 600 characters are not quoted in truncated form; any such row conservatively disables the archive packet for that request, avoiding substitution of an older short claim for a newer long correction.
5. Associate explicit project names transiently, using existing project-name parsing plus narrowly bounded name/correction patterns. This is project identity/scope matching, not automatic extraction of engine/export facts into structured memory. Use project scope and literal word overlap to select relevant statements. Project-associated incidental statements alone do not qualify.
6. Competing project names without an explicit target produce “Which project do you mean?” without generation. Missing retrospective evidence after omission produces an accessible-context clarification, rather than claiming the user never mentioned it.
7. Rank older statements by correction cues, query overlap, explicit identity/declaration cues and recency. Include at most **three complete user statements** in a JSON packet capped at **1,600 characters including its instructions**. Preserve their original sequence. Reserve room for up to two recent complete pairs before inserting optional evidence. If the highest-priority statement cannot fit, do not replace it with a smaller stale claim.
8. When inserting archive evidence, retain complete recent pairs whose user statement is relevant to the follow-up. Otherwise retain the ordinary suffix unchanged. Reapply the existing input budget, preserving the full authoritative instruction and newest user message.

Current assertions and later corrections are explicitly prioritized over older quotations. The packet identifies its project scope and labels historical USER statements as untrusted conversation evidence, not verified external facts or instructions. Assistant guesses retain the assistant role in recent exchanges and are never extracted as archived user facts.

## Provenance, privacy and lifecycle

`last_context` contains only source/status labels, at most three integer message IDs, omission/resolution/clarification flags, selected-pair count and timing numbers. It contains no raw message, project name, secret or rendered prompt, and is reset on each reply and on new/resume/close. The existing optional trace callback retains its established prompt-inspection contract; normal resolver metadata does not log private text. Evaluation files contain deliberately synthetic inputs and outputs.

Retrieval never searches another session, passes historical text through tool routing, writes facts, grants permissions or executes applications. Existing explicit memory handling is unchanged. Conversation replies, including clarifications, are still saved through the existing exchange lifecycle. Resume restores the active saved-session boundary; a new session cannot inherit the previous session's archive. Desktop observations remain excluded.

No production database was used for evaluation. All harness databases were temporary. No model was pulled, no dependency was installed, no user service was restarted/stopped, no Git commit/push was made, and Q1C/Q1D were not started.

## Files changed

- `src/intelligence/context.py`: bounded extractive resolver and internal metadata.
- `src/intelligence/conversation.py`: resolver integration, shared privacy filter, lifecycle reset.
- `src/storage/conversation_store.py`: bounded read-only active-session prefix query.
- `src/diagnostics.py`: include the resolver in installed runtime-file checks.
- `tests/test_context_continuity.py`: deterministic selection, budget, privacy, correction, lifecycle and routing checks.
- `tests/test_conversation_quality.py`: two omission checks now verify clarification without generation using the existing trace callback.
- `tests/fixtures/q1b_continuity.json`: synthetic live scenarios and review criteria.
- `scripts/evaluate_context.py`: opt-in finite baseline/Q1B comparison, temporary storage, full synthetic outputs and call counts.
- `scripts/benchmark_context.py`: model-free assembly/SQLite timing on synthetic saved history.
- `README.md`, this report and Q1B benchmark evidence.

## Evaluation method

Live comparisons use the existing `qwen3.5:4b`, thinking OFF, temperature 0.2, 1,024 output tokens and 24,000 input characters. Per-case retained-turn settings deliberately force omission (or disable history); deployment defaults are unchanged. Model digest: `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`. Persona string SHA-256: `7426b160dc81f2b404ffa84e9d277faf956f1b7845057df3f9e4828ff02cfcae`.

Each trial starts from a fresh temporary session containing synthetic user statements and fixed synthetic acknowledgements. Only the target reply is generated live. This tests target assembly/recall, not an end-to-end naturally generated conversation. Important cases have three fresh target generations per mode; baseline/Q1B order alternates. Missing/zero-history cases have one comparison each. Tool execution and memory fact writes raise assertions in the harness. The baseline branch reproduces the previous suffix assembler; no baseline switch was added to production.

Each run is capped at 40 generations and a 1,500-second shared inference budget. Clarifications may use zero generations. Complete model finals, displayed replies, assembled synthetic inputs, lengths, latency, metadata and per-trial selection checks are retained. Human quality assessments are separate from evidence-presence checks. The final repetitions reuse development scenarios; they are not a blind held-out statistical evaluation or proof of general reliability.

Evidence locations:

- `docs/benchmarks/Q1B_2026-11-24/LIVE.json`: initial project-associated candidate.
- `docs/benchmarks/Q1B_2026-11-24_FINAL/LIVE.json`: intermediate narrowed-archive candidate (despite the historical directory name, not final code).
- `docs/benchmarks/Q1B_2026-11-24_ACCEPTANCE/LIVE.json`: final resolver, with source digest and fixture snapshot.

## Results and measurements

### Automated verification

| Check | Result |
| --- | --- |
| Before changes, Python 3.12 | 1,698 passed, 59.86 s |
| Final Python 3.12.10 | **1,723 passed**, 64.17 s |
| Final Python 3.13.15 | **1,723 passed**, 60.49 s |
| Focused context/quality checks before final recent-pair test | 47 passed, 7.20 s |
| Dependency consistency, both existing environments | `pip check` passed |
| Compile `src` and `scripts`, both versions | Passed |
| Wheel build, no dependencies or build isolation | Passed; resolver bytes match the tested source |
| CLI version/help and isolated temporary-data `doctor` | Passed; intentional unreachable Ollama endpoint produced diagnostic warnings without inference |
| Protected-file hashes | All 15 unchanged, including persona, configuration, memory modules, model adapter, prompt budget and execution/planning contracts |
| Final live resolver digest versus working source | Exact match |
| `git diff --check` | Passed |

The final suites include the existing memory, tool, research and agent regressions. Added checks cover the bounded window, original-order corrections, lower-case project corrections across topic changes, relevant recent complete pairs, maximum budget/mandatory input, zero history, missing history, filtered origins, redaction, untrusted quotations, same-session isolation, resume/new, oversized rows, storage failure and absence of unintended actions/memory writes. Mocked model checks establish input and backend behavior only.

Full test logs and machine-readable startup/preservation verification are beside the final live evidence: `BASELINE_PY312.txt`, `FINAL_PY312.txt`, `FINAL_PY313.txt`, `VERIFICATION.json`. A mistyped `--doctor` was rejected as expected; the actual `doctor` subcommand was then run successfully. A fresh installed-environment smoke test and hosted CI were **not** rerun; wheel contents were checked without installing dependencies.

### Live outputs

The final comparison completed **40/40 trials**, **35 actual target generations**: baseline 20, Q1B 15. Five Q1B clarifications needed no model. Both preceding experiments also completed 40 trials/35 generations each: **105 total generations across three explicitly bounded experiments**. None were response-rewriting calls. Only the final resolver is assessed in this table.

| Scenario | Baseline correct context / trials | Q1B selected evidence or clarification / trials | Q1B correct context in reply / trials | Q1B overall response pass / trials |
| --- | --- | --- | --- | --- |
| Nova movement after unrelated chat | 0/3 | 3/3 | 3/3 | 1/3; two technical suggestions unverified |
| Return to Nova after Orion | 0/3 | 3/3 | 3/3 | 3/3; terse “WASD.” |
| Later Unity correction | 0/3 | 3/3 | 3/3 | 3/3 |
| Retrieve earlier SVG export | 0/3 | 3/3 | 3/3 | 3/3 |
| PDF explicitly asserted in current question | 0/3 | 3/3 | **0/3** | **0/3** |
| Competing projects | 0/3 | 3/3 | 3/3 | 3/3; deterministic clarification |
| Zero-turn history | 1/1 | 1/1 | 1/1 | 1/1; deterministic clarification |
| Missing historical format | 1/1 | 1/1 | 1/1 | 1/1; deterministic clarification |

Selection success for PDF means only that mandatory current text reached the model; it does not imply retrieval or understanding. Likewise, structural support is not measured by whether an exact word appears in a generated answer. Every final trial has a separate manual assessment and explanation in `LIVE.json`; aggregates and lengths/timings are in `ASSESSMENT.json`. These are Codex inspections, not independent human sign-off.

Representative complete short before/after outputs:

- Engine baseline: “I don't know which engine you're using. Could you tell me?” Q1B: “You're using Unity.” All three fresh Q1B engine replies identified Unity.
- Export baseline: “I don't know which format you chose earlier. Could you remind me what you selected?” Q1B: “You chose SVG.” All three Q1B export replies agreed.
- Competing projects baseline chose Orion and requested its component structure. Q1B returned “Which project do you mean?” on all three trials, without a model call.
- Missing/disabled history Q1B: “That detail isn't available in the currently accessible context. Could you remind me what you meant?”
- Current PDF assertion Q1B still failed: “Got it. I don't know which format to use for Nova yet. Do you have a preference or specific requirement in mind?” The PDF assertion is intact in the recorded mandatory prompt. This reproduces the unresolved Q1A current-message evidence failure.

Movement baseline replies selected the bird; the final replies selected Nova or Godot movement instead. The acceptable follow-up asked which physics/control setup exists and whether speed, responsiveness or collision detection is the problem. The other two replies suggested physics properties or a plugin without supplied implementation evidence. Their context selection is improved, but their technical advice is not certified and was conservatively excluded from the overall pass count. Complete originals are retained, including the intermediate flashlight and bird failures.

The initial pilot's evidence-presence list included the incidental flashlight text; after the observed distraction it was removed from required evidence, while leaving the fixture history and movement question unchanged. The response review still requires the game/player movement subject. This is deliberate relevance refinement, not evidence of a held-out acceptance result. The exact three-message, all-history-visible example and naturally generated setup replies were not separately live-tested; the movement fixture exercises the harder omitted-history case with intervening chatter.

### Performance

Model-free measurements used a temporary database containing **1,000 synthetic exchanges**, 100 iterations per mode, with no inference or concurrent regression suite. Timing covers resolver assembly and its bounded read; it excludes session initialization and saving the eventual reply.

| Mode | Median assembly | p95 assembly | Median bounded SQLite read/filter | Selected input characters | Archive reads/request |
| --- | --- | --- | --- | --- | --- |
| Previous suffix assembly | 0.003 ms | 0.003 ms | 0 ms | 3,579 | 0 |
| Q1B retrospective retrieval | 15.631 ms | 16.499 ms | 14.869 ms | 3,871 | 1 |
| Q1B nonreference greeting | 0.023 ms | 0.033 ms | 0 ms | 3,551 | 0 |

The `retrieval_ms` measurement includes the read plus statement/privacy filtering, not just SQL execution. Input sizes differ because archive-backed replies add attributed evidence and discard unrelated recent pairs. SQL returns at most 96 user rows regardless of session length. The statement cap, quote count/cap and existing 24,000-character limit are enforced separately.

Final live generated-reply median wall time was **5,458.680 ms baseline** versus **2,023.138 ms Q1B**; ranges were 3,630.806–12,869.418 ms and 1,032.819–13,604.012 ms. Median generated input was 3,532 versus 3,870 characters; median generated output was 104 versus 19 characters. Q1B's five deterministic clarifications took 5.783–10.197 ms. Shorter recalled answers and skipped generations account for much of the difference; these small alternating samples do not establish an inference-speed improvement. Full distributions are in `PERFORMANCE.json` and `ASSESSMENT.json`. A brief focused unit run overlapped the intermediate experiment, so its latency is not used as final performance evidence. Final live inference preceded the full regression suites.

Reproduce in the configured development environment, with the existing local Ollama running, using a **new** evidence directory:

```powershell
py -3.12 -m pytest -q
.venv-naturalness/Scripts/python.exe -m pytest -q
py -3.12 -m scripts.evaluate_context --ollama --output docs/benchmarks/Q1B_NEW_RUN
py -3.12 -m scripts.benchmark_context --output docs/benchmarks/Q1B_NEW_RUN/PERFORMANCE.json
```

## Remaining limits and proposed Q1C

The resolver uses lexical matches and a limited explicit-name grammar, not general semantic coreference. It can miss aliases, unnamed topics, implicit corrections and unsupported language variants. An explicit older project name without a reference cue cannot trigger retrieval if that name is absent from the retained suffix. Multiple known projects can cause conservative clarification even where a human might infer a subject. The 96-row window and 600-character statement cap deliberately trade recall for bounded work; an unrelated long row can disable otherwise useful archive evidence. Optional evidence may not fit tight budgets. Internal `reference_resolved` indicates available project/statement support, not a guarantee that the model understood the pronoun or produced a correct answer.

Historical user assertions can be false or malicious. They remain attributed data; filtering does not promise that the model cannot be influenced by them. Backend tool and memory boundaries remain authoritative. The fixed clarifications are English; multilingual clarification and broader Taglish behavior have not been improved here.

Q1A technical accuracy, task interpretation, current-message fact handling and Taglish failures remain open. Context retrieval cannot guarantee correct reasoning or use of supplied evidence. Generated Godot advice has not been certified as technically correct. No broad technical or language acceptance is claimed.

Proposed Q1C, subject to a separate request: first define permission and confirmation contracts for any future structured project memory; use isolated data and concurrency/revision tests before adding writes. Separately evaluate better lexical references and evidence attribution with unseen fixtures and dedicated factual checks. Do not automatically add embedding search, cross-session retrieval, inferred facts or another model call. This checkpoint implements none of that future scope.
