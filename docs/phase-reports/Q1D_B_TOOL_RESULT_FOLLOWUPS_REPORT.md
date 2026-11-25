# Q1D-B — Grounded tool-result follow-ups

**Status: READY FOR MANUAL REVIEW.**

## Change

The executor already validates tool contracts and reports success, verification, permission and provenance. Previously, historical follow-ups had no trusted result context and could fall through to generation. Q1D-A's structured-memory responses remain unchanged.

Added a transient numeric projection for `system.snapshot` and `calculator.evaluate`. Retention requires matching request/result tool names, SUCCESS, explicit verification, READ_ONLY permission and successful validation. Existing output validators are reapplied without executing a tool. Only calculator numbers, RAM quantities, CPU utilization and bounded provenance are retained; raw tool payloads never enter instructions.

At most one result per supported tool is retained. Expiry is five minutes or the smaller of five/configured history exchanges. Zero-turn history disables retention. New/resume/close, relevant execution failures, interrupted executions, unsupported tools and transcript-storage failures discard context; disabled tools cannot supply follow-ups. Controlled-agent executions use the same retention checks.

Strict historical questions receive deterministic answers. System answers include the original collection timestamp/source and explicitly say they are not current measurements. Missing fields are reported unavailable. Generic “What was the result?” answers only an immediate, unique calculator result; competing sources or multiple calculations within one agent exchange clarify. Explicit current-system requests still execute normally. Analytical wording stays model-backed.

No durable tool-result cache or schema change was introduced. Human-readable replies use existing transcript persistence; recognized follow-up exchanges are excluded from ordinary model/archive context. Structured memory is neither read nor modified by this path.

Changed: `src/capabilities/tool_followup.py`, `src/intelligence/conversation.py`, `src/diagnostics.py`, `tests/test_tool_result_followups.py`, this report.

## Verification

Focused suites: **166 passed in 4.50 seconds**, covering field matching, provenance, mutation isolation, verification/permission failures, missing data, ambiguity, expiry, disabled tools, zero context, lifecycle/resume, storage failure, analytical fallback and fresh measurements. Single full Python 3.12 regression: **1,779 passed in 58.61 seconds**. Compilation and whitespace checks passed.

Eight temporary-data conversations passed using actual local snapshots/calculations: available RAM, CPU usage, calculation result, missing result, competing results, resumed session, failed calculation and analysis. All seven deterministic follow-ups made **zero additional executions and zero generations**. Analysis made one Ollama generation and no additional execution; its input contained no tool measurements. Memory tables remained unchanged. Evidence: `artifacts/q1db-checks.json`; actual system values were deliberately not retained there.

## Limits and next step

Grammar and supported fields are intentionally narrow; storage/OS/process follow-ups and analytical interpretation are not added. Generic references clarify conservatively. Saved transcripts do not restore trusted result context after resume. Original transcripts still follow existing storage behavior.

Q1C remains **FAILED live acceptance**; Q1A model-quality limitations remain open. Model settings, permissions, tools, memory schema and Q1D-A behavior are preserved. Next: manual review only. No commits, pushes or further phase work. Python 3.13, packaging and hosted CI were not rerun.
