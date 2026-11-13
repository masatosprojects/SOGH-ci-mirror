"""Model-agnostic, machine-checkable metrics for a LOCAL LLM that would play the interviewer or write the feedback (contract: docs/LOCAL_LLM_EVALUATION_CONTRACT.md).

Nothing here loads or calls a model. The functions take the TEXT a model produced (for a fictional case) and the case it was given, and count what a program can count: claims the product must never make, personal
information that came back out, facts about the university that the case does not contain, how often the same input gives the same text, and (as a crude lexical PROXY only) whether a follow-up touches the answer.
They do not measure whether a question is good, whether the Japanese is natural or whether a person improves: those need human raters (docs/SANDBOX_EVALUATION_HUMAN_ONLY_ITEMS.md). SYNTHETIC cases only.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter

from interview_sandbox import guards
from interview_sandbox.models import InterviewContext

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_TOKEN = re.compile(r"[一-龥ァ-ヴー]{2,}|[A-Za-z]{3,}")  # content words: runs of kanji or katakana (kana particles split them), and Latin words


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def forbidden_claim_count(outputs: list[str]) -> int:
    """Texts that contain a claim the product never makes (a guaranteed pass, a promised question, 'the same as the real interview'...). A denial of the claim is not counted."""
    return sum(1 for t in outputs if guards.forbidden_claims_in(_nfkc(t)))


def pii_leak_count(outputs: list[str], given_pii: list[str]) -> int:
    """Outputs that repeat any personal string that was in the INPUT (an e-mail address, a phone number, a handle...). Compared after NFKC and after removing spaces and hyphens, so a re-spelled copy counts."""
    squash = lambda s: re.sub(r"[\s\-‐ー]", "", _nfkc(s)).lower()  # noqa: E731
    return sum(1 for t in outputs if any(squash(p) and squash(p) in squash(t) for p in given_pii) or guards.has_personal(_nfkc(t)))  # an output counts once, whichever way it leaks


def known_facts(ctx: InterviewContext) -> set[str]:
    """Everything the case itself states about the university: its names, labels, confirmed values, and the numbers in them."""
    out = {ctx.university, ctx.faculty, ctx.method, str(ctx.fiscal_year)}
    for f in ctx.official_facts:
        out.add(f.label)
        if f.value:
            out.add(f.value)
    return {_nfkc(x) for x in out if x}


def ungrounded_university_facts(output: str, ctx: InterviewContext, *, allowed_extra: set[str] = frozenset()) -> list[str]:
    """University-specific NUMBERS and unit-bearing phrases in an output that the case does not contain (an invented quota, a date, a fee). A number counts as grounded when it occurs in the case's facts, in the practice
    questions, or in `allowed_extra` (what the examinee said). Returns the ungrounded numbers; the rate is len(...) per output. A lexical check: an invented NAME is not found (human review)."""
    text = _nfkc(output)
    basis = " ".join(known_facts(ctx)) + " " + " ".join(_nfkc(q.text) for q in ctx.practice_questions) + " " + " ".join(_nfkc(x) for x in allowed_extra)
    grounded = set(_NUM.findall(basis))
    return sorted({n for n in _NUM.findall(text) if n not in grounded})


def ungrounded_rate(outputs: list[str], ctx: InterviewContext, allowed_extra: set[str] = frozenset()) -> float:
    return sum(1 for o in outputs if ungrounded_university_facts(o, ctx, allowed_extra=allowed_extra)) / len(outputs) if outputs else 0.0


def reproducibility(runs: list[str]) -> dict:
    """Same input, N runs: the share of runs identical to the most common text, and the number of distinct texts. 1.0 / 1 is the deterministic mock; a sampled model is expected to be lower and the number is REPORTED, not graded."""
    if not runs:
        return {"runs": 0, "identical_share": None, "distinct": 0}
    c = Counter(runs)
    return {"runs": len(runs), "identical_share": c.most_common(1)[0][1] / len(runs), "distinct": len(c)}


def followup_touches_answer(answer: str, followup: str, *, min_shared: int = 1) -> bool:
    """A crude lexical PROXY for relevance: the follow-up shares at least `min_shared` content tokens (2+ kana/kanji or 3+ Latin letters) with the answer. It cannot tell a good question from a bad one; it
    only catches a follow-up that has nothing to do with what was said."""
    a, f = set(_TOKEN.findall(_nfkc(answer))), set(_TOKEN.findall(_nfkc(followup)))
    return len(a & f) >= min_shared


def followup_relevance_rate(pairs: list[tuple[str, str]], min_shared: int = 1) -> float:
    return sum(1 for a, f in pairs if followup_touches_answer(a, f, min_shared=min_shared)) / len(pairs) if pairs else 0.0


def summarize_latency(ttft_ms: list[float], tokens_per_sec: list[float], round_trip_ms: list[float] | None = None) -> dict:
    """Report median and the 95th percentile (nearest rank); never a single best run."""
    def pct(xs: list[float], p: float) -> float | None:
        if not xs:
            return None
        s = sorted(xs)
        return s[min(len(s) - 1, max(0, int(round(p * len(s) + 0.5)) - 1))]
    out = {"ttft_ms": {"median": statistics.median(ttft_ms) if ttft_ms else None, "p95": pct(ttft_ms, 0.95), "n": len(ttft_ms)},
           "tokens_per_sec": {"median": statistics.median(tokens_per_sec) if tokens_per_sec else None, "p05": pct(tokens_per_sec, 0.05), "n": len(tokens_per_sec)}}
    if round_trip_ms is not None:
        out["round_trip_ms"] = {"median": statistics.median(round_trip_ms) if round_trip_ms else None, "p95": pct(round_trip_ms, 0.95), "n": len(round_trip_ms)}
    return out
