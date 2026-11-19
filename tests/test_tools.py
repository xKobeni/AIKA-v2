from dataclasses import replace
from decimal import Inexact, ROUND_DOWN, localcontext
from unittest.mock import Mock

import pytest

import aika
import src.diagnostics as diagnostics
from src.capabilities import create_registry
from src.capabilities.calculator import calculator_tool
from src.capabilities.contracts import Permission, ToolRequest, ToolStatus
from src.capabilities.executor import ToolExecutor
from src.capabilities.intent import calculator_request
from src.capabilities.registry import ToolLookupError, ToolRegistry
from src.intelligence.conversation import ConversationSession
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore, StorageError


def calculate(expression):
    return ToolExecutor(create_registry()).execute(ToolRequest("calculator.evaluate", {"expression": expression}))


def test_registry_registration_duplicate_and_availability():
    registry = create_registry()
    tool = registry.lookup("calculator.evaluate")
    assert {item.name for item in registry.list_tools()} == {"calculator.evaluate", "app.open", "system.snapshot", "system.processes", "web.search", "web.read", "desktop.context"}
    assert tool.permission == Permission.READ_ONLY
    assert callable(tool.input_contract) and callable(tool.output_contract)
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(tool)
    with pytest.raises(ToolLookupError) as error:
        registry.lookup("unknown.tool")
    assert error.value.status == ToolStatus.UNKNOWN
    registry.register(replace(tool, name="calculator.disabled", enabled=False))
    with pytest.raises(ToolLookupError) as error:
        registry.lookup("calculator.disabled")
    assert error.value.status == ToolStatus.DISABLED


@pytest.mark.parametrize("change", [
    {"name": "arbitrary code"}, {"permission": "READ_ONLY"}, {"enabled": "yes"},
    {"handler": None}, {"input_contract": None}, {"output_contract": None},
])
def test_invalid_registration(change):
    with pytest.raises(ValueError):
        ToolRegistry().register(replace(calculator_tool(), **change))


@pytest.mark.parametrize("permission", [Permission.LOCAL_ACTION, Permission.SENSITIVE_ACTION])
def test_permissions_fail_closed_before_validation_or_handler(permission):
    handler, validator = Mock(), Mock()
    registry = ToolRegistry()
    registry.register(replace(calculator_tool(), permission=permission, handler=handler, input_contract=validator))
    result = ToolExecutor(registry).execute(ToolRequest("calculator.evaluate", {"expression": "2+2"}))
    assert result.status == ToolStatus.DENIED
    assert not result.verified and result.data is None
    handler.assert_not_called()
    validator.assert_not_called()


def test_unknown_and_disabled_are_structured_and_never_execute():
    handler = Mock()
    registry = ToolRegistry()
    registry.register(replace(calculator_tool(), enabled=False, handler=handler))
    executor = ToolExecutor(registry)
    for name, status in [("unknown.tool", ToolStatus.UNKNOWN), ("calculator.evaluate", ToolStatus.DISABLED)]:
        result = executor.execute(ToolRequest(name, {}))
        assert result.status == status and result.error
        assert not result.verified and result.data is None and result.validation == "NOT_RUN"
    handler.assert_not_called()


@pytest.mark.parametrize("arguments", [{}, {"expression": 4}, {"expression": "2+2", "code": "extra"}, None])
def test_argument_contract(arguments):
    result = ToolExecutor(create_registry()).execute(ToolRequest("calculator.evaluate", arguments))
    assert result.status == ToolStatus.INVALID_INPUT
    assert result.validation == "FAIL" and not result.verified and result.data is None


def test_untrusted_tool_name_and_callable_cannot_execute():
    function = Mock()
    for name in (function, ["calculator.evaluate"], None):
        result = ToolExecutor(create_registry()).execute(ToolRequest(name, {}))
        assert result.status == ToolStatus.INVALID_INPUT and not result.verified
    function.assert_not_called()


def test_decimal_context_is_independent_of_callers():
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert calculate("1/3").data == {"result": "0." + "3" * 50}
        assert calculate("0.1+0.2").data == {"result": "0.3"}


@pytest.mark.parametrize(("expression", "expected"), [
    ("2+3", "5"), ("10-15", "-5"), ("245 * 18", "4410"), ("9 / 4", "2.25"),
    ("(125 + 75) / 4", "50"), ("0.1 + 0.2", "0.3"), ("-25 + 40", "15"),
    ("-(2+3) * -4", "20"), ("15% of 800", "120"), ("-12.5% of 80", "-10"),
    (".1 + .2", "0.3"), ("-0.0", "0"), ("1 / 3", "0." + "3" * 50),
    ("12345678901234567890.1 + .2", "12345678901234567890.3"),
])
def test_arithmetic(expression, expected):
    result = calculate(expression)
    assert result.status == ToolStatus.SUCCESS and result.verified
    assert result.data == {"result": expected} and result.error is None
    assert result.permission == Permission.READ_ONLY and result.validation == "PASS"
    assert result.elapsed_ms >= 0


@pytest.mark.parametrize("expression", [
    "", "2 +", "(2+3", "a+1", "__import__('os').system('echo unsafe')", "(1).__class__",
    "abs(-2)", "import os", "True+1", "[1,2]", "2**1000000", "10//3", "10%3", "2^3",
    "1e10", "1_000+2", "0xff", "lambda: 1", "1; print(1)", "1\n+2",
    "1" * 513, "9" * 51, "(" * 17 + "1" + ")" * 17, "+" * 20 + "1", "1+" * 100 + "1",
])
def test_unsafe_or_unsupported_input_is_rejected(expression):
    result = calculate(expression)
    assert result.status == ToolStatus.INVALID_INPUT
    assert not result.verified and result.data is None and result.error


@pytest.mark.parametrize("expression", ["100/0", "1/(2-2)", ("9" * 50 + "*") * 2 + "999", "0." + "0" * 48 + "1 * 0." + "0" * 48 + "1 / 1000"])
def test_execution_failures(expression):
    result = calculate(expression)
    assert result.status == ToolStatus.EXECUTION_FAILED
    assert result.validation == "PASS" and not result.verified and result.data is None
    assert result.error


def test_handler_and_output_failures_are_private_and_unverified():
    for changes in (
        {"handler": Mock(side_effect=RuntimeError("private input and credentials"))},
        {"handler": Mock(return_value={"result": "fabricated"})},
        {"input_contract": Mock(side_effect=RuntimeError("private input and credentials"))},
    ):
        registry = ToolRegistry()
        registry.register(replace(calculator_tool(), **changes))
        result = ToolExecutor(registry).execute(ToolRequest("calculator.evaluate", {"expression": "1+1"}))
        assert result.status == ToolStatus.EXECUTION_FAILED
        assert not result.verified and result.data is None
        assert "private" not in result.error and "credentials" not in result.error


@pytest.mark.parametrize(("prompt", "expected"), [
    ("What is 245 multiplied by 18?", "4410"), ("Calculate (125 + 75) / 4.", "50"),
    ("What is 0.1 + 0.2?", "0.3"), ("What is 15% of 800?", "120"),
    ("-25 + 40", "15"), ("What is 3 times 4?", "12"), ("/calc 12 / 4", "3"),
    ("Please calculate 2 × 4.", "8"),
])
def test_chat_routes_and_persists_verified_results(tmp_path, prompt, expected):
    generate = Mock(side_effect=AssertionError("Calculator must not reach model"))
    store = ConversationStore(tmp_path)
    session = ConversationSession("Identity", 10, generate, store, MemoryStore(tmp_path))
    trace = Mock()
    assert session.reply(prompt, tool_trace=trace) == expected
    result = trace.call_args.args[0]
    assert result.verified and result.data == {"result": expected}
    restored = ConversationSession("Identity", 10, generate, ConversationStore(tmp_path))
    restored.resume(session.session_id)
    assert restored.history() == session.history()
    assert store.load_session(session.session_id, 10) == (2, [(prompt, expected)])
    with store._transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0] == 0
    generate.assert_not_called()


@pytest.mark.parametrize("prompt", ["Calculate 100/0", "/calc __import__('os').system('echo unsafe')", "/calc", "What is 2 ** 1000?"])
def test_failed_calculator_does_not_fall_back_to_model(tmp_path, prompt):
    generate = Mock(return_value="Successfully calculated 42")
    store = ConversationStore(tmp_path)
    session = ConversationSession("Identity", 10, generate, store)
    answer = session.reply(prompt)
    assert answer.startswith("Calculator error:") and "42" not in answer
    assert store.load_session(session.session_id, 10) == (2, [(prompt, answer)])
    generate.assert_not_called()


@pytest.mark.parametrize("prompt", ["Close Spotify.", "Close Notepad.", "Run powershell", "Delete the file test.txt", "Install a browser"])
def test_unsupported_actions_do_not_claim_success(tmp_path, prompt):
    generate = Mock(return_value="I opened Spotify successfully")
    session = ConversationSession("Identity", 10, generate, ConversationStore(tmp_path))
    assert "not implemented" in session.reply(prompt)
    generate.assert_not_called()


@pytest.mark.parametrize("prompt", ["Explain multiplication", "What is 15% of my income?", "I have 2 + 3 questions", "Write a story", "Start a conversation"])
def test_ambiguous_and_ordinary_requests_keep_conversation_path(tmp_path, prompt):
    assert calculator_request(prompt) is None
    generate = Mock(return_value="Ordinary reply")
    session = ConversationSession("Identity", 10, generate, ConversationStore(tmp_path))
    assert session.reply(prompt) == "Ordinary reply"
    generate.assert_called_once()


@pytest.mark.parametrize("claim", ["I've opened Spotify.", "Spotify is now open.", "I used the calculator to get 42."])
def test_generated_tool_claim_has_no_execution_evidence(tmp_path, claim):
    session = ConversationSession("Identity", 10, Mock(return_value=claim), ConversationStore(tmp_path))
    assert "haven't" in session.reply("Did you do that?")


def test_tool_storage_failure_preserves_context(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path)
    session = ConversationSession("Identity", 10, Mock(), store)
    session.reply("2+3")
    history = session.history()
    monkeypatch.setattr(store, "save_exchange", Mock(side_effect=StorageError("Test storage failure")))
    with pytest.raises(StorageError):
        session.reply("/calc 4+5")
    assert session.history() == history
    assert store.load_session(session.session_id, 10) == (2, [("2+3", "5")])


def test_memory_and_calculator_coexist(tmp_path):
    generate = Mock(side_effect=AssertionError("Deterministic path expected"))
    store = ConversationStore(tmp_path)
    session = ConversationSession("Identity", 10, generate, store, MemoryStore(tmp_path))
    assert "Next.js" in session.reply("Remember that Orion uses Next.js for its frontend.")
    assert session.reply("/calc 245 * 18") == "4410"
    assert "Next.js" in session.reply("What frontend does Orion currently use?")
    assert len(MemoryStore(tmp_path).list_facts("project", "Orion")) == 1


def test_explicit_calculator_never_enters_memory_write_path(tmp_path):
    store = ConversationStore(tmp_path)
    memory = MemoryStore(tmp_path)
    session = ConversationSession("Identity", 10, Mock(), store, memory)
    session.reply("Remember that Calculate Orion uses React for its frontend.")
    assert session.reply("Calculate Orion uses SvelteKit for its frontend.").startswith("Calculator error:")
    assert memory.get_fact("project", "Calculate Orion", "frontend").value == "React"


def test_cli_tools_calc_debug_and_restart(monkeypatch, capsys, mock_ollama, tmp_path):
    mock_ollama()
    monkeypatch.setenv("AIKA_CONTEXT_DEBUG", "roles")
    inputs = iter(["/help", "/tools", "/calc (125 + 75) / 4", "/calc 100/0", "/calc", "/history", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    generate = Mock(side_effect=AssertionError("No model calculation"))
    monkeypatch.setattr("src.cli.OllamaClient.generate", generate)
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "calculator.evaluate" in output.out and "Permission: READ_ONLY" in output.out
    assert "Status: AVAILABLE" in output.out and "AIKA > 50" in output.out
    assert "Division by zero" in output.out and "You: /calc (125 + 75) / 4" in output.out
    assert "intent=recognized tool=calculator.evaluate permission=READ_ONLY validation=PASS execution=success verified=yes" in output.err
    assert "validation=FAIL execution=invalid_input verified=no" in output.err
    assert "125" not in output.err and "100/0" not in output.err and "result=50" not in output.err
    session_id = ConversationStore(tmp_path).list_sessions()[0][0]
    inputs = iter([f"/resume {session_id}", "/history", "/exit"])
    assert aika.main(["chat"]) == 0
    assert "AIKA: 50" in capsys.readouterr().out
    generate.assert_not_called()


def test_doctor_does_not_report_broken_tools_as_available(monkeypatch):
    monkeypatch.setattr(diagnostics, "create_registry", Mock(side_effect=ValueError("private registration failure")))
    checks = diagnostics.inspect_tools()
    assert all(check.status == "FAIL" for check in checks)
    assert all("private" not in check.detail for check in checks)
    registry = ToolRegistry()
    registry.register(replace(calculator_tool(), enabled=False))
    monkeypatch.setattr(diagnostics, "create_registry", lambda *args: registry)
    checks = diagnostics.inspect_tools()
    assert next(check for check in checks if check.name == "Calculator").status == "FAIL"


def test_doctor_returns_failure_when_calculator_probe_fails(monkeypatch, capsys):
    registry = ToolRegistry()
    registry.register(replace(calculator_tool(), handler=Mock(return_value={"result": "999"})))
    monkeypatch.setattr(diagnostics, "create_registry", lambda *args: registry)
    assert aika.main(["doctor"]) == 1
    assert "FAIL  Calculator: Execution probe failed" in capsys.readouterr().out


def test_cli_tool_storage_error_hides_uncommitted_result(monkeypatch, capsys, mock_ollama):
    mock_ollama()
    monkeypatch.setattr(ConversationStore, "save_exchange", Mock(side_effect=StorageError("Test database failure")))
    inputs = iter(["/calc 245*18", "/history", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "Storage error: Test database failure" in output.err
    assert "AIKA > 4410" not in output.out and "No completed turns" in output.out
