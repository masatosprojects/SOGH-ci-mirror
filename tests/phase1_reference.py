"""Reference semantics of the MRIF-1 Phase 1 decisions (docs/realtime-interview/PHASE1_MINIMAL_CONTRACTS_R1_R8.md).

Claude-owned QA helper. SYNTHETIC_ONLY, no I/O, no sockets, no files. This is NOT Work's implementation and Work does not import it: it states, in executable form, WHAT the Phase 1 controller must do, so that the same behaviours
can be checked against Work's controller (tests/test_phase1_reference_contracts.py holds the behavioural cases; Work's PR is reviewed against them).
Three small parts: the clock (R3), the command ledger (R2) and the retention rules (R7)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

MAX_ANSWER_SECONDS = 3600  # the engine's own per-answer bound (InterviewSession.answer)
DEFAULT_GRACE_MS = 120_000
MAX_GRACE_MS = 600_000
DEFAULT_RECONNECT_TTL_MS = 60_000
MAX_ERROR_EVENTS = 50


class ClockRegression(Exception):
    """The monotonic reading went backwards: never clamped silently."""


class Clock:
    """Integer milliseconds since the session started. A reading may only stay or grow; bool, float and negative readings are refused."""

    def __init__(self):
        self._last = 0

    def read(self, now_ms) -> int:
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("now_ms must be a non-negative integer")
        if now_ms < self._last:
            raise ClockRegression(f"{now_ms} < {self._last}")
        self._last = now_ms
        return now_ms


class ElapsedBridge:
    """R3. The engine accepts only an integer `elapsed_seconds` per answer (0..3600). The controller owns the milliseconds and hands the engine the *cumulative floor* delta,
    so the engine's total never drifts from the clock by one second or more, and nothing is rounded up or lost per answer. A delta over 3600 is passed in parts: the remainder is carried to the next call, never dropped."""

    def __init__(self):
        self.engine_total_s = 0

    def next_elapsed_seconds(self, clock_total_ms: int) -> int:
        target = clock_total_ms // 1000
        delta = max(0, target - self.engine_total_s)
        step = min(delta, MAX_ANSWER_SECONDS)
        self.engine_total_s += step
        return step


def canonical_payload_sha256(command: dict) -> str:
    body = {k: v for k, v in command.items() if k != "idempotency_key"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass
class Ledger:
    """R2. The controller is the only writer; `seq` is assigned here, at commit, and is contiguous from 1. The producer's order is never a ledger order.
    A command is `{idempotency_key, session_id, turn_id, generation_id, ...payload}`. An exact replay is acknowledged with the first result and appends nothing;
    the same key with a different payload is refused and appends nothing but one error event (bounded)."""

    session_id: str
    generation_id: int = 1
    events: list = field(default_factory=list)
    _seen: dict = field(default_factory=dict)
    _errors: int = 0
    _suppressed_errors: int = 0
    _next_seq: int = 1

    def _append(self, kind: str, **fields) -> dict:
        e = {"seq": self._next_seq, "session_id": self.session_id, "kind": kind, **fields}
        self._next_seq += 1
        self.events.append(e)
        return e

    def error(self, code: str) -> None:
        if self._errors >= MAX_ERROR_EVENTS:
            self._suppressed_errors += 1  # counted, never appended: a flood cannot grow the log without bound
            return
        self._errors += 1
        self._append("error", code=code)

    def new_generation(self) -> int:
        self.generation_id += 1
        return self.generation_id

    def commit(self, command: dict, accept) -> dict:
        """`accept(command)` is the engine call; it returns True when the engine took the event (it is NOT called for a replay, a conflict or a stale generation)."""
        key = command.get("idempotency_key")
        if not isinstance(key, str) or not key:
            self.error("missing_idempotency_key")
            return {"ok": False, "reason": "missing_idempotency_key"}
        if command.get("session_id") != self.session_id:
            self.error("foreign_session")
            return {"ok": False, "reason": "foreign_session"}
        sha = canonical_payload_sha256(command)
        if key in self._seen:
            first_sha, first_result = self._seen[key]
            if first_sha == sha:
                return {**first_result, "replayed": True}
            self.error("idempotency_conflict")
            return {"ok": False, "reason": "idempotency_conflict"}
        gid = command.get("generation_id")
        if type(gid) is not int or gid != self.generation_id:  # an int equal to the current generation only: not older, not newer, not bool/float/str/missing (True == 1 and 1.0 == 1 must not pass)
            self.error("stale_generation")
            return {"ok": False, "reason": "stale_generation"}
        if not accept(command):
            self.error("engine_rejected")
            return {"ok": False, "reason": "engine_rejected"}
        event = self._append("final", turn_id=command.get("turn_id"), generation_id=self.generation_id, idempotency_key=key)
        result = {"ok": True, "seq": event["seq"], "replayed": False}
        self._seen[key] = (sha, result)
        return result

    def seqs_are_contiguous(self) -> bool:
        return [e["seq"] for e in self.events] == list(range(1, len(self.events) + 1))


@dataclass
class Retention:
    """R7. Memory only. `deadline_ms` is when the session's content must be gone: a disconnect longer than the reconnect TTL, or the feedback display TTL after the end, whichever applies."""

    reconnect_ttl_ms: int = DEFAULT_RECONNECT_TTL_MS
    feedback_ttl_ms: int = 600_000
    state: str = "in_progress"
    disconnected_at_ms: int | None = None
    ended_at_ms: int | None = None
    content_cleared: bool = False

    def disconnect(self, now_ms: int) -> None:
        if self.state == "in_progress":
            self.state, self.disconnected_at_ms = "reconnecting", now_ms

    def reconnect(self, now_ms: int) -> bool:
        if self.state != "reconnecting":
            return False
        if now_ms - self.disconnected_at_ms > self.reconnect_ttl_ms:
            self._expire()
            return False
        self.state, self.disconnected_at_ms = "in_progress", None
        return True

    def end(self, now_ms: int) -> None:
        if self.state in ("in_progress", "reconnecting"):
            self.state, self.ended_at_ms = "ended", now_ms

    def tick(self, now_ms: int) -> None:
        if self.state == "reconnecting" and now_ms - self.disconnected_at_ms > self.reconnect_ttl_ms:
            self._expire()
        elif self.state == "ended" and now_ms - self.ended_at_ms > self.feedback_ttl_ms:
            self._expire()

    def _expire(self) -> None:
        self.state, self.content_cleared = "expired", True  # answers, turns, events and feedback are dropped; nothing is written anywhere
