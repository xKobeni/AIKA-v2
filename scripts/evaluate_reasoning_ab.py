"""Sequential, opt-in developer experiment; never stores model thinking text.

Run capability verification first, then --stage pilot. Later stages are gated by
recorded results. --resume skips terminal trials, including failures; it never
silently retries them. Interrupted trials remain incomplete.
"""

import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import platform
import re
from tempfile import TemporaryDirectory
from time import monotonic, perf_counter, sleep
from unittest.mock import patch

from scripts.evaluate_conversation import CASES, DEVELOPMENT_CASES, ACCEPTANCE_CASES, DIMENSIONS, load_cases
from src.capabilities.applications import create_applications
from src.capabilities.contracts import ToolExecutionError
from src.capabilities.web_search import SearchRouter
from src.config import load_config
from src.intelligence.conversation import ConversationSession
from src.intelligence.ollama_client import OllamaClient, OllamaError
from src.intelligence.persona import SYSTEM_INSTRUCTION
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore


PILOT_IDS = {
    "detail", "q2d-committed-rollback", "q2d-persistent-undo", "q2d-hot-row", "q2h-unseen-api",
    "thanks", "q2h-rubber-duck", "q2d-tired-taglish", "q2d-language-switch", "q2h-taglish-correction",
}
PRIORITY_IDS = {"detail", "q2d-committed-rollback", "q2d-persistent-undo", "q2d-hot-row", "q2h-unseen-api"}
LIMITS = {"seconds": 2700, "chat_requests": 200, "http_requests": 1000}
STAGE_SECONDS = {"pilot": 1200, "full": 2700, "diagnostic": 600, "repetitions": 300}
DIAGNOSTIC_TOKENS = 2048
DIAGNOSTIC_TIMEOUT = 360.0


class StudyStop(Exception):
    """A finite budget or identity/control condition stopped the experiment."""


def fingerprint(value):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(text.encode()).hexdigest()


def environment(settings):
    with OllamaClient(settings) as client:
        version = client._request("GET", "/api/version", client.probe_timeout)
        model = client.check_model()
        show = client._request("POST", "/api/show", client.probe_timeout, {"model": settings.model})
    if not isinstance(model.get("digest"), str) or len(model["digest"]) < 32:
        raise StudyStop("model_digest_unavailable")
    controls = show.get("thinking", {})
    controls = controls if isinstance(controls, dict) else {}
    return {"python": platform.python_version(), "platform": platform.system(), "machine": platform.machine(),
            "ollama_version": version.get("version"), "model_name": model.get("name"), "model_digest": model["digest"],
            "model_details": {k: show.get("details", {}).get(k) for k in ("format", "family", "parameter_size", "quantization_level")},
            "thinking_boolean_controls": [v for v in controls.get("values", []) if type(v) is bool],
            "renderer": show.get("renderer"), "parser": show.get("parser"), "setup_http_requests": 3,
            "production_think": settings.ollama_think, "timeout_seconds": settings.model_timeout,
            "context_chars": settings.context_chars, "context_turns": settings.context_turns,
            "production_response_tokens": settings.response_tokens}


def response_metrics(payload):
    """Allowlist numeric metadata; private thinking strings never leave this function."""
    message = payload.get("message")
    message = message if isinstance(message, dict) else {}
    thinking, final = message.get("thinking"), message.get("content")
    reason = payload.get("done_reason")
    result = {"done": payload.get("done") is True, "assistant_role": message.get("role") == "assistant",
              "done_reason": reason if isinstance(reason, str) and reason in {"length", "stop"} else "other",
              "thinking_present": isinstance(thinking, str) and bool(thinking.strip()),
              "thinking_characters": len(thinking) if isinstance(thinking, str) else 0,
              "final_content_present": isinstance(final, str) and bool(final.strip()),
              "final_characters": len(final) if isinstance(final, str) else 0}
    for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration", "prompt_eval_count", "eval_count"):
        if type(payload.get(key)) in (int, float) and math.isfinite(payload[key]) and payload[key] >= 0:
            result[key] = payload[key]
    return result


def completion_status(error_kind, metrics):
    if metrics.get("done_reason") == "length":
        return "output_limit"
    if error_kind == "unavailable" and "done" in metrics:
        if not metrics["done"] or not metrics.get("assistant_role"):
            return "invalid_response"
        if not metrics.get("final_content_present"):
            return "thinking_only" if metrics.get("thinking_present") else "missing_final"
    if error_kind:
        return error_kind
    return "complete"


def error_kind(error):
    # These are the existing adapter's own controlled errors, never raw API bodies.
    if "does not support thinking" in str(error) or "did not report supported thinking controls" in str(error):
        return "thinking_unsupported"
    return error.kind


def thinking_observation(mode, status, metrics):
    if status == "thinking_unsupported" or metrics.get("http_status") in {400, 422}:
        return "unsupported_or_rejected"
    if metrics.get("thinking_present"):
        if mode == "off":
            return "thinking_observed_despite_off"
        return "supported_and_observed" if status == "complete" else "activated_without_complete_final"
    return "requested_not_demonstrably_active" if mode == "on" else "no_thinking_observed"


class Ledger:
    def __init__(self, state, output, stage):
        self.state, self.output, self.stage = state, output, stage
        reserved = state.pop("inflight_reserved_seconds", 0)
        prior_stage = state.pop("inflight_stage", stage)
        self.stage_times = state.setdefault("stage_runtime_seconds", {})
        self.stage_times[prior_stage] = self.stage_times.get(prior_stage, 0) + reserved
        self.base = state.get("runtime_seconds", 0) + reserved
        self.stage_base = self.stage_times.get(stage, 0)
        self.started = monotonic()
        self.deadline = self.started + min(STAGE_SECONDS[stage] - self.stage_base, LIMITS["seconds"] - self.base)

    def remaining(self):
        return min(self.deadline - monotonic(), LIMITS["seconds"] - self.base - (monotonic() - self.started))

    def save(self):
        elapsed = monotonic() - self.started
        self.state["runtime_seconds"] = round(self.base + elapsed, 3)
        self.stage_times[self.stage] = round(self.stage_base + elapsed, 3)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_name(self.output.name + ".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for attempt in range(6):
            try:
                temporary.replace(self.output)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                sleep(0.05 * 2 ** attempt)

    @contextmanager
    def request(self, method, path, timeout, body):
        if self.remaining() <= 0 or len(self.state["http"]) >= LIMITS["http_requests"]:
            raise StudyStop("runtime_or_http_budget")
        chat = path == "/api/chat"
        if chat and self.state["chat_requests"] >= LIMITS["chat_requests"]:
            raise StudyStop("chat_request_budget")
        effective = min(timeout, self.remaining())
        event = {"stage": self.stage, "method": method, "path": path, "timeout_seconds": round(effective, 3)}
        if chat:
            self.state["chat_requests"] += 1
            event.update(think=body.get("think"), num_predict=body["options"].get("num_predict"),
                         temperature=body["options"].get("temperature"), input_sha256=fingerprint(body["messages"]),
                         input_characters=sum(len(m["content"]) for m in body["messages"]))
        self.state["http"].append(event)
        self.state["inflight_reserved_seconds"] = effective
        self.state["inflight_stage"] = self.stage
        self.save()
        started = perf_counter()
        try:
            yield event, effective
        finally:
            event["wall_ms"] = round((perf_counter() - started) * 1000, 3)
            self.state["inflight_reserved_seconds"] = 0
            self.state.pop("inflight_stage", None)
            self.save()


class MeasuredClient(OllamaClient):
    def __init__(self, settings, ledger, digest):
        super().__init__(settings)
        self.ledger, self.digest = ledger, digest

    def check_model(self):
        entry = super().check_model()
        if entry.get("digest") != self.digest:
            raise StudyStop("model_digest_changed")
        return entry

    def _request(self, method, path, timeout, body=None):
        with self.ledger.request(method, path, timeout, body) as (event, effective):
            try:
                payload = super()._request(method, path, effective, body)
            except OllamaError as exc:
                event["error_kind"] = error_kind(exc)
                match = re.search(r"HTTP (\d{3})", str(exc))
                if match:
                    event["http_status"] = int(match[1])
                raise
            if path == "/api/chat":
                event.update(response_metrics(payload))
            return payload

    def generate(self, messages, **kwargs):
        final = super().generate(messages, **kwargs)
        if any(marker in final.casefold() for marker in ("<think", "</think", "<analysis", "</analysis")):
            raise OllamaError("Evaluator suppressed reasoning-tagged final text.", kind="contaminated_final")
        return final


def resources(client):
    import psutil
    try:
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.05)
    except (psutil.Error, OSError):
        return {"source": "psutil", "status": "unavailable"}
    result = {"collected_at": datetime.now(UTC).isoformat(),
              "source": "psutil before/after samples; RSS sums may double-count shared pages",
              "available_ram_bytes": memory.available, "total_ram_bytes": memory.total,
              "system_cpu_percent_50ms": cpu}
    sizes = []
    for process in psutil.process_iter(["name", "memory_info"], ad_value=None):
        try:
            if (process.info["name"] or "").casefold().startswith("ollama"):
                sizes.append(process.info["memory_info"].rss)
        except (psutil.Error, AttributeError):
            continue
    result.update(ollama_processes=len(sizes), ollama_working_set_sum_bytes=sum(sizes) if sizes else None)
    try:
        loaded = client._request("GET", "/api/ps", client.probe_timeout).get("models", [])
        matches = [m for m in loaded if m.get("name") == client.settings.model or m.get("model") == client.settings.model]
        result["ollama_reported_model_vram_bytes"] = next(
            (m["size_vram"] for m in matches if type(m.get("size_vram")) is int and m["size_vram"] >= 0), None)
    except (OllamaError, StudyStop):
        result["ollama_reported_model_vram_bytes"] = None
    return result


def mode_order(index, repetition=0):
    return ("off", "on") if (index + repetition) % 2 == 0 else ("on", "off")


def run_trial(settings, case, mode, tokens, repetition, ledger):
    state = ledger.state
    key = [ledger.stage, case["id"], mode, repetition]
    if any(t["key"] == key for t in state["trials"]):
        return  # Terminal failures and interrupted trials are never silently retried.
    if ledger.remaining() <= 0:
        raise StudyStop("runtime_budget")
    trial = {"key": key, "stage": ledger.stage, "id": case["id"], "category": case["category"],
             "mode": mode, "tokens": tokens, "repetition": repetition, "status": "running", "turns": [],
             "configured_timeout_seconds": DIAGNOSTIC_TIMEOUT if ledger.stage == "diagnostic" else settings.model_timeout,
             "expected_turns": len(case["turns"]), "human_review": dict.fromkeys(DIMENSIONS)}
    state["trials"].append(trial)
    ledger.save()
    with TemporaryDirectory(prefix="aika-reasoning-ab-") as directory, patch(
        "src.capabilities.applications._launch", side_effect=ToolExecutionError("Launch blocked by evaluation harness.")
    ) as launch:
        root = Path(directory)
        configuration = replace(settings, data_dir=root, ollama_think=mode, response_tokens=tokens,
                                model_timeout=trial["configured_timeout_seconds"],
                                web_search_enabled=False, web_reading_enabled=False, tavily_api_key="")
        with MeasuredClient(configuration, ledger, state["environment"]["model_digest"]) as client:
            session = ConversationSession(SYSTEM_INSTRUCTION, case.get("context_turns", settings.context_turns),
                                          client.generate, ConversationStore(root), MemoryStore(root),
                                          applications=create_applications(settings.disabled_apps), web_search=SearchRouter(),
                                          context_chars=case.get("context_chars", settings.context_chars))
            if case.get("history_padding"):
                previous = ("Synthetic mode Tide has no timer. " + "padding " * 600, "Understood.")
                session._sequence = session._store.save_exchange(session.session_id, 0, *previous)
                session._turns.append(previous)
            for index, prompt in enumerate(case["turns"]):
                turn = {"index": index, "status": "running", "final": None}
                trial["turns"].append(turn)
                all_start = len(state["http"])
                before = resources(client)
                start_event, before_launches = len(state["http"]), launch.call_count
                tools, context = [], []
                ledger.save()
                started = perf_counter()
                error = None
                try:
                    turn["final"] = session.reply(prompt, tool_trace=tools.append,
                                                  trace=lambda _id, _messages, included, omitted: context.append([included, omitted]))
                except OllamaError as exc:
                    error = error_kind(exc)
                except (KeyboardInterrupt, StudyStop):
                    turn["status"] = trial["status"] = "interrupted_or_budget"
                    trial["unrun_turns"] = trial["expected_turns"] - len(trial["turns"])
                    ledger.save()
                    raise
                turn["wall_ms"] = round((perf_counter() - started) * 1000, 3)
                events = state["http"][start_event:]
                chats = [e for e in events if e["path"] == "/api/chat"]
                metrics = chats[-1] if chats else {}
                if (error == "timeout" and metrics.get("timeout_seconds", configuration.model_timeout) < configuration.model_timeout
                        and ledger.remaining() <= 0):
                    error = "study_deadline"
                if chats and any(e.get("think") is not (mode == "on") for e in chats):
                    error = "thinking_control_not_applied"
                after = resources(client)
                turn.update(status=completion_status(error, metrics), model_requests=len(chats),
                            generation_http_requests=len(events), http_requests=len(state["http"]) - all_start,
                            http_start=all_start, http_end=len(state["http"]), metrics=dict(metrics), context=context,
                            tools=[{"tool": t.tool, "status": str(t.status), "verified": t.verified} for t in tools],
                            blocked_launch_attempts=launch.call_count - before_launches,
                            resources_before=before, resources_after=after)
                turn["thinking_observation"] = thinking_observation(mode, turn["status"], metrics)
                ledger.save()
                if turn["status"] != "complete":
                    trial["status"] = turn["status"]
                    break
            else:
                trial["status"] = "complete"
    trial["unrun_turns"] = trial["expected_turns"] - len(trial["turns"])
    ledger.save()
    print(ledger.stage, case["id"], mode, trial["status"], flush=True)


def pilot_usable(state):
    trials = [t for t in state["trials"] if t["stage"] == "pilot"]
    if len(trials) != len(PILOT_IDS) * 2 or any(t["status"] != "complete" for t in trials):
        return False
    on = [turn for t in trials if t["mode"] == "on" for turn in t["turns"]]
    off = [turn for t in trials if t["mode"] == "off" for turn in t["turns"]]
    return any(t["metrics"].get("thinking_present") for t in on) and not any(
        t["metrics"].get("thinking_present") for t in off)


def run_stage(settings, cases, ledger):
    stage = ledger.stage
    if stage in {"full", "repetitions"} and not pilot_usable(ledger.state):
        raise StudyStop("pilot_not_usable_full_comparison_not_run")
    selected = [c for c in cases if (c["id"] in PILOT_IDS if stage == "pilot" else
                                    c["id"] not in PILOT_IDS if stage == "full" else c["id"] in PRIORITY_IDS)]
    if stage == "diagnostic":
        failures = {t["id"] for t in ledger.state["trials"] if t["stage"] == "pilot" and t["mode"] == "on" and t["status"] == "output_limit"}
        if len(failures) < 2:
            raise StudyStop("higher_budget_requires_repeated_primary_output_limit_failures")
        selected = sorted([c for c in cases if c["id"] in failures], key=lambda c: c["id"] not in PRIORITY_IDS)[:1]
    repetitions = (1, 2) if stage == "repetitions" else (0,)
    for repetition in repetitions:
        for index, case in enumerate(selected):
            for mode in mode_order(index, repetition):
                run_trial(settings, case, mode, DIAGNOSTIC_TOKENS if stage == "diagnostic" else 1024, repetition, ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", action="store_true")
    parser.add_argument("--stage", choices=STAGE_SECONDS, default="pilot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not args.ollama:
        parser.error("Use --ollama to explicitly request this bounded local inference experiment.")
    settings = load_config()
    actual = (settings.model, settings.ollama_think, settings.response_tokens, settings.context_chars, settings.context_turns)
    if actual != ("qwen3.5:4b", "off", 1024, 24000, 10):
        parser.error("Production baseline differs from the requested experiment; configuration was not changed.")
    cases = load_cases([CASES, DEVELOPMENT_CASES, ACCEPTANCE_CASES])
    identity = {"fixture_sha256": fingerprint(cases), "persona_sha256": fingerprint(SYSTEM_INSTRUCTION), "limits": LIMITS}
    if args.output.exists():
        if not args.resume:
            parser.error("Output exists; use --resume to preserve completed/failed trials.")
        state = json.loads(args.output.read_text(encoding="utf-8"))
        if state["identity"] != identity:
            parser.error("Fixtures, active persona or study limits changed; do not mix experiments.")
        for trial in state["trials"]:
            if trial["status"] == "running":
                trial["status"] = "interrupted"
                for turn in trial["turns"]:
                    if turn["status"] == "running":
                        turn.update(status="interrupted", final=None)
    else:
        state = {"created_at": datetime.now(UTC).isoformat(), "identity": identity, "environment": environment(settings),
                 "chat_requests": 0, "http": [], "trials": [], "stages": [], "runtime_seconds": 0,
                 "note": "Synthetic fixture references and accepted final responses only; thinking text is never logged. Primary 1024-token/production-timeout trials and the separate 2048-token/360-second diagnostic must not be pooled. Before/after resource samples are not peaks or causal attribution."}
    ledger = Ledger(state, args.output, args.stage)
    stage_record = {"stage": args.stage, "status": "running"}
    state["stages"].append(stage_record)
    try:
        with MeasuredClient(settings, ledger, state["environment"]["model_digest"]) as client:
            version = client._request("GET", "/api/version", client.probe_timeout).get("version")
            if version != state["environment"]["ollama_version"]:
                raise StudyStop("ollama_version_changed")
        run_stage(settings, cases, ledger)
        stage_record["status"] = "complete"
    except (StudyStop, KeyboardInterrupt) as exc:
        stage_record.update(status="stopped", reason=str(exc) if isinstance(exc, StudyStop) else "user_interrupt")
    finally:
        ledger.save()


if __name__ == "__main__":
    main()
