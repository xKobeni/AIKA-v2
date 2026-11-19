"""Opt-in local-model evaluation using synthetic input and temporary storage only.

Run: python -m scripts.evaluate_conversation --ollama --output <review.json>
Review each dimension separately; generated wording is never a unit-test oracle.
"""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from src.cli import SYSTEM_INSTRUCTION
from src.config import load_config
from src.capabilities.contracts import ToolExecutionError
from src.capabilities.web_search import SearchRouter
from src.intelligence.conversation import ConversationSession
from src.intelligence.ollama_client import OllamaClient, OllamaError
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore


CASES = Path(__file__).resolve().parents[1] / "tests/fixtures/conversation_quality.json"
DEVELOPMENT_CASES = CASES.with_name("conversation_quality_2_development.json")
ACCEPTANCE_CASES = CASES.with_name("conversation_quality_2_acceptance.json")
DIMENSIONS = ("technical_factuality", "naturalness", "relevance", "context_retention", "length",
              "taglish_fluency", "repetitiveness", "uncertainty", "safety")


def load_cases(paths):
    cases = [case for path in paths for case in json.loads(path.read_text(encoding="utf-8"))]
    return cases


def evaluate(settings, cases, output, *, instruction=SYSTEM_INSTRUCTION):
    if (len({case["id"] for case in cases}) != len(cases)
            or any(not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", case["id"]) for case in cases)):
        raise ValueError("Use unique bounded case IDs without path components.")
    rows = []
    report = {"created_at": datetime.now(UTC).isoformat(), "model": settings.model,
              "system_instruction": instruction, "system_characters": len(instruction),
              "context_chars": settings.context_chars, "response_tokens": settings.response_tokens,
              "thinking": settings.ollama_think, "temperature": 0.2,
              "note": "Synthetic inputs; fresh per-case temporary databases; web disabled; app launch denied by harness. "
                      "System snapshots are real local measurements. Scores require independent manual review.",
              "cases": rows}
    with TemporaryDirectory(prefix="aika-conversation-eval-") as directory, OllamaClient(settings) as client, patch(
        "src.capabilities.applications._launch", side_effect=ToolExecutionError("Launch blocked by synthetic evaluation harness.")
    ) as launches:
        client.check_model()
        for case in cases:
            root = Path(directory) / case["id"]
            calls = []

            def generate(messages):
                calls.append({"content_characters": sum(len(m["content"]) for m in messages),
                              "system_characters": len(messages[0]["content"]),
                              "history_pairs": (len(messages) - 2) // 2})
                return client.generate(messages)

            session = ConversationSession(instruction, case.get("context_turns", settings.context_turns), generate,
                                          ConversationStore(root), MemoryStore(root), web_search=SearchRouter(),
                                          context_chars=case.get("context_chars", settings.context_chars))
            if case.get("history_padding"):
                previous = ("Synthetic mode Tide has no timer. " + "padding " * 600, "Understood.")
                session._sequence = session._store.save_exchange(session.session_id, 0, *previous)
                session._turns.append(previous)
            row = {"id": case["id"], "category": case["category"], "review": case["review"], "turns": [],
                   "split": case.get("split", "legacy_development"),
                   "scores": dict.fromkeys(DIMENSIONS)}
            rows.append(row)
            for prompt in case["turns"]:
                started = perf_counter()
                before = len(calls)
                before_launches = launches.call_count
                tools, traces = [], []
                try:
                    answer = session.reply(prompt, tool_trace=tools.append,
                                           trace=lambda _id, _messages, _included, omitted: traces.append(omitted))
                    error = None
                except OllamaError as exc:
                    answer, error = None, str(exc)
                row["turns"].append({"user": prompt, "assistant": answer, "error": error,
                                     "elapsed_ms": round((perf_counter() - started) * 1000, 1),
                                     "launch_attempts_blocked": launches.call_count - before_launches,
                                     "context_omitted": traces[-1] if traces else None,
                                     "tools": [{"tool": tool.tool, "status": str(tool.status), "verified": tool.verified}
                                               for tool in tools],
                                     "model_calls": len(calls) - before, "inputs": calls[before:]})
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(case["id"], flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", action="store_true", help="explicitly enable real local inference")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, nargs="+", default=[CASES, DEVELOPMENT_CASES, ACCEPTANCE_CASES],
                        help="synthetic fixture files; defaults to all 44 legacy and 20 new cases")
    args = parser.parse_args()
    if not args.ollama:
        parser.error("Live evaluation requires --ollama; no inference was requested.")
    settings = replace(load_config(), web_search_enabled=False, web_reading_enabled=False, tavily_api_key="")
    evaluate(settings, load_cases(args.cases), args.output)


if __name__ == "__main__":
    main()
