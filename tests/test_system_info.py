from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import PureWindowsPath
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

import aika
import src.capabilities.system_info as info
import src.diagnostics as diagnostics
from src.capabilities import create_registry
from src.capabilities.contracts import Permission, ToolExecutionError, ToolRequest, ToolStatus
from src.capabilities.executor import ToolExecutor
from src.capabilities.registry import ToolRegistry
from src.capabilities.system_info import initialize_measurements as initialize_interfaces
from src.capabilities.system_intent import gib, system_request
from src.intelligence.conversation import ConversationSession
from src.intelligence.persona import HISTORY_OMITTED
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore, StorageError


GIB = 1024**3


class AccessDenied(Exception):
    pass


class NoSuchProcess(Exception):
    pass


class ZombieProcess(NoSuchProcess):
    pass


def process(pid, name, rss, **extra):
    return NS(info={"pid": pid, "name": name, "memory_info": NS(rss=rss) if rss is not None else None, **extra})


@pytest.fixture
def measurements(monkeypatch):
    rows = [process(8, "small.exe", GIB), process(4, "large.exe", 3*GIB), process(12, "medium.exe", 2*GIB)]
    backend = NS(
        __version__="test-version", AccessDenied=AccessDenied, NoSuchProcess=NoSuchProcess, ZombieProcess=ZombieProcess,
        cpu_percent=Mock(return_value=22.5), cpu_count=Mock(side_effect=lambda *, logical: 8 if logical else 4),
        virtual_memory=Mock(return_value=NS(total=16*GIB, available=6*GIB)),
        disk_usage=Mock(return_value=NS(total=1000*GIB, used=600*GIB, free=400*GIB, percent=60)),
        process_iter=Mock(side_effect=lambda **_: iter(rows)),
    )
    monkeypatch.setattr(info, "initialize_measurements", lambda: backend)
    monkeypatch.setattr(info.platform, "system", lambda: "Windows")
    monkeypatch.setattr(info.platform, "win32_ver", lambda: ("11", "10.0.26100", "", ""))
    monkeypatch.setattr(info.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(info.sys, "getwindowsversion", lambda: NS(build=26100), raising=False)
    monkeypatch.setattr(info, "windows_system_directory", lambda: PureWindowsPath("Z:/Windows/System32"))
    return backend


def execute(name="system.snapshot", arguments=None):
    return ToolExecutor(create_registry()).execute(ToolRequest(name, {} if arguments is None else arguments))


def session_for(tmp_path, generate=None):
    return ConversationSession("Identity", 10, generate or Mock(side_effect=AssertionError("No model measurements")),
                               ConversationStore(tmp_path), MemoryStore(tmp_path))


def test_registration_and_read_only_permissions():
    registry = create_registry()
    for name in ("system.snapshot", "system.processes"):
        tool = registry.lookup(name)
        assert tool.permission == Permission.READ_ONLY and tool.enabled
        assert callable(tool.input_contract) and callable(tool.output_contract)


def test_snapshot_measures_cpu_ram_storage_os_and_provenance(measurements):
    result = execute()
    assert result.status == ToolStatus.SUCCESS and result.verified
    data = result.data
    assert data["measurements"]["cpu"] == {"usage_percent": 22.5, "logical_cores": 8, "physical_cores": 4}
    measurements.cpu_percent.assert_called_once_with(interval=0.1)
    assert data["measurements"]["memory"] == {"total_bytes": 16*GIB, "used_bytes": 10*GIB, "available_bytes": 6*GIB, "usage_percent": 62.5}
    assert data["measurements"]["storage"] == {"system_drive": "Z:\\", "total_bytes": 1000*GIB, "used_bytes": 600*GIB, "free_bytes": 400*GIB, "usage_percent": 60}
    measurements.disk_usage.assert_called_once_with("Z:\\")
    assert data["measurements"]["os"] == {"name": "Windows", "version": "11 10.0.26100", "build": 26100, "architecture": "AMD64"}
    assert datetime.fromisoformat(data["collected_at"]).utcoffset() is not None
    assert "psutil" in data["source"] and data["unavailable_fields"] == []
    measurements.process_iter.assert_not_called()


@pytest.mark.parametrize("section", ["cpu", "memory", "storage", "os"])
def test_focused_snapshot_does_not_collect_unrequested_sections(measurements, section):
    result = execute(arguments={"section": section})
    assert set(result.data["measurements"]) == {section}
    assert measurements.cpu_percent.call_count == (section == "cpu")
    assert measurements.virtual_memory.call_count == (section == "memory")
    assert measurements.disk_usage.call_count == (section == "storage")
    measurements.process_iter.assert_not_called()


def test_cpu_sample_is_fresh_and_can_legitimately_be_zero(measurements):
    measurements.cpu_percent.side_effect = [0, 37.5]
    assert execute(arguments={"section": "cpu"}).data["measurements"]["cpu"]["usage_percent"] == 0
    assert execute(arguments={"section": "cpu"}).data["measurements"]["cpu"]["usage_percent"] == 37.5
    assert measurements.cpu_percent.call_count == 2


def test_optional_core_count_is_unavailable_not_zero(measurements):
    measurements.cpu_count.side_effect = lambda *, logical: 8 if logical else None
    data = execute(arguments={"section": "cpu"}).data
    assert data["measurements"]["cpu"]["physical_cores"] is None
    assert "cpu.physical_cores" in data["unavailable_fields"]


@pytest.mark.parametrize(("method", "path"), [("cpu_percent", "cpu.usage_percent"), ("virtual_memory", "memory"), ("disk_usage", "storage")])
def test_partial_measurement_failures_preserve_other_valid_fields(measurements, method, path):
    getattr(measurements, method).side_effect = OSError("private API error")
    result = execute()
    assert result.verified and result.status == ToolStatus.SUCCESS
    assert path in result.data["unavailable_fields"]
    assert result.data["measurements"]["os"]["name"] == "Windows"
    assert "private" not in repr(result)


def test_cpu_failure_does_not_invent_usage(measurements, tmp_path):
    measurements.cpu_percent.side_effect = OSError("private")
    answer = session_for(tmp_path).reply("What's my CPU usage?")
    assert "CPU Usage: unavailable" in answer and "0.0%" not in answer


def test_full_measurement_failure_is_not_verified(measurements):
    measurements.virtual_memory.side_effect = OSError("private")
    result = execute(arguments={"section": "memory"})
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified and result.data is None
    assert "private" not in result.error


def test_full_snapshot_failure_has_no_verified_metadata_only_success(measurements, monkeypatch):
    for name in ("cpu_count", "cpu_percent", "virtual_memory", "disk_usage"):
        getattr(measurements, name).side_effect = OSError("private")
    monkeypatch.setattr(info.platform, "system", Mock(side_effect=OSError()))
    monkeypatch.setattr(info.platform, "win32_ver", Mock(side_effect=OSError()))
    monkeypatch.setattr(info.platform, "machine", Mock(side_effect=OSError()))
    monkeypatch.setattr(info.sys, "getwindowsversion", Mock(side_effect=OSError()))
    result = execute()
    assert not result.verified and result.status == ToolStatus.EXECUTION_FAILED


def test_unavailable_system_drive_does_not_probe_arbitrary_locations(measurements, monkeypatch):
    monkeypatch.setattr(info, "windows_system_directory", lambda: None)
    result = execute(arguments={"section": "storage"})
    assert result.status == ToolStatus.EXECUTION_FAILED
    measurements.disk_usage.assert_not_called()


def test_missing_os_fields_are_individually_unavailable(measurements, monkeypatch):
    monkeypatch.setattr(info.platform, "win32_ver", Mock(side_effect=OSError()))
    monkeypatch.setattr(info.sys, "getwindowsversion", Mock(side_effect=OSError()))
    data = execute(arguments={"section": "os"}).data
    assert data["measurements"]["os"]["version"] is None and data["measurements"]["os"]["build"] is None
    assert {"os.version", "os.build"} <= set(data["unavailable_fields"])
    assert data["measurements"]["os"]["architecture"] == "AMD64"


@pytest.mark.parametrize("value", [-1, 101, float("nan"), float("inf"), True])
def test_invalid_cpu_readings_are_never_presented_as_measured(measurements, value):
    measurements.cpu_percent.return_value = value
    result = execute(arguments={"section": "cpu"})
    assert result.data["measurements"]["cpu"]["usage_percent"] is None


@pytest.mark.parametrize("arguments", [{"section": "network"}, {"section": []}, {"section": True}, {"path": "C:/private"}, {"section": "cpu", "interval": 1000}])
def test_invalid_snapshot_arguments_reject_without_measurement(measurements, arguments):
    result = execute(arguments=arguments)
    assert result.status == ToolStatus.INVALID_INPUT and not result.verified
    measurements.cpu_percent.assert_not_called()
    measurements.virtual_memory.assert_not_called()


def test_snapshot_output_contract_rejects_fabricated_shapes(measurements):
    data = execute().data
    registry = ToolRegistry()
    tool = create_registry().lookup("system.snapshot")
    for change in (lambda value: value.update(collected_at="2026-11-18T00:00:00"),
                   lambda value: value["measurements"]["cpu"].update(usage_percent=1000),
                   lambda value: value["measurements"]["memory"].update(total_bytes=-1)):
        invalid = deepcopy(data)
        change(invalid)
        registry = ToolRegistry()
        registry.register(replace(tool, handler=Mock(return_value=invalid)))
        result = ToolExecutor(registry).execute(ToolRequest("system.snapshot", {}))
        assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified


@pytest.mark.parametrize(("value", "expected"), [(None, "unavailable"), (0, "0.00 GiB"), (GIB, "1.00 GiB"), (GIB//2, "0.50 GiB")])
def test_consistent_gib_format(value, expected):
    assert gib(value) == expected


def test_process_enumeration_and_ordering(measurements):
    result = execute("system.processes")
    assert result.verified and [row["pid"] for row in result.data["processes"]] == [4, 8, 12]
    measurements.process_iter.assert_called_once_with(attrs=["pid", "name", "memory_info"], ad_value=None)
    assert result.data["limit"] == 10
    assert datetime.fromisoformat(result.data["collected_at"]).utcoffset() is not None
    measurements.cpu_percent.assert_not_called()
    measurements.virtual_memory.assert_not_called()


@pytest.mark.parametrize("limit", [1, 10, 25])
def test_process_memory_ordering_result_limits_and_unknown_values_last(measurements, limit):
    rows = [process(pid, f"sample{pid}.exe", pid*GIB) for pid in range(1, 40)]
    rows.append(process(100, "denied-memory.exe", None))
    measurements.process_iter.side_effect = lambda **_: iter(reversed(rows))
    data = execute("system.processes", {"sort": "memory", "limit": limit}).data
    assert len(data["processes"]) == limit and data["enumerated_count"] == 40
    assert [row["pid"] for row in data["processes"]] == list(range(39, 39-limit, -1))
    assert data["inaccessible_count"] == 1


@pytest.mark.parametrize("arguments", [{"limit": 0}, {"limit": 26}, {"limit": True}, {"limit": "10"}, {"limit": -1}, {"sort": "cpu"}, {"sort": []}, {"cmdline": True}])
def test_invalid_process_arguments_do_not_enumerate(measurements, arguments):
    result = execute("system.processes", arguments)
    assert result.status == ToolStatus.INVALID_INPUT and not result.verified
    measurements.process_iter.assert_not_called()


class BrokenProcess:
    def __init__(self, error):
        self.error = error

    @property
    def info(self):
        raise self.error


def test_protected_and_exiting_processes_do_not_crash(measurements):
    rows = [BrokenProcess(AccessDenied()), BrokenProcess(NoSuchProcess()), BrokenProcess(ZombieProcess()), process(20, None, None), process(30, "accessible.exe", GIB)]
    measurements.process_iter.side_effect = lambda **_: iter(rows)
    result = execute("system.processes")
    assert result.verified and [row["pid"] for row in result.data["processes"]] == [20, 30]
    assert result.data["inaccessible_count"] == 2 and result.data["exited_count"] == 2
    assert result.data["processes"][0]["memory_bytes"] is None


def test_fully_inaccessible_processes_are_not_verified(measurements):
    measurements.process_iter.side_effect = lambda **_: iter([BrokenProcess(AccessDenied())])
    result = execute("system.processes")
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified


def test_empty_process_snapshot_is_explicit(measurements, tmp_path):
    measurements.process_iter.side_effect = lambda **_: iter(())
    assert "No process entries were returned" in session_for(tmp_path).reply("/processes")


def test_process_api_failure_is_controlled_and_private(measurements):
    measurements.process_iter.side_effect = OSError("private API credentials")
    result = execute("system.processes")
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified
    assert "private" not in result.error


def test_iterator_races_and_cache_cleanup_are_bounded(measurements):
    class RacyIterator:
        def __init__(self):
            self.events = iter([AccessDenied(), NoSuchProcess(), process(30, "accessible.exe", GIB)])

        def __iter__(self):
            return self

        def __next__(self):
            event = next(self.events)
            if isinstance(event, Exception):
                raise event
            return event

    measurements.process_iter.side_effect = lambda **_: RacyIterator()
    data = execute("system.processes").data
    assert data["inaccessible_count"] == data["exited_count"] == 1
    assert data["processes"][0]["pid"] == 30
    assert measurements.process_iter.cache_clear.call_count == 2


def test_exited_processes_alone_are_not_a_verified_live_inventory(measurements):
    measurements.process_iter.side_effect = lambda **_: iter([BrokenProcess(NoSuchProcess())])
    result = execute("system.processes")
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified


@pytest.mark.parametrize("change", [
    lambda row: row.update(cmdline="private-token"), lambda row: row.update(name="C:\\private\\sample.exe"),
    lambda row: row.update(pid=True), lambda row: row.update(memory_bytes=-1),
])
def test_process_output_contract_rejects_private_or_invalid_fields(measurements, change):
    data = execute("system.processes").data
    change(data["processes"][0])
    tool = create_registry().lookup("system.processes")
    registry = ToolRegistry()
    registry.register(replace(tool, handler=Mock(return_value=data)))
    result = ToolExecutor(registry).execute(ToolRequest("system.processes", {}))
    assert result.status == ToolStatus.EXECUTION_FAILED and not result.verified and result.data is None


def test_process_names_are_bounded_basename_data_only(measurements, tmp_path):
    measurements.process_iter.side_effect = lambda **_: iter([
        process(1, "C:\\private\\secret\\sample.exe", GIB, cmdline="password=private", username="private-user", environ={"token": "private-token"}),
        process(2, "line\ncontrol\x1b.exe", 0), process(3, "x"*200, None),
    ])
    result = execute("system.processes")
    assert result.data["processes"][0]["name"] == "sample.exe"
    assert result.data["processes"][1]["name"] == "linecontrol.exe"
    assert len(result.data["processes"][2]["name"]) == 120
    assert "private" not in repr(result.data)
    assert all(set(row) == {"pid", "name", "memory_bytes"} for row in result.data["processes"])


@pytest.mark.parametrize(("prompt", "tool", "section"), [
    ("What's my CPU usage?", "system.snapshot", "cpu"), ("How busy is my processor?", "system.snapshot", "cpu"),
    ("How many CPU cores do I have?", "system.snapshot", "cpu"), ("How much RAM do I have?", "system.snapshot", "memory"),
    ("AIKA, how much RAM is my computer using?", "system.snapshot", "memory"),
    ("How much memory is currently being used?", "system.snapshot", "memory"), ("What's my RAM usage?", "system.snapshot", "memory"),
    ("How much RAM am I using?", "system.snapshot", "memory"), ("How much storage space do I have left?", "system.snapshot", "storage"),
    ("How much disk space is left?", "system.snapshot", "storage"), ("Check my storage.", "system.snapshot", "storage"),
    ("How much free space is on my system drive?", "system.snapshot", "storage"), ("Show my PC specs.", "system.snapshot", "all"),
    ("What's my system information?", "system.snapshot", "all"), ("Show my system information.", "system.snapshot", "all"),
    ("What Windows version am I using?", "system.snapshot", "os"), ("What Windows version am I running?", "system.snapshot", "os"),
    ("Show running processes.", "system.processes", None), ("What processes are running?", "system.processes", None),
    ("Which processes use the most RAM?", "system.processes", None), ("Which processes are using the most memory?", "system.processes", None),
    ("List the top 10 processes by memory.", "system.processes", None),
])
def test_natural_language_routing_without_model(measurements, tmp_path, prompt, tool, section):
    request = system_request(prompt)
    assert request.tool == tool
    if section:
        assert request.arguments["section"] == section
    trace = Mock()
    answer = session_for(tmp_path).reply(prompt, tool_trace=trace)
    assert trace.call_args.args[0].tool == tool and trace.call_args.args[0].verified
    assert "Source:" in answer


@pytest.mark.parametrize("prompt", ["Explain how RAM works", "How does CPU utilization work?", "What is disk space?", "Open Notepad.", "Open Calculator", "What is 245 multiplied by 18?", "Remember that Orion uses SvelteKit for its frontend."])
def test_unrelated_requests_do_not_select_system_tools(prompt):
    assert system_request(prompt) is None


@pytest.mark.parametrize("prompt", ["What's my CPU temperature?", "Is my CPU overheating?"])
def test_temperature_is_not_inferred_or_measured(measurements, tmp_path, prompt):
    answer = session_for(tmp_path).reply(prompt)
    assert "not implemented" in answer and "utilization alone" in answer
    measurements.cpu_percent.assert_not_called()


def test_slow_pc_snapshot_does_not_claim_a_diagnosis(measurements, tmp_path):
    answer = session_for(tmp_path).reply("Why is my PC slow?")
    assert "CPU Usage: 22.5%" in answer and "single snapshot cannot diagnose" in answer
    measurements.process_iter.assert_not_called()


@pytest.mark.parametrize("prompt", ["/processes 26", "/processes -1", "/processes --all", "/processes 10 --cpu", "/processes 10.", "/system private", "/processes " + "9"*5000])
def test_bad_commands_return_validation_error_without_model_or_measurements(measurements, tmp_path, prompt):
    answer = session_for(tmp_path).reply(prompt)
    assert answer.startswith("System information error:")
    measurements.process_iter.assert_not_called()
    measurements.cpu_percent.assert_not_called()


def test_failed_measurement_never_reaches_model(measurements, tmp_path):
    measurements.virtual_memory.side_effect = OSError("private")
    generate = Mock(return_value="Your RAM usage is 62%")
    session = session_for(tmp_path, generate)
    answer = session.reply("What's my RAM usage?")
    assert "System information error" in answer and "62%" not in answer
    generate.assert_not_called()


@pytest.mark.parametrize("claim", ["Your CPU usage is 50%.", "Your RAM is 16 GB.", "I checked your processes.", "PID: 1234 is running.", "CPU Usage: 42%", "chrome.exe | 1234 | 2 GiB", "You're running Windows 11."])
def test_unverified_generated_measurement_claim_is_guarded(measurements, tmp_path, claim):
    assert "haven't collected" in session_for(tmp_path, Mock(return_value=claim)).reply("Tell me something about my computer")
    measurements.cpu_percent.assert_not_called()


def test_system_history_persists_but_is_excluded_from_model_after_resume(measurements, tmp_path):
    session = session_for(tmp_path)
    process_answer = session.reply("/processes")
    snapshot_answer = session.reply("What's my CPU usage?")
    generate = Mock(return_value="Ordinary reply")
    restored = session_for(tmp_path, generate)
    restored.resume(session.session_id)
    assert restored.history() == session.history()
    assert restored.history(for_model=True) == []
    assert restored.reply("Explain how RAM works") == "Ordinary reply"
    outbound = generate.call_args.args[0]
    assert outbound == [{"role": "system", "content": "Identity" + HISTORY_OMITTED},
                        {"role": "user", "content": "Explain how RAM works"}]
    assert process_answer not in repr(outbound) and snapshot_answer not in repr(outbound)
    assert measurements.process_iter.call_count == 1
    assert len(MemoryStore(tmp_path).list_facts("project", "Orion")) == 0


def test_system_storage_failure_preserves_completed_history(measurements, tmp_path, monkeypatch):
    session = session_for(tmp_path)
    session.reply("/calc 2+3")
    history = session.history()
    monkeypatch.setattr(session._store, "save_exchange", Mock(side_effect=StorageError("Test storage failure")))
    with pytest.raises(StorageError, match="Test storage failure"):
        session.reply("/system")
    assert session.history() == history


def test_calculator_memory_and_app_launcher_regression(measurements, tmp_path, monkeypatch):
    session = session_for(tmp_path)
    monkeypatch.setattr("src.capabilities.applications._launch", lambda app: {"application": app.app_id, "launch_state": "verified", "pid": 4321, "process_observed": True, "exit_code": None})
    monkeypatch.setattr(session.applications, "availability", lambda app: "AVAILABLE")
    session.reply("Remember that Orion uses SvelteKit for its frontend.")
    assert "is running" in session.reply("Open Calculator")
    assert "is running" in session.reply("Open Notepad")
    assert session.reply("What is 245 multiplied by 18?") == "4410"
    assert "CPU Usage: 22.5%" in session.reply("What's my CPU usage?")
    assert "SvelteKit" in session.reply("What frontend does Orion currently use?")
    generate = Mock()
    restored = session_for(tmp_path, generate)
    assert "SvelteKit" in restored.reply("What frontend does Orion currently use?")
    generate.assert_not_called()
    measurements.process_iter.assert_not_called()


def test_cli_system_processes_help_and_private_trace(measurements, monkeypatch, capsys, mock_ollama):
    mock_ollama()
    monkeypatch.setenv("AIKA_CONTEXT_DEBUG", "roles")
    entries = iter(["/help", "/system", "/processes", "/processes 2", "/processes --all", "/history", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(entries))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "/system" in output.out and "/processes [1-25]" in output.out
    assert "RAM: 10.00 GiB / 16.00 GiB" in output.out and "400.00 GiB free" in output.out
    assert "large.exe" in output.out and "Showing 2 of 3" in output.out
    assert "System information error" in output.out
    assert "tool=system.snapshot permission=READ_ONLY" in output.err and "tool=system.processes permission=READ_ONLY" in output.err
    assert "large.exe" not in output.err and "22.5%" not in output.err and "Z:" not in output.err


def test_dependency_and_platform_initialization_is_controlled(monkeypatch, measurements):
    monkeypatch.setattr(info.platform, "system", lambda: "Linux")
    with pytest.raises(ToolExecutionError, match="Windows only"):
        initialize_interfaces()
    monkeypatch.setattr(info.platform, "system", lambda: "Windows")
    monkeypatch.setattr(info.importlib, "import_module", Mock(side_effect=ModuleNotFoundError("private dependency location")))
    with pytest.raises(ToolExecutionError, match="psutil is unavailable") as error:
        initialize_interfaces()
    assert "private" not in str(error.value)
    monkeypatch.setattr(info.importlib, "import_module", lambda _: NS())
    with pytest.raises(ToolExecutionError, match="interfaces"):
        initialize_interfaces()


def test_doctor_checks_interfaces_without_sampling_or_enumeration(measurements, monkeypatch):
    monkeypatch.setattr(diagnostics, "initialize_measurements", lambda: measurements)
    checks = diagnostics.inspect_system_tools()
    assert all(check.status == "PASS" for check in checks)
    assert "No metrics sampled" in checks[-1].detail
    measurements.cpu_percent.assert_not_called()
    measurements.virtual_memory.assert_not_called()
    measurements.disk_usage.assert_not_called()
    measurements.process_iter.assert_not_called()


def test_doctor_missing_dependency_is_not_reported_ready(monkeypatch):
    monkeypatch.setattr(diagnostics, "initialize_measurements", Mock(side_effect=ToolExecutionError("psutil is unavailable", status=ToolStatus.UNAVAILABLE)))
    checks = diagnostics.inspect_system_tools()
    assert checks[0].status == "FAIL" and "unavailable" in checks[0].detail


def test_doctor_cli_keeps_all_checks_without_collecting_metrics(measurements, monkeypatch, capsys, mock_ollama):
    mock_ollama()
    monkeypatch.setattr(diagnostics, "initialize_measurements", lambda: measurements)
    assert aika.main(["doctor"]) == 0
    output = capsys.readouterr().out
    for name in ("System Information", "SQLite", "Ollama", "Calculator", "Application Launcher"):
        assert f"PASS  {name}:" in output
    assert "Tools Registered: 7" in output and "large.exe" not in output
    measurements.cpu_percent.assert_not_called()
    measurements.virtual_memory.assert_not_called()
    measurements.disk_usage.assert_not_called()
    measurements.process_iter.assert_not_called()


def test_unsupported_platform_tool_result_and_diagnostics_are_truthful(measurements, tmp_path, monkeypatch):
    error = ToolExecutionError("System measurements are supported on Windows only.", status=ToolStatus.UNAVAILABLE)
    monkeypatch.setattr(info, "initialize_measurements", Mock(side_effect=error))
    result = execute()
    assert result.status == ToolStatus.UNAVAILABLE and not result.verified
    assert "Windows only" in session_for(tmp_path).reply("/system")
    monkeypatch.setattr(diagnostics, "initialize_measurements", Mock(side_effect=error))
    monkeypatch.setattr(info.platform, "system", lambda: "Linux")
    assert diagnostics.inspect_system_tools()[0].status == "WARN"


@pytest.mark.parametrize("prompt", [
    "How much free storage do I have?", "How much storage do I have left?",
    "How much space is left on my PC?", "What's my remaining disk space?",
    "Check my free storage.", "How much disk space is available?",
    "How much free space is on my system drive?", "How full is my system drive?",
])
def test_storage_variations_use_executor_and_actual_measurement(measurements, tmp_path, prompt):
    request = ToolRequest("system.snapshot", {"section": "storage"})
    assert system_request(prompt) == request
    generate = Mock(return_value="I don't know your storage")
    session = session_for(tmp_path, generate)
    session.tools.execute = Mock(wraps=session.tools.execute)
    trace = Mock()
    answer = session.reply(prompt, tool_trace=trace)
    session.tools.execute.assert_called_once_with(request, authorization=None)
    assert "400.00 GiB free" in answer and "600.00 GiB / 1000.00 GiB used (60.0%)" in answer
    assert trace.call_args.args[0].verified
    measurements.disk_usage.assert_called_once_with("Z:\\")
    measurements.cpu_percent.assert_not_called()
    measurements.virtual_memory.assert_not_called()
    measurements.process_iter.assert_not_called()
    generate.assert_not_called()


@pytest.mark.parametrize("prompt", ["What is cloud storage?", "How much storage should I buy?", "Explain SSD versus HDD."])
def test_educational_storage_requests_stay_conversational(measurements, tmp_path, prompt):
    assert system_request(prompt) is None
    generate = Mock(return_value="An ordinary explanation")
    session = session_for(tmp_path, generate)
    session.tools.execute = Mock(wraps=session.tools.execute)
    assert session.reply(prompt) == "An ordinary explanation"
    generate.assert_called_once()
    session.tools.execute.assert_not_called()
    measurements.disk_usage.assert_not_called()


def test_storage_followup_after_summary_collects_fresh_value(measurements, tmp_path):
    measurements.disk_usage.side_effect = [
        NS(total=1000*GIB, used=600*GIB, free=400*GIB, percent=60),
        NS(total=1000*GIB, used=650*GIB, free=350*GIB, percent=65),
    ]
    generate = Mock(return_value="I don't know how much free storage you have. Could you tell me the name of your device or drive?")
    session = session_for(tmp_path, generate)
    session.tools.execute = Mock(wraps=session.tools.execute)
    assert "400.00 GiB free" in session.reply("/system")
    answer = session.reply("How much free storage do I have?")
    assert "350.00 GiB free" in answer and "400.00 GiB" not in answer
    assert measurements.disk_usage.call_count == session.tools.execute.call_count == 2
    assert session.tools.execute.call_args.args[0] == ToolRequest("system.snapshot", {"section": "storage"})
    assert "350.00 GiB free" in session.history()[-1]["content"]
    assert session.history(for_model=True) == []
    generate.assert_not_called()


def test_storage_followup_failure_never_reuses_success_or_model(measurements, tmp_path):
    measurements.disk_usage.side_effect = [
        NS(total=1000*GIB, used=600*GIB, free=400*GIB, percent=60), OSError("private failure"),
    ]
    generate = Mock(return_value="You have 400 GiB free")
    session = session_for(tmp_path, generate)
    assert "400.00 GiB free" in session.reply("/system")
    answer = session.reply("How much free storage do I have?")
    assert answer.startswith("System information error:") and "400" not in answer and "private" not in answer
    assert measurements.disk_usage.call_count == 2
    generate.assert_not_called()


@pytest.mark.parametrize(("prompt", "limitation"), [
    ("How much storage is available in my Google Drive?", "Cloud-storage"),
    ("How much disk space is left on my external drive?", "Windows system drive"),
])
def test_unimplemented_storage_targets_explain_limit_without_measuring(measurements, tmp_path, prompt, limitation):
    assert system_request(prompt) is None
    generate = Mock(return_value="An unsupported storage answer")
    session = session_for(tmp_path, generate)
    session.tools.execute = Mock(wraps=session.tools.execute)
    assert limitation in session.reply(prompt)
    session.tools.execute.assert_not_called()
    measurements.disk_usage.assert_not_called()
    generate.assert_not_called()
