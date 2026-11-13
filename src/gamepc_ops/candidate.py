"""Typed candidate states for the gaming-PC database-building flow (STR-134 Q36).

Pure, offline, deterministic. No model, no network, no database write, no apply/publish authority.

Happy path (forward by exactly one step, each step needs its own evidence):
  OBSERVED -> DIFFERENCE_DETECTED -> SOURCE_SCOPE_CHECKED -> EXTRACTED -> EVIDENCE_VALIDATED -> QA_READY
Side states: UNKNOWN_HELD (not enough to decide), REJECTED_QUARANTINED (terminal), HUMAN_REVIEW_REQUIRED.
QA_READY only means "ready for independent QA / a human"; it carries no authority (see AUTHORITY).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Optional, Tuple


class State(str, Enum):
    OBSERVED = "OBSERVED"
    DIFFERENCE_DETECTED = "DIFFERENCE_DETECTED"
    SOURCE_SCOPE_CHECKED = "SOURCE_SCOPE_CHECKED"
    EXTRACTED = "EXTRACTED"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    QA_READY = "QA_READY"
    UNKNOWN_HELD = "UNKNOWN_HELD"
    REJECTED_QUARANTINED = "REJECTED_QUARANTINED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


HAPPY = (State.OBSERVED, State.DIFFERENCE_DETECTED, State.SOURCE_SCOPE_CHECKED,
         State.EXTRACTED, State.EVIDENCE_VALIDATED, State.QA_READY)
SIDE = (State.UNKNOWN_HELD, State.REJECTED_QUARANTINED, State.HUMAN_REVIEW_REQUIRED)

# QA_READY never creates any of these. They are constants on purpose: nothing here can switch them on.
AUTHORITY = {"apply_to_canonical_db": False, "publish": False, "start_model": False, "release_hold": False}


class TransitionError(ValueError):
    pass


def normalize(text: str) -> str:
    """Normalisation used for quote matching: NFKC, whitespace removed. Deterministic, no model."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    source_sha256: str
    state: State = State.OBSERVED
    university: Optional[str] = None
    fiscal_year: Optional[int] = None
    method: Optional[str] = None            # admission method
    fact_key: Optional[str] = None
    value: Optional[str] = None
    quote: Optional[str] = None
    scope_evidence_ref: Optional[str] = None   # STR-101: independent official evidence for binding year/faculty
    high_risk: bool = False
    independent_qa_ref: Optional[str] = None
    history: Tuple[Tuple[str, str, str], ...] = field(default_factory=tuple)  # (from, to, reason)

    # ---- helpers -------------------------------------------------------------------------
    def _next(self, to: State, reason: str, **changes) -> "Candidate":
        if not reason or not reason.strip():
            raise TransitionError("a reason is required for every transition")
        return replace(self, state=to, history=self.history + ((self.state.value, to.value, reason),), **changes)

    # ---- transitions ---------------------------------------------------------------------
    def to_difference_detected(self, *, previous_sha256: str, reason: str = "source hash differs from the previous edition") -> "Candidate":
        self._need(State.OBSERVED)
        if not previous_sha256 or previous_sha256 == self.source_sha256:
            raise TransitionError("no difference: previous hash is missing or identical")
        return self._next(State.DIFFERENCE_DETECTED, reason)

    def to_scope_checked(self, *, university: str, fiscal_year: int, method: str, scope_evidence_ref: str, reason: str = "scope proven by independent evidence") -> "Candidate":
        self._need(State.DIFFERENCE_DETECTED)
        if not (university and method) or not isinstance(fiscal_year, int):
            raise TransitionError("university, fiscal_year (int) and method are all required")
        if not scope_evidence_ref or scope_evidence_ref == self.source_sha256:
            raise TransitionError("scope needs independent evidence (STR-101); the source itself does not count")
        return self._next(State.SOURCE_SCOPE_CHECKED, reason, university=university, fiscal_year=fiscal_year, method=method, scope_evidence_ref=scope_evidence_ref)

    def to_extracted(self, *, fact_key: str, value: str, quote: str, reason: str = "typed fact extracted") -> "Candidate":
        self._need(State.SOURCE_SCOPE_CHECKED)
        if not (fact_key and value and quote):
            raise TransitionError("fact_key, value and quote are all required")
        return self._next(State.EXTRACTED, reason, fact_key=fact_key, value=value, quote=quote)

    def to_evidence_validated(self, *, source_text: str, reason: str = "quote found verbatim in the source text") -> "Candidate":
        self._need(State.EXTRACTED)
        if sha256_hex(source_text) != self.source_sha256:
            raise TransitionError("source text does not match source_sha256")
        if normalize(self.quote) not in normalize(source_text):
            raise TransitionError("quote not found in the source text")
        if normalize(self.value) not in normalize(self.quote):
            raise TransitionError("value does not appear in its own quote")
        return self._next(State.EVIDENCE_VALIDATED, reason)

    def to_qa_ready(self, *, reason: str = "all evidence present; waiting for independent QA / human") -> "Candidate":
        self._need(State.EVIDENCE_VALIDATED)
        if self.high_risk and not self.independent_qa_ref:
            raise TransitionError("high-risk candidates need an independent QA reference before QA_READY")
        return self._next(State.QA_READY, reason)

    def hold_unknown(self, reason: str) -> "Candidate":
        self._not_terminal()
        return self._next(State.UNKNOWN_HELD, reason)

    def quarantine(self, reason: str) -> "Candidate":
        if self.state is State.REJECTED_QUARANTINED:
            raise TransitionError("already quarantined")
        return self._next(State.REJECTED_QUARANTINED, reason)

    def need_human(self, reason: str) -> "Candidate":
        self._not_terminal()
        return self._next(State.HUMAN_REVIEW_REQUIRED, reason)

    def human_decision(self, *, human_ref: str, resume_at: State, reason: str) -> "Candidate":
        """Only a human decision (recorded by reference) can leave UNKNOWN_HELD / HUMAN_REVIEW_REQUIRED."""
        if self.state not in (State.UNKNOWN_HELD, State.HUMAN_REVIEW_REQUIRED):
            raise TransitionError("not waiting for a human")
        if not human_ref:
            raise TransitionError("a human decision reference is required")
        if resume_at is State.QA_READY or resume_at not in HAPPY[:-1] + (State.REJECTED_QUARANTINED,):
            raise TransitionError("a human decision cannot jump straight to QA_READY")
        return self._next(resume_at, f"{reason} [human_ref={human_ref}]")

    # ---- guards --------------------------------------------------------------------------
    def _need(self, expected: State) -> None:
        if self.state is not expected:
            raise TransitionError(f"expected state {expected.value}, got {self.state.value}")

    def _not_terminal(self) -> None:
        if self.state is State.REJECTED_QUARANTINED:
            raise TransitionError("REJECTED_QUARANTINED is terminal")

    @property
    def authority(self) -> dict:
        return dict(AUTHORITY)
