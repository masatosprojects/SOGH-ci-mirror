"""The clarity / specificity cases of the practice rubric (v1.2): what a rule can be held to, what is recorded only as an observation, and the history of every rubric change.
SYNTHETIC_ONLY. A pass here is NOT a validation of the rubric: nobody has rated these cases (`human_label` is blank), and no agreement with people is computed.
Also covers the defect found while building the table: an answer that contains a claim the tool must never make used to crash the session (the guard fired on the person's own words)."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from evaluation import evalset as ev  # noqa: E402
from evaluation.clarity_cases import CASES, C, D, G, M, B, run_answers  # noqa: E402
from interview_sandbox import guards  # noqa: E402
from interview_sandbox.feedback import RUBRIC_VERSION, STAGES, RUBRIC  # noqa: E402

BY_ID = {c.case_id: c for c in CASES}
ORDER = {B: 0, M: 1, G: 2}


def stages_of(case_id):
    _, fb = run_answers(BY_ID[case_id].answers)
    return {i.key: i.stage for i in fb.items}


def test_the_table_covers_every_kind_of_answer_the_review_asked_for():
    assert {c.category for c in CASES} >= {"数字だけ含む曖昧な回答", "活動・役割・結果が具体的な回答", "抽象語が多いが意味のある回答", "短いが十分明確な回答", "長いが曖昧な回答", "根拠のない自信や断定",
                                           "志望理由と活動内容が合わない回答", "回答を単に長くしただけの例", "個人情報やセンシティブな内容を含む例"}
    assert RUBRIC_VERSION == D and len({c.case_id for c in CASES}) == len(CASES)


def test_nobody_has_rated_these_cases_so_no_agreement_with_people_is_computed():
    assert all(c.human_label == {} for c in CASES)
    result = ev.agreement({}, {(c.case_id, k): v for c in CASES for k, v in stages_of(c.case_id).items()})
    assert result["status"] == "not_run" and "exact" not in result


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_the_recorded_stages_of_the_current_version_are_what_the_mock_gives(case):
    got = stages_of(case.case_id)
    assert {k: got[k] for k in case.stages_by_version[D]} == case.stages_by_version[D]


def test_a_number_alone_never_makes_a_vague_answer_clear_or_concrete():
    s = stages_of("numeric-vague")
    assert s["clarity"] != G and s["specificity"] != G


def test_a_short_concrete_answer_is_still_clear_and_the_fix_does_not_punish_it():
    assert stages_of("short-clear")["clarity"] == G and stages_of("concrete")["clarity"] == G
    assert stages_of("concrete")["specificity"] != B


def test_a_long_vague_first_sentence_is_not_clear_and_has_no_specificity():
    s = stages_of("long-vague")
    assert s["clarity"] != G and s["specificity"] == B


def test_a_bare_assertion_of_certainty_is_not_rated_clear_and_gives_no_credit_for_experience():
    s = stages_of("unfounded-confidence")
    assert s["clarity"] != G and s["experience"] == B and s["specificity"] == B


def test_activity_and_reason_that_share_nothing_are_marked_as_not_consistent():
    assert stages_of("activity-reason-mismatch")["consistency"] == B  # a rule can say "no shared words"; whether a person would see another link is human_only


def test_repeating_the_same_sentences_never_raises_any_stage():
    base, padded = stages_of("short-clear"), stages_of("padded")
    assert all(ORDER[padded[k]] <= ORDER[base[k]] for k in padded if base[k] in ORDER and padded[k] in ORDER)


def test_a_sensitive_sentence_is_never_quoted_back_or_probed():
    s, _ = run_answers(BY_ID["sensitive"].answers)
    asked = " ".join(t.text for t in s.turns if t.role == "interviewer")
    assert "家庭の事情" not in asked and "宗教" not in asked
    assert "sensitive_topic_not_probed" in {n.code for n in s.notices}


def test_cases_that_only_a_person_can_judge_say_so_and_make_no_claim_for_the_mock():
    human = [c for c in CASES if c.human_only]
    assert {"abstract-meaningful", "numeric-vague", "unfounded-confidence", "activity-reason-mismatch"} <= {c.case_id for c in human}
    assert BY_ID["abstract-meaningful"].objective == ()  # nothing about it is asserted as correct


# ------------------------------------------------------------------------------------------------ the history of the rubric: every change is a recorded choice
def test_every_difference_between_v1_1_and_v1_2_is_recorded_and_none_is_a_new_downgrade_of_a_concrete_answer():
    changed = {}
    for c in CASES:
        old, new = c.stages_by_version[C], c.stages_by_version[D]
        for k in new:
            if old.get(k) != new[k]:
                changed[(c.case_id, k)] = (old.get(k, old.get("error")), new[k])
    assert changed == {("numeric-vague", "clarity"): (G, M), ("unfounded-confidence", "clarity"): ("ValueError: the forbidden-claim guard fired on the person's own words", M),
                       ("unfounded-confidence", "specificity"): ("ValueError: the forbidden-claim guard fired on the person's own words", B)}
    worse = [key for key, (a, b) in changed.items() if a in ORDER and b in ORDER and ORDER[b] < ORDER[a]]
    assert worse == [("numeric-vague", "clarity")]  # the one intended downgrade: broad words with a bare number
    assert BY_ID["concrete"].stages_by_version[C] == BY_ID["concrete"].stages_by_version[D]  # a concrete answer was not touched


# ------------------------------------------------------------------------------------------------ the guard is for the tool's words, not the person's
CLAIMS = ["私は絶対に合格できますし、必ず成果を出せます。", "この面接は実際の入試と同じ形式だと聞きました。", "先輩から必ず聞かれる質問だと教わりました。", "合格確率80%と言われました。", "大学公認の対策だと思って参加しました。", "完全に再現できていると思います。"]


@pytest.mark.parametrize("claim", CLAIMS)
def test_an_answer_that_contains_a_forbidden_claim_does_not_crash_and_is_never_repeated_by_the_tool(claim):
    assert guards.forbidden_claims_in(claim)  # the input really contains one
    s, fb = run_answers((claim, "調査を担当しました。"))
    emitted = [t.text for t in s.turns if t.role == "interviewer"] + [fb.text()] + [n.text for n in s.notices]
    assert all(guards.forbidden_claims_in(x) == [] for x in emitted), "the tool repeated the person's claim"
    assert "claim_not_repeated" in {n.code for n in s.notices}
    cand = [t for t in s.turns if t.role == "candidate"][0]
    assert cand.text == claim  # the person's own words stay in the transcript as typed (they are theirs)
    assert s.state == "ended" and fb.answered == 2


def test_the_redacted_quote_keeps_its_place_in_the_answer_and_is_marked():
    s, fb = run_answers((CLAIMS[0],))
    items = [i for i in fb.items if i.evidence]
    assert items and all(i.evidence.redacted and i.evidence.text.startswith("（この部分は") for i in items)
    cand = s.candidate_turns()[0]
    assert all(0 <= i.evidence.start < i.evidence.end <= len(cand.text) for i in items)


def test_the_session_stays_usable_after_such_an_answer():
    from interview_sandbox import InterviewSession, get_case
    s = InterviewSession(get_case("fiction-ac-1"))
    turn = s.start()
    r = s.answer(turn.turn_id, CLAIMS[2], 30)
    assert r.accepted and r.next_turn is not None  # a neutral follow-up, not a wedged session
    assert not re.search(r"必ず|聞かれ", r.next_turn.text)
    r2 = s.answer(r.next_turn.turn_id, "調査の担当として、避難経路を調べました。", 30)
    assert r2.accepted


def test_the_tools_own_words_are_still_refused_when_they_make_a_forbidden_claim():
    with pytest.raises(ValueError, match="forbidden claim"):
        guards.assert_clean("これは実際の入試と同じ形式の練習です。")
