# Model Quality & Reasoning A/B Evaluation

Date: 2026-11-19. Experimental checkpoint; production behavior was not changed.

## Conclusion

**C. INCONCLUSIVE**

Thinking is explicitly supported and was observed with `think: true`, but the primary 1,024-token experiment produced no complete ON final answers. Output-budget interference, timeouts, severe available-memory pressure, and an incomplete bounded pilot prevent a defensible comparison of technical accuracy or conversational quality. This is evidence against deploying ON under these conditions, not evidence that its unobserved answers are factually better or worse.

Neither mode qualifies as a reliable technical assistant from this checkpoint: OFF made a serious SQLite recovery error; ON did not deliver evaluable primary answers. The current OFF default remains unchanged. Do not activate the rejected Quality 2.0 persona or switch models on this evidence.

## Environment and preserved baseline

| Setting | Actual value |
| --- | --- |
| OS / architecture | Windows / AMD64 |
| Inference harness | Python 3.12.10 |
| Ollama | 0.40.16, existing validated loopback endpoint |
| Model | `qwen3.5:4b`, GGUF, qwen35, 4.2B, Q4_K_M |
| Digest | `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04` |
| Renderer / parser | qwen3.5 / qwen3.5 |
| Metadata thinking values | `[false, true]`; reported model default true, explicitly overridden per request |
| Active central persona | Restored 3,320-character instruction, SHA-256 `7426b160dc81f2b404ffa84e9d277faf956f1b7845057df3f9e4828ff02cfcae` |
| Production settings | OFF, temperature 0.2, 1,024 output tokens, 24,000 input-content characters, 10 retained turns, 180-second model timeout |
| System RAM reported by psutil | 7,879,598,080 bytes, approximately 7.34 GiB usable |

The persona digest above is over its raw UTF-8 text; fixture/request hashes in the data use the evaluator's canonical serialization where applicable. The previous persona rejection and restoration are documented in [Conversation Quality 2.0](CONVERSATION_QUALITY_2_REPORT.md). The existing omission notice and conversation assembly remain in place. No second-pass answer rewriting was added.

## Protocol and bounds

The existing validated `OllamaClient` performs inference. A developer-only subclass observes allowlisted metadata without changing its pool, metadata cache, model validation, request construction, or final-answer validation. `dataclasses.replace` supplies temporary per-mode settings. One sequential evaluation worker ran at a time. No model was pulled, explicitly unloaded, restarted, or replaced.

Each case and mode gets independent temporary conversation/memory databases and the existing production conversation session. Fixture IDs, wording, categories and turn sequences are unchanged. Web search/reading and provider credentials are disabled in the temporary settings; application launching is blocked by the harness. No private conversation or user memory is loaded. Actual generated earlier replies are retained within each case; after a failed turn, remaining turns of that case/mode are unrun. A failure never becomes conversation history.

The ten selected scenarios are five technical cases, two social cases, two Taglish cases and one continuity case, totaling 16 turns per mode if all complete. Selection is filtered in original fixture order; mode order alternates OFF/ON, then ON/OFF. Six reached first-turn matched inputs have identical per-pair input hashes. Follow-up histories necessarily contain each mode's real earlier replies; no cross-mode reply substitution occurs.

Finite limits: capability verification at most two chat calls / 360 seconds; pilot 1,200 seconds cumulative across resumes; separate diagnostic 600 seconds; total active evaluation 2,700 seconds / 200 chat calls / 1,000 instrumented HTTP calls. Individual primary model calls have a 180-second timeout, clamped to remaining study time. Retries do not reset these limits. The terminal OFF language-switch timeout had only **9.328 seconds** remaining; it is a study-deadline-censored observation, not evidence that OFF needs more than its normal 180-second timeout. The preceding completed tiredness OFF call was also deadline-clamped, to 23.437 seconds.

The pilot stopped at its time bound before all ten scenarios completed. Full evaluation and technical repetitions were gated off because ON had no usable primary finals. No unrun case is counted as a success or factual failure. The 64-case inventory in the summary data explicitly records coverage and missing cases.

### Capability verification

Same synthetic committed-rollback question and active persona, one call per mode, ordinary output budget:

| Mode | Result | Wall time | Observed activation |
| --- | --- | --- | --- |
| OFF | Complete 242-character answer; 47 reported generation tokens | 22.243 s | Explicit false, no thinking field content |
| ON | Timeout; no final or response metrics | 180.363 s | Requested, not demonstrably active in this particular call |

The first OFF call reported 13.060 s model loading. This was the first observed call, not a controlled cold start. Subsequent pilot responses established actual ON activation: three returned a nonempty separate thinking field, `done_reason: length`, exactly 1,024 generation tokens, and zero final-content characters. Only presence/length metadata was retained; thinking text was never logged or reviewed. These are **activated without a complete final answer**, not unsupported-mode failures. Timeout calls alone cannot establish activation.

The unchanged client accepts the explicit controls and rejects output-limited/missing final content as an error rather than exposing thinking as an answer. Offline tests also verify valid thinking-plus-final responses, unsupported controls, malformed responses and reasoning-tagged content rejection in developer tooling.

## Primary production-budget comparison

All values below exclude the separate capability probe and higher-budget diagnostic. Latency is per attempted user turn, including conversation routing/storage and model HTTP work, excluding resource sampling before/after. Timeout values are censored. Completed-case sums and individual HTTP/model durations are available in the JSON data; case sums do not include setup/resource-sampling time.

| Measure | Thinking OFF | Thinking ON |
| --- | --- | --- |
| Technical correctness | Clear committed-rollback failure; basic generator/undo answers acceptable; concurrency advice overconfident | Not measurable: no complete finals |
| Hallucination failures | One technical case with invented recovery advice | Not measurable; missing final is not an accuracy success |
| Conversation naturalness | Gratitude appropriate; tiredness reply semantically awkward | Not reviewable |
| Taglish | One completed tiredness response; meaning/relevance concerns | No final available |
| Median attempted-turn latency | 9.392 s, n=10; completed-only median 9.208 s, n=9 | 176.253 s, n=6; all failed |
| p95 latency | Not estimated: small selected, censored sample | Not estimated: small selected, censored sample |
| Attempted-turn latency range | 2.728–35.453 s, includes one deadline-censored failure | 158.255–180.180 s |
| Incomplete responses | 1/10 attempted turns, study-deadline censored; 6/7 started cases complete | 6/6 attempted turns incomplete; 0/6 started cases complete |
| Output-limit / timeout | 0 / 1 deadline-censored | 3 / 3 ordinary 180-second timeouts |
| Synthetic complete final answers | 9 | 0 |
| Measured chat attempts | 10 | 6 |
| Memory impact | Available-RAM median 101.79 MiB across 18 snapshots | Available-RAM median 138.12 MiB across 12 snapshots; no causal claim |

### Case-level findings

These are agent reviews of synthetic final answers, not human acceptance scores. Human review fields for all nine dimensions remain unfilled in the data.

| Original case ID | OFF | ON | Factual/style finding |
| --- | --- | --- | --- |
| `thanks` | Complete, 15.202 s | Output limit, 172.382 s | OFF: brief, appropriate acknowledgement. ON has no final even for gratitude. |
| `detail` | Complete, 35.453 s | Output limit, 158.255 s | OFF explains lazy generator iteration and supplies a Fibonacci example; no generator execution-timing misconception observed. Runnable snippet checked separately. |
| `q2d-committed-rollback` | Both turns complete, 39.367 s summed | First turn timeout, 180.124 s; follow-up unrun | OFF initially distinguishes committed changes correctly. On correction, it falsely offers `VACUUM` as recovery, with a misleading schema-change qualification, and gives a confused backup-copy/ATTACH/INSERT sequence. Hard technical failure. |
| `q2d-persistent-undo` | Both complete, 11.436 s summed | First turn output limit, 162.822 s; follow-up unrun | OFF says history must be stored and that transactions alone do not preserve undo. Adequate basic answer, though incomplete as an implementation design. |
| `q2d-hot-row` | Both complete, 13.448 s summed | First turn timeout, 180.129 s; follow-up unrun | OFF rejects a universal optimistic-concurrency speed guarantee and explains low-conflict tradeoffs. Its claim that locking wins is too categorical without measurement, though the answer includes workload qualifications. |
| `q2d-tired-taglish` | Complete, 10.475 s | Timeout, 180.180 s | OFF avoids tasks/questions but says “Parang naglalaro ka lang sa sarili mo,” which distorts the tiredness/venting context. Fluent-looking language is not enough for relevance or empathy. |
| `q2d-language-switch` | First turn deadline-censored after 9.575 s; second unrun | Not run | No language-switch conclusion can be drawn. |
| `q2h-unseen-api` | Not run | Not run | Unknown private API and fabricated-docs behavior remain untested here. |
| `q2h-rubber-duck` | Not run | Not run | Second social scenario untested. |
| `q2h-taglish-correction` | Not run | Not run | Three-turn continuity/correction scenario untested. |

The remaining 54 cases were not expanded after the failed pilot gate. FPS/frame-time reasoning, missing/omitted history, exact memory recall, browsing claims, system-measurement and broader tool-safety scenarios consequently have no new live A/B result. Prior reports are historical context, not substitute measurements for this experiment.

Across completed OFF outputs: relevance/length vary by case; gratitude is concise, the generator request gets the requested detail, SQLite correction becomes misleading and overlong, and tiredness misses the intended emotional meaning. Persistent-undo and concurrency follow-ups retain local context. The injected SQLite correction was accepted even though the initial answer was already correct, followed by new misinformation. There is no basis to claim ON improves correction, uncertainty, repetition, naturalness, technical terminology, hallucination rate, or multi-step explanations. No unauthorized action appeared in recorded traces; the recovered first OFF trace was not checkpointed, so that trace is unknown rather than asserted empty.

### Reported generation metrics and loading

Metrics are available only when Ollama returned a payload. Nanosecond durations are converted here to seconds; exact originals are retained in the data.

| Metric | OFF, 9 returned payloads | ON, 3 returned payloads |
| --- | --- | --- |
| Loading median / range | 0.0093 s / 0.0054–12.4672 s | 0.0154 s / 0.0104–13.3942 s |
| Prompt evaluation median / range | 0.8268 s / 0.5259–1.7776 s | 1.2802 s / 1.0336–1.4207 s |
| Generation median / range | 7.7686 s / 0.7954–34.7358 s | 157.3891 s / 156.7660–161.4918 s |
| Prompt token count median / range | 675 / 654–774 | 664 / 652–666 |
| Generation token count median / range | 50 / 5–223 | 1,024 / 1,024–1,024 |
| Final characters median / range | 265 / 15–985 | 0 / 0–0 |

ON's counts combine generation including thinking; no separate thinking-token count is reported or inferred from characters. The three length-limited responses show the ordinary budget was exhausted before any final content. Timeouts return no usable generation/load metrics, so those fields are missing, not zero. Model loading recurred; cache/OS residency was not controlled. Medians over successful payloads exclude timeouts and are not an unbiased speed comparison.

### Resource observations

Before/after psutil snapshots are not peak measurements. Across the primary snapshots, available memory ranged from **1.51 to 219.13 MiB OFF** and **27.09 to 1,668.50 MiB ON**. This substantial and changing system memory pressure is a confounder; no process was closed or service restarted to change it. The 50-ms whole-system CPU samples ranged 0–66.7% OFF (median 35.6%) and 0–58.7% ON (median 43.05%); these are neither inference-average CPU nor mode-attributable costs.

Working-set sums cover only processes whose names begin with `ollama`: OFF 1.00–27.19 MiB, ON 4.80–27.75 MiB. They may double-count shared pages and can omit runner processes with other names or paged-out memory. They are not model-memory footprints. Existing `/api/ps` reported model `size_vram` 1,879,813,650 bytes where available in both modes; this is server-reported allocation, not a measured device peak or evidence of a thinking-related increase. No GPU framework was installed. Resources for the recovered first OFF response were not checkpointed.

## Separate higher-budget diagnostic

Only `detail` was repeated, in OFF/ON order, after at least two distinct primary ON output-limit failures. Both temporary clients used the same **2,048-token cap and 360-second timeout**; this deliberately changes two constraints relative to primary trials and cannot isolate which additional resource would help. It is a diagnostic, not another primary sample or an automatic fallback.

| Measure | OFF diagnostic | ON diagnostic |
| --- | --- | --- |
| Final/status | Complete, 798 characters | Timeout; no final |
| Wall time | 85.246 s | 360.176 s |
| Reported load / prompt / generation | 0.0221 / 2.1989 / 82.7308 s | Unavailable |
| Prompt / generation tokens | 666 / 213 | Unavailable |
| Thinking | Explicit false, none observed | Requested; this timed-out response alone cannot verify activation |
| Technical review | Fibonacci code works, but the final sentence incorrectly places the state update during the pause, before resuming | Not evaluable |

The assignment after `yield` executes when iteration resumes, not during suspension. This is a separate OFF technical failure in a separate budget condition. It is not pooled into the primary case counts. The one ON diagnostic did not demonstrate that a larger cap produces a usable answer; its timeout prevents knowing whether it would eventually finish or exhaust the larger cap.

Across all stages there were **20 known chat attempts**: 2 capability, 16 primary pilot, 2 diagnostic. The ledger contains **85 instrumented HTTP events**, including metadata and resource probes, excluding separately collected capability metadata/setup traffic. It does not purport to count every HTTP request made by unrelated applications or by uninstrumented initial inspection. Charged active evaluation time was **1,854.966 seconds** (30 min 54.966 s): capability 202.606 s, pilot 1,201.110 s including bounded shutdown/checkpoint overhead, diagnostic 451.250 s. Documentation, offline tests and CLI checks are outside this inference budget. No model trial was replayed to recover the checkpoint.

## Reproducibility, interruption and data

Use the opt-in developer CLI, preserving checkpoints between stages:

```powershell
py -3.12 -m scripts.evaluate_reasoning_ab --ollama --stage pilot --output <local-checkpoint.json>
py -3.12 -m scripts.evaluate_reasoning_ab --ollama --stage diagnostic --resume --output <local-checkpoint.json>
```

Use a local path outside a synced folder for the active checkpoint, then export sanitized results for review. These commands are instructions for reproducing a new experiment, not an instruction to rerun this finished study. `--resume` skips terminal successes and failures; interrupted trials stay incomplete rather than being silently replayed. Fixture/persona identity, model digest and Ollama version are checked; changes stop the experiment. A resumed outstanding request is conservatively charged its reserved timeout. Ctrl+C stops at the client boundary; cancellation cannot guarantee immediate termination of server-side inference or undo completed work. Server scheduling after timeouts is an uncontrolled condition.

The first pilot encountered Windows access denial while replacing its checkpoint in OneDrive. A complete OFF gratitude final and its HTTP metrics had survived in the file. Those were recovered without another model call; missing callback/resource fields are explicitly unknown. Developer tooling now bounds replacement retries, and the active checkpoint was moved to a unique OS-temporary path. The initial runtime and both capability calls remain charged to the study. Later evaluator error-classification/diagnostic improvements did not change primary model inputs; the in-flight pilot retained its older `timeout` label for the deadline-censored language-switch request. Raw records preserve that label and effective timeout; this report explains the censoring instead of rewriting measurements.

Sanitized review artifacts:

- [Capability verification](../benchmarks/REASONING_AB_CAPABILITY_2026-11-19.json): requested mode, final text and allowlisted metrics only.
- [Trial records](../benchmarks/REASONING_AB_STUDY_2026-11-19.json): synthetic finals, per-turn status, timing, input hashes, request controls, resource snapshots and empty human-review slots.
- [Summary and all 64 case coverage records](../benchmarks/REASONING_AB_SUMMARY_2026-11-19.json): separate pilot/diagnostic groups; missing values stay null.
- [Agent review](../benchmarks/REASONING_AB_AGENT_REVIEW_2026-11-19.json): categorical review separate from human scores.

No raw prompts, API bodies, private user data or private reasoning traces are logged. Fixture IDs refer to already-public synthetic inputs. Exact request input hashes support matching without duplicating inputs. Timing includes client errors and does not turn incompleteness into a quality score.

## Regression and preservation

| Check | Result |
| --- | --- |
| Before-implementation full regression, Python 3.12.10 | **1,574 passed**, 40.80 s |
| Added focused offline evaluator tests | **28 passed**; included in both full runs |
| Final full regression, Python 3.12.10 | **1,602 passed**, 42.68 s |
| Final full regression, Python 3.13.15 | **1,602 passed**, 43.59 s |
| Source CLI startup, doctor, version, help | All four exited **0**, isolated temporary data/profile; web disabled |
| Production preservation | **41 protected files** match starting SHA-256 hashes, including all existing Python runtime sources, entry point, `pyproject.toml` and actual `.env`; no new runtime Python source |
| Persona / fixtures | Raw persona SHA-256 unchanged, 3,320 characters; canonical fixture identity unchanged, 64 cases / 92 turns inventoried |
| Matched starting inputs | Six pilot pairs and one diagnostic pair have equal initial input hashes |
| Final current model | Installed digest matches recorded study digest; production config remains OFF / 1,024 / 24,000 / 10 / 180 s |
| Synthetic code checks | Both exact reviewed Fibonacci snippets ran and printed their expected sequences; in-memory SQLite commit → rollback → VACUUM retained the committed value |
| Diff whitespace | `git diff --check` passed; existing Windows line-ending warnings only |
| Hosted CI | Not run; these are local results |

The new files `scripts/evaluate_reasoning_ab.py` and `tests/test_reasoning_ab.py` are opt-in developer tooling only. Offline tests cover response/thinking separation and sanitization, invalid/unsupported responses, explicit controls and existing adapter use, model identity, temporary state/history, finite runtime/request limits, accumulated budgets across resume, conservative interruption accounting, bounded checkpoint retries, failed-trial non-replay, pilot/full gating, separate diagnostic prerequisites and opt-in-before-configuration behavior. Generated prose is not a unit-test exact-match oracle.

There were no production implementation changes, dependency additions, new models, user-database operations, V1 operations, GUI launches, web-provider actions, commits, pushes or tags. Existing unrelated working-tree changes were preserved. The six executable tools, permission boundaries, launch semantics, planning limits, research/citation verification, schemas, cache policy and roadmap were not edited. The experiment's temporary diagnostic cap/timeout are not production changes. [Sanitized verification record](../benchmarks/REASONING_AB_VERIFICATION_2026-11-19.json) accompanies the local test logs under `artifacts/`.

## Next action and limits

Manual review should inspect the SQLite correction and tiredness finals, then decide whether another isolated experiment under more stable memory conditions is worth its cost. A meaningful accuracy comparison still requires complete matched ON answers. Do not infer that a still larger generation cap will solve this: the finite diagnostic is separately documented, and neither production cap nor timeout was changed. Broader technical reliability remains unresolved even with thinking OFF.

No model change, persona rewrite or automatic continuation to another phase follows this checkpoint. The full 64-case live comparison, repetitions and human/native-language acceptance review were not completed; the report provides bounded failure evidence and explicit coverage gaps. Sampling used the same temperature and adapter options but no fixed seed or independent repetitions; selected-case medians have different prompt mixes and must not be turned into a general speed ratio.

**READY FOR MANUAL REVIEW**
