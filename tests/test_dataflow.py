import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from unittest.mock import Mock

import pytest

from test_agent import agent
from src.capabilities.contracts import Permission, ToolExecutionError, ToolRequest, ToolResult, ToolStatus
from src.capabilities.system_info import SOURCE
from src.intelligence.dataflow import (BindingError, PercentageCalculation, VerifiedBinding, calculation_for,
    percentage_intent, resolve_calculation)
from src.intelligence.planning import PlanError, PlanStep, agent_task, build_plan, validate_plan


FREE = "/agent check my system storage and calculate the percentage of free disk space"
USED = "/agent calculate what percentage of my C drive is used"
RAM = "/agent get my RAM information and calculate the percentage currently used"
GIB = 2**30


def snapshot(group="storage"):
    values = ({"system_drive": "C:\\", "total_bytes": 320 * GIB, "free_bytes": 80 * GIB,
               "used_bytes": 240 * GIB, "usage_percent": 75.0} if group == "storage" else
              {"total_bytes": 16 * GIB, "used_bytes": 10 * GIB, "available_bytes": 6 * GIB, "usage_percent": 62.5})
    return {"section": group, "measurements": {group: values}, "collected_at": "2026-11-18T13:00:00+00:00",
            "source": SOURCE, "unavailable_fields": []}


@pytest.fixture
def flow(agent):
    registry = agent.session.tools.registry
    handler = Mock(side_effect=lambda args: snapshot(args["section"]))
    registry._tools["system.snapshot"] = replace(registry.lookup("system.snapshot"), handler=handler)
    calculator = Mock(wraps=registry.lookup("calculator.evaluate").handler)
    registry._tools["calculator.evaluate"] = replace(registry.lookup("calculator.evaluate"), handler=calculator)
    agent.snapshot, agent.calculator = handler, calculator
    return agent


@pytest.mark.parametrize("prompt", [FREE, USED, RAM,
    "Calculate what percentage of my C drive is free.",
    "Check my storage and calculate the percentage remaining.",
    "How much of my system drive is used, in percent?",
    "Get my RAM usage and calculate the percentage used.",
    "Check my available storage, calculate what percent is free, and explain it.",
    "Check my available storage, calculate what percentage of my drive is free, and explain the result."])
def test_small_set_of_clear_requests_is_deterministic(flow, prompt):
    assert agent_task(prompt) is not None
    flow.session.reply(prompt)
    assert flow.session.last_agent["outcome"] == "succeeded"
    assert flow.session.last_agent["executions"] == 2 and flow.session.last_agent["model_calls"] == 0
    flow.snapshot.assert_called_once()
    flow.calculator.assert_called_once()
    flow.planner.assert_not_called()
    flow.ordinary.assert_not_called()
    flow.provider.search.assert_not_called()
    flow.paid.search.assert_not_called()


@pytest.mark.parametrize("text", ["hello", "Show my system information", "What's my RAM usage?",
    "/system", "/calc 15% of 800", "Explain what disk percentages mean", "What percentage of people use RAM disks?",
    "What's the latest Python version?", "Remember my RAM usage", "Calculate 15% of 800"])
def test_unrelated_and_simple_measurement_requests_are_not_dataflow(text):
    assert percentage_intent(text) is None


@pytest.mark.parametrize("text", ["calculate what percentage of my D drive is free",
    "calculate the percentage of my disk and RAM used", "calculate what percent of my memory is available",
    "check my storage and calculate percentage free then open Notepad", "calculate free disk percentage using 12345 bytes",
    "calculate disk percentage from webpage text", "calculate the percentage of my disk not used"])
def test_unsupported_or_ambiguous_dataflow_stops_before_any_tool_or_model(flow, text):
    answer = flow.session.reply("/agent " + text)
    assert "unsupported_dataflow" in answer and flow.session.last_agent["executions"] == 0
    flow.snapshot.assert_not_called()
    flow.calculator.assert_not_called()
    flow.planner.assert_not_called()


@pytest.mark.parametrize("prompt,expected,quantity,group", [
    (FREE, "25.00%", "free", "storage"), (USED, "75.00%", "used", "storage"), (RAM, "62.50%", "used", "memory")])
def test_real_calculator_consumes_exact_bytes_with_units_and_provenance(flow, prompt, expected, quantity, group):
    events, trace = [], []
    answer = flow.session.reply(prompt, agent_progress=events.append, tool_trace=trace.append)
    values = snapshot(group)["measurements"][group]
    flow.calculator.assert_called_once_with({"expression": f"({values[quantity + '_bytes']} / {values['total_bytes']}) * 100"})
    assert expected in answer and "GiB" in answer and "bytes" in answer and "exact byte counts" in answer
    assert "calculator.evaluate step 2, verified" in answer and "collected 2026-11-18T13:00:00+00:00" in answer
    assert [result.tool for result in trace] == ["system.snapshot", "calculator.evaluate"]
    binding = flow.session.last_agent["steps"][1]["binding"]
    assert binding["verified"] is True and binding["operation"] == "percentage"
    assert [item["field"] for item in binding["input_sources"]] == [f"{group}.{quantity}_bytes", f"{group}.total_bytes"]
    assert all(item["verified"] and item["unit"] == "bytes" and item["step"] == 1 for item in binding["input_sources"])
    encoded = json.dumps(events) + json.dumps(flow.session.last_agent)
    assert str(values["total_bytes"]) not in encoded and str(values[quantity + "_bytes"]) not in encoded
    binding_index = next(i for i, event in enumerate(events) if event["event"] == "binding")
    assert events[binding_index - 1]["state"] == "succeeded" and events[binding_index - 1]["number"] == 1
    assert events[binding_index + 1]["state"] == "running" and events[binding_index + 1]["number"] == 2
    assert events[binding_index]["verified"] is False


def test_decimal_precision_and_operand_order_avoid_float_artifacts(flow):
    data = snapshot()
    data["measurements"]["storage"].update(total_bytes=3, free_bytes=1, used_bytes=2)
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    answer = flow.session.reply(FREE)
    flow.calculator.assert_called_once_with({"expression": "(1 / 3) * 100"})
    assert "Free percentage: 33.33%" in answer and "(1 bytes)" in answer and "rounded" in answer


@pytest.mark.parametrize("target", ["numerator", "denominator"])
@pytest.mark.parametrize("change", [
    {"source_step": 0}, {"source_step": 2}, {"source_step": 3}, {"source_step": True},
    {"source_field": "__dict__"}, {"source_field": "storage.__class__"},
    {"source_field": "processes.0.name"}, {"source_field": "api_key"},
    {"source_field": "storage.usage_percent"}, {"source_field": []},
    {"unit": "GiB"}, {"expected_type": "string"},
])
def test_binding_schema_and_allowlist_fail_preflight(flow, target, change):
    plan = list(build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry))
    calculation = plan[1].calculation
    reference = replace(getattr(calculation, target), **change)
    plan[1] = replace(plan[1], calculation=replace(calculation, **{target: reference}))
    with pytest.raises(PlanError):
        validate_plan(plan, flow.session.tools.registry)
    flow.snapshot.assert_not_called()
    flow.calculator.assert_not_called()


@pytest.mark.parametrize("change", [
    {"depends_on": ()}, {"depends_on": (2,)},
    {"request": ToolRequest("app.open", {"app_id": "notepad"})},
    {"request": ToolRequest("web.search", {"query": "secret"})},
    {"request": ToolRequest("calculator.evaluate", {"expression": "100"})},
    {"research": "latest Python release"},
])
def test_consumer_dependency_and_no_literal_measurement_substitution(flow, change):
    plan = list(build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry))
    plan[1] = replace(plan[1], **change)
    with pytest.raises(PlanError):
        validate_plan(plan, flow.session.tools.registry)
    flow.snapshot.assert_not_called()


def test_operation_and_operand_order_cannot_be_rewritten(flow):
    plan = list(build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry))
    calc = plan[1].calculation
    for malformed in [replace(calc, operation="eval"), replace(calc, numerator=calc.denominator, denominator=calc.numerator),
                      replace(calc, numerator=VerifiedBinding(1, "storage.used_bytes"))]:
        with pytest.raises(PlanError):
            validate_plan([plan[0], replace(plan[1], calculation=malformed)], flow.session.tools.registry)


@pytest.mark.parametrize("tool", ["app.open", "web.search", "web.read", "system.processes"])
def test_no_other_producer_can_authorize_binding(flow, tool):
    from src.intelligence.dataflow import validate_calculation
    plan = list(build_plan(FREE.removeprefix("/agent "), flow.session.tools.registry))
    producer = replace(plan[0], request=ToolRequest(tool, {}))
    with pytest.raises(BindingError, match="binding_producer"):
        validate_calculation(plan[1].calculation, plan[1], [producer])


@pytest.mark.parametrize("bad", [None, True, "123", float("nan"), float("inf"), -1, 2**64, 1.25])
@pytest.mark.parametrize("field", ["free_bytes", "total_bytes"])
def test_invalid_numeric_evidence_never_reaches_calculator(flow, bad, field):
    data = snapshot()
    data["measurements"]["storage"][field] = bad
    if bad is None:
        data["unavailable_fields"] = [f"storage.{field}"]
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    answer = flow.session.reply(FREE)
    flow.calculator.assert_not_called()
    assert "Execution status: succeeded" not in answer
    assert flow.session.last_agent["steps"][1]["state"] == "skipped"


@pytest.mark.parametrize("total,free,used", [(0, 0, 0), (10, 11, 0), (10, 4, 5)])
def test_zero_denominator_and_inconsistent_capacities_are_rejected(flow, total, free, used):
    data = snapshot()
    data["measurements"]["storage"].update(total_bytes=total, free_bytes=free, used_bytes=used)
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    flow.session.reply(FREE)
    flow.calculator.assert_not_called()
    assert flow.session.last_agent["steps"][1]["state"] == "skipped"


def test_zero_numerator_is_valid(flow):
    data = snapshot()
    data["measurements"]["storage"].update(total_bytes=5, free_bytes=0, used_bytes=5)
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    assert "Free percentage: 0.00%" in flow.session.reply(FREE)
    flow.calculator.assert_called_once_with({"expression": "(0 / 5) * 100"})


def test_missing_value_from_partially_verified_snapshot_is_skipped_not_zero(flow):
    data = snapshot()
    data["measurements"]["storage"]["free_bytes"] = None
    data["unavailable_fields"] = ["storage.free_bytes"]
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    answer = flow.session.reply(FREE)
    first, second = flow.session.last_agent["steps"]
    assert first["state"] == "succeeded" and second["state"] == "skipped"
    assert second["category"] == "binding_missing_value" and second["attempts"] == 0
    assert second["started_at"] is None and second["binding"]["verified"] is False
    assert "No calculator call was made" in answer
    flow.calculator.assert_not_called()


@pytest.mark.parametrize("state,status,verified", [("failed", ToolStatus.EXECUTION_FAILED, False),
    ("inconclusive", ToolStatus.INCONCLUSIVE, False), ("succeeded", ToolStatus.SUCCESS, False)])
def test_unverified_or_failed_evidence_is_unavailable(flow, state, status, verified):
    task = FREE.removeprefix("/agent ")
    calc = build_plan(task, flow.session.tools.registry)[1].calculation
    result = ToolResult("system.snapshot", status, snapshot(), verified)
    with pytest.raises(BindingError, match="binding_unverified"):
        resolve_calculation(calc, percentage_intent(task), {1: result}, state)
    flow.calculator.assert_not_called()


def test_wrong_named_drive_never_uses_other_system_drive_silently(flow):
    data = snapshot()
    data["measurements"]["storage"]["system_drive"] = "Z:\\"
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    answer = flow.session.reply(USED)
    assert "binding_drive_mismatch" in answer
    flow.calculator.assert_not_called()


def test_cancel_after_source_prevents_binding_and_calculator(flow):
    answer = flow.session.reply(FREE, agent_cancelled=lambda: flow.session.last_agent["executions"] >= 1)
    assert [row["state"] for row in flow.session.last_agent["steps"]] == ["succeeded", "cancelled"]
    assert "Execution status: interrupted" in answer
    flow.calculator.assert_not_called()


def test_cancel_during_binding_resolution_event_prevents_consumer(flow):
    def cancel(event):
        if event["event"] == "binding":
            raise KeyboardInterrupt
    flow.session.reply(FREE, agent_progress=cancel)
    assert [row["state"] for row in flow.session.last_agent["steps"]] == ["succeeded", "cancelled"]
    flow.calculator.assert_not_called()


def test_history_resume_keeps_values_and_does_not_reexecute(flow):
    flow.session.reply(FREE)
    history, identifier = flow.session.history(), flow.session.session_id
    flow.session.resume(identifier)
    assert flow.session.history() == history and "Free percentage: 25.00%" in history[-1]["content"]
    assert flow.session.last_agent is None and flow.session.history(for_model=True) == []
    flow.snapshot.assert_called_once()
    flow.calculator.assert_called_once()


def test_previous_history_never_supplies_a_new_missing_measurement(flow):
    flow.session.reply(FREE)
    flow.snapshot.side_effect = ToolExecutionError("Current snapshot unavailable")
    answer = flow.session.reply(FREE)
    assert "Free percentage: 25.00%" not in answer
    assert flow.calculator.call_count == 1


def test_model_cannot_invent_binding_keys_in_existing_schema(flow):
    flow.planner.return_value = json.dumps({"steps": [{"instruction": "calculate 100", "depends_on": [],
        "binding": {"source_field": "api_key", "value": 12345}}]})
    flow.session.reply("/agent First calculate 2+2. Afterwards calculate 3+3.")
    assert flow.session.last_agent["executions"] == 0
    flow.calculator.assert_not_called()


def test_simple_system_route_is_still_one_snapshot_without_calculation(flow):
    assert "AIKA System Information" in flow.session.reply("what is my disk space")
    assert flow.session.last_agent is None
    flow.snapshot.assert_called_once()
    flow.calculator.assert_not_called()


def test_failed_producer_cannot_run_the_consumer(flow):
    flow.snapshot.side_effect = ToolExecutionError("Snapshot unavailable")
    answer = flow.session.reply(FREE)
    assert [row["state"] for row in flow.session.last_agent["steps"]] == ["failed", "skipped"]
    assert "Free percentage:" not in answer
    flow.calculator.assert_not_called()


@pytest.mark.parametrize("verified,status", [(False, ToolStatus.SUCCESS), (False, ToolStatus.INCONCLUSIVE)])
def test_unverified_source_returned_to_session_never_binds(flow, monkeypatch, verified, status):
    execute = flow.session.tools.execute
    def unverified(request, **kwargs):
        if request.tool == "system.snapshot":
            return ToolResult("system.snapshot", status, snapshot(), verified)
        return execute(request, **kwargs)
    monkeypatch.setattr(flow.session.tools, "execute", unverified)
    flow.session.reply(FREE)
    assert [row["state"] for row in flow.session.last_agent["steps"]] == ["inconclusive", "skipped"]
    flow.calculator.assert_not_called()


def test_calculator_failure_never_becomes_verified_derived_answer(flow):
    flow.calculator.side_effect = ToolExecutionError("Calculator unavailable")
    answer = flow.session.reply(FREE)
    assert [row["state"] for row in flow.session.last_agent["steps"]] == ["succeeded", "failed"]
    assert flow.session.last_agent["steps"][1]["binding"]["verified"] is False
    assert "Free percentage:" not in answer and "Execution status: partial" in answer
    flow.calculator.assert_called_once()


def test_permission_recheck_blocks_resolved_calculation(flow):
    def change(event):
        if event["event"] == "binding":
            registry = flow.session.tools.registry
            registry._tools["calculator.evaluate"] = replace(registry.lookup("calculator.evaluate"), permission=Permission.SENSITIVE_ACTION)
    answer = flow.session.reply(FREE, agent_progress=change)
    assert "Free percentage:" not in answer and "Execution status: partial" in answer
    assert flow.session.last_agent["steps"][1]["category"] == "denied"
    flow.calculator.assert_not_called()


@pytest.mark.parametrize("name", ["calculator.evaluate", "system.snapshot"])
def test_disabled_or_restricted_tools_reject_entire_bound_plan(flow, name):
    registry = flow.session.tools.registry
    registry._tools[name] = replace(registry.lookup(name), enabled=False)
    flow.session.reply(FREE)
    assert flow.session.last_agent["executions"] == 0
    flow.snapshot.assert_not_called()
    flow.calculator.assert_not_called()


def test_expired_budget_after_measurement_never_calls_calculator(flow, monkeypatch):
    from src.capabilities import web_budget
    clock = [0.0]
    monkeypatch.setattr(web_budget, "monotonic", lambda: clock[0])
    def slow(arguments):
        clock[0] = 301.0
        return snapshot(arguments["section"])
    flow.snapshot.side_effect = slow
    answer = flow.session.reply(FREE)
    assert "Execution status: budget_exhausted" in answer
    assert flow.session.last_agent["steps"][0]["verified"] is True
    assert flow.session.last_agent["steps"][1]["state"] == "skipped"
    flow.calculator.assert_not_called()


def test_controlled_blocking_producer_returns_before_observing_cancel_without_consumer(flow):
    from threading import Event, Thread
    entered, release, cancelled = Event(), Event(), Event()
    answers = []
    def blocking(arguments):
        entered.set()
        assert release.wait(5)
        return snapshot(arguments["section"])
    flow.snapshot.side_effect = blocking
    worker = Thread(target=lambda: answers.append(flow.session.reply(FREE, agent_cancelled=cancelled.is_set)))
    worker.start()
    try:
        assert entered.wait(5)
        cancelled.set()
        assert worker.is_alive()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and "interrupted" in answers[0]
    assert [row["state"] for row in flow.session.last_agent["steps"]] == ["succeeded", "cancelled"]
    flow.calculator.assert_not_called()


def test_storage_failure_preserves_derived_answer_without_replay(flow, monkeypatch):
    from src.storage.conversation_store import StorageError
    save = Mock(side_effect=StorageError("private path"))
    monkeypatch.setattr(flow.store, "save_exchange", save)
    with pytest.raises(StorageError) as failure:
        flow.session.reply(FREE)
    assert "Free percentage: 25.00%" in str(failure.value) and "could not be saved" in str(failure.value)
    assert "private path" not in str(failure.value) and flow.session.turn_count == 0
    flow.snapshot.assert_called_once()
    flow.calculator.assert_called_once()
    save.assert_called_once()


def test_verified_evidence_is_copied_before_observers_can_mutate_payload(flow):
    def trace(result):
        if result.tool == "system.snapshot":
            result.data["measurements"]["storage"].update(total_bytes=1, free_bytes=0, used_bytes=1)
    answer = flow.session.reply(FREE, tool_trace=trace)
    assert "Free percentage: 25.00%" in answer
    flow.calculator.assert_called_once_with({"expression": f"({80*GIB} / {320*GIB}) * 100"})


def test_one_step_wording_and_inconclusive_launch_summary(flow, capsys):
    from src.cli import handle_chat_command
    from src.config import load_config
    handle_chat_command("/agent calculate 2+2", load_config(), flow.session, flow.store)
    output = capsys.readouterr().out
    assert "Plan validated: 1 step\n" in output and "1 steps" not in output
    registry = flow.session.tools.registry
    handler = Mock(return_value={"application": "notepad", "launch_state": "initiated", "pid": 123,
        "process_observed": False, "exit_code": 0})
    registry._tools["app.open"] = replace(registry.lookup("app.open"), handler=handler)
    answer = flow.session.reply("/agent open notepad")
    assert "Execution status: inconclusive" in answer and "Execution status: failed" not in answer
    assert "1 inconclusive" in answer
    handler.assert_called_once()


def test_research_call_label_distinguishes_parent_step_from_operation_count(flow):
    answer = flow.session.reply("/agent calculate 2+2; research latest Python release")
    assert "Research operations for step 2 (2 calls): web.search [succeeded], web.read [succeeded]" in answer
    flow.paid.search.assert_not_called()


def test_field_marked_unavailable_is_not_used_even_if_value_is_present(flow):
    data = snapshot()
    data["unavailable_fields"] = ["storage.free_bytes"]
    flow.snapshot.side_effect = None
    flow.snapshot.return_value = data
    answer = flow.session.reply(FREE)
    assert "binding_missing_value" in answer
    flow.calculator.assert_not_called()


def test_existing_literal_percentage_then_storage_request_keeps_separate_operations(flow):
    answer = flow.session.reply("/agent calculate 15% of 800 then check my storage")
    assert "1. 120" in answer and "Execution status: succeeded" in answer
    flow.calculator.assert_called_once_with({"expression": "15% of 800"})
    flow.snapshot.assert_called_once_with({"section": "storage"})
    assert "binding" not in flow.session.last_agent["steps"][0]
