from dataclasses import replace

import pytest

from test_agent import agent
from test_dataflow import flow
from test_applications import apps, mocked_process, session_for
from test_capability_routing import local
from src.capabilities.application_intent import application_request
from src.capabilities.contracts import Permission, ToolStatus
from src.capabilities.system_intent import system_request, unsupported_measurement


@pytest.mark.parametrize("prompt", [
    "How much space is left on my laptop?", "How much storage is available on my computer?",
    "How much disk space is free on my notebook?", "How much space is left on my desktop?",
    "How much storage do I have left on my laptop?", "How much free space do I have on my laptop?",
])
def test_general_device_storage_uses_labeled_system_drive(flow, prompt):
    request = system_request(prompt)
    assert request.tool == "system.snapshot" and request.arguments == {"section": "storage"}
    assert unsupported_measurement(prompt) is None
    trace = []
    answer = flow.session.reply(prompt, tool_trace=trace.append)
    assert len(trace) == 1 and trace[0].tool == "system.snapshot" and trace[0].verified
    assert "System Drive: C:" in answer and "80.00 GiB free" in answer and "320.00 GiB" in answer
    assert "Windows system drive only; not aggregate storage across all drives" in answer
    assert "Collected: 2026-11-18T13:00:00+00:00" in answer and "Source:" in answer
    flow.ordinary.assert_not_called()
    flow.planner.assert_not_called()


@pytest.mark.parametrize("prompt", [
    "How much space is left on my D: drive?", "How much space is left on D:?", "How full is my D drive?",
    "How much space is left across all drives?", "Show my combined storage capacity.",
    "How much space is left on my laptop across all my drives?",
])
def test_explicit_other_drive_and_aggregate_never_substitute_system_drive(flow, prompt):
    trace = []
    answer = flow.session.reply(prompt, tool_trace=trace.append)
    assert "not implemented" in answer and "System Drive: C:" not in answer
    assert trace == []
    flow.snapshot.assert_not_called()
    flow.ordinary.assert_not_called()


@pytest.mark.parametrize("prompt", ["What is cloud storage?", "Explain storage across all drives."])
def test_storage_explanation_stays_conversation(local, prompt):
    session, model, _, _ = local
    trace = []
    assert session.reply(prompt, tool_trace=trace.append) == "ordinary explanation"
    assert trace == []
    model.assert_called_once()


@pytest.mark.parametrize("prompt", [
    "Can you open Notepad?", "Are you able to launch Notepad?", "Do you support opening applications?",
    "Can you open Windows Calculator?", "Could you please open Notepad?", "Can you open Spotify?",
    "Can you open Notepad now?", "Can you open PowerShell?", "Can you open C:/Windows/System32/cmd.exe?",
])
def test_ability_questions_never_authorize_launch(tmp_path, apps, mocked_process, prompt):
    session = session_for(tmp_path, apps)
    trace = []
    assert application_request(prompt) is None
    answer = session.reply(prompt, tool_trace=trace.append)
    assert answer and "launch verified" not in answer and trace == []
    mocked_process[0].assert_not_called()
    if prompt == "Can you open Notepad?":
        assert 'Yes, I can launch Notepad' in answer and '"Open Notepad"' in answer
        assert "Window readiness is not guaranteed" in answer


@pytest.mark.parametrize("prompt", [
    "Open Notepad.", "Please launch Notepad.", "Open Notepad now.", "/open notepad",
    "Can you open Notepad for me now?", "Can you open Notepad for me?",
])
def test_explicit_launches_keep_existing_permission_checked_adapter(tmp_path, apps, mocked_process, prompt):
    trace = []
    answer = session_for(tmp_path, apps).reply(prompt, tool_trace=trace.append)
    assert "launch verified" in answer and len(trace) == 1
    assert trace[0].tool == "app.open" and trace[0].verified
    assert trace[0].permission == Permission.LOCAL_ACTION
    mocked_process[0].assert_called_once()


def test_disabled_app_ability_does_not_claim_ready(tmp_path, apps, mocked_process):
    apps._apps["notepad"] = replace(apps.lookup("notepad"), enabled=False)
    answer = session_for(tmp_path, apps).reply("Can you open Notepad?")
    assert "unavailable or disabled" in answer
    mocked_process[0].assert_not_called()


def test_launch_permission_denial_is_preserved(tmp_path, apps, mocked_process):
    session = session_for(tmp_path, apps)
    registry = session.tools.registry
    registry._tools["app.open"] = replace(registry.lookup("app.open"), permission=Permission.SENSITIVE_ACTION)
    trace = []
    session.reply("Open Notepad now.", tool_trace=trace.append)
    assert trace[0].status == ToolStatus.DENIED
    mocked_process[0].assert_not_called()


@pytest.mark.parametrize("prompt", ["Open PowerShell now.", "Open arbitrary.exe now."])
def test_unauthorized_targets_remain_blocked(tmp_path, apps, mocked_process, prompt):
    trace = []
    session_for(tmp_path, apps).reply(prompt, tool_trace=trace.append)
    assert trace[0].status == ToolStatus.INVALID_INPUT and not trace[0].verified
    mocked_process[0].assert_not_called()


def test_agent_cannot_reinterpret_ability_question_as_launch(agent):
    trace = []
    agent.session.reply("/agent calculate 12*7 then Can you open Notepad?", tool_trace=trace.append)
    assert trace == [] and agent.session.last_agent["executions"] == 0


def test_ram_condition_removes_only_redundant_label(flow):
    trace = []
    answer = flow.session.reply("Check whether my RAM usage exceeds 90%.", tool_trace=trace.append)
    assert [row.tool for row in trace] == ["system.snapshot", "calculator.evaluate"]
    assert all(row.verified for row in trace)
    assert "AIKA RAM Status\nRAM used: 62.50%" in answer
    assert "\nRAM\n" not in answer and "Condition: FALSE" in answer
    assert "Verified from system.snapshot" in answer


def test_ability_history_restore_never_replays_launch(tmp_path, apps, mocked_process):
    session = session_for(tmp_path, apps)
    answer = session.reply("Can you open Notepad?")
    saved = session.session_id
    restored = session_for(tmp_path, apps)
    restored.resume(saved)
    assert restored.history()[-1]["content"] == answer
    mocked_process[0].assert_not_called()
