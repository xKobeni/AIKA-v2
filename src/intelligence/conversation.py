from collections import deque
import re
from collections.abc import Callable
from dataclasses import replace
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4
from time import monotonic
from threading import Lock

from src.capabilities.discovery import capability_answer, clarification, unsupported_request
from src.capabilities import create_registry
from src.capabilities.application_intent import application_request, format_application_result
from src.capabilities.applications import ApplicationRegistry, create_applications
from src.capabilities.contracts import LocalActionAuthorization, ToolResult, ToolStatus, ToolRequest, ToolExecutionError, ToolInputError
from src.capabilities.registry import ToolLookupError
from src.capabilities.executor import ToolExecutor
from src.capabilities.intent import calculator_request, format_result, guard_action_claim, unsupported_action
from src.capabilities.system_intent import format_system_result, guard_system_claim, system_request, unsupported_measurement
from src.capabilities.web_intent import format_web_result, guard_web_claim, web_request
from src.capabilities.web_search import DDGSSearchProvider, SearchRouter, TavilySearchProvider
from src.capabilities.web_reader import WebReader
from src.capabilities.web_content import SourceEvidence
from src.capabilities.web_read_intent import reading_request, answer_question, format_read_result
from src.capabilities.web_answer import grounded_answer
from src.capabilities.web_answer import INSUFFICIENT
from src.capabilities.web_answer import _topics, _words
from src.capabilities.web_budget import request_budget, bounded_timeout
from src.capabilities.research import (research_question, temporal_context, prepare_query, ranked_candidates, publication_matches_day,
                                       safe_failure, log_summary, MAX_ATTEMPTS, MAX_SOURCES)
from src.intelligence.ollama_client import ChatMessage
from src.intelligence.ollama_client import OllamaError
from src.intelligence.planning import (agent_task, build_plan, call_identity, execution_outcome, execution_counts,
                                      record_summary, PlanError, MAX_EXECUTIONS, MAX_MODEL_CALLS, MAX_STEP_TEXT)
from src.intelligence.dataflow import (BindingError, validate_calculation, resolve_calculation, provenance,
                                      format_percentage, requested_percentage, evaluate_condition, format_condition)
from src.memory.chat import HistoryAnchor, MemoryReply, PendingMemory, ordinary_statement_reply, resolve_pending, respond
from src.memory.intent import Intent, parse_intent
from src.memory.store import MemoryInputError, MemoryStore
from src.storage.conversation_store import ConversationStore, StorageError


class ConversationSession:
    """Run a conversation and retain its most recent completed turns in memory."""

    def __init__(
        self,
        system_instruction: str,
        context_turns: int,
        generate: Callable[[list[ChatMessage]], str],
        store: ConversationStore,
        memory: MemoryStore | None = None,
        *, applications: ApplicationRegistry | None = None,
        web_search: SearchRouter | TavilySearchProvider | DDGSSearchProvider | None = None,
        web_reading_enabled: bool = False,
        web_debug: bool = False,
        grounded_generate: Callable[[list[ChatMessage]], str] | None = None,
        research_timeout: float = 180.0,
        timezone: str = "local",
        agent_generate: Callable | None = None,
        agent_timeout: float = 180.0,
    ):
        self._system_instruction = system_instruction
        self._generate = generate
        self._grounded_generate = grounded_generate if grounded_generate is not None else generate
        self._store = store
        self._memory = memory
        self._context_turns = context_turns
        self.applications = applications if applications is not None else create_applications()
        self.web_search = web_search if web_search is not None else SearchRouter()
        key = getattr(self.web_search, "api_key", getattr(self.web_search, "redaction_key", ""))
        self.web_reader = WebReader(web_reading_enabled, self.web_search.enabled, key)
        self._web_debug = web_debug
        self._research_timeout = research_timeout
        self._timezone = timezone
        self._agent_generate = agent_generate if agent_generate is not None else generate
        self._agent_timeout = agent_timeout
        self._request_lock = Lock()
        self.tools = ToolExecutor(create_registry(self.applications, self.web_search, self.web_reader), web_debug=web_debug)
        self._turns: deque[tuple[str, str]] = deque(maxlen=context_turns)
        self.new()

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    def history(self, *, for_model: bool = False) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        for user, assistant in self._turns:
            if for_model and (system_request(user) is not None or web_request(user) is not None
                              or reading_request(user) is not None or answer_question(user) is not None
                              or research_question(user) is not None or agent_task(user) is not None):
                continue
            messages.append({"role": "user", "content": self.web_search.redact(user)})
            messages.append({"role": "assistant", "content": self.web_search.redact(assistant)})
        return messages

    def new(self) -> None:
        self.session_id = uuid4().hex
        self._sequence = 0
        self._pending_memory: PendingMemory | None = None
        self._history_anchor: HistoryAnchor | None = None
        self._turns.clear()
        self.web_reader.clear()
        self.last_research = None
        self.last_agent = None

    def resume(self, session_id: str) -> None:
        sequence, turns = self._store.load_session(session_id, self._context_turns)
        self.session_id = session_id
        self._sequence = sequence
        self._pending_memory = None
        self._history_anchor = None
        self._turns.clear()
        self._turns.extend(turns)
        self.web_reader.clear()
        self.last_research = None
        self.last_agent = None

    def reply(self, prompt: str, **callbacks) -> str | None:
        """Reject overlapping/reentrant requests without changing the active exchange."""
        if not self._request_lock.acquire(blocking=False):
            return "Another request is already running in this conversation. Wait for its result before sending another."
        try:
            return self._reply(prompt, **callbacks)
        finally:
            self._request_lock.release()

    def _reply(
        self, prompt: str, *, trace: Callable[[str, list[ChatMessage], int, bool], None] | None = None,
        memory_trace: Callable[[str, Intent, MemoryReply | None, str | None], None] | None = None,
        tool_trace: Callable[[ToolResult], None] | None = None,
        research_progress: Callable[[str], None] | None = None,
        agent_cancelled: Callable[[], bool] | None = None,
        agent_progress: Callable[[dict], None] | None = None,
    ) -> str | None:
        if len(prompt) > 16000 or any(not char.isprintable() and char not in "\r\n\t" for char in prompt):
            return "Request exceeds the input limit or contains unsupported control characters. No action was executed."
        prompt = self.web_search.redact(prompt.strip())
        if not prompt:
            return None
        resolution = capability_answer(prompt, self) if not prompt.startswith("/") or prompt.casefold() == "/capabilities" else None
        memory_intent = parse_intent(prompt) if not prompt.startswith("/") else None
        if memory_intent is not None and memory_intent.action == "statement":
            memory_intent = None
        agent = agent_task(prompt) if resolution is None and memory_intent is None else None
        if not prompt.startswith("/") and agent is None and memory_intent is None:
            resolution = resolution or clarification(prompt) or unsupported_request(prompt)
        question = answer_question(prompt) if agent is None else None
        request = None if resolution is not None or memory_intent is not None or question is not None or agent is not None else (reading_request(prompt) or calculator_request(prompt)
                  or application_request(prompt) or system_request(prompt))
        research = research_question(prompt) if resolution is None and memory_intent is None and question is None and request is None and agent is None else None
        if request is None and question is None and research is None:
            request = web_request(prompt) if resolution is None and memory_intent is None and agent is None else None
        unsupported = unsupported_measurement(prompt)
        if unsupported is not None:
            research = None
        if resolution is not None or request is not None or unsupported is not None or question is not None or research is not None or agent is not None:
            self._pending_memory = None
        intent = None
        if resolution is None and self._memory is not None and request is None and unsupported is None and question is None and research is None and agent is None:
            pending, self._pending_memory = self._pending_memory, None
            intent, confirmation = resolve_pending(pending, prompt)
            intent = intent or parse_intent(prompt)
            if intent is not None:
                source = f"chat:{self.session_id}:{self._sequence + 1}"
                try:
                    with self._store._transaction(write=True) as db:
                        result = respond(intent, (user for user, _ in self._turns), self._memory, db, source,
                                         confirmation=confirmation, pending=pending, history_anchor=self._history_anchor,
                                         session_id=self.session_id, sequence=self._sequence,
                                         has_session_context=bool(self._turns))
                        if result is not None:
                            result = replace(result, answer=self.web_search.redact(result.answer))
                            sequence = self._store.save_exchange(
                                self.session_id, self._sequence, prompt, result.answer, connection=db,
                            )
                except (StorageError, MemoryInputError) as exc:
                    if memory_trace:
                        memory_trace(prompt, intent, None, "storage" if isinstance(exc, StorageError) else "validation")
                    raise
                if memory_trace:
                    memory_trace(prompt, intent, result, None)
                if result is not None:
                    self._sequence = sequence
                    self._pending_memory = result.pending
                    self._history_anchor = result.history_anchor
                    self._turns.append((prompt, result.answer))
                    return result.answer

        if resolution is not None:
            answer = resolution
        elif memory_intent is not None and self._memory is None:
            answer = "Structured memory is unavailable in this session; no memory operation was performed."
        elif agent is not None:
            answer = self._agent_reply(agent, tool_trace, research_progress, agent_cancelled, agent_progress)
        elif request is not None:
            if request.tool == "web.search":
                self.web_reader.clear()
            authorization = LocalActionAuthorization(request.tool, request.arguments["app_id"]) if request.tool == "app.open" else None
            tool_result = self.tools.execute(request, authorization=authorization)
            if tool_trace:
                tool_trace(tool_result)
            if request.tool.startswith("system."):
                answer = format_system_result(tool_result, prompt)
            elif request.tool == "web.search":
                answer = format_web_result(tool_result)
            elif request.tool == "web.read":
                answer = format_read_result(tool_result)
            else:
                answer = format_application_result(tool_result) if request.tool == "app.open" else format_result(tool_result)
        elif research is not None:
            answer = self._research_reply(research, tool_trace, research_progress)
        elif question is not None:
            answer = grounded_answer(question, self.web_reader.evidence, self._grounded_generate, self.web_reader._key, debug=self._web_debug)
        elif unsupported is not None:
            answer = unsupported
        elif unsupported_action(prompt):
            answer = "That desktop action is not implemented. I can launch approved applications with /open or evaluate arithmetic with /calc."
        else:
            answer = self._ordinary_reply(prompt, trace)
        answer = self.web_search.redact(answer)
        try:
            self._sequence = self._store.save_exchange(self.session_id, self._sequence, prompt, answer)
        except StorageError:
            if agent is not None and self.last_agent:
                self.web_reader.clear()
                self.last_agent["outcome"] = "storage_failed"
                if self.last_agent["executions"]:
                    raise StorageError(f"{answer}\nAgent results could not be saved. Operations already attempted are not rolled back; check actual application state before retrying.") from None
            if research is not None:
                self.web_reader.clear()
                if self.last_research:
                    self.last_research["outcome"] = "storage_failed"
                    log_summary(self._web_debug, self.last_research)
            if (request is not None and request.tool == "app.open"
                    and (tool_result.data or tool_result.status == ToolStatus.EXECUTION_FAILED)):
                raise StorageError(f"{answer} This exchange could not be saved. Check the application before retrying; launching is not rolled back.") from None
            raise
        self._history_anchor = None
        if research is not None and self.last_research:
            log_summary(self._web_debug, self.last_research)
        if request is not None and tool_result.verified and tool_result.data is not None:
            if request.tool == "web.search":
                self.web_reader.select_search(tool_result.data)
            elif request.tool == "web.read":
                self.web_reader.evidence[request.arguments["source_number"]] = SourceEvidence(**tool_result.data)
        self._turns.append((prompt, answer))
        return answer

    def _agent_reply(self, task, tool_trace, progress, cancelled, agent_progress=None) -> str:
        started = monotonic()
        summary = {"request_id": uuid4().hex, "outcome": "planning", "steps": [],
                   "executions": 0, "model_calls": 0, "elapsed_ms": 0.0}
        self.last_agent = summary
        lines = []
        current = None
        stopped = None
        limit_failure = None
        executed = set()
        cancellation_pending = False
        starts = {}
        observed = {}
        verified_calculations = {}
        condition_step = None

        def emit(event, row=None, **fields):
            nonlocal cancellation_pending
            if agent_progress is None:
                return
            payload = {"event": event, "total": len(summary["steps"]), **fields}
            if row is not None:
                payload.update({key: row[key] for key in ("number", "tool", "state", "category", "verified")})
            try:
                agent_progress(payload)
            except KeyboardInterrupt:
                cancellation_pending = True
            except Exception:
                pass  # Presentation failures cannot invalidate a real tool outcome.

        def begin(row):
            row["state"] = "running"
            row["started_at"] = datetime.now(UTC).isoformat()
            starts[id(row)] = monotonic()

        def finish(row):
            if row["finished_at"] is None:
                row["finished_at"] = datetime.now(UTC).isoformat()
                tick = starts.pop(id(row), None)
                row["duration_ms"] = round(max(0, monotonic() - tick) * 1000, 3) if tick is not None else 0.0
                row["result_summary"] = record_summary(row)

        def append_result(number, text):
            if len(text) > MAX_STEP_TEXT:
                text = text[:MAX_STEP_TEXT] + "\nResult display truncated at the configured output bound."
            lines.append(f"{number}. {text}")

        def checkpoint():
            if limit_failure:
                raise PlanError(limit_failure)
            if cancellation_pending or cancelled and cancelled():
                raise KeyboardInterrupt
            bounded_timeout(1)

        def generate(callback, messages):
            nonlocal limit_failure
            checkpoint()
            if summary["model_calls"] >= MAX_MODEL_CALLS:
                limit_failure = "model_budget"
                raise PlanError("model_budget")
            summary["model_calls"] += 1
            value = callback(messages)
            checkpoint()
            return value

        def execute(request, *, authorization=None):
            nonlocal limit_failure, cancellation_pending
            checkpoint()
            if summary["executions"] >= MAX_EXECUTIONS:
                limit_failure = "execution_budget"
                raise PlanError("execution_budget")
            identity = call_identity(request)
            if identity in executed:
                limit_failure = "duplicate_operation"
                raise PlanError("duplicate_operation")
            executed.add(identity)
            call = {"number": current["number"], "tool": request.tool, "state": "pending", "category": None,
                    "verified": False, "started_at": None, "finished_at": None, "duration_ms": 0.0}
            current["operations"].append(call)
            call["state"] = "running"
            if current["tool"] == "research":
                emit("tool", call)
            invoked = False
            try:
                checkpoint()
                summary["executions"] += 1
                current["attempts"] += 1
                begin(call)
                invoked = True
                result = self.tools.execute(request, authorization=authorization)
                call["state"], call["category"], call["verified"] = execution_outcome(result, request)
                if request.tool == "system.snapshot" and call["verified"]:
                    observed[current["number"]] = replace(result, data=deepcopy(result.data))
                if request.tool == "calculator.evaluate" and call["verified"]:
                    verified_calculations[current["number"]] = replace(result, data=deepcopy(result.data))
                if result.tool != request.tool:
                    result = replace(result, tool=request.tool, status=ToolStatus.INCONCLUSIVE, verified=False,
                                     data=None, error="Tool result did not match the requested operation.", failure_category="contract")
                if call["category"] in {"internal", "contract", "input_internal", "result_size"}:
                    limit_failure = "tool_internal_failure" if call["category"] != "result_size" else "result_size"
            except KeyboardInterrupt:
                call["state"], call["category"] = "inconclusive" if invoked else "cancelled", "interrupted"
                raise
            except Exception:
                call["state"], call["category"] = "inconclusive", "internal"
                raise
            finally:
                finish(call)
                if current["tool"] == "research":
                    emit("tool", call)
            if tool_trace:
                try:
                    tool_trace(result)
                except KeyboardInterrupt:
                    cancellation_pending = True
                except Exception:
                    pass
            return result

        def research_progress(message):
            checkpoint()
            if progress:
                progress(message)

        try:
            with request_budget(self._agent_timeout):
                emit("planning")
                checkpoint()
                plan = build_plan(task, self.tools.registry, lambda messages: generate(self._agent_generate, messages))
                condition_step = next((step for step in plan if step.condition is not None), None)
                summary["steps"] = [{"number": step.number, "tool": step.request.tool if step.request else "research",
                                     "state": "pending", "category": None, "attempts": 0,
                                     "depends_on": list(step.depends_on), "operations": [], "verified": False,
                                     "started_at": None, "finished_at": None, "duration_ms": 0.0,
                                     "result_summary": "Operation pending."} for step in plan]
                emit("validated")
                for step, row in zip(plan, summary["steps"]):
                    checkpoint()
                    if any(summary["steps"][dep - 1]["state"] != "succeeded" for dep in step.depends_on):
                        row["state"], row["category"] = "skipped", "dependency_failed"
                        lines.append(f"{step.number}. Skipped: a required earlier operation was not verified.")
                        finish(row)
                        emit("step", row)
                        continue
                    current = row
                    resolved = None
                    if step.calculation is not None:
                        row["binding"] = provenance(step.calculation, step.number)
                        emit("binding", row)
                        checkpoint()
                        try:
                            intent = validate_calculation(step.calculation, step, plan[:step.number - 1])
                            source = step.calculation.numerator.source_step
                            resolved = resolve_calculation(step.calculation, intent, observed,
                                                           summary["steps"][source - 1]["state"])
                            row["binding"] = provenance(step.calculation, step.number, collected_at=resolved[3]["collected_at"])
                        except BindingError as exc:
                            row["state"], row["category"] = "skipped", str(exc)
                            append_result(step.number, f"Skipped: verified numeric inputs are unavailable [{exc}]. No calculator call was made.")
                            finish(row)
                            emit("step", row)
                            current = None
                            continue
                        checkpoint()
                    if progress and agent_progress is None:
                        progress(f"Running operation {step.number} of {len(plan)}...")
                    checkpoint()
                    begin(row)
                    if step.research is None:
                        emit("step", row)
                    checkpoint()
                    if step.research is not None:
                        text = self._research_reply(step.research, None, research_progress, execute_tool=execute,
                            generate=lambda messages: generate(self._grounded_generate, messages))
                        outcome = (self.last_research or {}).get("outcome", "failed")
                        row["state"] = "succeeded" if outcome == "grounded" else "inconclusive" if outcome == "insufficient_evidence" else "failed"
                        row["category"] = outcome
                        if outcome == "interrupted":
                            row["state"] = "inconclusive" if row["attempts"] else "cancelled"
                            raise KeyboardInterrupt
                        row["verified"] = row["state"] == "succeeded"
                    else:
                        request = resolved[0] if resolved is not None else step.request
                        authorization = (LocalActionAuthorization("app.open", request.arguments["app_id"])
                                         if request.tool == "app.open" else None)
                        result = execute(request, authorization=authorization)
                        row["state"], row["category"], row["verified"] = execution_outcome(result, request)
                        if resolved is not None and row["verified"]:
                            row["binding"]["verified"] = True
                            text = format_percentage(result, intent, resolved[1], resolved[2], resolved[3], source, step.number)
                        elif request.tool == "app.open":
                            text = format_application_result(result)
                            if row["state"] == "failed" and result.data:
                                text += " A launch may have been initiated; check the application before retrying."
                        elif request.tool.startswith("system."):
                            text = format_system_result(result, step.instruction)
                        else:
                            text = format_result(result)
                    # Record known tool outcomes before checking cancellation/deadline again.
                    append_result(step.number, text)
                    finish(row)
                    emit("step", row)
                    current = None
                    checkpoint()
                states = [row["state"] for row in summary["steps"]]
                summary["outcome"] = ("succeeded" if all(state == "succeeded" for state in states) else "partial" if "succeeded" in states
                                      else "inconclusive" if "inconclusive" in states else "failed")
                if condition_step is not None and summary["outcome"] == "succeeded":
                    checkpoint()
                    emit("condition_evaluating")
                    checkpoint()
                    step = condition_step
                    intent = requested_percentage(step.instruction)
                    source = step.calculation.numerator.source_step
                    decision = evaluate_condition(step.condition, step.calculation, intent, observed,
                        summary["steps"][source - 1]["state"], verified_calculations.get(step.number), step.number)
                    checkpoint()
                    summary["condition"] = decision
                    summary["steps"][step.number - 1]["condition"] = decision
                    lines[:] = [format_condition(decision, intent, observed[source].data)]
                    emit("condition_result", condition_result=decision["condition_result"], selected_branch=decision["selected_branch"])
                    checkpoint()
        except KeyboardInterrupt:
            stopped = "interrupted"
        except OllamaError as exc:
            stopped = "model_timeout" if exc.kind == "timeout" else "model_unavailable"
        except PlanError as exc:
            stopped = str(exc)
        except BindingError as exc:
            stopped = str(exc)
        except ToolInputError:
            stopped = "invalid_input"
        except ToolLookupError as exc:
            stopped = "tool_unavailable" if exc.status == ToolStatus.DISABLED else "unknown_tool"
        except ToolExecutionError as exc:
            stopped = "budget_exhausted" if getattr(exc, "code", None) == "workflow_budget" else "tool_failure"
        except Exception:
            stopped = "invalid_plan" if not summary["steps"] else "internal_failure"
        finally:
            if stopped:
                summary["outcome"] = stopped
                if current is not None and current["state"] == "running":
                    current["state"] = ("inconclusive" if current["attempts"] else "cancelled" if stopped == "interrupted"
                                        else "skipped" if stopped in {"execution_budget", "duplicate_operation", "budget_exhausted"} else "failed")
                    current["category"] = stopped
                for row in summary["steps"]:
                    if row["state"] == "pending":
                        row["state"], row["category"] = ("cancelled" if stopped == "interrupted" else "skipped"), stopped
                    if row["finished_at"] is None:
                        finish(row)
                        emit("step", row)
                self.web_reader.clear()
            summary["elapsed_ms"] = round((monotonic() - started) * 1000, 1)
            summary["counts"] = execution_counts(summary["steps"])
        if stopped:
            guidance = ("Conditions support only free/used system-drive or used-RAM percentages, one below/above/at-most/at-least "
                        "threshold from 0 to 100 (up to three decimal places), and immediate warning/normal text. "
                        "Equality, nested conditions and conditional actions are unsupported." if stopped == "unsupported_condition" else
                        "Supported operations: arithmetic, explicit approved app launches, system snapshots/processes, "
                        "and public web research. Separate operations with ';' or 'then'.")
            lines.append(f"Agent stopped [{stopped}]. No further operations were started. {guidance}")
            if any(row["state"] == "inconclusive" for row in summary["steps"]):
                lines.append("An attempted operation could not be verified. Check its actual state before retrying.")
            skipped = sum(row["state"] == "skipped" for row in summary["steps"])
            if skipped:
                lines.append(f"{skipped} remaining operation(s) skipped.")
        elif summary["outcome"] != "succeeded":
            lines.append("Some operations were not verified; dependent operations were skipped." if summary["counts"]["skipped"]
                         else "Some operations were not verified; see the recorded outcomes.")
        if condition_step is not None and "condition" not in summary:
            lines.append("Condition was not evaluated; neither warning nor normal branch was selected.")
        rows = summary["steps"]
        if rows:
            lines.append("Steps: " + "; ".join(f"{row['number']} {row['tool']} [{row['state']}]" for row in rows))
            for row in rows:
                if row["tool"] == "research" and row["operations"]:
                    lines.append(f"Research operations for step {row['number']} ({len(row['operations'])} calls): " + ", ".join(
                        f"{call['tool']} [{call['state']}]" for call in row["operations"]))
        lines.append(f"Execution status: {summary['outcome']}.")
        lines.append(f"Total: {len(rows)} | " + " | ".join(f"{count} {state}" for state, count in summary["counts"].items()))
        emit("summary", outcome=summary["outcome"], counts=dict(summary["counts"]))
        return "\n".join(lines)

    def _research_reply(self, question: str, tool_trace, progress, *, execute_tool=None, generate=None) -> str:
        started = monotonic()
        summary = {"request_id": uuid4().hex, "provider": None, "candidates_evaluated": 0,
                   "attempted_providers": [], "read_attempts": 0, "successful_reads": 0, "failed_reads": 0,
                   "usable_sources": 0, "validation_outcome": "not_run", "failures": [], "outcome": "failed", "elapsed_ms": 0.0}
        self.last_research = summary
        self.web_reader.clear()
        def step(message):
            bounded_timeout(1)
            if progress:
                progress(message)
        def execute(request):
            bounded_timeout(1)
            result = (execute_tool or self.tools.execute)(request)
            if tool_trace:
                tool_trace(result)
            bounded_timeout(1)
            return result
        try:
            if not question or len(question) > 300 or not question.isprintable():
                return "Use /research <question> with 1 to 300 printable characters."
            plain_query = prepare_query(question, {"target_date": None})
            vague = not (_topics(plain_query) - {"here", "there"}) and re.search(r"\b(?:this|that|it|here|there)\b", plain_query, re.IGNORECASE)
            if plain_query.casefold() in {"", "this", "that", "it", "this topic"} or vague:
                return "Provide a specific web-search query before researching; earlier private conversation is not sent automatically."
            if self.web_search.enabled is not True or self.web_reader.network_enabled is not True or self.web_reader.enabled is not True:
                summary["outcome"] = "disabled"
                return "Web research is disabled. Current external information cannot be verified: enable AIKA_WEB_SEARCH_ENABLED and AIKA_WEB_READING_ENABLED explicitly. No network request was made."
            temporal = temporal_context(question, self._timezone)
            with request_budget(self._research_timeout):
                step("Searching...")
                searched = execute(ToolRequest("web.search", {"query": prepare_query(question, temporal)}))
                mode = getattr(self.web_search, "mode", getattr(self.web_search, "name", "ddgs"))
                default_attempt = "ddgs" if mode == "auto" else mode
                summary["attempted_providers"] = [name for name in (searched.data or {}).get("attempted_providers", [default_attempt]) if name in {"ddgs", "tavily"}]
                if not searched.verified or searched.data is None:
                    summary["failures"].append({"stage": "search", "category": safe_failure(searched)})
                    return f"Research could not verify current information. {searched.error or 'Search failed.'}"
                summary["provider"] = searched.data["provider"]
                summary["candidates_evaluated"] = len(searched.data["results"])
                self.web_reader.select_search(searched.data)
                step("Evaluating sources...")
                candidates = ranked_candidates(searched.data, question, temporal)
                if not candidates:
                    summary["outcome"] = "no_results" if not searched.data["results"] else "no_eligible_sources"
                    return "Research could not verify current information: no relevant supported HTTPS source was returned."
                usable = {}
                for number in candidates[:MAX_ATTEMPTS]:
                    if summary["successful_reads"] >= MAX_SOURCES:
                        break
                    step("Reading selected source...")
                    summary["read_attempts"] += 1
                    result = execute(ToolRequest("web.read", {"source_number": number}))
                    if not result.verified or result.data is None:
                        summary["failed_reads"] += 1
                        summary["failures"].append({"source": number, "category": safe_failure(result)})
                        continue
                    item = SourceEvidence(**result.data)
                    summary["successful_reads"] += 1
                    self.web_reader.evidence[number] = item
                    if temporal["require_publication_day"] and not publication_matches_day(item.published_at, temporal):
                        summary["failures"].append({"source": number, "category": "date_unverified"})
                        continue
                    usable[number] = item
                summary["usable_sources"] = len(usable)
                if not usable:
                    summary["outcome"] = "no_usable_evidence"
                    return "Research could not verify the requested information: sources were unavailable, unsupported, or lacked a verifiable publication date for the requested local day. No model guess was substituted."
                step("Preparing an evidence-backed answer...")
                summary["validation_outcome"] = "pending"
                answer = grounded_answer(question, usable, generate or self._grounded_generate, self.web_reader._key,
                                         debug=self._web_debug, research_context=temporal, concise=True)
                bounded_timeout(1)
                accepted = any(f"[{number}] {item.fetched_url}" in answer for number, item in usable.items())
                outcome = "grounded" if accepted else "insufficient_evidence"
                if not accepted and answer.startswith("Grounded answer generation"):
                    outcome = "model_timeout" if "timed out" in answer else "model_unavailable"
                elif not accepted and "[malformed_json]" in answer:
                    outcome = "malformed_json"
                summary["outcome"] = outcome
                summary["validation_outcome"] = "accepted" if accepted else outcome
                if accepted:
                    provider_label = "DDGS" if searched.data["provider"] == "ddgs" else "Tavily"
                    answer += f"\nSearch provider: {provider_label}."
                    if searched.data.get("fallback_used"):
                        answer += " Explicitly enabled fallback used: " + " -> ".join(searched.data["attempted_providers"]) + "."
                if accepted and temporal["require_publication_day"]:
                    answer += f"\nRequested local publication day: {temporal['target_date']} ({temporal['local_timezone']}). Publication date does not independently establish the event date."
                elif accepted and any(item.published_at is None for item in usable.values()):
                    answer += "\nSome publication dates are unavailable; recency cannot be independently established."
                if accepted and "compare" in question.casefold():
                    covered = set().union(*(_words((item.title or "") + " " + item.content) for item in usable.values()))
                    if _topics(question) - covered:
                        answer += "\nThe read pages did not cover every requested subject; a complete comparison could not be verified."
                return answer
        except KeyboardInterrupt:
            summary["outcome"] = "interrupted"
            summary["validation_outcome"] = "interrupted"
            self.web_reader.clear()
            return "Research was interrupted. No current answer was verified and no further requests were made."
        except ToolExecutionError as exc:
            exhausted = getattr(exc, "code", None) == "workflow_budget"
            summary["outcome"] = "budget_exhausted" if exhausted else "failed"
            summary["validation_outcome"] = "budget_exhausted" if exhausted else "not_run"
            self.web_reader.clear()
            return ("Research stopped because its overall operation budget was exhausted. No current answer was verified." if exhausted
                    else "Research could not complete safely. No further operations or model guesses were made.")
        except Exception:
            summary["outcome"] = "internal_failure"
            summary["validation_outcome"] = "internal_failure"
            self.web_reader.clear()
            return "Research failed internally. No further requests or unsupported answer were produced."
        finally:
            summary["elapsed_ms"] = round((monotonic() - started) * 1000, 1)

    def _ordinary_reply(self, prompt: str, trace) -> str:
        messages: list[ChatMessage] = [
            {"role": "system", "content": self.web_search.redact(self._system_instruction)},
            *self.history(for_model=True),
            {"role": "user", "content": prompt},
        ]
        if trace is not None:
            trace(self.session_id, messages, self.turn_count, self._sequence // 2 > self.turn_count)
        answer = self._generate(messages)
        if self._memory is not None:
            answer = ordinary_statement_reply(answer)
        return guard_web_claim(guard_system_claim(guard_action_claim(answer)))
