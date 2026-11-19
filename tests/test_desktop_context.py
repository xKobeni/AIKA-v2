from dataclasses import replace
from datetime import datetime
import ctypes as C
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.capabilities import create_registry
from src.capabilities import desktop_context as desktop
from src.capabilities.contracts import Permission, ToolRequest, ToolStatus
from src.capabilities.desktop_intent import desktop_request, desktop_question
from src.capabilities.executor import ToolExecutor
from src.config import load_config, resolve_user_config_path, ConfigError
from src.intelligence.conversation import ConversationSession
from src.intelligence.planning import build_plan, PlanError
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore


REAL_OPEN = desktop.open_windows


class FakeWindows:
    def window(self):
        return 100

    def pid(self, window):
        return 42

    def image(self, pid):
        return "Éditeur使用者.exe"

    def monitors(self):
        return [1, 2]

    def monitor(self, handle):
        return handle == 1, f"synthetic-display-{handle}"

    def resolution(self, device):
        return (3840, 2160) if device.endswith("1") else (1080, 1920)


@pytest.fixture
def windows(monkeypatch):
    api = FakeWindows()
    monkeypatch.setattr(desktop, "open_windows", Mock(return_value=api))
    return api


def execute(scope="all", enabled=True):
    return ToolExecutor(create_registry(desktop_context_enabled=enabled)).execute(
        ToolRequest("desktop.context", {"scope": scope}))


def test_default_gate_prevents_any_native_initialization():
    assert load_config().desktop_context_enabled is False
    tool = next(t for t in create_registry().list_tools() if t.name == "desktop.context")
    assert not tool.enabled and tool.permission == Permission.READ_ONLY
    result = execute(enabled=False)
    assert result.status == ToolStatus.DISABLED and not result.verified and result.data is None


def test_config_precedence_uses_existing_loader(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("AIKA_DESKTOP_CONTEXT_ENABLED=on\n", encoding="utf-8")
    assert load_config().desktop_context_enabled
    user = resolve_user_config_path()
    user.parent.mkdir(parents=True)
    user.write_text("AIKA_DESKTOP_CONTEXT_ENABLED=off\n", encoding="utf-8")
    assert not load_config().desktop_context_enabled
    monkeypatch.setenv("AIKA_DESKTOP_CONTEXT_ENABLED", "on")
    assert load_config().desktop_context_enabled


@pytest.mark.parametrize("value,expected", [("on", True), ("TRUE", True), ("1", True), ("off", False), ("false", False), ("0", False)])
def test_configuration_explicit_gate(monkeypatch, value, expected):
    monkeypatch.setenv("AIKA_DESKTOP_CONTEXT_ENABLED", value)
    assert load_config().desktop_context_enabled is expected


@pytest.mark.parametrize("value", ["", "yes", "sometimes", "private-invalid-value"])
def test_configuration_invalid_gate_is_safe(monkeypatch, value):
    monkeypatch.setenv("AIKA_DESKTOP_CONTEXT_ENABLED", value)
    with pytest.raises(ConfigError, match="must be off/on") as error:
        load_config()
    assert "private-invalid-value" not in str(error.value)


@pytest.mark.parametrize("prompt,scope", [
    ("Aika, what application am I using right now?", "foreground"),
    ("What's my active window's application?", "foreground"),
    ("What is my screen resolution?", "displays"),
    ("How many monitors are connected?", "displays"),
    ("Show my desktop information.", "all"), ("/desktop-context", "all"),
])
def test_explicit_intents(prompt, scope):
    assert desktop_request(prompt) == ToolRequest("desktop.context", {"scope": scope})


@pytest.mark.parametrize("prompt", [
    "Can you tell what app I'm using?", "Are you able to see my desktop?", "Do you support screen awareness?",
    "Can you take screenshots?", "How does Windows detect the active window?", "Show it.",
    "What is screen resolution?", "What application am I using and delete my files?",
    "/desktop-context --status", "/desktop-context --screenshot", "Remember what app I am using.",
])
def test_nonrequests_never_become_desktop_observations(prompt):
    assert desktop_request(prompt) is None


def test_verified_native_metadata_and_scope(windows):
    result = execute()
    assert result.status == ToolStatus.SUCCESS and result.verified
    data = result.data
    assert data["capability"] == "desktop.context" and data["status"] == "complete"
    assert data["foreground"]["executable"] == "Éditeur使用者.exe" and data["foreground"]["pid"] == 42
    assert data["displays"]["count"] == 2
    assert data["displays"]["primary_resolution"] == {"width_px": 3840, "height_px": 2160}
    assert data["displays"]["monitors"][1]["height_px"] == 1920
    assert datetime.fromisoformat(data["collected_at"]).utcoffset() is not None
    assert data["source"] == desktop.SOURCE
    assert "synthetic-display" not in json.dumps(data)
    windows.monitors = Mock(side_effect=AssertionError("Wrong scope"))
    assert execute("foreground").verified
    windows.image = Mock(side_effect=AssertionError("Wrong scope"))
    windows.monitors = lambda: [1, 2]
    assert execute("displays").verified


@pytest.mark.parametrize("failure,reason", [("none", "no_foreground"), ("denied", "access_denied"),
                                            ("dead", "process_unavailable"), ("window_race", "foreground_changed"),
                                            ("pid_race", "foreground_changed"), ("path", "image_unavailable")])
def test_foreground_failures_have_no_false_success_or_private_data(windows, failure, reason):
    if failure == "none":
        windows.window = lambda: 0
    elif failure in {"denied", "dead"}:
        windows.image = Mock(side_effect=PermissionError("PRIVATE_PATH") if failure == "denied" else OSError("PRIVATE_PATH"))
    elif failure == "window_race":
        windows.window = Mock(side_effect=[100, 101])
    elif failure == "pid_race":
        windows.pid = Mock(side_effect=[42, 43])
    else:
        windows.image = lambda pid: "C:\\PRIVATE_PATH\\Editor.exe"
    result = execute("foreground")
    assert not result.verified and result.status == ToolStatus.INCONCLUSIVE
    assert result.data["status"] == "unavailable" and result.data["foreground"]["error"] == reason
    assert result.data["foreground"]["executable"] is None and result.data["foreground"]["pid"] is None
    assert "PRIVATE_PATH" not in json.dumps(result.data)


def test_partial_display_does_not_use_logical_coordinates_or_claim_complete(windows):
    windows.resolution = Mock(side_effect=[(3840, 2160), OSError("PRIVATE_DEVICE")])
    result = execute()
    assert result.status == ToolStatus.INCONCLUSIVE and not result.verified
    assert result.data["status"] == "partial" and result.data["displays"]["status"] == "partial"
    assert result.data["displays"]["count"] == 2
    assert result.data["displays"]["monitors"][1]["width_px"] is None
    assert "PRIVATE_DEVICE" not in json.dumps(result.data)


@pytest.mark.parametrize("failure", ["change", "empty", "primary_missing", "disconnect", "oversize"])
def test_display_changes_and_missing_information_are_conservative(windows, failure):
    if failure == "change":
        windows.monitors = Mock(side_effect=[[1, 2], [1]])
    elif failure == "empty":
        windows.monitors = lambda: []
    elif failure == "primary_missing":
        windows.monitor = lambda handle: (False, "synthetic-display-1")
    elif failure == "disconnect":
        windows.monitor = Mock(side_effect=OSError())
    else:
        windows.monitors = lambda: list(range(65))
    result = execute("displays")
    assert not result.verified and result.data["status"] in {"partial", "unavailable"}
    assert result.data["displays"]["primary_resolution"] is None


@pytest.mark.parametrize("arguments", [{"scope": []}, {"scope": "screen"}, {"screenshot": True}, {"scope": None}])
def test_invalid_arguments_fail_before_collection(arguments):
    result = ToolExecutor(create_registry(desktop_context_enabled=True)).execute(ToolRequest("desktop.context", arguments))
    assert result.status == ToolStatus.INVALID_INPUT


def test_nonwindows_and_missing_api_are_controlled(monkeypatch):
    monkeypatch.setattr(desktop.platform, "system", lambda: "Linux")
    with pytest.raises(desktop.ToolExecutionError) as error:
        REAL_OPEN()
    assert error.value.status == ToolStatus.UNAVAILABLE
    monkeypatch.setattr(desktop.platform, "system", lambda: "Windows")
    monkeypatch.setattr(desktop, "WindowsDesktop", Mock(side_effect=AttributeError("PRIVATE")))
    with pytest.raises(desktop.ToolExecutionError, match="APIs are unavailable") as error:
        REAL_OPEN()
    assert "PRIVATE" not in str(error.value)


def test_output_contract_rejects_unverified_or_sensitive_fields(windows):
    data = desktop.collect_context({"scope": "all"})
    for mutation in (lambda d: d.update(status="complete", scope="invalid"),
                     lambda d: d["foreground"].update(window_title="PRIVATE"),
                     lambda d: d["foreground"].update(executable="C:\\PRIVATE\\app.exe"),
                     lambda d: d["displays"].update(count=3),
                     lambda d: d.update(collected_at="2026-11-19")):
        damaged = json.loads(json.dumps(data))
        mutation(damaged)
        with pytest.raises(ValueError):
            desktop.validate_output(damaged)
    registry = create_registry(desktop_context_enabled=True)
    tool = registry.lookup("desktop.context")
    registry._tools[tool.name] = replace(tool, handler=lambda _: {**data, "status": "partial"})
    result = ToolExecutor(registry).execute(ToolRequest(tool.name, {}))
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified and result.data is None


def test_failed_verifier_never_presents_complete_result_as_verified(windows):
    from src.capabilities.desktop_intent import format_desktop_result
    registry = create_registry(desktop_context_enabled=True)
    tool = registry.lookup("desktop.context")
    registry._tools[tool.name] = replace(tool, verify=lambda data: False)
    result = ToolExecutor(registry).execute(ToolRequest(tool.name, {}))
    assert result.status == ToolStatus.INCONCLUSIVE
    assert "Éditeur" not in format_desktop_result(result)


def test_native_bindings_minimum_rights_basename_handle_cleanup_and_physical_modes(monkeypatch):
    user = SimpleNamespace(**{name: Mock() for name in ("GetForegroundWindow", "GetWindowThreadProcessId", "EnumDisplayMonitors", "GetMonitorInfoW", "EnumDisplaySettingsW")})
    kernel = SimpleNamespace(**{name: Mock() for name in ("OpenProcess", "QueryFullProcessImageNameW", "CloseHandle")})
    monkeypatch.setattr(C, "WinDLL", lambda name, **kwargs: user if name == "user32" else kernel, raising=False)
    monkeypatch.setattr(C, "WINFUNCTYPE", getattr(C, "WINFUNCTYPE", C.CFUNCTYPE), raising=False)
    api = desktop.WindowsDesktop()
    kernel.OpenProcess.return_value = 123
    def query(handle, flags, buffer, size):
        buffer.value = "C:\\Private Synthetic\\Éditeur.exe"
        return 1
    kernel.QueryFullProcessImageNameW.side_effect = query
    assert api.image(42) == "Éditeur.exe"
    kernel.OpenProcess.assert_called_with(0x1000, False, 42)
    kernel.CloseHandle.assert_called_once_with(123)
    kernel.QueryFullProcessImageNameW.side_effect = None
    kernel.QueryFullProcessImageNameW.return_value = 0
    with pytest.raises(OSError):
        api.image(42)
    assert kernel.CloseHandle.call_count == 2
    kernel.OpenProcess.return_value = 0
    monkeypatch.setattr(C, "get_last_error", lambda: 5, raising=False)
    with pytest.raises(PermissionError):
        api.image(42)
    assert kernel.CloseHandle.call_count == 2
    def settings(device, mode, pointer):
        assert mode == 0xFFFFFFFF
        assert pointer._obj.dmSize == C.sizeof(desktop.DisplayMode)
        pointer._obj.dmFields = 0x180000
        pointer._obj.dmPelsWidth, pointer._obj.dmPelsHeight = 3840, 2160
        return 1
    user.EnumDisplaySettingsW.side_effect = settings
    assert api.resolution("synthetic-device") == (3840, 2160)
    user.GetForegroundWindow.return_value = 100
    assert api.window() == 100
    def process_id(window, pointer):
        pointer._obj.value = 42
        return 1
    user.GetWindowThreadProcessId.side_effect = process_id
    assert api.pid(100) == 42
    def enumerate_monitors(dc, rect, callback, data):
        assert dc is None and rect is None
        return callback(1, None, None, 0) and callback(2, None, None, 0)
    user.EnumDisplayMonitors.side_effect = enumerate_monitors
    assert api.monitors() == [1, 2]
    def monitor_info(handle, pointer):
        assert pointer._obj.cbSize == C.sizeof(desktop.MonitorInfo)
        pointer._obj.dwFlags = 1
        pointer._obj.szDevice = "SyntheticDisplay"
        # DPI-scaled logical dimensions intentionally disagree with the physical mode.
        pointer._obj.rcMonitor.right, pointer._obj.rcMonitor.bottom = 1920, 1080
        return 1
    user.GetMonitorInfoW.side_effect = monitor_info
    assert api.monitor(1) == (True, "SyntheticDisplay")
    assert api.resolution("SyntheticDisplay") == (3840, 2160)
    # No GetSystemMetrics, DPI setter, title, clipboard, screenshot, launch or input API is bound.
    assert set(vars(user)) == {"GetForegroundWindow", "GetWindowThreadProcessId", "EnumDisplayMonitors", "GetMonitorInfoW", "EnumDisplaySettingsW"}


def test_session_privacy_no_archive_memory_model_or_launch(windows, tmp_path, monkeypatch):
    model = Mock(return_value="ordinary response")
    store, memory = ConversationStore(tmp_path), MemoryStore(tmp_path)
    session = ConversationSession("Synthetic persona", 10, model, store, memory, desktop_context_enabled=True)
    save = Mock(wraps=store.save_exchange)
    monkeypatch.setattr(store, "save_exchange", save)
    monkeypatch.setattr(memory, "set_fact", Mock(side_effect=AssertionError("No desktop memory writes")))
    monkeypatch.setattr(memory, "delete_fact", Mock(side_effect=AssertionError("No desktop memory writes")))
    traces = []
    answer = session.reply("What application am I using right now?", tool_trace=traces.append)
    assert "Éditeur使用者.exe" in answer and traces[0].verified
    assert session.turn_count == 0 and session.history() == [] and store.list_sessions() == []
    save.assert_not_called()
    model.assert_not_called()
    session.reply("Hello")
    assert "Éditeur" not in json.dumps(model.call_args.args[0], ensure_ascii=False)
    assert session.turn_count == 1 and "Éditeur" not in json.dumps(store.load_session(session.session_id, 10), ensure_ascii=False)


@pytest.mark.parametrize("enabled", [False, True])
def test_capability_and_status_do_not_collect(enabled, tmp_path):
    model = Mock(side_effect=AssertionError("No inference permitted"))
    session = ConversationSession("Synthetic", 10, model, ConversationStore(tmp_path), desktop_context_enabled=enabled)
    for prompt in ("Can you tell what app I'm using?", "Are you able to see my desktop?", "Do you support screen awareness?",
                   "Can you take screenshots?", "/desktop-context --status", "/desktop-context --invalid", "/capabilities"):
        assert session.reply(prompt)
    if not enabled:
        assert "disabled" in session.reply("/desktop-context").lower()
    model.assert_not_called()


def test_sensitive_permission_override_denies_observation(windows):
    registry = create_registry(desktop_context_enabled=True)
    tool = registry.lookup("desktop.context")
    registry._tools[tool.name] = replace(tool, permission=Permission.SENSITIVE_ACTION)
    result = ToolExecutor(registry).execute(ToolRequest(tool.name, {}))
    assert result.status == ToolStatus.DENIED and not result.verified
    desktop.open_windows.assert_not_called()


def test_agent_cannot_acquire_desktop_observations_from_plan(windows, tmp_path):
    registry = create_registry(desktop_context_enabled=True)
    proposed = json.dumps({"steps": [{"instruction": "show my desktop information", "depends_on": []}]})
    with pytest.raises(PlanError):
        build_plan("show my desktop information", registry, lambda _: proposed)
    desktop.open_windows.assert_not_called()


def test_interrupt_does_not_store_observation_and_releases_session(windows, tmp_path):
    windows.image = Mock(side_effect=KeyboardInterrupt())
    store = ConversationStore(tmp_path)
    session = ConversationSession("Synthetic", 10, Mock(), store, desktop_context_enabled=True)
    with pytest.raises(KeyboardInterrupt):
        session.reply("/desktop-context")
    assert session.history() == [] and store.list_sessions() == []
    assert not session._request_lock.locked()


def test_cli_dispatch_and_trace_minimize_desktop_data(windows, tmp_path, capsys):
    from src.cli import handle_chat_command, show_tool_trace
    store = ConversationStore(tmp_path)
    settings = replace(load_config(), desktop_context_enabled=True, context_debug="roles")
    session = ConversationSession("Synthetic", 10, Mock(), store, desktop_context_enabled=True)
    handle_chat_command("/desktop-context --status", settings, session, store)
    desktop.open_windows.assert_not_called()
    handle_chat_command("/desktop-context", settings, session, store)
    output = capsys.readouterr()
    assert "Éditeur使用者.exe" in output.out and "3840" in output.out
    assert "desktop.context" in output.err and "Éditeur" not in output.err and "3840" not in output.err
    assert store.list_sessions() == []
