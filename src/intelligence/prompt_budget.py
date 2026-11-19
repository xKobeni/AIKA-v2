"""Pure content budgeting; no tokenization, model calls or storage changes."""

from src.config import MAX_CONTEXT_TURNS


def validate_messages(messages, limit):
    if (not isinstance(messages, list) or len(messages) > MAX_CONTEXT_TURNS * 2 + 2
            or any(not isinstance(message, dict) or set(message) != {"role", "content"}
                   or not isinstance(message["role"], str) or message["role"] not in {"system", "user", "assistant"}
                   or not isinstance(message["content"], str) for message in messages)):
        raise ValueError("Use bounded text-only system, user and assistant messages.")
    if sum(len(message["content"]) for message in messages) > limit:
        raise ValueError("Model input exceeds AIKA_CONTEXT_CHARS. Shorten the message or increase the configured budget.")


def bounded_context(system, history, current, limit):
    mandatory = [{"role": "system", "content": system}, {"role": "user", "content": current}]
    validate_messages(mandatory, limit)
    remaining = limit - len(system) - len(current)
    start = len(history)
    for index in range(len(history) - 2, -1, -2):
        size = len(history[index]["content"]) + len(history[index + 1]["content"])
        if size > remaining:
            break
        remaining -= size
        start = index
    messages = [mandatory[0], *history[start:], mandatory[1]]
    return messages, start > 0
