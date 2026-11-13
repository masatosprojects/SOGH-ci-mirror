"""Executable form of the MRIF-1 Phase 1 decisions R2 (event ledger), R3 (clock to elapsed seconds) and R7 (retention).
See docs/realtime-interview/PHASE1_MINIMAL_CONTRACTS_R1_R8.md. SYNTHETIC_ONLY, no I/O, no sockets.

These tests run the REFERENCE semantics in tests/phase1_reference.py (Claude's statement of the contract) together with the REAL, unchanged `InterviewSession`, so the contract is shown to be consistent with the existing engine.
They do not test Work's controller (not submitted at the time of writing); Work's PR is reviewed against the same cases. Passing accepts nothing: M1 stays 2/8, NOT ACCEPTED."""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import feedback  # noqa: E402
from interview_sandbox.cases import CASES  # noqa: E402
from interview_sandbox.engine import InterviewSession  # noqa: E402
from tests import phase1_reference as R  # noqa: E402

ANSWER = "探究活動で地域の課題を調べ、三人で役割を分けて取り組みました。"


# ------------------------------------------------------------------ R3: clock -> elapsed seconds
def test_r3_the_engine_total_never_differs_from_the_clock_floor_by_one_second_or_more():
    clock, bridge = R.Clock(), R.ElapsedBridge()
    for t in (999, 1_000, 1_999, 2_001, 2_999, 3_000, 61_999, 62_000):
        passed = bridge.next_elapsed_seconds(clock.read(t))
        assert passed >= 0
        assert bridge.engine_total_s == t // 1000  # no accumulated drift: 999 ms then 1 ms is 1 s, not 0 s and not 2 s


def test_r3_a_naive_per_answer_truncation_would_lose_time_and_the_bridge_does_not():
    clock, bridge = R.Clock(), R.ElapsedBridge()
    naive = 0
    last = 0
    for t in range(900, 9_001, 900):  # ten answers of 0.9 s: truncating each gives 0 s
        naive += (t - last) // 1000
        last = t
        bridge.next_elapsed_seconds(clock.read(t))
    assert naive == 0 and bridge.engine_total_s == 9


def test_r3_a_delta_over_the_engine_bound_is_carried_not_dropped():
    clock, bridge = R.Clock(), R.ElapsedBridge()
    first = bridge.next_elapsed_seconds(clock.read(5_000_000))  # 5000 s in one gap
    second = bridge.next_elapsed_seconds(clock.read(5_000_000))
    third = bridge.next_elapsed_seconds(clock.read(5_000_000))
    assert (first, second, third) == (3600, 1400, 0) and bridge.engine_total_s == 5000


@pytest.mark.parametrize("bad", [True, False, 1.5, "5", None, -1])
def test_r3_a_non_integer_or_negative_reading_is_refused(bad):
    with pytest.raises(ValueError):
        R.Clock().read(bad)


def test_r3_a_clock_that_goes_backwards_is_an_error_not_a_clamp():
    clock = R.Clock()
    clock.read(5_000)
    with pytest.raises(R.ClockRegression):
        clock.read(4_999)
    assert clock.read(5_000) == 5_000  # an equal reading is allowed (two events in the same millisecond)


def test_r3_the_bridge_feeds_the_real_engine_and_its_remaining_time_follows_the_clock():
    s = InterviewSession(CASES["fiction-ac-1"]())
    s.start()
    total = s.context.plan.total_seconds
    clock, bridge = R.Clock(), R.ElapsedBridge()
    t = 0
    for gap_ms in (12_400, 8_700, 15_900):
        t += gap_ms
        sec = bridge.next_elapsed_seconds(clock.read(t))
        result = s.answer(s._open.turn_id, ANSWER, sec)
        assert result.accepted
    assert s.remaining_seconds == total - t // 1000 == total - 37  # 12.4 + 8.7 + 15.9 = 37.0 s, no second lost


# ------------------------------------------------------------------ R3: the deadline (no timer thread; the controller is ticked)
def test_r3_the_grace_period_is_bounded():
    assert 0 <= R.DEFAULT_GRACE_MS <= R.MAX_GRACE_MS


def test_r3_an_unanswered_question_is_ended_by_the_controller_not_by_the_engine_clock():
    """The engine only evaluates time after an answer (`remaining_seconds == 0` inside `answer`). With no answer it never ends by itself: the controller must (R3 deadline rule). Documented here so a fake that waits forever is caught."""
    s = InterviewSession(CASES["fiction-ac-1"]())
    s.start()
    assert s.state == "in_progress" and s.remaining_seconds == s.context.plan.total_seconds  # nothing moved without an answer
    s.end()
    assert s.state == "ended"


# ------------------------------------------------------------------ R2: event ledger
def command(**kw):
    base = {"idempotency_key": "k1", "session_id": "s1", "turn_id": "t2", "generation_id": 1, "text": "回答", "elapsed_seconds": 5}
    base.update(kw)
    return base


def accepting(calls):
    def accept(cmd):
        calls.append(cmd["idempotency_key"])
        return True
    return accept


def test_r2_seq_is_assigned_at_commit_and_is_contiguous_whatever_order_the_producer_sent():
    ledger, calls = R.Ledger("s1"), []
    for k in ("k9", "k2", "k5"):
        assert ledger.commit(command(idempotency_key=k, turn_id=f"t-{k}"), accepting(calls))["ok"]
    assert [e["seq"] for e in ledger.events] == [1, 2, 3] and calls == ["k9", "k2", "k5"] and ledger.seqs_are_contiguous()


def test_r2_an_exact_replay_is_acknowledged_with_the_first_result_and_changes_nothing():
    ledger, calls = R.Ledger("s1"), []
    first = ledger.commit(command(), accepting(calls))
    again = ledger.commit(command(), accepting(calls))
    assert first["ok"] and again["ok"] and again["replayed"] is True and again["seq"] == first["seq"]
    assert calls == ["k1"] and len(ledger.events) == 1  # the engine was called once and nothing was appended twice


def test_r2_the_same_key_with_a_changed_payload_is_refused_and_the_first_result_stands():
    ledger, calls = R.Ledger("s1"), []
    ledger.commit(command(), accepting(calls))
    altered = ledger.commit(command(text="改ざんした回答"), accepting(calls))
    assert altered == {"ok": False, "reason": "idempotency_conflict"}
    assert calls == ["k1"] and [e["kind"] for e in ledger.events] == ["final", "error"] and ledger.seqs_are_contiguous()
    assert ledger.commit(command(), accepting(calls))["replayed"] is True  # the original is still acknowledged


def test_r2_a_stale_generation_is_refused_and_the_engine_is_not_called():
    ledger, calls = R.Ledger("s1"), []
    ledger.new_generation()
    out = ledger.commit(command(generation_id=1), accepting(calls))
    assert out == {"ok": False, "reason": "stale_generation"} and calls == []
    assert ledger.commit(command(idempotency_key="k2", generation_id=2), accepting(calls))["ok"]


def test_r2_a_foreign_session_and_a_missing_key_are_refused():
    ledger, calls = R.Ledger("s1"), []
    assert ledger.commit(command(session_id="s2"), accepting(calls))["reason"] == "foreign_session"
    assert ledger.commit(command(idempotency_key=""), accepting(calls))["reason"] == "missing_idempotency_key"
    no_key = command()
    del no_key["idempotency_key"]
    assert ledger.commit(no_key, accepting(calls))["reason"] == "missing_idempotency_key" and calls == []


def test_r2_an_engine_rejection_is_not_remembered_as_a_success():
    ledger = R.Ledger("s1")
    assert ledger.commit(command(), lambda c: False)["reason"] == "engine_rejected"
    assert ledger.commit(command(), lambda c: True)["ok"]  # the same key may be sent again after a refusal: a refusal is not committed


def test_r2_a_flood_of_bad_commands_cannot_grow_the_log_without_bound():
    ledger = R.Ledger("s1")
    for i in range(R.MAX_ERROR_EVENTS + 40):
        ledger.commit(command(session_id="other", idempotency_key=f"x{i}"), lambda c: True)
    assert len([e for e in ledger.events if e["kind"] == "error"]) == R.MAX_ERROR_EVENTS and ledger._suppressed_errors == 40
    assert ledger.seqs_are_contiguous()


def test_r2_the_real_engine_agrees_that_a_duplicate_turn_changes_nothing():
    s = InterviewSession(CASES["fiction-ac-1"]())
    s.start()
    turn_id = s._open.turn_id
    assert s.answer(turn_id, ANSWER, 5).accepted
    before = (len(s.turns), s.remaining_seconds, s.rejected_events)
    second = s.answer(turn_id, ANSWER, 5)  # the same turn answered again (a retransmission that slipped past the ledger)
    assert not second.accepted and second.rejected_reason == "duplicate_or_stale_turn"
    assert (len(s.turns), s.remaining_seconds) == before[:2] and s.rejected_events == before[2] + 1


# ------------------------------------------------------------------ R7: retention and reconnect
def test_r7_a_reconnect_inside_the_ttl_continues_and_after_the_ttl_clears_everything():
    r = R.Retention()
    r.disconnect(10_000)
    assert r.reconnect(10_000 + R.DEFAULT_RECONNECT_TTL_MS) and r.state == "in_progress" and not r.content_cleared
    r.disconnect(100_000)
    assert not r.reconnect(100_000 + R.DEFAULT_RECONNECT_TTL_MS + 1) and r.state == "expired" and r.content_cleared


def test_r7_feedback_is_kept_for_its_display_window_and_then_cleared():
    r = R.Retention()
    r.end(5_000)
    r.tick(5_000 + r.feedback_ttl_ms)
    assert r.state == "ended" and not r.content_cleared
    r.tick(5_000 + r.feedback_ttl_ms + 1)
    assert r.state == "expired" and r.content_cleared


def test_r7_an_ended_or_expired_session_cannot_be_reconnected():
    r = R.Retention()
    r.end(1_000)
    assert not r.reconnect(1_001)
    r2 = R.Retention()
    r2.disconnect(0)
    r2.tick(R.DEFAULT_RECONNECT_TTL_MS + 1)
    assert r2.state == "expired" and not r2.reconnect(R.DEFAULT_RECONNECT_TTL_MS + 2)


def test_r7_the_reference_and_the_engine_open_no_socket(monkeypatch):
    """The core (no UI) must work with sockets forbidden. A future loopback-only UI test is a different test with a different boundary."""
    def refuse(*a, **k):
        raise AssertionError("a socket was opened")
    monkeypatch.setattr(socket, "socket", refuse)
    s = InterviewSession(CASES["fiction-ac-1"]())
    s.start()
    s.answer(s._open.turn_id, ANSWER, R.ElapsedBridge().next_elapsed_seconds(R.Clock().read(3_000)))
    s.end()
    assert feedback.build_feedback(s)


# ------------------------------------------------------------------ R4: raw feedback with 0 or 1 answers
def test_r4_zero_and_one_answer_give_the_existing_cannot_judge_stage_with_no_invented_evidence():
    s = InterviewSession(CASES["fiction-ac-1"]())
    s.start()
    s.end()
    zero = feedback.build_feedback(s)
    assert zero.items and all(i.stage == feedback.NOT_ENOUGH for i in zero.items)
    assert all(not i.evidence for i in zero.items)  # no answer, so no span: Work must not invent one to satisfy a schema
    s1 = InterviewSession(CASES["fiction-ac-1"]())
    s1.start()
    s1.answer(s1._open.turn_id, ANSWER, 10)
    one = feedback.build_feedback(s1)
    consistency = [i for i in one.items if i.key == "consistency"]
    assert consistency and consistency[0].stage == feedback.NOT_ENOUGH and not consistency[0].evidence
