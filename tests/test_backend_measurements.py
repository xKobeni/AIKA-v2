import json
from unittest.mock import Mock

import httpx

from scripts import benchmark_backend as baseline
from src.intelligence.ollama_client import OllamaError


def test_archive_baseline_uses_synthetic_data_and_bounded_results():
    rows = baseline.archive_baseline(100, repeats=3)
    assert [(row["case"], row["results"]) for row in rows] == [("no_match", 0), ("many_matches", 5)]
    assert all(row["warm_median_ms"] >= 0 and row["first_ms"] >= 0 for row in rows)


def test_context_measurement_preserves_restore_and_never_infers():
    result = baseline.context_baseline()
    assert result["model_mocked"] is True and result["generations"] == 13
    assert result["full_history_content_characters"] == result["restored_content_characters"]
    assert result["full_history_content_characters"] <= result["context_budget_characters"]
    assert result["last_model_history_turns"] == 0 and result["retained_turns"] == 10
    assert result["persisted_exchanges"] == 13


def test_default_benchmark_does_not_contact_ollama_or_dump_environment(tmp_path, monkeypatch, capsys):
    forbidden = Mock(side_effect=AssertionError("Default benchmark must stay offline"))
    monkeypatch.setattr(baseline, "OllamaClient", forbidden)
    monkeypatch.setattr(baseline, "archive_baseline", lambda count: [{"user_rows": count}])
    monkeypatch.setenv("AIKA_TAVILY_API_KEY", "synthetic-private-key")
    output = tmp_path / "baseline.json"
    baseline.main(["--output", str(output)])
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert len(saved["archive"]) == 3 and "ollama" not in saved
    assert "synthetic-private-key" not in capsys.readouterr().out
    forbidden.assert_not_called()


def test_ollama_trace_counts_cached_client_requests_with_mocked_transport(mock_ollama):
    calls = []

    def request(request):
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("/api/tags"):
            payload = {"models": [{"name": "qwen3:4b", "capabilities": ["completion", "thinking"]}]}
        elif request.url.path.endswith("/api/show"):
            payload = {"thinking": {"values": [True, False]}}
        else:
            assert json.loads(request.content)["options"]["num_predict"] == 32
            payload = {"done": True, "message": {"role": "assistant", "content": "synthetic answer not exported"},
                       "total_duration": 12345, "prompt_eval_count": 5}
        return httpx.Response(200, json=payload)

    clients = mock_ollama(request)
    result = baseline.ollama_baseline()
    assert calls == ["tags", "show", "chat", "chat"]
    assert len(clients) == 1 and clients[0].is_closed
    assert [row["status"] for row in result["outcomes"]] == ["success", "success"]
    assert "synthetic answer not exported" not in json.dumps(result)


def test_ollama_trace_keeps_safe_failure_category(monkeypatch):
    def unavailable(self, *args, **kwargs):
        raise OllamaError("sensitive internal details", kind="connection")

    monkeypatch.setattr(baseline.OllamaClient, "_request", unavailable)
    result = baseline.ollama_baseline()
    assert result["outcomes"] == [{"stage": "startup_probe", "status": "connection"}]
    assert "sensitive internal details" not in json.dumps(result)
