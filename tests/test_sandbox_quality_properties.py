"""Properties of the practice feedback that a rule CAN be held to (SYNTHETIC_ONLY; no person has rated anything, so none of this is evidence that the feedback is good):
an improvement example never brings in a fact the person did not state, an improved answer is never rated lower than the weaker answer it improves, the same answers always give the same feedback,
and every retry comparison treats 'cannot judge' as neither a gain nor a loss. What stays human-only is listed in sandbox/evaluation/clarity_cases.py (`human_only`)."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from evaluation import evalset as ev  # noqa: E402
from evaluation.clarity_cases import CASES, G, M, B, run_answers  # noqa: E402
from interview_sandbox.feedback import NOT_ENOUGH, RUBRIC, STAGES, compare  # noqa: E402

ORDER = {B: 0, M: 1, G: 2}
ALL_ANSWER_SETS = [("case:" + c.case_id, c.answers) for c in CASES] + [("script:" + n, ev.SCRIPTS[n][1]) for n in ev.SCRIPTS]


@pytest.mark.parametrize("name,answers", ALL_ANSWER_SETS, ids=[x[0] for x in ALL_ANSWER_SETS])
def test_an_improvement_example_never_adds_a_number_or_a_fact_the_person_did_not_state(name, answers):
    session, feedback = run_answers(answers)
    said = " ".join(t.text for t in session.candidate_turns())
    for item in feedback.items:
        example = item.improvement
        outside_quote = example.replace(item.evidence.text, "") if item.evidence and not item.evidence.redacted else example
        instruction = re.sub(r"\d+\s*つ|\d+\s*〜\s*\d+\s*文|\d+\s*文|\d+\s*問", "", outside_quote)  # "choose 1 thing", "answer in 2-3 sentences": an instruction about the task, not a fact about the person
        invented_digits = set(re.findall(r"\d+", instruction)) - set(re.findall(r"\d+", said))
        assert not invented_digits, f"{name}/{item.key}: the example adds the number(s) {invented_digits}"
        assert "〇" in example or "◇" in example or item.stage == STAGES[2] or not item.evidence, f"{name}/{item.key}: an example without blanks for the facts"


@pytest.mark.parametrize("weak,better,keys", [
    ("numeric-vague", "concrete", ("clarity", "specificity", "experience")),
    ("long-vague", "short-clear", ("clarity",)),
    ("unfounded-confidence", "concrete", ("clarity", "specificity", "experience")),
])
def test_an_improved_answer_is_never_rated_lower_than_the_weaker_one_it_improves(weak, better, keys):
    by_id = {c.case_id: c for c in CASES}
    a = {i.key: i.stage for i in run_answers(by_id[weak].answers)[1].items}
    b = {i.key: i.stage for i in run_answers(by_id[better].answers)[1].items}
    for key in keys:
        assert ORDER[b[key]] >= ORDER[a[key]], f"{key}: {weak}={a[key]} but the improved answer {better}={b[key]}"


def test_the_same_answers_always_give_the_same_feedback_text():
    for name, answers in ALL_ANSWER_SETS:
        assert run_answers(answers)[1].text() == run_answers(answers)[1].text(), name


def test_every_answer_set_is_rated_with_all_five_items_a_known_stage_and_the_limits_are_always_shown():
    for name, answers in ALL_ANSWER_SETS:
        feedback = run_answers(answers)[1]
        assert [i.key for i in feedback.items] == [k for k, _ in RUBRIC], name
        assert all(i.stage in STAGES or i.stage == NOT_ENOUGH for i in feedback.items), name
        assert "練習用のルーブリック" in feedback.text() and "合格・不合格" in feedback.text(), name


def test_a_retry_that_cannot_be_judged_on_either_side_is_never_reported_as_a_gain_or_a_loss():
    one = run_answers(("私は防災を研究しました。",))[1]  # one answer: 'consistency' cannot be judged
    two = run_answers(("私は防災を研究しました。", "調査を担当しました。防災の研究から学びたいです。"))[1]
    result = compare(one, two)
    assert result["consistency"] == "比較できません"
    assert all(v in ("改善", "変わらず", "低下", "比較できません") for v in result.values())


def test_feedback_quotes_are_the_persons_own_words_at_the_recorded_place_or_are_marked_redacted():
    for name, answers in ALL_ANSWER_SETS:
        session, feedback = run_answers(answers)
        by_id = {t.turn_id: t for t in session.turns}
        for item in feedback.items:
            e = item.evidence
            if e is None:
                continue
            turn = by_id[e.turn_id]
            assert turn.role == "candidate" and 0 <= e.start < e.end <= len(turn.text), name
            assert e.redacted or turn.text[e.start:e.end] == e.text, f"{name}/{item.key}: the quote is not what the person wrote"


def test_no_follow_up_asks_about_a_sensitive_sentence_or_quotes_personal_information():
    session, _ = run_answers(("家庭の事情で苦労しました。連絡先は taro@example.com です。私は部活で研究に取り組みました。", "宗教的な理由で参加できない行事もありました。"))
    asked = " ".join(t.text for t in session.turns if t.role == "interviewer")
    assert "家庭の事情" not in asked and "宗教" not in asked and "taro" not in asked and "example.com" not in asked
