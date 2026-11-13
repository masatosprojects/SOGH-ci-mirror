"""Sandbox quality set, part 2 (on top of rubric v1.2 and the guards): the follow-up question set, the separation of official information from AI practice material, and the consistency of a retry.

SYNTHETIC_ONLY: invented cases and invented answers; no examinee data. This set checks PROPERTIES THAT A MACHINE CAN CHECK. It says nothing about whether a follow-up is a GOOD question for a real examinee,
whether the rubric measures what an interviewer values, or whether a person improves: those need human evaluation (docs/SANDBOX_EVALUATION_HUMAN_ONLY_ITEMS.md), which has not been done."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import guards  # noqa: E402
from interview_sandbox.cases import CASES  # noqa: E402
from interview_sandbox.engine import InterviewSession  # noqa: E402


def run(case, answers, variant=0):
    s = InterviewSession(CASES[case](), variant=variant)
    s.start()
    out = []
    for a in answers:
        if s.state != "in_progress":
            break
        r = s.answer(s._open.turn_id, a, 20)
        out.append(r)
    return s, out


def interviewer_followups(s):
    return [t for t in s.turns if t.role == "interviewer" and t.origin == "follow_up_to_the_answer"]


# (answer, a word the follow-up must contain, why) — the follow-up set: each kind of weakness gets its own kind of question
SET = [
    ("いろいろな活動を頑張りました。", "具体的", "broad words with no number -> ask for a concrete scene or number"),
    ("文化祭の実行委員として、クラスの出し物を企画しました。", "役割", "an activity with no stated role -> ask for the person's own role"),
    ("地域の課題に関心があります。", "理由", "no reason given -> ask for the reason"),
    ("仲間が好きだからです。", "もう少し", "a very short answer that has a reason -> ask for the process"),
]


@pytest.mark.parametrize("answer,word,why", SET, ids=[x[2] for x in SET])
def test_each_kind_of_weakness_gets_its_own_kind_of_follow_up(answer, word, why):
    s, out = run("fiction-ac-1", [answer])
    f = interviewer_followups(s)
    assert f and word in f[0].text, (why, [t.text for t in f])
    a, b = f[0].quote
    assert answer[a:b] and answer[a:b] in f[0].text, "the follow-up quotes the person's own words at the recorded span"


def test_an_answer_with_a_concrete_number_a_role_and_a_reason_gets_no_follow_up_on_it():
    answer = "私は生徒会の副会長として、月に2回の意見箱の集計を担当しました。理由は、全員の声を数字で示したかったからです。結果として投稿数が3倍になりました。"
    s, out = run("fiction-ac-1", [answer])
    assert interviewer_followups(s) == [] and out[0].next_turn.origin != "follow_up_to_the_answer"


def test_the_same_words_are_never_asked_about_twice_and_the_limits_hold():
    answer = "いろいろな活動を頑張りました。いろいろな経験をしました。いろいろな人と話しました。"
    s, _ = run("fiction-ac-1", [answer] * 12)
    quotes = [t.quote for t in interviewer_followups(s)]
    assert len(quotes) == len(set(quotes)), "a span is asked about once"
    plan = s.context.plan
    assert len(interviewer_followups(s)) <= plan.max_total_followups
    per_question = {}
    for t in interviewer_followups(s):
        per_question[t.question_id] = per_question.get(t.question_id, 0) + 1
    assert max(per_question.values()) <= plan.max_followups_per_question


def test_every_follow_up_passes_the_guard_and_is_marked_as_following_the_persons_answer():
    s, _ = run("fiction-ac-1", [x[0] for x in SET])
    for t in interviewer_followups(s):
        assert guards.forbidden_claims_in(t.text) == [] and not guards.has_personal(t.text) and t.followup_of


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_briefing_keeps_official_conditions_unknowns_and_experience_in_their_own_sections(case):
    ctx = CASES[case]()
    text = InterviewSession(ctx).briefing().text()
    head = {"cond": text.index("【公式に確認できた条件】"), "unk": text.index("【公式には確認できていない事項"), "plan": text.index("【この練習の進め方】")}
    cond = text[head["cond"]:head["unk"]]
    unknown = text[head["unk"]:text.index("【受験経験の報告") if "【受験経験の報告" in text else head["plan"]]
    for f in ctx.official_facts:
        if f.status == "confirmed":
            assert f.label in cond and f.value in cond and f.label not in unknown
        else:
            assert f.label in unknown and f.label not in cond
    for r in ctx.experience_reports:
        assert r.summary not in cond and r.summary not in unknown and "公式情報ではありません" in text
    assert head["cond"] < head["unk"] < head["plan"]


@pytest.mark.parametrize("case", sorted(CASES))
def test_practice_questions_are_always_ai_practice_material_and_a_question_that_touches_a_fact_names_it(case):
    ctx = CASES[case]()
    s = InterviewSession(ctx)
    s.start()
    seen = []
    while s.state == "in_progress":
        t = s._open
        if t.origin != "follow_up_to_the_answer":
            seen.append(t)
            assert t.origin == "ai_practice_material"
        s.answer(t.turn_id, "探究活動で調べたことを、担当した聞き取りを中心に話しました。理由は、実際の声を知りたかったからです。", 30)
    assert seen and all(q.kind == "ai_practice_material" for q in ctx.practice_questions)


def test_an_unknown_fact_is_never_filled_in_by_a_practice_question_or_a_follow_up():
    ctx = CASES["fiction-rec-2"]()
    s, _ = run("fiction-rec-2", ["探究活動を行いました。"] * 4)
    unknown_labels = [f.label for f in ctx.unknown_facts()]
    spoken = " ".join(t.text for t in s.turns if t.role == "interviewer")
    for q in ctx.practice_questions:
        assert not q.basis_fact_ids or all(ctx.fact(i).status == "confirmed" for i in q.basis_fact_ids)
    assert unknown_labels and all(l not in spoken for l in unknown_labels)


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_same_answers_give_the_same_questions_and_the_same_feedback_on_every_run_and_after_a_retry(case):
    answers = ["いろいろな活動を頑張りました。", "文化祭の実行委員として企画しました。", "理由は仲間と成果を出したかったからです。"] * 3
    s1, _ = run(case, answers)
    s2, _ = run(case, answers)
    assert [t.text for t in s1.turns] == [t.text for t in s2.turns]
    for s in (s1, s2):
        if s.state == "in_progress":
            s.end()
    assert s1.feedback().text() == s2.feedback().text()
    r = s1.retry()
    assert r.context == s1.context and r.state == "setup" and r.variant == s1.variant
    r.start()
    again = [t.text for t in r.turns]
    assert again == [t.text for t in s1.turns][:len(again)]  # the retry starts with the same first question


def test_a_retry_does_not_carry_over_the_previous_answers():
    s1, _ = run("fiction-ac-1", ["高校の探究活動で地域の課題を調べました。"])
    if s1.state == "in_progress":
        s1.end()
    r = s1.retry()
    assert [t for t in r.turns if t.role == "candidate"] == [] and r.rejected_events == 0
