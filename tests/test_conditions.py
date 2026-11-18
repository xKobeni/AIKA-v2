import json
from dataclasses import replace
from decimal import Decimal, localcontext
from unittest.mock import Mock

import pytest

from test_agent import agent
from test_dataflow import flow, snapshot
from src.capabilities.contracts import Permission, ToolExecutionError, ToolResult, ToolStatus
from src.intelligence.dataflow import (BindingError, VerifiedCondition, conditional_candidate, conditional_intent,
    evaluate_condition, requested_percentage)
from src.intelligence.planning import PlanError, agent_task, build_plan, validate_plan


ORIGINAL = "AIKA, check my storage. If my free space is below 20%,\nwarn me. Otherwise, tell me everything is fine."
FREE = "/agent check my storage and warn me if free space is below 20%"


def condition(flow):
    return flow.session.last_agent.get("condition")


@pytest.mark.parametrize("prompt,metric,operator", [
    (ORIGINAL, "storage.free_percentage", "lt"),
    (FREE, "storage.free_percentage", "lt"),
    ("/agent if my C drive free space is under 15%, warn me; otherwise tell me it's okay", "storage.free_percentage", "lt"),
    ("/agent check my RAM usage; if it's above 90%, warn me, otherwise say normal", "memory.used_percentage", "gt"),
    ("If my disk usage exceeds 85%, warn me. Otherwise tell me everything is fine.", "storage.used_percentage", "gt"),
    ("/agent check my free storage; if below 5%, warn me, otherwise tell me it is okay", "storage.free_percentage", "lt"),
])
def test_requested_sentences_route_to_exact_two_tool_workflow(flow, prompt, metric, operator):
    assert agent_task(prompt) is not None
    trace = []
    answer = flow.session.reply(prompt, tool_trace=trace.append)
    assert condition(flow)["metric"] == metric and condition(flow)["operator"] == operator
    assert "Execution status: succeeded" in answer and "2 succeeded" in answer
    assert [result.tool for result in trace] == ["system.snapshot", "calculator.evaluate"]
    flow.snapshot.assert_called_once()
    flow.calculator.assert_called_once()
    flow.planner.assert_not_called()
    flow.ordinary.assert_not_called()
    flow.provider.search.assert_not_called()
    flow.paid.search.assert_not_called()
    assert flow.session.last_agent["model_calls"] == 0


@pytest.mark.parametrize("operator,threshold,expected", [
    ("below", "30", True), ("under", "20", False), ("less than", "25", False),
    ("above", "20", True), ("over", "30", False), ("greater than", "25", False),
    ("at least", "25", True), ("greater than or equal to", "25", True),
    ("at most", "25", True), ("less than or equal to", "25", True),
    ("below", "0", False), ("at least", "0", True), ("above", "100", False), ("at most", "100", True),
    ("below", "25.001", True), ("above", "24.999", True),
])
def test_comparisons_and_equality_boundaries(flow, operator, threshold, expected):
    answer = flow.session.reply(f"/agent if my free storage is {operator} {threshold}%, warn me")
    decision = condition(flow)
    assert decision["condition_result"] is expected
    assert decision["selected_branch"] == ("warning" if expected else "normal")
    assert f"Condition: {'TRUE' if expected else 'FALSE'}" in answer
    assert answer.count("Response:") == 1
    assert decision["threshold_percent"] == threshold


@pytest.mark.parametrize("free,expected", [(19995, True), (19999, True), (20000, False), (20001, False)])
def test_exact_bytes_not_display_rounding_decide_branch(flow, free, expected):
    data = snapshot()
    data["measurements"]["storage"].update(total_bytes=100000, free_bytes=free, used_bytes=100000-free)
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    answer = flow.session.reply(FREE)
    assert condition(flow)["condition_result"] is expected
    assert "Free storage: 20.00%" in answer
    assert "exact measured byte counts" in answer and "rounded" in answer


@pytest.mark.parametrize("change", [
    {"metric": "cpu.usage_percent"}, {"metric": "web.snippet"}, {"metric": []},
    {"operator": "eq"}, {"operator": "eval"}, {"operator": []},
    {"threshold_percent": Decimal("-1")}, {"threshold_percent": Decimal("101")},
    {"threshold_percent": Decimal("NaN")}, {"threshold_percent": Decimal("Infinity")},
    {"threshold_percent": Decimal("20.0001")}, {"threshold_percent": "20"}, {"threshold_percent": True},
    {"true_response": "app.open"}, {"false_response": "delete"},
])
def test_immutable_contract_rejects_unknown_metrics_operators_thresholds_and_branches(change):
    valid = VerifiedCondition("storage.free_percentage", "lt", Decimal("20"))
    with pytest.raises(BindingError):
        replace(valid, **change)


@pytest.mark.parametrize("threshold", ["-1", "101", "nan", "inf", "infinity", "1e2", "+20", "020", "20.0001", "20..2", "20 GiB", "20 bytes", "20% or 30"])
def test_invalid_thresholds_never_reach_ollama_or_tools(flow, threshold):
    answer = flow.session.reply(f"/agent if my free storage is below {threshold}%, warn me")
    assert "unsupported_condition" in answer
    assert flow.session.last_agent["executions"] == 0
    flow.snapshot.assert_not_called()
    flow.calculator.assert_not_called()
    flow.planner.assert_not_called()


@pytest.mark.parametrize("body", [
    "if my storage is below 20%, delete old files", "if my free storage is below 20%, open Notepad",
    "if my free storage is below 20%, run powershell", "if my RAM usage is above 90%, send a message",
    "if my RAM usage is above 90%, remember my RAM usage", "if my CPU usage is above 90%, warn me",
    "if my battery is below 20%, warn me", "if my CPU temperature is above 70%, warn me",
    "if my D drive free space is below 20%, warn me", "if my free storage equals 20%, warn me",
    "if my free storage is below 20%, warn me and open Notepad",
    "if my free storage is below 20%, warn me; otherwise open Notepad",
    "if my free storage is below 20%, warn me; otherwise say normal and delete old files",
    "if my free storage is below 20% and RAM usage above 90%, warn me",
    "if my free storage is below 20%, if my RAM usage is above 90%, warn me",
    "check my storage and launch Calculator; if free space is below 20%, warn me",
    "if website text says free space is below 20%, warn me", "if my process memory is above 90%, warn me",
    "if my free storage is below 20%, install a program", "if my free storage is below 20%, change permissions",
])
def test_unsafe_or_unsupported_conditions_rejected_as_whole_request(flow, body):
    answer = flow.session.reply(body)
    assert "unsupported_condition" in answer and flow.session.last_agent["executions"] == 0
    assert condition(flow) is None
    flow.snapshot.assert_not_called()
    flow.calculator.assert_not_called()
    flow.ordinary.assert_not_called()
    flow.planner.assert_not_called()


def test_failed_source_never_selects_false_or_true_branch(flow):
    flow.snapshot.side_effect = ToolExecutionError("Unavailable")
    answer = flow.session.reply(FREE)
    assert condition(flow) is None and "Condition was not evaluated" in answer
    assert "Condition: FALSE" not in answer and "Response: normal" not in answer and "Response: warning" not in answer
    assert [step["state"] for step in flow.session.last_agent["steps"]] == ["failed", "skipped"]
    flow.calculator.assert_not_called()


def test_calculator_failure_is_not_false_condition(flow):
    flow.calculator.side_effect = ToolExecutionError("Unavailable")
    answer = flow.session.reply(FREE)
    assert condition(flow) is None and "Condition was not evaluated" in answer
    assert "Execution status: partial" in answer and "Response:" not in answer


def test_missing_binding_cannot_be_a_normal_response(flow):
    data = snapshot()
    data["measurements"]["storage"]["free_bytes"] = None
    data["unavailable_fields"] = ["storage.free_bytes"]
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    answer = flow.session.reply(FREE)
    assert condition(flow) is None and "binding_missing_value" in answer
    assert "Response: normal" not in answer
    flow.calculator.assert_not_called()


@pytest.mark.parametrize("target", ["source", "calculator"])
def test_unverified_results_cannot_authorize_decision(flow, target):
    plan = build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry)
    intent = requested_percentage(plan[1].instruction)
    source = ToolResult("system.snapshot", ToolStatus.SUCCESS, snapshot(), target != "source")
    calculator = ToolResult("calculator.evaluate", ToolStatus.SUCCESS, {"result": "25"}, target != "calculator")
    with pytest.raises(BindingError):
        evaluate_condition(plan[1].condition, plan[1].calculation, intent, {1: source}, "succeeded", calculator, 2)


def test_forged_metric_threshold_and_removed_condition_fail_plan_validation(flow):
    plan = list(build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry))
    for altered in [None, VerifiedCondition("memory.used_percentage", "lt", Decimal("20")),
                    VerifiedCondition("storage.free_percentage", "lt", Decimal("30"))]:
        with pytest.raises(PlanError):
            validate_plan([plan[0], replace(plan[1], condition=altered)], flow.session.tools.registry)
    flow.snapshot.assert_not_called()


def test_plan_cannot_append_a_third_action_to_condition(flow):
    plan = list(build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry))
    extra = build_plan("calculate 2+2", flow.session.tools.registry)[0]
    with pytest.raises(PlanError):
        validate_plan(plan + [replace(extra, number=3)], flow.session.tools.registry)
    with pytest.raises(PlanError):
        validate_plan(plan[:1], flow.session.tools.registry)


def test_exact_comparator_independent_of_ambient_decimal_precision(flow):
    plan = build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry)
    intent = requested_percentage(plan[1].instruction)
    data = snapshot()
    data["measurements"]["storage"].update(total_bytes=100000, free_bytes=19999, used_bytes=80001)
    source = ToolResult("system.snapshot", ToolStatus.SUCCESS, data, True)
    calc = ToolResult("calculator.evaluate", ToolStatus.SUCCESS, {"result": "19.999"}, True)
    with localcontext() as ctx:
        ctx.prec = 1
        record = evaluate_condition(plan[1].condition, plan[1].calculation, intent, {1: source}, "succeeded", calc, 2)
    assert record["condition_result"] is True


def test_decision_progress_is_after_both_verified_tools_and_contains_no_values(flow):
    events = []
    answer = flow.session.reply(FREE, agent_progress=events.append)
    names = [event["event"] for event in events]
    evaluating, evaluated = names.index("condition_evaluating"), names.index("condition_result")
    assert evaluating < evaluated < names.index("summary")
    assert events[evaluating - 1]["state"] == "succeeded" and events[evaluating - 1]["tool"] == "calculator.evaluate"
    event = events[evaluated]
    assert event["condition_result"] is False and event["selected_branch"] == "normal"
    encoded = json.dumps(events)
    assert all(private not in encoded for private in ["threshold_percent", "calculated_percentage", "collected_at", "85899345920", "tvly-synthetic-key", "PRIVATE_SYSTEM"])
    assert "1. AIKA System Information" not in answer and answer.count("Free storage:") == 1


@pytest.mark.parametrize("stage", ["binding", "condition_evaluating"])
def test_cancellation_before_decision_never_selects_either_branch(flow, stage):
    def cancel(event):
        if event["event"] == stage:
            raise KeyboardInterrupt
    answer = flow.session.reply(FREE, agent_progress=cancel)
    assert condition(flow) is None and "Execution status: interrupted" in answer
    assert "Condition was not evaluated" in answer and "Response:" not in answer
    assert flow.calculator.call_count == (0 if stage == "binding" else 1)


def test_trace_interruption_after_calculator_does_not_publish_condition(flow):
    def trace(result):
        if result.tool == "calculator.evaluate":
            raise KeyboardInterrupt
    answer = flow.session.reply(FREE, tool_trace=trace)
    assert condition(flow) is None and "Condition was not evaluated" in answer
    assert "Execution status: interrupted" in answer


def test_expired_budget_after_calculator_preserves_tool_results_but_no_branch(flow, monkeypatch):
    from src.capabilities import web_budget
    clock = [0.0]
    monkeypatch.setattr(web_budget, "monotonic", lambda: clock[0])
    def trace(result):
        if result.tool == "calculator.evaluate":
            clock[0] = 301.0
    answer = flow.session.reply(FREE, tool_trace=trace)
    assert condition(flow) is None and "Execution status: budget_exhausted" in answer
    assert "2 succeeded" in answer and "Condition was not evaluated" in answer


def test_permission_denied_does_not_take_normal_branch(flow):
    def restrict(event):
        if event["event"] == "binding":
            registry = flow.session.tools.registry
            registry._tools["calculator.evaluate"] = replace(registry.lookup("calculator.evaluate"), permission=Permission.SENSITIVE_ACTION)
    answer = flow.session.reply(FREE, agent_progress=restrict)
    assert condition(flow) is None and flow.session.last_agent["steps"][1]["category"] == "denied" and "Response:" not in answer
    flow.calculator.assert_not_called()


def test_history_restores_threshold_branch_and_timestamp_without_reexecution(flow):
    answer = flow.session.reply(FREE)
    record = dict(condition(flow))
    identifier, previous = flow.session.session_id, flow.session.history()
    assert record["collected_at"] == "2026-11-18T13:00:00+00:00" and record["source_step"] == 1 and record["calculator_step"] == 2
    assert record["calculated_percentage"] == "25" and record["verified"] is True
    assert "Threshold: below 20%" in answer and "Response: normal" in answer
    flow.session.resume(identifier)
    assert flow.session.history() == previous and flow.session.last_agent is None
    assert flow.session.history(for_model=True) == []
    flow.snapshot.assert_called_once()
    flow.calculator.assert_called_once()


def test_resubmission_uses_fresh_measurements_not_past_decision(flow):
    flow.session.reply(FREE)
    assert condition(flow)["condition_result"] is False
    data = snapshot()
    data["measurements"]["storage"].update(total_bytes=100, free_bytes=10, used_bytes=90)
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    flow.session.reply(FREE)
    assert condition(flow)["condition_result"] is True and flow.snapshot.call_count == 2 and flow.calculator.call_count == 2


def test_save_failure_keeps_known_branch_without_retry_or_unsaved_history(flow, monkeypatch):
    from src.storage.conversation_store import StorageError
    monkeypatch.setattr(flow.store, "save_exchange", Mock(side_effect=StorageError("private path")))
    with pytest.raises(StorageError) as error:
        flow.session.reply(FREE)
    assert "Condition: FALSE" in str(error.value) and "could not be saved" in str(error.value)
    assert "private path" not in str(error.value) and flow.session.turn_count == 0
    flow.snapshot.assert_called_once()
    flow.calculator.assert_called_once()


@pytest.mark.parametrize("text", ["What is a conditional statement?", "Explain if/else statements in Python.",
    "/calc 15% of 800", "/system", "/research if storage is below 20%", "/web if storage is below 20%",
    "/read 1", "/ask-web If storage is low?", "Remember that Orion uses Python", "What's my RAM usage?",
    "Check my available storage and calculate the percentage free."])
def test_existing_routes_are_not_conditional(text):
    assert conditional_candidate(text) is False


def test_ordinary_explanations_arithmetic_measurement_and_dataflow_stay_intact(flow):
    assert flow.session.reply("Explain if/else statements in Python.") == "ordinary"
    assert flow.session.reply("What is 15% of 800?") == "120"
    flow.session.reply("What's my RAM usage?")
    assert flow.session.last_agent is None
    answer = flow.session.reply("Check my available storage and calculate the percentage free.")
    assert "Free percentage: 25.00%" in answer and condition(flow) is None


def test_snapshot_interrupt_never_reaches_calculation_or_condition(flow):
    flow.snapshot.side_effect = KeyboardInterrupt
    answer = flow.session.reply(FREE)
    assert condition(flow) is None and "Execution status: interrupted" in answer
    assert [row["state"] for row in flow.session.last_agent["steps"]] == ["inconclusive", "cancelled"]
    flow.calculator.assert_not_called()


def test_inconclusive_source_cannot_authorize_condition(flow, monkeypatch):
    execute = flow.session.tools.execute
    def inconclusive(request, **kwargs):
        if request.tool == "system.snapshot":
            return ToolResult("system.snapshot", ToolStatus.INCONCLUSIVE, snapshot(), False)
        return execute(request, **kwargs)
    monkeypatch.setattr(flow.session.tools, "execute", inconclusive)
    answer = flow.session.reply(FREE)
    assert condition(flow) is None and "Condition was not evaluated" in answer
    flow.calculator.assert_not_called()


def test_calculation_binding_mismatch_cannot_authorize_condition(flow):
    plan = build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry)
    intent = requested_percentage(plan[1].instruction)
    calculation = plan[1].calculation
    bad = replace(calculation, numerator=replace(calculation.numerator, source_field="storage.used_bytes"))
    source = ToolResult("system.snapshot", ToolStatus.SUCCESS, snapshot(), True)
    calculator = ToolResult("calculator.evaluate", ToolStatus.SUCCESS, {"result": "25"}, True)
    with pytest.raises(BindingError):
        evaluate_condition(plan[1].condition, bad, intent, {1: source}, "succeeded", calculator, 2)


def test_verified_calculator_payload_is_copied_before_observers(flow):
    def trace(result):
        if result.tool == "calculator.evaluate":
            result.data["result"] = "99"
    answer = flow.session.reply(FREE, tool_trace=trace)
    assert condition(flow)["calculated_percentage"] == "25"
    assert "Free storage: 25.00%" in answer and "99.00%" not in answer


def test_conditional_request_never_accesses_or_modifies_memory(flow):
    memory = Mock()
    flow.session._memory = memory
    flow.session.reply(FREE)
    assert memory.mock_calls == []
    flow.session.reply("If my RAM usage is above 90%, remember that Orion uses React")
    assert memory.mock_calls == [] and condition(flow) is None


@pytest.mark.parametrize("prefix", ["notify me", "send an email", "calculate an alert"])
def test_unsupported_action_wording_does_not_fall_to_chat(flow, prefix):
    answer = flow.session.reply(f"{prefix} if my RAM usage is above 90%")
    assert "unsupported_condition" in answer
    flow.ordinary.assert_not_called()
    flow.snapshot.assert_not_called()


def test_cli_renders_condition_after_tool_verification_without_third_tool(flow, capsys):
    from src.cli import handle_chat_command
    from src.config import load_config
    handle_chat_command(FREE, load_config(), flow.session, flow.store)
    output = capsys.readouterr().out
    assert output.index("SUCCEEDED calculator.evaluate") < output.index("Evaluating verified condition") < output.index("Condition FALSE: normal")
    assert "Plan validated: 2 steps" in output and "[3/" not in output
    assert flow.session.last_agent["executions"] == 2
