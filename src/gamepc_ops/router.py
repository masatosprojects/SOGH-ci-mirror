"""Job routing for the gaming-PC flow (STR-134 Q15/Q16/Q45): deterministic checks first, a model only for ambiguity,
and never while the real-model HOLD is in force or without an explicit separate GO.

This module cannot start a model: the only backends are Null and Fake. "real" is refused while the HOLD file exists
and is otherwise not implemented here (a real runtime needs its own, separately approved and independently QA'd change).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

HOLD_RELATIVE = Path("research/antigravity-local-ai/HOLD_REAL_MODEL_RUN.txt")
THERMAL_LIMIT_C = 75.0       # Q45 / synthetic scenario SC26
MEMORY_LIMIT_PERCENT = 90.0  # synthetic scenario SC27

DETERMINISTIC_KINDS = {"hash_diff", "scope_check", "table_extract", "quote_validate", "series_link"}
AMBIGUOUS_KIND = "ambiguous_diff"


class ModelUnavailable(RuntimeError):
    pass


class HoldActive(ModelUnavailable):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def hold_active(root: Optional[Path] = None) -> bool:
    """The HOLD is in force while the file exists. Only the user may delete it; nothing here ever does."""
    return ((root or repo_root()) / HOLD_RELATIVE).exists()


class NullBackend:
    name = "null"

    def interpret(self, source_text: str, question: str) -> str:
        raise ModelUnavailable("no model backend is configured")


class FakeBackend:
    """Deterministic canned answers for tests. Never reads the text; marks every answer as fake."""
    name = "fake"

    def __init__(self, answers: Optional[Dict[str, str]] = None):
        self.answers = answers or {}

    def interpret(self, source_text: str, question: str) -> str:
        return "FAKE:" + self.answers.get(question, "NO_ANSWER")


def get_backend(kind: str, *, hold_check: Callable[[], bool] = hold_active):
    if kind == "null":
        return NullBackend()
    if kind == "fake":
        return FakeBackend()
    if kind == "real":
        if hold_check():
            raise HoldActive("real-model runs are on HOLD (HOLD_REAL_MODEL_RUN.txt exists)")
        raise ModelUnavailable("a real backend is not implemented in this module; it needs a separate approved change")
    raise ValueError(f"unknown backend kind: {kind!r}")


@dataclass(frozen=True)
class Route:
    lane: str            # NON_LLM | LLM_CANDIDATE_ONLY | DEFER | HUMAN_REVIEW
    reason: str
    llm_may_run: bool = False


def route(job: dict, *, hold_check: Callable[[], bool] = hold_active) -> Route:
    kind = job.get("kind")
    if kind in DETERMINISTIC_KINDS:
        return Route("NON_LLM", f"{kind} is decided by deterministic code")
    if kind != AMBIGUOUS_KIND:
        return Route("HUMAN_REVIEW", f"unknown job kind: {kind!r}")
    # ambiguity: a model may only produce a CANDIDATE, and only if everything below is known and safe
    if hold_check():
        return Route("DEFER", "real-model HOLD is in force")
    if not job.get("go_ref"):
        return Route("DEFER", "no separate GO reference for running a model")
    temp, mem = job.get("die_temp_c"), job.get("mem_used_percent")
    if temp is None or job.get("temp_sensor_authentic") is not True:
        return Route("DEFER", "temperature unknown or its sensor is not proven genuine")
    if temp > THERMAL_LIMIT_C:
        return Route("DEFER", f"temperature above {THERMAL_LIMIT_C} C")
    if mem is None or mem > MEMORY_LIMIT_PERCENT:
        return Route("DEFER", "memory use unknown or above the limit")
    return Route("LLM_CANDIDATE_ONLY", "model output may only become a candidate and still needs the deterministic checks", llm_may_run=True)
