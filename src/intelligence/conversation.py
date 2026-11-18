from collections import deque
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from src.capabilities import create_registry
from src.capabilities.application_intent import application_request, format_application_result
from src.capabilities.applications import ApplicationRegistry, create_applications
from src.capabilities.contracts import LocalActionAuthorization, ToolResult, ToolStatus
from src.capabilities.executor import ToolExecutor
from src.capabilities.intent import calculator_request, format_result, guard_action_claim, unsupported_action
from src.capabilities.system_intent import format_system_result, guard_system_claim, system_request, unsupported_measurement
from src.capabilities.web_intent import format_web_result, guard_web_claim, web_request
from src.capabilities.web_search import DDGSSearchProvider, SearchRouter, TavilySearchProvider
from src.capabilities.web_reader import WebReader
from src.capabilities.web_content import SourceEvidence
from src.capabilities.web_read_intent import reading_request, answer_question, format_read_result
from src.capabilities.web_answer import grounded_answer
from src.intelligence.ollama_client import ChatMessage
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
    ):
        self._system_instruction = system_instruction
        self._generate = generate
        self._store = store
        self._memory = memory
        self._context_turns = context_turns
        self.applications = applications if applications is not None else create_applications()
        self.web_search = web_search if web_search is not None else SearchRouter()
        key = getattr(self.web_search, "api_key", getattr(self.web_search, "redaction_key", ""))
        self.web_reader = WebReader(web_reading_enabled, self.web_search.enabled, key)
        self.tools = ToolExecutor(create_registry(self.applications, self.web_search, self.web_reader))
        self._turns: deque[tuple[str, str]] = deque(maxlen=context_turns)
        self.new()

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    def history(self, *, for_model: bool = False) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        for user, assistant in self._turns:
            if for_model and (system_request(user) is not None or web_request(user) is not None
                              or reading_request(user) is not None or answer_question(user) is not None):
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

    def resume(self, session_id: str) -> None:
        sequence, turns = self._store.load_session(session_id, self._context_turns)
        self.session_id = session_id
        self._sequence = sequence
        self._pending_memory = None
        self._history_anchor = None
        self._turns.clear()
        self._turns.extend(turns)
        self.web_reader.clear()

    def reply(
        self, prompt: str, *, trace: Callable[[str, list[ChatMessage], int, bool], None] | None = None,
        memory_trace: Callable[[str, Intent, MemoryReply | None, str | None], None] | None = None,
        tool_trace: Callable[[ToolResult], None] | None = None,
    ) -> str | None:
        prompt = self.web_search.redact(prompt.strip())
        if not prompt:
            return None

        question = answer_question(prompt)
        request = None if question is not None else (reading_request(prompt) or calculator_request(prompt)
                  or application_request(prompt) or system_request(prompt) or web_request(prompt))
        unsupported = unsupported_measurement(prompt)
        if request is not None or unsupported is not None or question is not None:
            self._pending_memory = None
        intent = None
        if self._memory is not None and request is None and unsupported is None and question is None:
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

        if request is not None:
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
        elif question is not None:
            answer = grounded_answer(question, self.web_reader.evidence, self._generate, self.web_reader._key)
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
            if (request is not None and request.tool == "app.open"
                    and (tool_result.data or tool_result.status == ToolStatus.EXECUTION_FAILED)):
                raise StorageError(f"{answer} This exchange could not be saved. Check the application before retrying; launching is not rolled back.") from None
            raise
        self._history_anchor = None
        if request is not None and tool_result.verified and tool_result.data is not None:
            if request.tool == "web.search":
                self.web_reader.select_search(tool_result.data)
            elif request.tool == "web.read":
                self.web_reader.evidence[request.arguments["source_number"]] = SourceEvidence(**tool_result.data)
        self._turns.append((prompt, answer))
        return answer

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
