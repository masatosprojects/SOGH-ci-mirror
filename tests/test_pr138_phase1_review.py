"""Independent review of Work's MRIF-1 R2 ledger, R3 clock and R7 expiry (PR #138: `research/inbox/work-interview-room/phase1.py`, stacked on PR #135) against Claude's Phase 1 decisions
(docs/realtime-interview/PHASE1_MINIMAL_CONTRACTS_R1_R8.md).

Claude-owned QA. DEFINED ONLY when Work's file exists (absent until PR #138 is merged, or merged locally for a check; set SOGH_WORK_MRIF_DIR to point at a directory that holds mrif.py and phase1.py).
SYNTHETIC_ONLY: the three fictional cases, no I/O, no sockets (forbidden for every test here). Work's own tests are not called. Passing accepts nothing: M1 stays 2/8, NOT ACCEPTED.
`known_issue` tests pin a CURRENT behaviour that differs from, or is undecided in, the contract; flip them when Work changes it (do not delete or skip them)."""
import gc
import json
import os
import socket
import sys
import threading
import weakref
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_MRIF_DIR") or REPO / "research" / "inbox" / "work-interview-room")

if (WORK / "phase1.py").exists():
    sys.path.insert(0, str(REPO / "sandbox"))
    sys.path.insert(0, str(WORK))
    sys.dont_write_bytecode = True
    from phase1 import Phase1Controller  # noqa: E402

    CASE = "fiction-ac-1"
    TEXT = "架空の発表で資料を3回見直しました。"
    SCHEMA = REPO / "docs" / "realtime-interview" / "schemas" / "realtime_contracts_v1.schema.json"

    @pytest.fixture(autouse=True)
    def no_sockets(monkeypatch):
        def refuse(*a, **k):
            raise AssertionError("a socket was opened")
        monkeypatch.setattr(socket, "socket", refuse)

    def room(**kw):
        c = Phase1Controller(CASE, **kw)
        c.start()
        return c

    def cmd(c, now, key="k1", **over):
        d = dict(session_id=c.session_id, turn_id=c.current_question().turn_id, generation_id=c.generation_id, idempotency_key=key, text=TEXT, now_ms=now)
        d.update(over)
        return d

    def candidates(c):
        return [t for t in c.turns if t.role == "candidate"]

    def contiguous(c):
        return [e["seq"] for e in c.events] == list(range(1, len(c.events) + 1))

    # ------------------------------------------------------------------ R2: the committed order
    def test_r2_seq_is_contiguous_from_one_across_answers_errors_and_state_changes_and_the_events_are_schema_valid():
        import jsonschema  # a missing package fails this test: in this repository a skip is not a pass (tests/test_regression_handoffs.py)
        c = room()
        d = cmd(c, 1000)
        assert c.answer(**d).accepted
        c.answer(**{**d, "session_id": "other"})          # error
        c.disconnect(1500)                                 # state_changed
        c.reconnect(2000)                                  # state_changed
        c.answer(**{**d, "text": "changed"})              # error (conflict)
        assert contiguous(c) and c.events[0]["seq"] == 1
        schema = json.loads(SCHEMA.read_text(encoding="utf8"))
        validator = jsonschema.Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/TurnEvent"})
        for e in c.events:
            validator.validate(e)
        assert {e["session_id"] for e in c.events} == {c.session_id} and TEXT not in json.dumps(c.events, ensure_ascii=False)

    def test_r2_error_events_stop_at_50_the_rest_are_only_counted_and_a_valid_answer_still_commits():
        c = room()
        d = cmd(c, 10)
        assert c.answer(**d).accepted
        for i in range(70):
            c.answer(**{**d, "idempotency_key": f"f{i}", "session_id": "other"})
        kinds = [e["kind"] for e in c.events]
        assert kinds.count("error") == 50 and c.suppressed_errors == 20 and contiguous(c)
        before = len(c.events)
        assert c.answer(**cmd(c, 4000, key="after-flood")).accepted and len(c.events) > before  # the cap is on errors, not on the ledger

    def test_r2_an_exact_replay_is_acknowledged_with_the_first_result_and_appends_nothing():
        c = room()
        d = cmd(c, 1000)
        first = c.answer(**d)
        snapshot = (c.events, c.turns, c.remaining_seconds, len(candidates(c)))
        for _ in range(3):
            again = c.answer(**d)
            assert (again.accepted, again.replayed, again.reason) == (True, True, None) and again.result == first.result
        assert (c.events, c.turns, c.remaining_seconds, len(candidates(c))) == snapshot

    def test_r2_a_replay_after_the_generation_moved_is_acknowledged_and_an_unregistered_old_generation_is_refused():
        c = room()
        d = cmd(c, 1000)
        assert c.answer(**d).accepted and c.generation_id == d["generation_id"] + 1  # the next question moved the generation
        before = c.events
        assert c.answer(**d).replayed and c.events == before
        out = c.answer(**{**d, "idempotency_key": "new-key"})
        assert (out.accepted, out.reason) == (False, "stale_generation")

    def test_r2_a_newer_generation_than_the_current_one_is_refused_without_effect():
        c = room()
        out = c.answer(**cmd(c, 100, generation_id=c.generation_id + 3))
        assert (out.accepted, out.reason) == (False, "stale_generation") and candidates(c) == []

    MISSING = object()

    @pytest.mark.parametrize("bad", [True, False, 1.0, "1", None, [1], -1, MISSING], ids=lambda v: "missing" if v is MISSING else repr(v))
    def test_r2_a_generation_that_is_not_the_current_int_is_refused_as_stale_generation_with_one_error_event_and_nothing_else_changes(bad):
        """F-138-2, RESOLVED at head bfc68cb (Work answered the finding): a non-int, negative or missing generation is a `stale_generation` RESULT (as in #135), not an exception, and is recorded as one bounded error event."""
        c = room()
        turns, remaining, n = c.turns, c.remaining_seconds, len(c.events)
        d = cmd(c, 100)
        if bad is MISSING:
            del d["generation_id"]
        else:
            d["generation_id"] = bad
        out = c.answer(**d)
        assert (out.accepted, out.replayed, out.reason) == (False, False, "stale_generation")
        assert len(c.events) == n + 1 and c.events[-1]["kind"] == "error" and c.events[-1]["text"] == "stale_generation" and contiguous(c)
        assert (c.turns, c.remaining_seconds) == (turns, remaining) and candidates(c) == []

    def test_r2_a_refused_generation_does_not_poison_the_key_and_the_later_valid_command_commits():
        c = room()
        assert c.answer(**cmd(c, 100, key="kz", generation_id=True)).reason == "stale_generation"
        assert c.answer(**cmd(c, 100, key="kz")).accepted and len(candidates(c)) == 1

    def test_known_issue_pr138_a_malformed_text_or_clock_reading_is_recorded_and_then_raises_valueerror():
        """Work's choice at bfc68cb: malformed text / `now_ms` leaves one `invalid_command` error event AND raises ValueError (a caller must catch it; the HTTP layer turns it into a 400).
        Pinned, not judged: the contract (R2) says only that a bad command is refused without effect on the engine. Flip if Work changes it."""
        c = room()
        n = len(c.events)
        with pytest.raises(ValueError):
            c.answer(**cmd(c, 100, text=""))
        with pytest.raises(ValueError):
            c.answer(**cmd(c, 100, key="k2", now_ms=True))
        assert len(c.events) == n + 2 and [e["text"] for e in c.events[-2:]] == ["invalid_command", "invalid_command"] and candidates(c) == [] and contiguous(c)

    def test_r2_the_same_key_with_a_changed_text_turn_or_generation_is_a_conflict_and_the_first_result_stands():
        c = room()
        d = cmd(c, 1000)
        first = c.answer(**d)
        assert c.answer(**{**d, "text": d["text"] + "改ざん"}).reason == "idempotency_conflict"
        assert c.answer(**{**d, "generation_id": d["generation_id"] + 1}).reason == "idempotency_conflict"
        assert c.answer(**{**d, "turn_id": "someone-elses-turn"}).reason == "idempotency_conflict"
        assert c.answer(**d).result == first.result and len(candidates(c)) == 1

    def test_r2_a_retransmission_with_a_later_clock_reading_is_a_replay_and_costs_nothing():
        """F-138-1, RESOLVED at head 88770061 (Work answered the finding): `now_ms` is the controller's clock reading, not part of the sender's logical operation, so it is out of the digest.
        The SAME operation (same key, text, turn, generation) re-sent later, with a later reading, is acknowledged with the first result; it appends nothing and uses none of the 50 error events."""
        c = room()
        d = cmd(c, 1000)
        first = c.answer(**d)
        snapshot = (c.events, c.turns, c.remaining_seconds)
        for later in (1001, 5000, 59_999):
            out = c.answer(**{**d, "now_ms": later})
            assert (out.accepted, out.replayed, out.reason) == (True, True, None) and out.result == first.result
        assert (c.events, c.turns, c.remaining_seconds) == snapshot and not any(e["kind"] == "error" for e in c.events)  # no error event consumed, no state moved by the later readings

    def test_r2_a_changed_text_turn_or_generation_is_still_a_conflict_even_with_a_later_clock_reading():
        c = room()
        d = cmd(c, 1000)
        c.answer(**d)
        for change in ({"text": d["text"] + "改ざん"}, {"generation_id": d["generation_id"] + 1}, {"turn_id": "someone-elses-turn"}):
            assert c.answer(**{**d, **change, "now_ms": 5000}).reason == "idempotency_conflict", change

    def test_r2_a_refusal_is_not_remembered_as_a_success():
        c = room()
        d = cmd(c, 100, key="kx", generation_id=c.generation_id + 1)
        assert c.answer(**d).reason == "stale_generation"
        assert c.answer(**d).reason == "stale_generation"  # refused again, not replayed
        assert c.answer(**cmd(c, 100, key="kx")).accepted  # the same key with the right generation is a first delivery

    def test_r2_eight_threads_sending_the_same_operation_commit_it_once_and_eight_different_keys_for_one_turn_commit_once():
        c = room()
        d = cmd(c, 1000)
        out = []
        threads = [threading.Thread(target=lambda: out.append(c.answer(**d))) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(candidates(c)) == 1 and sum(1 for r in out if r.accepted and not r.replayed) == 1 and sum(1 for r in out if r.replayed) == 7
        c = room()
        base = cmd(c, 1000)
        out = []
        threads = [threading.Thread(target=lambda i=i: out.append(c.answer(**{**base, "idempotency_key": f"k{i}"}))) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(candidates(c)) == 1 and sum(1 for r in out if r.accepted) == 1 and contiguous(c)

    def test_r2_after_the_session_ended_a_new_answer_is_refused_and_a_replay_of_a_committed_one_is_acknowledged():
        c = room()
        d = cmd(c, 1000)
        assert c.answer(**d).accepted
        late = dict(d, idempotency_key="late", generation_id=c.generation_id)  # current generation, a key never seen
        c.end(2000)
        assert c.state == "ended"
        assert c.answer(**late).accepted is False
        assert c.answer(**d).replayed is True

    # ------------------------------------------------------------------ R3: time
    def test_r3_the_engine_total_follows_the_clock_floor_not_a_per_answer_truncation():
        c = room()
        k = 0
        while c.current_question() is not None and k < 30:
            k += 1
            assert c.answer(**cmd(c, 900 * k, key=f"a{k}")).accepted
            assert sum(t.elapsed_seconds for t in candidates(c)) == (900 * k) // 1000  # never 0 for 0.9 s steps; never drifting by a second
        assert k >= 3

    def test_r3_999_ms_then_1000_ms_is_zero_then_one_second():
        c = room()
        c.answer(**cmd(c, 999))
        c.answer(**cmd(c, 1000, key="second"))
        assert [t.elapsed_seconds for t in candidates(c)] == [0, 1]

    @pytest.mark.parametrize("bad", [True, False, 1.5, -1, "5", None])
    def test_r3_a_bool_float_negative_or_non_integer_reading_is_refused_and_nothing_changes(bad):
        c = room()
        before = (c.events, c.remaining_seconds, c.state)
        with pytest.raises(ValueError):
            c.tick(bad)
        assert (c.events, c.remaining_seconds, c.state) == before

    def test_r3_a_clock_that_goes_backwards_is_an_error_but_the_same_millisecond_twice_is_fine():
        c = room()
        c.tick(100)
        c.tick(100)
        with pytest.raises(ValueError):
            c.tick(99)
        with pytest.raises(ValueError):
            c.answer(**cmd(c, 99, key="back"))
        assert candidates(c) == []

    def test_r3_a_backwards_reading_is_refused_after_the_end_and_after_the_expiry_too():
        """Found by mutation: removing the controller's own regression check changed nothing while the session ran (FakeClock refuses it too), but a session that had already ended took a backwards reading silently."""
        c = room(grace_ms=0)
        due = c.remaining_seconds * 1000
        c.tick(due + 1)
        assert c.state == "ended"
        with pytest.raises(ValueError):
            c.tick(due)
        assert c.tick(due + 1 + 600_001) == "expired"
        with pytest.raises(ValueError):
            c.tick(due)

    def test_r3_with_no_answer_the_controller_marks_the_deadline_once_keeps_the_grace_and_then_ends_without_a_fake_answer():
        c = room()
        deadline = c.remaining_seconds * 1000
        assert c.tick(deadline - 1) == "in_progress" and not any(e["text"] == "deadline_passed" for e in c.events)
        assert c.tick(deadline) == "in_progress" and c.tick(deadline + 10) == "in_progress"
        assert sum(e["text"] == "deadline_passed" for e in c.events) == 1
        assert c.tick(deadline + 120_000) == "in_progress"             # the grace is inclusive
        assert c.tick(deadline + 120_001) == "ended" and c.end_reason == "time_up"
        assert candidates(c) == [] and len(c.feedback().items) == 5   # the existing 5 aspects, from zero answers

    @pytest.mark.parametrize("offset,accepted", [(-1, True), (0, True), (120_000, True), (120_001, False)])
    def test_r3_an_answer_is_taken_up_to_the_end_of_the_grace_and_refused_after_it(offset, accepted):
        c = room()
        deadline = c.remaining_seconds * 1000
        out = c.answer(**cmd(c, deadline + offset))
        assert out.accepted is accepted and (accepted or out.reason == "answer_after_grace")
        assert (len(candidates(c)) == 1) is accepted

    @pytest.mark.parametrize("bad", [True, 1.5, -1, 600_001])
    def test_r3_the_grace_is_a_bounded_non_negative_integer(bad):
        with pytest.raises(ValueError):
            Phase1Controller(CASE, grace_ms=bad)

    def test_r3_a_retry_is_a_new_session_with_a_new_empty_ledger_and_inherits_no_answer():
        c = room(grace_ms=5000)
        c.answer(**cmd(c, 1000))
        c.end(2000)
        again = c.retry()
        assert again.session_id != c.session_id and again.grace_ms == 5000 and again.events == [] and candidates(again) == []

    def test_r3_pause_is_refused_as_not_supported_phase1_records_one_error_and_changes_nothing():
        """F-138-3, RESOLVED at head 88770061: contract R3 says pause is refused with `not_supported_phase1`; the method now exists and refuses."""
        c = room()
        c.answer(**cmd(c, 1000))
        question, remaining, turns, n = c.current_question(), c.remaining_seconds, c.turns, len(c.events)
        out = c.pause()
        assert (out.accepted, out.reason) == (False, "not_supported_phase1")
        assert len(c.events) == n + 1 and c.events[-1]["kind"] == "error" and c.events[-1]["text"] == "not_supported_phase1" and contiguous(c)
        assert (c.state, c.current_question(), c.remaining_seconds, c.turns) == ("in_progress", question, remaining, turns)

    def test_r3_a_flood_of_pause_requests_cannot_grow_the_log_past_the_error_cap_and_after_expiry_leaves_no_record():
        c = room()
        for _ in range(70):
            assert c.pause().reason == "not_supported_phase1"
        assert [e["kind"] for e in c.events].count("error") == 50 and c.suppressed_errors == 20 and contiguous(c)
        c.disconnect(1000)
        assert c.tick(1000 + 60_001) == "expired"
        out = c.pause()
        assert (out.accepted, out.reason) == (False, "session_expired") or out.accepted is False
        assert c.events == []  # a refusal on an expired session leaves no record

    # ------------------------------------------------------------------ R7: retention and expiry
    def test_r7_a_reconnect_at_exactly_the_ttl_is_taken_and_one_millisecond_later_everything_is_gone():
        c = room()
        c.disconnect(1000)
        assert c.reconnect(61_000).accepted and c.state == "in_progress"
        c = room()
        c.answer(**cmd(c, 500))
        c.disconnect(1000)
        assert c.tick(61_000) == "reconnecting" and c.tick(61_001) == "expired"
        assert c.reconnect(61_001).accepted is False

    def test_r7_a_second_connection_cannot_take_over_a_live_session():
        c = room()
        out = c.reconnect(100)
        assert (out.accepted, out.reason) == (False, "session_already_attached")

    def test_r7_the_feedback_is_kept_600_s_after_the_end_and_gone_one_millisecond_later():
        c = room(grace_ms=0)
        due = c.remaining_seconds * 1000
        c.tick(due + 1)
        assert c.state == "ended" and len(c.feedback().items) == 5
        assert c.tick(due + 1 + 600_000) == "ended" and c.reconnect(due + 1 + 600_000).accepted is False
        assert c.tick(due + 1 + 600_001) == "expired"
        with pytest.raises(RuntimeError):
            c.feedback()

    def test_r7_on_expiry_the_answers_turns_events_feedback_and_the_engine_are_discarded_and_nothing_can_be_revived():
        c = room()
        d = cmd(c, 1000)
        assert c.answer(**d).accepted
        engine = weakref.ref(c._engine)  # a private attribute, used only to prove the discard of the Python object; the public checks follow
        c.disconnect(2000)
        assert c.tick(2000 + 60_001) == "expired"
        gc.collect()
        assert engine() is None, "the engine (answers, turns, feedback) is still referenced after expiry"
        assert c.turns == [] and c.events == [] and c.end_reason is None and c.remaining_seconds == 0
        assert c._receipts == {} and c._event_ids == {}
        for call in (c.feedback, c.briefing):
            with pytest.raises(RuntimeError):
                call()
        with pytest.raises(RuntimeError):
            c.start(0)
        with pytest.raises(RuntimeError):
            c.retry()
        assert c.current_question() is None
        out = c.answer(**d)
        assert (out.accepted, out.reason) == (False, "session_expired") and c.events == []  # a refusal on an expired session leaves no record
        assert c.reconnect(2000 + 60_002).accepted is False

    def test_r7_an_answer_while_disconnected_is_refused_and_the_partial_text_is_dropped_at_disconnect():
        c = room()
        d = cmd(c, 100)
        assert c.submit_partial(session_id=c.session_id, generation_id=c.generation_id, turn_id=d["turn_id"], text="途中の文").accepted
        assert c.disconnect(200).accepted and c._partial is None
        out = c.answer(**{**d, "now_ms": 300})
        assert out.accepted is False and candidates(c) == []
        assert c.reconnect(400).accepted and c.answer(**cmd(c, 500, key="after-reconnect")).accepted  # a refusal while detached is not remembered

    def test_r7_the_core_opens_no_file_and_keeps_the_config_frozen():
        import ast
        source = (WORK / "phase1.py").read_text(encoding="utf8")
        tree = ast.parse(source)
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert imported <= {"copy", "hashlib", "json", "uuid", "mrif"}
        assert not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") in ("open", "exec", "eval") for n in ast.walk(tree))
