"""Opt-in fixed-label diagnostics: never record inputs, exception text, or responses."""

import logging
from time import perf_counter

from src.capabilities.contracts import ToolExecutionError, ToolStatus


STAGES = {"input", "provider", "normalization", "contract", "internal", "retrieval", "extraction", "grounding"}


class WebFailure(ToolExecutionError):
    def __init__(self, message: str, stage: str, code: str, *, status=ToolStatus.EXECUTION_FAILED):
        if stage not in STAGES:
            raise ValueError("Unknown web failure stage.")
        super().__init__(message, status=status)
        self.stage = stage
        self.code = code


def record(enabled: bool, stage: str, outcome: str, started: float, *, reason: str = "none"):
    if reason not in {"none", "malformed_json", "missing_quote", "quote_not_found", "quote_not_selected",
                      "unsupported_number", "source_mismatch", "insufficient_evidence", "model_timeout",
                      "model_unavailable", "invalid_claim", "unsupported_claim"}:
        reason = "none"
    if enabled and stage in STAGES and outcome in {"success", "controlled_failure", "unexpected_failure", "model_failure", "draft_rejected", "claim_rejected"}:
        logging.getLogger("aika.web").warning("event=web_diagnostic stage=%s outcome=%s reason=%s elapsed_ms=%.1f",
                                               stage, outcome, reason, (perf_counter() - started) * 1000)
