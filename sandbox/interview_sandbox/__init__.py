"""SOGH interview sandbox (isolated prototype, text only, invented cases, deterministic mock; no network, no storage, no connection to any SOGH database).
See sandbox/README.md. A synthetic pass is not a result with real users and is not part of the M1 gates."""
from .cases import CASES, get_case
from .engine import InterviewSession
from .feedback import compare, compare_text, focus_of

__all__ = ["CASES", "get_case", "InterviewSession", "compare", "compare_text", "focus_of"]
