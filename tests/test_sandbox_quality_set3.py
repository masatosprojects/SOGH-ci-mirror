"""Sandbox quality set, part 3: planned areas are not dropped silently, a session that ended early says so, one case never speaks about another, and an unsure answer is not corrected with an assertion.

SYNTHETIC_ONLY: invented cases and answers; no examinee data. Machine-checkable properties only. Whether the questions are the right ones, whether a hedged answer deserves a higher or lower stage, and whether the feedback
helps a real examinee need human evaluation (docs/SANDBOX_EVALUATION_HUMAN_ONLY_ITEMS.md): not done, and nothing here claims it."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import guards  # noqa: E402
from interview_sandbox.cases import CASES  # noqa: E402
from interview_sandbox.engine import InterviewSession  # noqa: E402

GOOD = "探究活動で地域の課題を調べ、担当は聞き取りでした。理由は現場の声を知りたかったからです。大学では社会調査を学びたいです。"


def drive(case, answer, seconds=20, limit=40):
    s = InterviewSession(CASES[case]())
    s.start()
    n = 0
    while s.state == "in_progress" and n < limit:
        s.answer(s._open.turn_id, answer, seconds)
        n += 1
    return s


def first_questions(s):
    ids = [t.question_id for t in s.turns if t.role == "interviewer" and t.origin == "ai_practice_material"]
    by_id = {q.question_id: q for q in s.context.practice_questions}
    return [by_id[i].category for i in ids]


@pytest.mark.parametrize("case", sorted(CASES))
def test_with_enough_time_every_planned_area_is_asked_once_in_the_planned_order(case):
    s = drive(case, GOOD)
    assert s.end_reason == "all_questions_asked"
    assert first_questions(s) == list(s.context.plan.categories)


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_full_session_reports_no_unasked_area(case):
    s = drive(case, GOOD)
    assert not any("質問されなかった分野" in n for n in s.feedback().notes)


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_session_that_ends_early_names_the_areas_it_never_asked_and_warns_about_the_items_that_depend_on_them(case):
    s = InterviewSession(CASES[case]())
    s.start()
    # one answer that does not say what the person's part was, so the engine asks a follow-up and the session is still inside its first area when it ends
    # (GOOD says "担当は聞き取り": since the follow-up focus fix (PR #255) the role is no longer asked again, the session moves on, and for a case with two areas nothing would be left unasked)
    s.answer(s._open.turn_id, "探究活動に参加しました。", 20)
    s.end("user")
    asked = set(first_questions(s))
    unasked = [c for c in s.context.plan.categories if c not in asked]
    notes = " ".join(s.feedback().notes)
    assert unasked, "the test needs an early end"
    for c in unasked:
        assert c in notes
    listed = notes.split("質問されなかった分野：")[1].split("。")[0].split("、")
    assert listed == unasked and not (set(listed) & asked)
    assert "参考にしないでください" in notes and guards.forbidden_claims_in(notes) == []
    assert "質問されなかった分野" in s.feedback().text()


def test_the_time_up_case_found_by_this_set_is_reported():
    s = InterviewSession(CASES["fiction-ac-1"]())
    s.start()
    for _ in range(2):
        if s.state == "in_progress":
            s.answer(s._open.turn_id, GOOD, 400)
    assert s.end_reason == "time_up"
    notes = " ".join(s.feedback().notes)
    assert "学びたいこと" in notes and "終了の理由：time_up" in notes


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_case_never_speaks_about_another_universe_faculty_or_method(case):
    me = CASES[case]()
    s = drive(case, GOOD)
    spoken = InterviewSession(me).briefing().text() + "\n".join(t.text for t in s.turns if t.role == "interviewer") + s.feedback().text()
    for other_name, factory in CASES.items():
        if other_name == case:
            continue
        o = factory()
        assert o.university not in spoken and o.method not in spoken and o.case_id not in spoken, other_name
    assert me.university in InterviewSession(me).briefing().text() and me.method in InterviewSession(me).briefing().text()


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_briefing_states_the_case_year_and_the_fictional_label(case):
    me = CASES[case]()
    text = InterviewSession(me).briefing().text()
    assert "架空" in me.university and "架空" in text


HEDGED = ["たぶん探究活動をしたと思います。自信はありません。", "よく分かりませんが、地域の課題を調べたような気がします。", "間違っているかもしれませんが、聞き取りを担当しました。"]
ASSERTIVE_CORRECTION = re.compile(r"間違い(です|ました)|不正解|正しくありません|誤り(です|が)|嘘")


@pytest.mark.parametrize("answer", HEDGED)
def test_an_unsure_answer_is_never_told_it_is_wrong_and_never_gets_a_promise(answer):
    s = drive("fiction-ac-1", answer, limit=12)
    if s.state == "in_progress":
        s.end()
    text = s.feedback().text() + "\n".join(t.text for t in s.turns if t.role == "interviewer")
    assert not ASSERTIVE_CORRECTION.search(text) and guards.forbidden_claims_in(text) == []


@pytest.mark.parametrize("answer", HEDGED)
def test_the_feedback_for_an_unsure_answer_quotes_the_persons_own_words_and_adds_no_number_or_fact(answer):
    s = drive("fiction-ac-1", answer, limit=3)
    if s.state == "in_progress":
        s.end()
    rep = s.feedback()
    spoken = "".join(t.text for t in s.turns if t.role == "candidate")
    for item in rep.items:
        quote = re.search(r"「(.+?)」", item.quote or "") if getattr(item, "quote", None) else None
        if quote:
            assert quote.group(1) in spoken
    stated_numbers = set(re.findall(r"\d+", spoken))
    example_numbers = set(re.findall(r"\d+", " ".join(i.example for i in rep.items if getattr(i, "example", None))))
    assert example_numbers <= stated_numbers | {"1", "60", "2"}  # the rubric's own constants only (1 つ, 60 文字, 2 個)
