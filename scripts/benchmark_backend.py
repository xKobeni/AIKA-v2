"""Developer-only synthetic baselines. Live local inference requires --ollama."""

import argparse
from contextlib import closing
from dataclasses import replace
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sqlite3
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from src.capabilities.web_search import SearchRouter
from src.config import load_config, DEFAULT_CONTEXT_CHARS
from src.intelligence.conversation import ConversationSession
from src.intelligence.ollama_client import OllamaClient, OllamaError
from src.memory.retrieval import search_archive
from src.storage.conversation_store import ConversationStore


def archive_baseline(count, repeats=6):
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE conversation_messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, created_at TEXT)")
        db.executemany("INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?)", (
            (i, "synthetic", "user", f"Synthetic observation {i} about nebula planning.", "2026-11-19T00:00:00+00:00")
            for i in range(count)
        ))
        rows = []
        for label, query in (("no_match", ("missingtopic",)), ("many_matches", ("nebula",))):
            samples = []
            for _ in range(repeats):
                started = perf_counter()
                results = search_archive(db, query)
                samples.append((perf_counter() - started) * 1000)
            rows.append({"user_rows": count, "case": label, "first_ms": round(samples[0], 3),
                         "warm_median_ms": round(median(samples[1:]), 3), "results": len(results)})
        return rows


def context_baseline():
    sizes = []
    counts = []
    prompt = "Discuss a synthetic concept: " + "topic " * 2000
    answer = "Synthetic response. " * 500
    with TemporaryDirectory(prefix="aika-context-baseline-") as directory:
        def generate(messages):
            sizes.append(sum(len(message["content"]) for message in messages))
            counts.append(len(messages))
            return answer

        session = ConversationSession("Synthetic system instruction.", 10, generate,
                                      ConversationStore(Path(directory)), web_search=SearchRouter())
        for _ in range(12):
            session.reply(prompt)
        saved = session.session_id
        session.resume(saved)
        session.reply(prompt)
        retained = session.turn_count
        persisted = session._sequence // 2
    return {"turn_limit": 10, "user_characters": len(prompt.strip()), "assistant_characters": len(answer),
            "first_content_characters": sizes[0], "full_history_content_characters": sizes[-2],
            "restored_content_characters": sizes[-1], "generations": len(sizes), "model_mocked": True,
            "context_budget_characters": DEFAULT_CONTEXT_CHARS, "last_model_history_turns": (counts[-1] - 2) // 2,
            "retained_turns": retained, "persisted_exchanges": persisted,
            "note": "Character counts only; no tokenizer or model context-window assumption."}


def ollama_baseline():
    settings = load_config()
    settings = replace(settings, model_timeout=min(45, settings.model_timeout))
    client = OllamaClient(settings)
    original = client._request
    requests = []
    stage = "startup_probe"

    def measured(method, path, timeout, body=None):
        started = perf_counter()
        row = {"stage": stage, "method": method, "path": path}
        try:
            result = original(method, path, timeout, body)
            row["status"] = "success"
            for key in ("total_duration", "load_duration", "prompt_eval_count", "eval_count"):
                if type(result.get(key)) is int:
                    row[key] = result[key]
            return result
        except OllamaError as exc:
            row["status"] = exc.kind
            raise
        finally:
            row["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
            requests.append(row)

    client._request = measured
    outcomes = []
    try:
        client.check_model()
        for stage in ("first_generation", "consecutive_generation"):
            started = perf_counter()
            try:
                client.generate([{"role": "user", "content": "Reply only with OK."}], num_predict=32)
                outcome = "success"
            except OllamaError as exc:
                outcome = exc.kind
            outcomes.append({"stage": stage, "status": outcome,
                             "elapsed_ms": round((perf_counter() - started) * 1000, 3)})
    except OllamaError as exc:
        outcomes.append({"stage": stage, "status": exc.kind})
    finally:
        client.close()
    return {"model": settings.model, "requests": requests, "outcomes": outcomes,
            "note": "No forced unload/restart; first call is not proof of a cold model. No reply content recorded."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", action="store_true", help="also run two short synthetic local generations")
    parser.add_argument("--output", type=Path, help="write JSON measurements here")
    args = parser.parse_args(argv)
    result = {"python": platform.python_version(), "platform": platform.system(),
              "dependencies": {name: version(name) for name in ("httpx", "psutil", "ddgs", "python-dotenv", "trafilatura")},
              "archive": [row for count in (100, 1000, 10000) for row in archive_baseline(count)],
              "context": context_baseline()}
    if args.ollama:
        result["ollama"] = ollama_baseline()
    output = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
