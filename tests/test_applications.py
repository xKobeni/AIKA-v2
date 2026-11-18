import json
import subprocess
from dataclasses import replace
from unittest.mock import Mock

import pytest

import aika
import src.capabilities.applications as applications
from src.capabilities import create_registry
from src.capabilities.application_intent import application_request
from src.capabilities.applications import Application, ApplicationRegistry, _launch as launch_process, create_applications
from src.capabilities.contracts import LocalActionAuthorization, Permission, ToolInputError, ToolRequest, ToolStatus
from src.capabilities.executor import ToolExecutor
from src.config import ConfigError, load_config
from src.diagnostics import inspect_applications
from src.intelligence.conversation import ConversationSession
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore, StorageError


@pytest.fixture
def apps(tmp_path, monkeypatch):
    system = tmp_path / "System32"
    system.mkdir()
    for filename in ("notepad.exe", "calc.exe"):
        (system / filename).write_bytes(b"synthetic executable; never launched")
    monkeypatch.setattr(applications, "windows_system_directory", lambda: system)
    return create_applications()


@pytest.fixture
def mocked_process(monkeypatch):
    # Exercise the real narrowly scoped adapter while replacing OS process creation.
    process = Mock(pid=4321)
    process.wait.side_effect = subprocess.TimeoutExpired("approved executable", 0.25)
    start = Mock(return_value=process)
    monkeypatch.setattr(applications.subprocess, "Popen", start)
    monkeypatch.setattr(applications, "_launch", launch_process)
    return start, process


def execute(apps, app_id, *, authorize=True):
    request = ToolRequest("app.open", {"app_id": app_id})
    auth = LocalActionAuthorization("app.open", app_id) if authorize else None
    return ToolExecutor(create_registry(apps)).execute(request, authorization=auth)


def session_for(tmp_path, apps, generate=None):
    return ConversationSession("Identity", 10, generate or Mock(side_effect=AssertionError("No model launch")),
                               ConversationStore(tmp_path), MemoryStore(tmp_path), applications=apps)


def test_registration_known_unknown_and_duplicate(apps):
    assert [app.app_id for app in apps.list_apps()] == ["notepad", "calculator", "spotify"]
    assert apps.lookup("notepad").display_name == "Notepad"
    assert apps.lookup("calculator").launch_method == "executable"
    assert apps.lookup("notepad").permission == Permission.LOCAL_ACTION
    with pytest.raises(ToolInputError, match="Unsupported"):
        apps.lookup("unknown")
    with pytest.raises(ValueError, match="Duplicate"):
        apps.register(apps.lookup("notepad"))
    assert apps.availability(apps.lookup("notepad")) == "AVAILABLE"
    assert apps.availability(apps.lookup("spotify")) == "UNAVAILABLE"


@pytest.mark.parametrize("change", [
    {"app_id": "powershell"}, {"target": "notepad.exe"}, {"launch_method": "shell"},
    {"permission": Permission.READ_ONLY}, {"permission": "LOCAL_ACTION"}, {"enabled": "yes"},
    {"display_name": "Injected app"},
])
def test_registration_rejects_unapproved_definitions(apps, change):
    registry = ApplicationRegistry()
    with pytest.raises(ValueError):
        registry.register(replace(apps.lookup("notepad"), **change))


@pytest.mark.parametrize("target", ["../notepad.exe", "notepad.exe", "notepad.exe & calc.exe", "C:/evil/notepad.exe", "C:/Windows/System32/cmd.exe"])
def test_executable_target_validation_rejects_substitution(apps, target):
    from pathlib import Path
    with pytest.raises(ValueError):
        ApplicationRegistry().register(replace(apps.lookup("notepad"), target=Path(target)))


@pytest.mark.parametrize("target", [
    "notepad.exe", "../notepad", "C:\\Windows\\System32\\notepad.exe", "notepad & calc", "notepad; calc",
    "notepad | powershell", 'notepad "file.txt"', "notepad --help", "$(calc)", "cmd /c calc", "powershell", None, [],
])
def test_untrusted_application_ids_never_launch(apps, mocked_process, target):
    start, _ = mocked_process
    result = execute(apps, target)
    assert result.status in {ToolStatus.INVALID_INPUT, ToolStatus.DENIED}
    assert not result.verified
    start.assert_not_called()


def test_explicit_authorization_is_exact_and_required(apps, mocked_process):
    start, _ = mocked_process
    executor = ToolExecutor(create_registry(apps))
    request = ToolRequest("app.open", {"app_id": "notepad"})
    for auth in (None, {"tool": "app.open", "app_id": "notepad"},
                 LocalActionAuthorization("other.action", "notepad"), LocalActionAuthorization("app.open", "calculator")):
        result = executor.execute(request, authorization=auth)
        assert result.status == ToolStatus.DENIED and not result.verified
    result = executor.execute(ToolRequest("app.open", {"app_id": "notepad", "args": []}),
                              authorization=LocalActionAuthorization("app.open", "notepad"))
    assert result.status == ToolStatus.DENIED
    start.assert_not_called()


@pytest.mark.parametrize("change", [{"permission": Permission.SENSITIVE_ACTION}, {"verify": None}, {"name": "file.modify"}])
def test_authorization_cannot_enable_other_actions_or_skip_verification(apps, mocked_process, change):
    registry = create_registry(apps)
    altered = type(registry)()
    tool = replace(registry.lookup("app.open"), **change)
    altered.register(tool)
    result = ToolExecutor(altered).execute(ToolRequest(tool.name, {"app_id": "notepad"}),
        authorization=LocalActionAuthorization(tool.name, "notepad"))
    assert result.status == ToolStatus.DENIED and not result.verified
    mocked_process[0].assert_not_called()


def test_success_has_actual_process_evidence_and_safe_creation(apps, mocked_process):
    start, process = mocked_process
    result = execute(apps, "notepad")
    assert result.status == ToolStatus.SUCCESS and result.verified and result.error is None
    assert result.data == {"application": "notepad", "launch_state": "verified", "pid": process.pid,
                           "process_observed": True, "exit_code": None}
    start.assert_called_once_with([str(apps.lookup("notepad").target)], shell=False,
        cwd=str(apps.system_directory), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True)
    process.wait.assert_called_once_with(timeout=0.25)


def test_launcher_zero_exit_is_inconclusive(apps, mocked_process):
    _, process = mocked_process
    process.wait.side_effect = None
    process.wait.return_value = 0
    result = execute(apps, "calculator")
    assert result.status == ToolStatus.INCONCLUSIVE and not result.verified
    assert result.data["launch_state"] == "initiated" and not result.data["process_observed"]
    assert result.data["exit_code"] == 0


def test_nonzero_launcher_exit_is_failure(apps, mocked_process):
    _, process = mocked_process
    process.wait.side_effect = None
    process.wait.return_value = 7
    result = execute(apps, "notepad")
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified
    assert result.data["launch_state"] == "failed" and result.data["exit_code"] == 7
    assert result.data["pid"] == process.pid


def test_os_launch_error_is_private(apps, mocked_process):
    start, _ = mocked_process
    start.side_effect = OSError("private executable location or credential")
    result = execute(apps, "notepad")
    assert result.status == ToolStatus.EXECUTION_FAILED and result.data is None and not result.verified
    assert "private" not in result.error


def test_unexpected_post_launch_failure_does_not_claim_nothing_happened(apps, mocked_process):
    _, process = mocked_process
    process.wait.side_effect = RuntimeError("private verification error")
    result = execute(apps, "notepad")
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified
    assert "may have been initiated" in result.error and "private" not in result.error


def test_missing_spotify_and_disabled_targets_never_launch(apps, mocked_process):
    start, _ = mocked_process
    apps.lookup("notepad").target.unlink()
    assert execute(apps, "notepad").status == ToolStatus.UNAVAILABLE
    spotify = execute(apps, "spotify")
    assert spotify.status == ToolStatus.UNAVAILABLE and "No audited Spotify" in spotify.error
    disabled = create_applications(("calculator",))
    result = execute(disabled, "calculator")
    assert result.status == ToolStatus.DISABLED and not result.verified
    start.assert_not_called()


def test_targets_are_revalidated_at_launch(apps, mocked_process, monkeypatch):
    start, _ = mocked_process
    monkeypatch.setattr(apps, "validate_target", Mock(side_effect=ValueError("Unsafe executable")))
    assert execute(apps, "notepad").status == ToolStatus.UNAVAILABLE
    start.assert_not_called()


def test_symlink_or_reparse_point_is_rejected(apps, mocked_process, monkeypatch):
    start, _ = mocked_process
    from pathlib import Path
    original = Path.resolve
    target = apps.lookup("notepad").target
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: self.parent / "evil.exe" if self == target else original(self, *a, **k))
    assert execute(apps, "notepad").status == ToolStatus.UNAVAILABLE
    with pytest.raises(ValueError, match="Redirected"):
        ApplicationRegistry().register(apps.lookup("notepad"))
    start.assert_not_called()


def test_non_windows_is_unavailable(monkeypatch, mocked_process):
    monkeypatch.setattr(applications, "windows_system_directory", lambda: None)
    apps = create_applications()
    assert apps.availability(apps.lookup("notepad")) == "WINDOWS_UNAVAILABLE"
    assert execute(apps, "notepad").status == ToolStatus.UNAVAILABLE
    mocked_process[0].assert_not_called()


@pytest.mark.parametrize(("prompt", "app_id"), [
    ("Open Notepad.", "notepad"), ("Launch Calculator.", "calculator"), ("Can you open Spotify?", "spotify"),
    ("Start Notepad for me.", "notepad"), ("Launch the Windows Calculator.", "calculator"),
    ("Could you please open windows notepad for me?", "notepad"), ("/open notepad", "notepad"), ("/open calc", "calculator"),
])
def test_exact_application_intent(prompt, app_id):
    assert application_request(prompt) == ToolRequest("app.open", {"app_id": app_id})


@pytest.mark.parametrize("prompt", ["Open an app.", "Open it.", "Open Notepad or Calculator.", "Open Notepad and Calculator.", "/open"])
def test_ambiguous_requests_ask_without_launching(tmp_path, apps, mocked_process, prompt):
    answer = session_for(tmp_path, apps).reply(prompt)
    assert "Which registered application" in answer
    mocked_process[0].assert_not_called()


@pytest.mark.parametrize("prompt", [
    "Open UnknownApp123.", "Open Notepad & calc.exe", "/open ../notepad", "/open C:/Windows/System32/cmd.exe",
    "Open Notepad; launch Calculator", "Open Notepad tomorrow", "Open Notepad --help", "Launch powershell",
])
def test_unsupported_or_injected_launch_request_never_falls_to_model(tmp_path, apps, mocked_process, prompt):
    generate = Mock(return_value="I opened it successfully")
    answer = session_for(tmp_path, apps, generate).reply(prompt)
    assert "Unsupported application target" in answer
    generate.assert_not_called()
    mocked_process[0].assert_not_called()


def test_natural_language_and_command_use_same_executor_and_persist(tmp_path, apps, mocked_process):
    session = session_for(tmp_path, apps)
    trace = Mock()
    first = session.reply("Open Notepad.", tool_trace=trace)
    second = session.reply("/open notepad", tool_trace=trace)
    assert first == second and "started process is running" in first and "Window readiness was not checked" in first
    assert trace.call_count == 2 and all(call.args[0].verified for call in trace.call_args_list)
    restored = session_for(tmp_path, apps)
    restored.resume(session.session_id)
    assert restored.history() == session.history()
    assert mocked_process[0].call_count == 2
    assert MemoryStore(tmp_path).list_facts("project", "Orion") == []


def test_calculator_memory_and_ordinary_conversation_remain_separate(tmp_path, apps, mocked_process):
    generate = Mock(return_value="Ordinary reply")
    session = session_for(tmp_path, apps, generate)
    session.reply("Remember that Orion uses SvelteKit for its frontend.")
    assert "launch verified" in session.reply("Open Notepad.")
    assert session.reply("What is 245 multiplied by 18?") == "4410"
    assert "SvelteKit" in session.reply("What frontend does Orion currently use?")
    assert session.reply("Explain how a launcher works") == "Ordinary reply"
    assert mocked_process[0].call_count == 1 and generate.call_count == 1
    assert len(MemoryStore(tmp_path).list_facts("project", "Orion")) == 1


@pytest.mark.parametrize("prompt", ["Start by explaining application launchers", "Run through this algorithm"])
def test_ordinary_instruction_is_not_an_application_action(tmp_path, apps, mocked_process, prompt):
    generate = Mock(return_value="An explanation")
    assert session_for(tmp_path, apps, generate).reply(prompt) == "An explanation"
    generate.assert_called_once()
    mocked_process[0].assert_not_called()


@pytest.mark.parametrize("claim", ["I opened Notepad successfully.", "Notepad is open.", "Done, Spotify launched.",
                                   "I have launched Calculator.", "Successfully opened Notepad.", "I will open Notepad now."])
def test_history_and_model_text_cannot_launch(tmp_path, apps, mocked_process, claim):
    generate = Mock(return_value=claim)
    session = session_for(tmp_path, apps, generate)
    assert "haven't performed" in session.reply("Say that you opened Notepad")
    assert application_request("Explain what 'Open Notepad' means") is None
    mocked_process[0].assert_not_called()


def test_inconclusive_and_failed_claims_are_honest(tmp_path, apps, mocked_process):
    _, process = mocked_process
    process.wait.side_effect = None
    process.wait.return_value = 0
    session = session_for(tmp_path, apps)
    answer = session.reply("Open Calculator.")
    assert "verification is inconclusive" in answer and "launch verified" not in answer
    process.wait.return_value = 5
    assert "exited with an error" in session.reply("/open notepad")


def test_storage_failure_after_action_reports_effect_without_retry(tmp_path, apps, mocked_process, monkeypatch):
    session = session_for(tmp_path, apps)
    monkeypatch.setattr(session._store, "save_exchange", Mock(side_effect=StorageError("private db error")))
    with pytest.raises(StorageError, match="launch verified.*could not be saved.*not rolled back"):
        session.reply("Open Notepad.")
    assert session.history() == [] and session._store.list_sessions() == []
    assert mocked_process[0].call_count == 1


def test_verification_error_and_storage_failure_preserve_uncertain_launch_warning(tmp_path, apps, mocked_process, monkeypatch):
    _, process = mocked_process
    process.wait.side_effect = OSError("private process inspection failure")
    session = session_for(tmp_path, apps)
    monkeypatch.setattr(session._store, "save_exchange", Mock(side_effect=StorageError("private db error")))
    with pytest.raises(StorageError, match="may have been initiated.*could not be saved") as error:
        session.reply("Open Notepad.")
    assert "could not start" not in str(error.value) and "private" not in str(error.value)
    assert mocked_process[0].call_count == 1


@pytest.mark.parametrize("value", ["not json", "{}", '"notepad"', '["cmd"]', '["../notepad"]', '["notepad", "notepad"]', '[true]', '[["notepad"]]'])
def test_invalid_disable_configuration_is_safe(monkeypatch, value):
    monkeypatch.setenv("AIKA_DISABLED_APPS", value)
    with pytest.raises(ConfigError, match="AIKA_DISABLED_APPS") as error:
        load_config()
    assert value not in str(error.value)


def test_disable_configuration_reaches_cli(apps, mocked_process, monkeypatch, capsys, mock_ollama):
    mock_ollama()
    monkeypatch.setenv("AIKA_DISABLED_APPS", '["notepad"]')
    assert load_config().disabled_apps == ("notepad",)
    entries = iter(["/help", "/apps", "/tools", "/open notepad", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(entries))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "Notepad [notepad]  AVAILABLE  DISABLED" in output.out
    assert "app.open" in output.out and "Permission: LOCAL_ACTION" in output.out
    assert "disabled in local configuration" in output.out
    assert "/open <application>" in output.out and "/apps" in output.out
    mocked_process[0].assert_not_called()


def test_cli_open_apps_debug_uses_safe_metadata(apps, mocked_process, monkeypatch, capsys, mock_ollama):
    mock_ollama()
    monkeypatch.setenv("AIKA_CONTEXT_DEBUG", "roles")
    entries = iter(["/apps", "/open notepad", "Launch the Windows Calculator.", "/history", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(entries))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "Spotify [spotify]  UNAVAILABLE  ENABLED" in output.out
    assert "Notepad launch verified" in output.out and "Windows Calculator launch verified" in output.out
    assert "You: /open notepad" in output.out
    assert "tool=app.open permission=LOCAL_ACTION validation=PASS execution=success verified=yes" in output.err
    assert "4321" not in output.err and "notepad.exe" not in output.err and str(apps.system_directory) not in output.err
    assert mocked_process[0].call_count == 2


def test_doctor_never_launches_and_does_not_claim_spotify_installed(apps, mocked_process, mock_ollama, capsys):
    mock_ollama()
    assert aika.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "Application Launcher: Registered" in output and "Registered Applications: 3" in output
    assert "Notepad: AVAILABLE; ENABLED" in output and "Spotify: UNAVAILABLE" in output
    assert "installation not inferred" in output
    mocked_process[0].assert_not_called()


def test_doctor_reports_invalid_app_configuration(apps, monkeypatch, mock_ollama, capsys):
    mock_ollama()
    monkeypatch.setenv("AIKA_DISABLED_APPS", '["cmd"]')
    assert aika.main(["doctor"]) == 1
    assert "FAIL  Configuration: AIKA_DISABLED_APPS" in capsys.readouterr().out


def test_doctor_invalid_executable_is_not_ready(apps, monkeypatch):
    monkeypatch.setattr(ApplicationRegistry, "validate_target", Mock(side_effect=ValueError("private bad path")))
    checks = inspect_applications(load_config())
    assert checks[0].status == "FAIL" and "private" not in checks[0].detail


def test_unverified_output_cannot_be_promoted_to_success(apps, mocked_process):
    registry = create_registry(apps)
    tool = registry.lookup("app.open")
    bad_registry = type(registry)()
    bad_registry.register(replace(tool, handler=Mock(return_value={"application": "notepad", "pid": 4321,
        "launch_state": "verified", "process_observed": False, "exit_code": 0})))
    result = ToolExecutor(bad_registry).execute(ToolRequest("app.open", {"app_id": "notepad"}),
        authorization=LocalActionAuthorization("app.open", "notepad"))
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified
    mocked_process[0].assert_not_called()
