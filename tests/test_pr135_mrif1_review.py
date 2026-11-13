"""Independent review of Work's MRIF-1 Phase 1 core (PR #135: `research/inbox/work-interview-room/mrif.py`) against Claude's Phase 1 decisions (docs/realtime-interview/PHASE1_MINIMAL_CONTRACTS_R1_R8.md).

Claude-owned QA. DEFINED ONLY when Work's file exists (absent, not skipped, until PR #135 is merged or merged locally for a check). SYNTHETIC_ONLY: the three fictional cases, no I/O, no sockets (forbidden for every test here).
Work's own tests are not called. Passing accepts nothing: the PR stays Work's, M1 stays 2/8 NOT ACCEPTED."""
import ast
import os
import socket
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_MRIF_DIR") or REPO / "research" / "inbox" / "work-interview-room")
MRIF = WORK / "mrif.py"

if MRIF.exists():
    sys.path.insert(0, str(REPO / "sandbox"))
    sys.path.insert(0, str(WORK))
    sys.dont_write_bytecode = True
    from interview_sandbox import InterviewSession, get_case  # noqa: E402
    from interview_sandbox.feedback import NOT_ENOUGH, build_feedback  # noqa: E402
    from mrif import RealtimeInterviewController  # noqa: E402

    CASES = ("fiction-ac-1", "fiction-rec-2", "fiction-gen-3")
    ANSWER = "架空の探究活動で、私は三回の発表資料を担当しました。大学で情報を伝える方法を学びたいからです。"

    @pytest.fixture(autouse=True)
    def no_sockets(monkeypatch):
        def refuse(*a, **k):
            raise AssertionError("a socket was opened")
        monkeypatch.setattr(socket, "socket", refuse)

    def started(case=CASES[0]):
        room = RealtimeInterviewController.create(case)
        room.start()
        return room

    def cmd(room, text=ANSWER, elapsed=30, event="e1", key="k1"):
        return dict(session_id=room.session_id, generation_id=room.generation_id, turn_id=room.current_question().turn_id, event_id=event, idempotency_key=key, text=text, elapsed_seconds=elapsed)

    def candidate_count(room):
        return sum(1 for t in room.turns if t.role == "candidate")

    # ---------------------------------------------------------------- R1: the engine is the only source of questions
    @pytest.mark.parametrize("case", CASES)
    def test_r1_the_questions_and_the_feedback_equal_the_engine_used_directly(case):
        room, direct = started(case), InterviewSession(get_case(case))
        direct.start()
        n = 0
        while room.state == "in_progress" and n < 12:
            a = room.submit_final_answer(**cmd(room, ANSWER + str(n), 20, f"e{n}", f"k{n}"))
            b = direct.answer(direct._open.turn_id, ANSWER + str(n), 20)
            assert a.accepted == b.accepted
            n += 1
        assert room.state == direct.state == "ended" or n == 12
        if room.state != "ended":
            room.end()
            direct.end()
        assert [(t.role, t.text, t.question_id) for t in room.turns] == [(t.role, t.text, t.question_id) for t in direct.turns]
        assert room.feedback() == direct.feedback()

    def test_r1_only_the_public_engine_api_is_used():
        tree = ast.parse(MRIF.read_text(encoding="utf-8"))
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "_engine"}
        assert used <= {"start", "answer", "end", "feedback", "retry", "briefing", "state", "remaining_seconds", "end_reason", "turns"}, used

    def test_r1_the_core_imports_only_the_standard_library_and_the_sandbox():
        tree = ast.parse(MRIF.read_text(encoding="utf-8"))
        roots = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                roots |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0:
                roots.add(n.module.split(".")[0])
        assert roots <= {"__future__", "copy", "dataclasses", "hashlib", "json", "threading", "uuid", "interview_sandbox"}, roots

    # ---------------------------------------------------------------- R2: replay, conflict, generation, scope
    def test_r2_an_exact_replay_returns_the_first_result_and_the_engine_answers_once():
        room = started()
        first = room.submit_final_answer(**cmd(room))
        before = (candidate_count(room), room.remaining_seconds, len(room.turns))
        # the same operation sent again (same key, same payload) after the engine moved on: rebuild the command from the FIRST question
        c = dict(session_id=room.session_id, generation_id=room.generation_id, turn_id=first_question_id(room), event_id="e-resend", idempotency_key="k1", text=ANSWER, elapsed_seconds=30)
        again = room.submit_final_answer(**c)
        assert again.accepted is True and again.replayed is True and again.reason is None and again.result == first.result  # W-1 fixed at 53eb15f: a replay is an acknowledgement
        assert (candidate_count(room), room.remaining_seconds, len(room.turns)) == before

    def test_w1_a_replay_is_acknowledged_as_accepted_true_replayed_true_and_changes_nothing():
        """W-1 (Issue #75), FIXED at head 53eb15f and re-verified here: a replay is an acknowledgement of a committed operation, so `accepted=True` with `replayed=True`; the engine is not called again and nothing is appended.
        This test replaces `test_known_issue_pr135_a_replay_is_reported_as_accepted_false` (flipped to the contract value, not deleted)."""
        room = started()
        first = room.submit_final_answer(**cmd(room))
        before = (candidate_count(room), room.remaining_seconds, len(room.turns))
        c = dict(session_id=room.session_id, generation_id=room.generation_id, turn_id=first_question_id(room), event_id="e2", idempotency_key="k1", text=ANSWER, elapsed_seconds=30)
        again = room.submit_final_answer(**c)
        assert (again.accepted, again.replayed, again.reason) == (True, True, None) and again.result == first.result
        assert (candidate_count(room), room.remaining_seconds, len(room.turns)) == before

    def test_w2_a_replay_after_an_interruption_is_acknowledged_with_the_first_result():
        """W-2 (Issue #75), FIXED at head 53eb15f and re-verified here: the key is looked up BEFORE the generation, so a retransmission of an operation that already committed is acknowledged even if the generation moved on.
        This test replaces `test_known_issue_pr135_a_replay_after_an_interruption_is_refused_as_stale_not_acknowledged` (flipped to the contract value, not deleted)."""
        room = started()
        first = room.submit_final_answer(**cmd(room))
        assert first.accepted
        room.interrupt()
        before = (candidate_count(room), room.remaining_seconds, len(room.turns))
        c = dict(session_id=room.session_id, generation_id=0, turn_id=first_question_id(room), event_id="e-late", idempotency_key="k1", text=ANSWER, elapsed_seconds=30)
        out = room.submit_final_answer(**c)
        assert (out.accepted, out.replayed, out.reason) == (True, True, None) and out.result == first.result
        assert (candidate_count(room), room.remaining_seconds, len(room.turns)) == before

    def test_w2_an_unregistered_operation_with_the_old_generation_is_still_refused_after_the_move():
        room = started()
        assert room.submit_final_answer(**cmd(room)).accepted
        room.interrupt()
        c = dict(session_id=room.session_id, generation_id=0, turn_id=first_question_id(room), event_id="e-new", idempotency_key="k-new", text=ANSWER, elapsed_seconds=30)
        out = room.submit_final_answer(**c)
        assert (out.accepted, out.replayed, out.reason) == (False, False, "stale_generation") and candidate_count(room) == 1

    def test_w2_the_same_key_with_only_the_generation_changed_is_a_conflict_and_the_first_result_stands():
        room = started()
        first = room.submit_final_answer(**cmd(room))
        new_generation = room.interrupt()
        c = dict(session_id=room.session_id, generation_id=new_generation, turn_id=first_question_id(room), event_id="e-g", idempotency_key="k1", text=ANSWER, elapsed_seconds=30)
        out = room.submit_final_answer(**c)
        assert (out.accepted, out.reason) == (False, "idempotency_conflict") and candidate_count(room) == 1
        old = dict(c, generation_id=0, event_id="e-old")
        assert room.submit_final_answer(**old).result == first.result  # the original is still acknowledged

    @pytest.mark.parametrize("bad", [False, 0.0, "0", None, [0]])
    def test_pr137_a_generation_that_is_not_an_int_is_refused_even_when_it_equals_the_current_one(bad):
        """From PR #137: `False == 0` and `0.0 == 0` in Python; the current generation of a fresh room is 0."""
        room = started()
        out = room.submit_final_answer(**{**cmd(room), "generation_id": bad})
        assert (out.accepted, out.reason) == (False, "stale_generation") and candidate_count(room) == 0

    def test_pr137_a_newer_generation_than_the_current_one_is_refused():
        room = started()
        out = room.submit_final_answer(**{**cmd(room), "generation_id": room.generation_id + 5})
        assert (out.accepted, out.reason) == (False, "stale_generation") and candidate_count(room) == 0

    def test_r2_the_same_key_with_a_changed_text_is_refused_and_nothing_moves():
        room = started()
        room.submit_final_answer(**cmd(room))
        before = (candidate_count(room), room.remaining_seconds)
        c = dict(session_id=room.session_id, generation_id=room.generation_id, turn_id=first_question_id(room), event_id="e3", idempotency_key="k1", text=ANSWER + "改ざん", elapsed_seconds=30)
        out = room.submit_final_answer(**c)
        assert (out.accepted, out.reason) == (False, "idempotency_conflict") and (candidate_count(room), room.remaining_seconds) == before

    def test_r2_the_same_key_with_a_changed_elapsed_time_is_also_a_conflict():
        room = started()
        room.submit_final_answer(**cmd(room))
        c = dict(session_id=room.session_id, generation_id=room.generation_id, turn_id=first_question_id(room), event_id="e4", idempotency_key="k1", text=ANSWER, elapsed_seconds=31)
        assert room.submit_final_answer(**c).reason == "idempotency_conflict"

    def test_r2_one_event_id_cannot_carry_a_second_operation():
        room = started()
        room.submit_final_answer(**cmd(room))
        out = room.submit_final_answer(**cmd(room, event="e1", key="k2"))
        assert out.accepted is False and out.reason == "event_id_conflict" and candidate_count(room) == 1

    def test_r2_a_foreign_session_a_stale_generation_and_a_stale_turn_are_refused_without_effect():
        room = started()
        base = cmd(room)
        for change, reason in (({"session_id": "not-this-session"}, "foreign_session"), ({"generation_id": room.generation_id + 1}, "stale_generation"),
                               ({"turn_id": "someone-elses-turn"}, "stale_turn")):
            out = room.submit_final_answer(**{**base, **change, "event_id": "x" + reason, "idempotency_key": "x" + reason})
            assert (out.accepted, out.reason) == (False, reason)
        assert candidate_count(room) == 0 and room.state == "in_progress"

    def test_r2_after_an_interruption_the_old_generation_is_refused_and_the_new_one_is_accepted():
        room = started()
        old = cmd(room)
        new_generation = room.interrupt()
        assert room.submit_final_answer(**old).reason == "stale_generation" and candidate_count(room) == 0
        assert room.submit_final_answer(**{**old, "generation_id": new_generation}).accepted is True

    def test_r2_eight_threads_sending_the_same_operation_commit_it_once():
        room = started()
        c = cmd(room)
        results = []

        def send(i):
            results.append(room.submit_final_answer(**{**c, "event_id": f"e-t{i}"}))
        threads = [threading.Thread(target=send, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        # After W-1 every delivery is acknowledged (accepted=True); exactly one of them is the commit (replayed=False) and seven are replays, and the engine took the answer once.
        assert candidate_count(room) == 1 and all(r.accepted for r in results) and sum(1 for r in results if not r.replayed) == 1 and sum(1 for r in results if r.replayed) == 7

    def test_r2_a_partial_answer_never_reaches_the_engine():
        room = started()
        out = room.submit_partial(session_id=room.session_id, generation_id=room.generation_id, turn_id=room.current_question().turn_id, text="途中の文")
        assert out.accepted is True and candidate_count(room) == 0 and room.remaining_seconds == InterviewSession(get_case(CASES[0])).remaining_seconds

    # ---------------------------------------------------------------- R3: the clock (Phase 1 keeps the explicit integer path)
    @pytest.mark.parametrize("bad", [True, False, 1.5, "5", None, -1, 3601])
    def test_r3_an_elapsed_time_that_is_not_an_integer_from_0_to_3600_is_refused_and_changes_nothing(bad):
        room = started()
        with pytest.raises(ValueError):
            room.submit_final_answer(**cmd(room, elapsed=bad))
        assert candidate_count(room) == 0 and room.state == "in_progress"

    def test_r3_the_fake_clock_does_not_move_the_engine_time():
        room = started()
        before = room.remaining_seconds
        room.clock.advance_ms(600_000)
        assert room.remaining_seconds == before  # Work states this openly; the bridge of R3 is a later step
        with pytest.raises(ValueError):
            room.clock.set_ms(5)  # backwards
        with pytest.raises(ValueError):
            room.clock.advance_ms(True)

    # ---------------------------------------------------------------- R4: raw feedback
    def test_r4_zero_and_one_answer_give_the_existing_cannot_judge_stage_without_invented_evidence():
        room = started()
        room.end()
        zero = room.feedback()
        assert zero.items and all(i.stage == NOT_ENOUGH and not i.evidence for i in zero.items)
        one = started()
        one.submit_final_answer(**cmd(one))
        one.end()
        c = [i for i in one.feedback().items if i.key == "consistency"]
        assert c and c[0].stage == NOT_ENOUGH and not c[0].evidence

    # ---------------------------------------------------------------- R7 and privacy
    def test_r7_a_retry_is_a_new_session_that_inherits_no_answer():
        room = started()
        room.submit_final_answer(**cmd(room))
        room.end()
        again = room.retry()
        assert again.session_id != room.session_id and again.state == "setup" and candidate_count(again) == 0
        again.start()
        assert again.current_question().text == room.turns[0].text  # the same conditions again

    def test_r7_a_returned_object_cannot_be_used_to_change_the_session():
        room = started()
        room.turns.clear()
        room.briefing().conditions.append("改ざん")
        q = room.current_question()
        q.text = "別の質問"
        assert room.turns and room.current_question().text != "別の質問"

    def test_privacy_a_contact_string_in_an_answer_is_masked_in_the_stored_turn():
        room = started()
        room.submit_final_answer(**cmd(room, text=ANSWER + " 連絡は test.user@example.com まで。"))
        stored = [t.text for t in room.turns if t.role == "candidate"][0]
        assert "example.com" not in stored and "@" not in stored

    def test_privacy_the_config_cannot_enable_an_external_capability():
        from mrif import RealtimeSessionConfig
        for name, value in (("llm_provider", "x"), ("voice_provider", "x"), ("recording", "stored"), ("persist", True), ("external_network", True), ("real_database", True), ("camera", True), ("microphone", True)):
            with pytest.raises(ValueError):
                RealtimeSessionConfig(**{name: value})

    def first_question_id(room):
        return room.turns[0].turn_id
