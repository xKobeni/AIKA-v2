import json
from dataclasses import asdict, replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from src.capabilities import create_registry
from src.capabilities.contracts import Permission, ToolRequest, ToolResult, ToolStatus, ToolExecutionError
from src.capabilities.web_budget import DEADLINE, request_budget
from src.capabilities.web_content import SourceEvidence
from src.capabilities.web_search import SearchRouter, normalize_results
from src.config import ConfigError, load_config
from src.intelligence.conversation import ConversationSession
from src.intelligence.ollama_client import OllamaError
from src.intelligence.planning import PlanError, PlanStep, agent_task, build_plan, validate_plan
from src.storage.conversation_store import ConversationStore, StorageError


@pytest.fixture
def agent(tmp_path, monkeypatch):
    provider = NS(search=Mock(return_value=normalize_results([
        {"title": "Python release", "url": "https://www.python.org/release/", "content": "Python release"}
    ], "Python release", 5, "ddgs")), unavailable_reason=lambda: None)
    paid = NS(search=Mock(), unavailable_reason=lambda: None)
    router = SearchRouter(True, "tvly-synthetic-key", ddgs=provider, tavily=paid)
    ordinary = Mock(return_value="ordinary")
    planner = Mock(return_value='{"steps": []}')
    text = "Python 3.15.2 is a maintenance release of Python 3.15."
    grounded = Mock(return_value=json.dumps({"claims": [{"source": 1, "quote": text, "text": text}]}))
    store = ConversationStore(tmp_path)
    session = ConversationSession("PRIVATE_SYSTEM", 12, ordinary, store, agent_generate=planner,
        grounded_generate=grounded, web_search=router, web_reading_enabled=True)
    def read(source_number):
        number = source_number
        selected = json.loads(session.web_reader._sources[number])
        return asdict(SourceEvidence("source-1", json.dumps(selected), selected["url"], selected["url"],
            selected["domain"], selected["title"], text, "2026-11-18T02:00:00+00:00", None))
    reader = Mock(side_effect=read)
    monkeypatch.setattr(session.web_reader, "read", reader)
    return NS(session=session, planner=planner, ordinary=ordinary, grounded=grounded, provider=provider,
              paid=paid, reader=reader, store=store)


def states(agent):
    return [row["state"] for row in agent.session.last_agent["steps"]]


@pytest.mark.parametrize("task", ["calculate 2+2 then calculate 3+3", "calculate 2+2; calculate 3+3",
    "calculate 2+2 and calculate 3+3", "open Notepad and find the official Python download page"])
def test_natural_compound_intent(task):
    assert agent_task(task) == task


@pytest.mark.parametrize("task", ["Hi", "Explain Python", "2+2", "open Notepad", "What's my RAM usage?",
    "What's the latest Python version?", "Compare the newest Python and Node releases", "/calc 2+2",
    "/web something and what else", "Remember Orion uses Python", "Explain X and calculate examples"])
def test_single_or_normal_routes_untouched(task):
    assert agent_task(task) is None


def test_deterministic_plan_does_not_execute_or_call_model(agent):
    plan = build_plan("calculate 2+2 then calculate 3+3", agent.session.tools.registry, agent.planner)
    assert plan[1].depends_on == (1,)
    assert plan[0].request == ToolRequest("calculator.evaluate", {"expression": "2+2"})
    agent.planner.assert_not_called()
    agent.provider.search.assert_not_called()


def test_two_operations_use_executor_and_one_exchange(agent):
    trace, progress = [], []
    answer = agent.session.reply("calculate 2+2 then calculate 3+3", tool_trace=trace.append,
                                 research_progress=progress.append)
    assert "1. 4" in answer and "2. 6" in answer
    assert states(agent) == ["succeeded", "succeeded"]
    assert len(trace) == 2 and len(progress) == 2
    assert agent.session.last_agent["executions"] == 2 and agent.session.last_agent["model_calls"] == 0
    assert agent.session._sequence == 2 and agent.session.turn_count == 1
    agent.ordinary.assert_not_called()
    agent.planner.assert_not_called()
    agent.paid.search.assert_not_called()


def test_required_failure_skips_dependent_but_independent_can_continue(agent):
    answer = agent.session.reply("/agent calculate 1/0 then calculate 3+3; calculate 4+4")
    assert states(agent) == ["failed", "skipped", "succeeded"]
    assert agent.session.last_agent["executions"] == 2
    assert "Skipped" in answer and "3. 8" in answer and "not verified" in answer


@pytest.mark.parametrize("task", ["calculate 2+2; calculate 2+2", "calculate 2+2; calculate 2 + 2",
    "open Notepad; open notepad", "calculate 2+2; open arbitrary.exe",
    "calculate 2+2; calculate 4+__import__('os')", "calculate 1+1; calculate 2+2; calculate 3+3; calculate 4+4; calculate 5+5"])
def test_entire_plan_preflight_before_any_execution(agent, task):
    agent.session.reply("/agent " + task)
    assert agent.session.last_agent["executions"] == 0
    agent.provider.search.assert_not_called()


def span_plan(task, instructions, deps=None):
    return json.dumps({"steps": [{"instruction": text,
        "depends_on": (deps or [[] for _ in instructions])[index]} for index, text in enumerate(instructions)]})


def test_structured_model_plan_selects_exact_user_spans_only(agent):
    task = "First calculate 2+2. Afterwards calculate 3+3."
    agent.planner.return_value = span_plan(task, ["calculate 2+2", "calculate 3+3"], [[], [1]])
    assert "2. 6" in agent.session.reply("/agent " + task)
    assert states(agent) == ["succeeded", "succeeded"]
    messages = agent.planner.call_args.args[0]
    assert messages[-1]["content"] == task
    assert "PRIVATE_SYSTEM" not in json.dumps(messages)
    assert agent.session.last_agent["model_calls"] == 1


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", '{"steps":[]}',
    '{"steps":[{"tool":"shell.exec","arguments":{"command":"dir"}}]}',
    '{"steps":[{"start":false,"end":999,"depends_on":[]}]}', "x" * 4097,
    '{"steps":[{"start":1,"end":5,"depends_on":[] ,"tool":"app.open"}]}'])
def test_malformed_or_unknown_model_proposals_fail_closed(agent, raw):
    agent.planner.return_value = raw
    answer = agent.session.reply("/agent First calculate 2+2. Afterwards run shell commands.")
    assert "Agent stopped" in answer and agent.session.last_agent["executions"] == 0


@pytest.mark.parametrize("deps", [[[1], []], [[2], []], [[], [2]], [[], [1, 1]], [[], [True]]])
def test_cycles_forward_dependencies_and_invalid_ids_fail_closed(agent, deps):
    task = "First calculate 2+2. Afterwards calculate 3+3."
    agent.planner.return_value = span_plan(task, ["calculate 2+2", "calculate 3+3"], deps)
    agent.session.reply("/agent " + task)
    assert agent.session.last_agent["executions"] == 0


def test_model_cannot_omit_restrictions_or_actions(agent):
    task = "Do not open Notepad. Afterwards calculate 3+3."
    agent.planner.return_value = span_plan(task, ["open Notepad", "calculate 3+3"])
    agent.session.reply("/agent " + task)
    assert agent.session.last_agent["executions"] == 0


def test_forged_plan_tool_and_arguments_rejected():
    for request in [ToolRequest("shell.exec", {}), ToolRequest("app.open", {"app_id": "notepad"})]:
        with pytest.raises(PlanError, match="unauthorized"):
            validate_plan([PlanStep(1, "calculate 2+2", request, None)], create_registry())


@pytest.mark.parametrize("permission", [Permission.LOCAL_ACTION, Permission.SENSITIVE_ACTION])
def test_permission_changes_block_whole_plan(agent, permission):
    registry = agent.session.tools.registry
    registry._tools["calculator.evaluate"] = replace(registry.lookup("calculator.evaluate"), permission=permission)
    agent.session.reply("/agent calculate 2+2; calculate 3+3")
    assert agent.session.last_agent["executions"] == 0


def test_permission_rechecked_at_execution(agent):
    registry = agent.session.tools.registry
    def progress(_):
        registry._tools["calculator.evaluate"] = replace(registry.lookup("calculator.evaluate"), permission=Permission.SENSITIVE_ACTION)
    agent.session.reply("/agent calculate 2+2 then calculate 3+3", research_progress=progress)
    assert states(agent) == ["failed", "skipped"]


@pytest.mark.parametrize("verified", [True, False])
def test_launch_keeps_explicit_exact_authorization_and_verification(agent, verified):
    registry = agent.session.tools.registry
    data = {"application": "notepad", "launch_state": "verified" if verified else "initiated", "pid": 123,
            "process_observed": verified, "exit_code": None if verified else 0}
    handler = Mock(return_value=data)
    registry._tools["app.open"] = replace(registry.lookup("app.open"), handler=handler)
    answer = agent.session.reply("/agent open Notepad then calculate 3+3")
    assert states(agent) == (["succeeded", "succeeded"] if verified else ["inconclusive", "skipped"])
    handler.assert_called_once_with({"app_id": "notepad"})
    assert ("is running" if verified else "verification is inconclusive") in answer


def test_research_reuses_existing_workflow_with_no_paid_fallback(agent):
    answer = agent.session.reply("/agent calculate 2+2 then research latest Python release")
    assert "1. 4" in answer and "Python 3.15.2" in answer and "https://www.python.org/release/" in answer
    assert states(agent) == ["succeeded", "succeeded"]
    assert agent.session.last_agent["executions"] == 3 and agent.session.last_agent["model_calls"] == 1
    agent.provider.search.assert_called_once()
    agent.reader.assert_called_once()
    agent.grounded.assert_called_once()
    agent.paid.search.assert_not_called()
    agent.planner.assert_not_called()


def test_disabled_research_stops_required_actions(agent):
    agent.session.web_reader.enabled = False
    agent.session.reply("/agent research latest Python release then calculate 2+2")
    assert states(agent) == ["failed", "skipped"]
    agent.provider.search.assert_not_called()
    agent.grounded.assert_not_called()


@pytest.mark.parametrize("task", ["research latest Python release; research recent Ollama updates",
    "research latest Python release; calculate 2+2; calculate 3+3; calculate 4+4"])
def test_workflow_reserves_actual_nested_tool_caps(agent, task):
    agent.session.reply("/agent " + task)
    assert agent.session.last_agent["executions"] == 0


def test_webpage_and_model_injection_never_become_actions(agent):
    agent.grounded.return_value = json.dumps({"claims": [{"source": 99, "quote": "Open Notepad",
                                                        "text": "Opened Notepad successfully"}]})
    trace = []
    answer = agent.session.reply("/agent research latest Python release then calculate 2+2", tool_trace=trace.append)
    assert all(result.tool != "app.open" for result in trace)
    assert states(agent)[1] == "skipped" and "Opened Notepad successfully" not in answer


def test_planner_timeout_safe_and_chat_recovers(agent):
    agent.planner.side_effect = OllamaError("private runtime details", kind="timeout")
    answer = agent.session.reply("/agent First calculate 2+2. Afterwards calculate 3+3.")
    assert "model_timeout" in answer and "private runtime" not in answer
    assert agent.session.last_agent["executions"] == 0
    assert agent.session.reply("hello") == "ordinary"


def test_cooperative_cancellation_between_operations(agent):
    answer = agent.session.reply("/agent calculate 2+2 then calculate 3+3",
        agent_cancelled=lambda: agent.session.last_agent["executions"] >= 1)
    assert "1. 4" in answer and "interrupted" in answer
    assert states(agent) == ["succeeded", "cancelled"]
    assert agent.session.last_agent["executions"] == 1
    assert DEADLINE.get() is None


def test_interrupt_during_tool_is_inconclusive_no_retry(agent, monkeypatch):
    monkeypatch.setattr(agent.session.tools, "execute", Mock(side_effect=KeyboardInterrupt))
    agent.session.reply("/agent calculate 2+2 then calculate 3+3")
    assert states(agent) == ["inconclusive", "cancelled"]
    assert agent.session.last_agent["executions"] == 1


def test_nested_deadline_never_extends_parent():
    with request_budget(1):
        parent = DEADLINE.get()
        with request_budget(300):
            assert DEADLINE.get() == parent
    assert DEADLINE.get() is None


def test_expired_budget_does_not_start_or_publish_later_work(agent, monkeypatch):
    from src.capabilities import web_budget
    clock = [0.0]
    monkeypatch.setattr(web_budget, "monotonic", lambda: clock[0])
    execute = agent.session.tools.execute
    def slow(request, **kwargs):
        value = execute(request, **kwargs)
        clock[0] = 999.0
        return value
    monkeypatch.setattr(agent.session.tools, "execute", slow)
    answer = agent.session.reply("/agent calculate 2+2 then calculate 3+3")
    assert "1. 4" in answer and "budget_exhausted" in answer
    assert states(agent) == ["succeeded", "skipped"]
    assert DEADLINE.get() is None


def test_saved_history_is_not_reexecuted_or_sent_to_ordinary_model(agent):
    agent.session.reply("/agent calculate 2+2; calculate 3+3")
    session_id = agent.session.session_id
    previous = agent.session.history()
    agent.session.resume(session_id)
    assert agent.session.history() == previous and agent.session.last_agent is None
    assert agent.session.history(for_model=True) == []
    agent.session.reply("hi")
    assert "calculate" not in json.dumps(agent.ordinary.call_args.args[0])
    agent.provider.search.assert_not_called()


def test_storage_failure_does_not_retry_or_append_partial_history(agent, monkeypatch):
    monkeypatch.setattr(agent.store, "save_exchange", Mock(side_effect=StorageError("failure")))
    with pytest.raises(StorageError, match="not rolled back"):
        agent.session.reply("/agent calculate 2+2; calculate 3+3")
    assert agent.session.last_agent["outcome"] == "storage_failed"
    assert agent.session.last_agent["executions"] == 2 and agent.session.turn_count == 0


def test_diagnostics_contain_no_prompt_results_or_credentials(agent, caplog):
    agent.session.reply("/agent calculate 123456+123456; research latest Python release")
    summary = json.dumps(agent.session.last_agent)
    assert all(secret not in summary + caplog.text for secret in ["123456", "246912", "tvly-synthetic-key", "PRIVATE_SYSTEM", "https://", "Python 3.15.2"])


@pytest.mark.parametrize("value", ["nan", "inf", "0", "29", "301", "garbage"])
def test_invalid_budget_config(value, monkeypatch):
    monkeypatch.setenv("AIKA_AGENT_TIMEOUT", value)
    with pytest.raises(ConfigError, match="AIKA_AGENT_TIMEOUT"):
        load_config()


def test_agent_budget_config(monkeypatch):
    monkeypatch.setenv("AIKA_AGENT_TIMEOUT", "45")
    assert load_config().agent_timeout == 45


def test_eight_actual_executions_include_research_failed_reads(agent):
    agent.provider.search.return_value = normalize_results([
        {"title": "Python release", "url": f"https://www.python.org/release/{i}", "content": "Python release"}
        for i in range(5)], "Python release", 5, "ddgs")
    original = agent.reader.side_effect
    count = [0]
    def read(source_number):
        count[0] += 1
        if count[0] < 5:
            raise ToolExecutionError("Source unavailable")
        return original(source_number)
    agent.reader.side_effect = read
    agent.grounded.return_value = json.dumps({"claims": [{"source": 5,
        "quote": "Python 3.15.2 is a maintenance release of Python 3.15.",
        "text": "Python 3.15.2 is a maintenance release of Python 3.15."}]})
    agent.session.reply("/agent research latest Python release; calculate 2+2; calculate 3+3")
    assert agent.session.last_agent["executions"] == 8
    assert states(agent) == ["succeeded"] * 3
    agent.provider.search.assert_called_once()
    agent.grounded.assert_called_once()
    agent.paid.search.assert_not_called()


def test_runtime_execution_budget_is_checked_independently_of_planner(agent, monkeypatch):
    plan = [PlanStep(i, f"calculate {i}+1", ToolRequest("calculator.evaluate", {"expression": f"{i}+1"}), None)
            for i in range(1, 10)]
    monkeypatch.setattr("src.intelligence.conversation.build_plan", lambda *args: plan)
    answer = agent.session.reply("/agent calculate 2+2")
    assert "execution_budget" in answer and agent.session.last_agent["executions"] == 8
    assert states(agent)[-1] == "skipped"
    assert agent.session.last_agent["steps"][-1]["attempts"] == 0


def test_model_budget_checked_before_generation(agent, monkeypatch):
    def exercise(question, trace, progress, *, execute_tool, generate):
        for _ in range(3):
            generate([])
        return "unreachable"
    monkeypatch.setattr(agent.session, "_research_reply", exercise)
    agent.session.reply("/agent research latest Python release")
    assert agent.session.last_agent["model_calls"] == 2 and agent.grounded.call_count == 2
    assert agent.session.last_agent["outcome"] == "model_budget"


def test_runtime_duplicate_guard_does_not_retry_failed_operations(agent, monkeypatch):
    plan = [PlanStep(i, "calculate 1/0", ToolRequest("calculator.evaluate", {"expression": "1/0"}), None)
            for i in range(1, 3)]
    monkeypatch.setattr("src.intelligence.conversation.build_plan", lambda *args: plan)
    agent.session.reply("/agent calculate 1/0")
    assert agent.session.last_agent["executions"] == 1
    assert agent.session.last_agent["outcome"] == "duplicate_operation"


@pytest.mark.parametrize("result", [
    ToolResult("calculator.evaluate", ToolStatus.SUCCESS, {"result": "4"}, False),
    ToolResult("calculator.evaluate", ToolStatus.SUCCESS, None, True),
    ToolResult("calculator.evaluate", ToolStatus.INCONCLUSIVE, {"result": "4"}, False),
    ToolResult("calculator.evaluate", ToolStatus.UNAVAILABLE, error="Unavailable"),
])
def test_unverified_results_cannot_unlock_dependencies(agent, monkeypatch, result):
    execute = Mock(return_value=result)
    monkeypatch.setattr(agent.session.tools, "execute", execute)
    agent.session.reply("/agent calculate 2+2 then calculate 3+3")
    assert states(agent)[1] == "skipped" and states(agent)[0] != "succeeded"
    execute.assert_called_once()


def test_explicit_agent_memory_changes_fail_without_access(agent):
    memory = Mock()
    agent.session._memory = memory
    agent.session.reply("/agent Remember that Orion uses Python; calculate 2+2")
    assert memory.mock_calls == [] and agent.session.last_agent["executions"] == 0


@pytest.mark.parametrize("instruction", ["open Notepad", "calculate 99+99"])
def test_model_cannot_invent_an_operation_absent_from_user_task(agent, instruction):
    agent.planner.return_value = json.dumps({"steps": [{"instruction": instruction, "depends_on": []}]})
    agent.session.reply("/agent First calculate 2+2. Afterwards calculate 3+3.")
    assert agent.session.last_agent["executions"] == 0


def test_cancellation_before_planning_has_no_model_or_tool_calls(agent):
    agent.session.reply("/agent calculate 2+2 then calculate 3+3", agent_cancelled=lambda: True)
    assert agent.session.last_agent["outcome"] == "interrupted"
    assert agent.session.last_agent["executions"] == 0
    agent.planner.assert_not_called()


def test_model_failure_during_research_skips_dependency(agent):
    agent.grounded.side_effect = OllamaError("timeout", kind="timeout")
    answer = agent.session.reply("/agent research latest Python release then calculate 3+3")
    assert states(agent) == ["failed", "skipped"]
    assert agent.session.last_agent["steps"][0]["category"] == "model_timeout"
    assert "timed out" in answer
    agent.paid.search.assert_not_called()


def test_model_spacing_and_case_resolve_to_original_user_arguments(agent):
    task = "First calculate 12*7. Afterwards calculate 20/4."
    agent.planner.return_value = span_plan(task, ["Calculate 12 * 7", "Calculate 20 / 4"], [[], [1]])
    trace = []
    answer = agent.session.reply("/agent " + task, tool_trace=trace.append)
    assert answer == ("1. 84\n2. 5\nSteps: 1 calculator.evaluate [succeeded]; 2 calculator.evaluate [succeeded]"
                      "\nExecution status: succeeded.\nTotal: 2 | 2 succeeded | 0 failed | 0 skipped | 0 cancelled | 0 inconclusive") and len(trace) == 2
    assert agent.session.last_agent["model_calls"] == 1


def test_model_omitting_operation_verbs_is_rejected_without_retry(agent):
    task = "First calculate 12*7. Afterwards calculate 20/4."
    agent.planner.return_value = span_plan(task, ["12*7", "20/4"], [[], [1]])
    agent.session.reply("/agent " + task)
    assert agent.session.last_agent["outcome"] == "invalid_span"
    assert agent.session.last_agent["executions"] == 0
    agent.planner.assert_called_once()


def test_missing_registered_tool_rejected_before_other_operations(agent):
    del agent.session.tools.registry._tools["calculator.evaluate"]
    assert "unknown_tool" in agent.session.reply("/agent calculate 2+2; calculate 3+3")
    assert agent.session.last_agent["executions"] == 0


def test_unknown_or_restricted_capability_cannot_follow_successful_prefix(agent):
    agent.session.reply("/agent calculate 2+2 then run powershell")
    assert agent.session.last_agent["executions"] == 0
    agent.planner.assert_called_once()


def test_research_receives_only_its_user_clause_not_local_results(agent):
    agent.session.reply("/agent calculate 123456+123456; research latest Python release")
    assert "123456" not in json.dumps(agent.provider.search.call_args.args)
    assert "246912" not in json.dumps(agent.grounded.call_args.args)


def test_model_cannot_erase_required_sequencing(agent):
    task = "First calculate 2+2. Afterwards calculate 3+3."
    agent.planner.return_value = span_plan(task, ["calculate 2+2", "calculate 3+3"])
    agent.session.reply("/agent " + task)
    assert agent.session.last_agent["executions"] == 0


def test_agent_cli_command_and_help(agent, capsys):
    from src.cli import handle_chat_command
    handle_chat_command("/help", load_config(), agent.session, agent.store)
    assert "/agent <task>" in capsys.readouterr().out
    handle_chat_command("/agent calculate 2+2 then calculate 3+3", load_config(), agent.session, agent.store)
    output = capsys.readouterr().out
    assert "Agent > [1/2] RUNNING calculator.evaluate" in output and "2. 6" in output
    assert "Agent > [1/2] SUCCEEDED calculator.evaluate" in output and "2 succeeded" in output


@pytest.mark.parametrize("task", ["", "x" * 1201, "calculate 2+2\nthen open notepad"])
def test_invalid_tasks_never_call_planner_or_tools(agent, task):
    agent.session.reply("/agent " + task)
    assert agent.session.last_agent["executions"] == 0
    agent.planner.assert_not_called()
