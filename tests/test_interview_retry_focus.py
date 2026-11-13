"""SELF_TEST (Claude, the author) of the feedback-informed retry of the interview sandbox.  SYNTHETIC_ONLY; a deterministic mock; not an independent QA, not an acceptance.

Step 7 of the practice flow: "use the feedback and try again".  A retry keeps the same conditions (case, plan, questions, profile) and now also carries ONE focus: the weakest judged item of
the earlier feedback with its improvement example.  After the retry the change is stated plainly; only a judged improvement is called an improvement.
"""
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import InterviewSession, compare, compare_text, focus_of, get_case  # noqa: E402
from interview_sandbox import feedback as fb  # noqa: E402
from interview_sandbox import profile as prof  # noqa: E402
from interview_sandbox.feedback import STAGES  # noqa: E402

VAGUE = ["いろいろ頑張りました。", "とても楽しかったです。", "なんとなく関心があります。"]
GOOD = ["毎週土曜日に図書館で絵本を選び、案内の掲示を作り直したところ、参加者が12人から18人に増えました。私は選定係として働きました。",
        "掲示の文字を大きくしたのは、小さな子どもにも読んでもらうためです。",
        "大学では情報の探し方を研究し、誰でも使える案内を作りたいと考えています。"]
PROFILE = prof.build_profile("私は地域の図書館で子どもの読み聞かせを手伝った経験から、情報の届け方に関心を持ちました。大学では、誰もが使いやすい情報の探し方を研究したいと考えています。",
                             [{"title": "地域図書館の読み聞かせボランティア", "description": "毎週土曜日に絵本の選定を手伝いました。"}])


def run(s, answers, secs=20):
    turn, n = s.start(), 0
    while turn is not None and s.state == "in_progress" and n < 40:
        r = s.answer(turn.turn_id, answers[n % len(answers)], secs)
        turn, n = r.next_turn, n + 1
    if s.state != "ended":
        s.end("closed")
    return s


def first(case="fiction-ac-1", answers=VAGUE, profile=PROFILE):
    return run(InterviewSession(get_case(case), profile=profile), answers)


def test_R1_the_focus_is_the_weakest_judged_item_with_its_own_improvement_example():
    s = first()
    report = s.feedback()
    f = focus_of(report)
    judged = [i for i in report.items if i.stage in STAGES]
    assert f is not None and f.stage == min((i.stage for i in judged), key=STAGES.index)
    assert f.improvement and f in report.items
    order = [k for k, _ in fb.RUBRIC]
    ties = [i for i in judged if i.stage == f.stage]
    assert f.key == min(ties, key=lambda i: order.index(i.key)).key       # ties go to the rubric order


def test_R2_a_retry_with_the_report_carries_the_focus_and_the_same_conditions():
    s = first()
    report = s.feedback()
    again = s.retry(report)
    assert again.focus == focus_of(report) and again.profile is PROFILE and again.state == "setup"
    text = again.briefing().text()
    assert "前回の講評を踏まえた今回の練習の焦点" in text and again.focus.label in text and again.focus.improvement in text
    run(again, GOOD)
    assert again.turns[0].text == s.turns[0].text                          # the same first question: the same conditions
    assert "焦点" not in s.retry().briefing().text()                       # a plain retry has no focus


def test_R3_nothing_to_focus_on_when_nothing_was_judged_or_everything_is_already_good():
    s = InterviewSession(get_case("fiction-ac-1"), profile=PROFILE)
    s.start()
    s.end("user")
    empty = s.feedback()                                                   # no answer: nothing could be judged
    assert focus_of(empty) is None and s.retry(empty).focus is None
    top = fb.FeedbackReport("fiction-ac-1", fb.RUBRIC_VERSION, [fb.RubricItem(k, label, STAGES[-1], "x", None, "y") for k, label in fb.RUBRIC], 3, "all_questions_asked")
    assert focus_of(top) is None                                           # every item is already at the top stage: nothing to focus on


def test_R4_a_report_of_another_case_or_another_type_is_refused():
    s = first("fiction-ac-1")
    other = first("fiction-rec-2").feedback()
    for bad in (other, "feedback", {"items": []}, object()):
        with pytest.raises(ValueError):
            s.retry(bad)


def test_R5_the_comparison_names_the_focus_and_calls_only_a_judged_improvement_an_improvement():
    s = first()
    before = s.feedback()
    focus = focus_of(before)
    better = run(s.retry(before), GOOD).feedback()
    same = run(s.retry(before), VAGUE).feedback()
    t_better, t_same = compare_text(before, better, focus), compare_text(before, same, focus)
    assert compare(before, better)[focus.key] == "改善" and f"前回の練習の焦点「{focus.label}」：改善" in t_better   # specific, numbered answers do improve the focus item
    assert f"前回の練習の焦点「{focus.label}」：変わらず" in t_same and "改善" not in t_same.split("\n", 2)[1]   # the same vague answers: "no change", never "improved"
    assert "合否" in t_better                                              # it says that this is not a pass/fail or a measure of the real interview
    empty = InterviewSession(get_case("fiction-ac-1"))
    empty.start()
    empty.end("user")
    assert "改善" not in compare_text(empty.feedback(), empty.feedback()).replace("練習用", "")   # not judged on either side: "比較できません"


def test_R6_the_focus_text_repeats_only_the_persons_own_words_and_no_claim_of_the_tool():
    claim = ["私は必ず合格できます。", "いろいろ頑張りました。"]
    s = first(answers=claim)
    again = s.retry(s.feedback())
    text = again.briefing().text()                                         # briefing() asserts that nothing forbidden is said
    assert "合格できます" not in text


def test_R7_the_retry_with_a_focus_keeps_everything_in_memory_and_logs_no_words(caplog):
    with caplog.at_level(logging.DEBUG):
        s = first()
        again = s.retry(s.feedback())
        again.briefing()
        run(again, GOOD)
        compare_text(s.feedback(), again.feedback(), again.focus)
    for word in ("読み聞かせ", "図書館", "掲示", "いろいろ頑張りました", "選定係"):
        assert word not in caplog.text
    assert not hasattr(again, "save") and again.config.persist is False
