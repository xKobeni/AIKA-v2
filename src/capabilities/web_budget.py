"""A synchronous request deadline shared by the existing provider and model adapters."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from src.capabilities.web_diagnostics import WebFailure


DEADLINE = ContextVar("aika_web_deadline", default=None)


def bounded_timeout(seconds: float) -> float:
    deadline = DEADLINE.get()
    if deadline is None:
        return seconds
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise WebFailure("Research stopped because its overall time budget was exhausted.", "retrieval", "workflow_budget")
    return min(seconds, remaining)


@contextmanager
def request_budget(seconds: float):
    parent = DEADLINE.get()
    deadline = monotonic() + seconds
    token = DEADLINE.set(min(parent, deadline) if parent is not None else deadline)
    try:
        yield
    finally:
        DEADLINE.reset(token)
