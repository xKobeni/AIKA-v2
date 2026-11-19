from dataclasses import replace
import json
from unittest.mock import Mock
from types import SimpleNamespace as NS

import httpx
import pytest

from scripts import evaluate_reasoning_ab as ab
from src.config import load_config
from src.intelligence.ollama_client import OllamaError


def ledger(tmp_path, stage="pilot"):
    return ab.Ledger({"http": [], "chat_requests": 0, "trials": []}, tmp_path / "study.json", stage)


def test_response_metrics_never_include_private_thinking_or_partial_content():
    result = ab.response_metrics({"done": True, "done_reason": "length", "eval_count": 1024,
                                  "eval_duration": float("inf"), "other": "SECRET",
                                  "message": {"role": "assistant", "thinking": "SECRET_THOUGHT", "content": "SECRET_PARTIAL"}})
    assert result["thinking_present"] and result["final_content_present"]
    assert result["eval_count"] == 1024 and "eval_duration" not in result
    assert "SECRET" not in json.dumps(result)
    assert ab.completion_status("unavailable", result) == "output_limit"
    assert ab.thinking_observation("on", "output_limit", result) == "activated_without_complete_final"


@pytest.mark.parametrize("payload", [{}, {"message": [], "done_reason": []}, {"message": {"thinking": {}, "content": None}}])
def test_invalid_metrics_are_explicit_and_do_not_crash(payload):
    result = ab.response_metrics(payload)
    assert not result["thinking_present"] and not result["final_content_present"]
    assert result["done_reason"] == "other"


@pytest.mark.parametrize("mode,observed", [("on", "requested_not_demonstrably_active"), ("off", "no_thinking_observed")])
def test_http_success_alone_does_not_prove_thinking_activation(mode, observed):
    assert ab.thinking_observation(mode, "complete", {"done": True}) == observed


def test_thinking_despite_explicit_off_is_not_a_clean_comparison():
    assert ab.thinking_observation("off", "complete", {"thinking_present": True}) == "thinking_observed_despite_off"


@pytest.mark.parametrize("thinking,status", [(True, "thinking_only"), (False, "missing_final")])
def test_missing_final_is_a_failure_even_with_successful_http(thinking, status):
    assert ab.completion_status("unavailable", {"done": True, "assistant_role": True,
                                                "thinking_present": thinking, "final_content_present": False}) == status


def test_unsupported_and_invalid_responses_are_explicit():
    error = OllamaError("Ollama did not report supported thinking controls. Set AIKA_OLLAMA_THINK=default or off.")
    assert ab.error_kind(error) == "thinking_unsupported"
    assert ab.thinking_observation("on", "thinking_unsupported", {}) == "unsupported_or_rejected"
    assert ab.completion_status("unavailable", {"done": False}) == "invalid_response"


@pytest.mark.parametrize("mode", ["off", "on"])
def test_measured_client_keeps_existing_request_controls_and_sanitizes_response(tmp_path, mock_ollama, mode):
    study = ledger(tmp_path)
    settings = replace(load_config(), ollama_think=mode)

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": settings.model, "digest": "synthetic-digest"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"thinking": {"values": [False, True]}})
        body = json.loads(request.content)
        assert body["think"] is (mode == "on")
        assert body["options"] == {"temperature": 0.2, "num_predict": 1024}
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "eval_count": 60,
                                        "message": {"role": "assistant", "content": "Final answer.",
                                                    "thinking": "SECRET_THOUGHT" if mode == "on" else ""}})

    mock_ollama(handle)
    with ab.MeasuredClient(settings, study, "synthetic-digest") as client:
        assert client.generate([{"role": "user", "content": "Synthetic input."}]) == "Final answer."
    chats = [e for e in study.state["http"] if e["path"] == "/api/chat"]
    assert len(chats) == 1 and chats[0]["thinking_present"] == (mode == "on")
    assert "SECRET_THOUGHT" not in study.output.read_text(encoding="utf-8")


@pytest.mark.parametrize("content,reason,error", [("", "length", "generation limit"),
                                                   ("<think>SECRET</think>Final", "stop", "suppressed")])
def test_incomplete_or_contaminated_final_never_becomes_an_answer(tmp_path, mock_ollama, content, reason, error):
    settings = replace(load_config(), ollama_think="on")
    study = ledger(tmp_path)

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": settings.model, "digest": "digest"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"thinking": {"values": [False, True]}})
        return httpx.Response(200, json={"done": True, "done_reason": reason,
                                        "message": {"role": "assistant", "thinking": "SECRET", "content": content}})

    mock_ollama(handle)
    with ab.MeasuredClient(settings, study, "digest") as client:
        with pytest.raises(OllamaError, match=error):
            client.generate([{"role": "user", "content": "Synthetic."}])
    assert "SECRET" not in study.output.read_text(encoding="utf-8")


def test_model_digest_change_stops_before_generation(tmp_path, mock_ollama):
    settings = load_config()
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"models": [{"name": settings.model, "digest": "new-digest"}]})

    mock_ollama(handle)
    with ab.MeasuredClient(settings, ledger(tmp_path), "old-digest") as client:
        with pytest.raises(ab.StudyStop, match="digest_changed"):
            client.generate([])
    assert calls == ["/api/tags"]


def test_finite_runtime_and_request_limits_apply_before_transport(tmp_path, monkeypatch):
    time = [100.0]
    monkeypatch.setattr(ab, "monotonic", lambda: time[0])
    study = ledger(tmp_path)
    time[0] += ab.STAGE_SECONDS["pilot"] + 1
    with pytest.raises(ab.StudyStop, match="budget"):
        with study.request("GET", "/api/tags", 3, None):
            pytest.fail("No transport should be attempted")
    study = ledger(tmp_path)
    study.state["chat_requests"] = ab.LIMITS["chat_requests"]
    with pytest.raises(ab.StudyStop, match="chat_request_budget"):
        with study.request("POST", "/api/chat", 180, {}):
            pytest.fail("No transport should be attempted")


def test_resume_charges_unfinished_request_conservatively(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "monotonic", lambda: 100.0)
    state = {"http": [], "chat_requests": 1, "runtime_seconds": 10, "inflight_reserved_seconds": 180}
    study = ab.Ledger(state, tmp_path / "study.json", "full")
    assert study.base == 190 and study.remaining() == ab.LIMITS["seconds"] - 190
    assert "inflight_reserved_seconds" not in state


def test_resume_does_not_reset_stage_runtime_limit(tmp_path, monkeypatch):
    time = [100.0]
    monkeypatch.setattr(ab, "monotonic", lambda: time[0])
    state = {"http": [], "chat_requests": 0, "runtime_seconds": 1195,
             "stage_runtime_seconds": {"pilot": 1195}}
    study = ab.Ledger(state, tmp_path / "study.json", "pilot")
    assert study.remaining() == 5
    time[0] += 6
    with pytest.raises(ab.StudyStop):
        with study.request("GET", "/api/tags", 3, None):
            pytest.fail("Expired stage must not resume inference")


def test_checkpoint_replace_retries_are_bounded(tmp_path, monkeypatch):
    original = ab.Path.replace
    calls = []
    pauses = []

    def temporarily_locked(path, target):
        calls.append(target)
        if len(calls) < 3:
            raise PermissionError("synthetic lock")
        return original(path, target)

    monkeypatch.setattr(ab.Path, "replace", temporarily_locked)
    monkeypatch.setattr(ab, "sleep", pauses.append)
    study = ledger(tmp_path)
    study.save()
    assert len(calls) == 3 and pauses == [0.05, 0.1]
    assert json.loads(study.output.read_text())["chat_requests"] == 0


def test_resume_never_retries_terminal_trial(tmp_path):
    study = ledger(tmp_path)
    study.state["trials"] = [{"key": ["pilot", "case", "on", 0], "status": "timeout"}]
    ab.run_trial(None, {"id": "case"}, "on", 1024, 0, study)
    assert study.state["chat_requests"] == 0


def test_pilot_is_ten_cases_with_requested_coverage_and_alternating_order():
    cases = ab.load_cases([ab.CASES, ab.DEVELOPMENT_CASES, ab.ACCEPTANCE_CASES])
    selected = [c for c in cases if c["id"] in ab.PILOT_IDS]
    assert len(cases) == 64 and len(selected) == 10
    assert sum(c["id"] in ab.PRIORITY_IDS for c in selected) == 5
    assert sum(len(c["turns"]) for c in selected) == 16
    assert ab.mode_order(0) == ("off", "on") and ab.mode_order(1) == ("on", "off")


def test_full_comparison_requires_complete_verified_pilot(tmp_path):
    study = ledger(tmp_path, "full")
    with pytest.raises(ab.StudyStop, match="pilot_not_usable"):
        ab.run_stage(None, [], study)
    trials = [{"stage": "pilot", "mode": mode, "status": "complete",
               "turns": [{"metrics": {"thinking_present": mode == "on"}}]}
              for _ in ab.PILOT_IDS for mode in ("off", "on")]
    assert ab.pilot_usable({"trials": trials})
    trials[0]["status"] = "output_limit"
    assert not ab.pilot_usable({"trials": trials})


def test_higher_budget_diagnostic_is_separate_and_requires_cap_failures(tmp_path):
    study = ledger(tmp_path, "diagnostic")
    assert ab.DIAGNOSTIC_TOKENS == 2048 and ab.DIAGNOSTIC_TOKENS <= 4096
    assert ab.DIAGNOSTIC_TIMEOUT == 360 and ab.STAGE_SECONDS["diagnostic"] == 600
    with pytest.raises(ab.StudyStop, match="repeated_primary_output_limit"):
        ab.run_stage(None, [], study)


def test_opt_in_is_required_before_configuration_or_inference(tmp_path, monkeypatch):
    config = Mock()
    monkeypatch.setattr(ab, "load_config", config)
    monkeypatch.setattr("sys.argv", ["evaluate_reasoning_ab", "--output", str(tmp_path / "result.json")])
    with pytest.raises(SystemExit) as exc:
        ab.main()
    assert exc.value.code == 2
    config.assert_not_called()
    assert not (tmp_path / "result.json").exists()


def test_resources_are_conservative_filtered_samples(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: NS(available=100, total=800))
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval: 12.0)
    monkeypatch.setattr(psutil, "process_iter", lambda *args, **kwargs: iter([
        NS(info={"name": "ollama.exe", "memory_info": NS(rss=123)}),
        NS(info={"name": "PRIVATE_APP", "memory_info": NS(rss=999)})]))
    client = Mock(settings=NS(model="synthetic-model"), probe_timeout=3)
    client._request.return_value = {"models": [{"name": "synthetic-model", "size_vram": 0},
                                                {"name": "other-model", "size_vram": 999}]}
    result = ab.resources(client)
    assert result["ollama_working_set_sum_bytes"] == 123
    assert result["ollama_reported_model_vram_bytes"] == 0
    assert result["available_ram_bytes"] == 100 and "PRIVATE_APP" not in json.dumps(result)
    monkeypatch.setattr(psutil, "virtual_memory", Mock(side_effect=psutil.AccessDenied()))
    assert ab.resources(client)["status"] == "unavailable"


@pytest.mark.parametrize("failure", [None, "timeout", "interrupt"])
def test_trial_history_is_isolated_and_failures_never_become_answers(tmp_path, monkeypatch, failure):
    study = ledger(tmp_path)
    study.state["environment"] = {"model_digest": "digest"}
    settings = load_config()
    seen = []
    monkeypatch.setattr(ab, "resources", lambda client: {"status": "synthetic"})

    class FakeClient:
        def __init__(self, configuration, active_ledger, digest):
            assert configuration.data_dir != settings.data_dir
            assert configuration.ollama_think in {"off", "on"}
            assert configuration.response_tokens == 1024
            self.settings = configuration
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def generate(self, messages):
            self.calls += 1
            seen.append(messages)
            study.state["chat_requests"] += 1
            study.state["http"].append({"path": "/api/chat", "think": self.settings.ollama_think == "on",
                                         "thinking_present": self.settings.ollama_think == "on"})
            if failure == "timeout":
                raise OllamaError("Synthetic timeout.", kind="timeout")
            if failure == "interrupt":
                raise KeyboardInterrupt()
            return f"Synthetic answer {self.calls}."

    monkeypatch.setattr(ab, "MeasuredClient", FakeClient)
    case = {"id": "synthetic", "category": "continuity", "turns": ["Discuss a fictional topic.", "Explain it further."]}
    if failure == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            ab.run_trial(settings, case, "off", 1024, 0, study)
        assert study.state["trials"][0]["status"] == "interrupted_or_budget"
        assert study.state["trials"][0]["turns"][0]["final"] is None
    elif failure == "timeout":
        ab.run_trial(settings, case, "off", 1024, 0, study)
        trial = study.state["trials"][0]
        assert trial["status"] == "timeout" and trial["unrun_turns"] == 1
        assert trial["turns"][0]["final"] is None and len(seen) == 1
    else:
        for mode in ("off", "on"):
            ab.run_trial(settings, case, mode, 1024, 0, study)
        assert len(seen[0]) == len(seen[2]) == 2
        assert seen[1][2] == seen[3][2] == {"role": "assistant", "content": "Synthetic answer 1."}
        assert all(t["status"] == "complete" for t in study.state["trials"])
    assert settings.ollama_think == "off" and settings.response_tokens == 1024
