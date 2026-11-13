"""Experience-report contract v0: the shape, the three separate permissions, and the negative cases (reward-driven padding, duplicates and copies, a named interviewer, a conflict with the official
source, a trend drawn from a few reports). SYNTHETIC_ONLY: every report below is invented; nothing is collected or stored."""
import ast
import re
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from experience_report import contract as c  # noqa: E402
from experience_report.contract import Consent, Question, Report  # noqa: E402


def make(i=1, **over):
    base = dict(reporter_key=f"pseudonym-{i:04d}", university="架空第一大学", faculty="練習学部", method="架空総合型方式", fiscal_year=2026, phase="second_stage", interview_format="individual",
                duration_minutes=10, interviewers=2, questions=(Question("志望理由を教えてください。", certainty="sure"), Question("その研究のきっかけは？", is_followup=True, followup_of=0, certainty="unsure")),
                overall_certainty="unsure", consent=Consent(sogh_internal=True, given_at="2026-11-02"), age_band="18plus")
    base.update(over)
    return Report(**base)


# ------------------------------------------------------------------------------------------------ the shape and the quick form
def test_a_complete_invented_report_is_valid_and_the_quick_form_is_short_and_mostly_taps():
    assert c.validate(make()) == [] and c.review_flags(make()) == []
    assert len(c.STAGE1_FIELDS) <= 6 and c.stage1_needs_at_most_one_free_text()
    assert len(c.STAGE1_CHOICE_FIELDS) >= 3 and any("optional" in f for f in c.STAGE2_FIELDS)  # the extra effort is optional and the outcome is never required
    assert make(outcome=None).outcome is None


def test_the_three_permissions_are_independent_and_all_default_to_no():
    assert (Consent().school_internal, Consent().sogh_internal, Consent().public) == (False, False, False)
    only_public = make(consent=Consent(public=True, given_at="2026-11-02"))
    assert c.validate(only_public) == [] and not only_public.consent.sogh_internal  # public without an internal permission is the reporter's choice, and the reverse too
    internal_only = make(consent=Consent(sogh_internal=True, given_at="2026-11-02"))
    assert c.public_visibility(internal_only, [])[0] is False  # internal permission never publishes
    assert "consent_without_a_date" in c.validate(make(consent=Consent(sogh_internal=True)))
    assert c.validate(make(consent=Consent())) == []  # no consent at all is a valid (private, unused) record


def test_a_reward_is_not_tied_to_public_permission_or_to_the_amount_written():
    r = make(reward_requested=True, consent=Consent(sogh_internal=True, given_at="2026-11-02"))
    assert c.validate(r) == []  # a reward can be requested without allowing public display
    assert not hasattr(r, "reward_amount") and "reward" not in " ".join(c.STAGE1_FIELDS + c.STAGE2_FIELDS)  # the contract has no amount that grows with the text


# ------------------------------------------------------------------------------------------------ negative cases of one report
def test_unusable_reports_are_refused_with_a_reason_and_never_called_a_lie():
    cases = {
        "reporter_key_must_be_a_pseudonym": make(reporter_key="taro@example.com"),
        "no_question": make(questions=()),
        "too_many_questions": make(questions=tuple(Question(f"質問{n}です。") for n in range(21))),
        "duration_implausible": make(duration_minutes=900),
        "interviewer_count_implausible": make(interviewers=40),
        "fiscal_year_out_of_range": make(fiscal_year=1999),
        "personal_contact_in_text": make(free_text="連絡は 090-1234-5678 まで"),
        "link_in_text": make(free_text="詳細は https://example.com/x を見てください"),
        "question_0_empty_or_too_long": make(questions=(Question(" "),)),
        "question_1_follow_up_of_nothing": make(questions=(Question("最初の質問です。"), Question("続きです。", is_followup=True, followup_of=None))),
        "question_1_not_a_follow_up_but_has_a_parent": make(questions=(Question("最初の質問です。"), Question("別の質問です。", followup_of=0))),
        "university_missing": make(university=" "),
    }
    for code, report in cases.items():
        assert code in c.validate(report), code
    for code in c.validate(make(reporter_key="x")):
        assert "lie" not in code and "fraud" not in code and "false" not in code  # a code describes the record, never the person


def test_a_minor_cannot_share_beyond_sogh_without_a_guardian_and_this_rule_is_marked_proposed():
    minor = make(age_band="under18", consent=Consent(school_internal=True, given_at="2026-11-02"))
    assert "under18_needs_guardian_consent_to_share" in c.validate(minor)
    assert c.validate(replace(minor, guardian_consent=True)) == []
    assert "under18_needs_guardian_consent_to_share" in c.validate(make(age_band="under18", consent=Consent(public=True, given_at="2026-11-02")))
    assert "PROPOSED" in c.__doc__  # the age and guardian rules wait for the user and counsel


def test_padding_and_a_named_interviewer_are_flagged_for_a_human_not_rejected():
    padded = make(reward_requested=True, duration_minutes=10, questions=tuple(Question("志望理由は何ですか。" if n % 2 else f"活動{n}について。") for n in range(13)))
    flags = c.review_flags(padded)
    assert {"repeated_question_text", "implausible_volume_for_the_duration", "many_questions_with_a_reward_requested"} <= set(flags) and c.validate(padded) == []
    named = make(questions=(Question("田中教授が志望理由を聞きました。"),))
    assert "possible_named_interviewer" in c.review_flags(named)
    visible, labels = c.public_visibility(c.with_flags(replace(named, consent=Consent(public=True, given_at="2026-11-02")), c.review_flags(named)), [])
    assert visible is False  # held for review


# ------------------------------------------------------------------------------------------------ across reports
def test_duplicate_submissions_and_near_copies_are_found_but_different_answers_are_not_punished():
    a = make(1)
    dup = make(1, questions=(Question("別の質問です。"),))  # the same pseudonym, the same target and year
    copy = make(2, questions=a.questions)  # another pseudonym, the same two questions word for word
    different = make(3, questions=(Question("高校時代に力を入れたことは？"), Question("併願の状況を教えてください。")), interview_format="group", duration_minutes=25)
    flags = c.cross_checks([a, dup, copy, different])
    assert "duplicate_submission_same_reporter_and_target" in flags[0] and "duplicate_submission_same_reporter_and_target" in flags[1]
    assert "near_copy_of_another_reporters_text" in flags[2] and flags[3] == []  # a different format and different questions for one target are normal
    many = [make(9, fiscal_year=2020 + n % 6, faculty=f"学部{n}") for n in range(5)]
    assert all("one_reporter_many_reports" in v for v in c.cross_checks(many).values())


def test_a_difference_from_the_official_source_is_a_note_for_review_never_a_verdict():
    r = make()
    assert c.against_official(r, {"interview_present": "なし"}) == ["official_source_says_no_interview_review_needed"]
    assert c.against_official(r, {"interview_present": "あり", "interview_duration_minutes": "30"}) == ["duration_differs_from_the_official_figure_informational"]
    assert c.against_official(r, {"interview_present": "あり", "interview_duration_minutes": "10"}) == []
    assert c.against_official(r, {"interview_present": None}) == []  # an unknown official fact raises nothing


def test_public_visibility_needs_the_explicit_permission_a_usable_unflagged_report_and_carries_its_labels():
    shown = make(consent=Consent(public=True, given_at="2026-11-02"))
    ok, labels = c.public_visibility(shown, [])
    assert ok and "受験経験の報告（公式情報ではありません）" in labels and "未確認" in labels and "記憶は不確か" in labels
    ok2, labels2 = c.public_visibility(replace(shown, verification="corroborated", overall_certainty="sure"), [])
    assert ok2 and "未確認" not in labels2
    for blocked in (replace(shown, verification="withheld"), replace(shown, verification="rejected"), replace(shown, consent=Consent(sogh_internal=True, given_at="2026-11-02")), replace(shown, questions=())):
        assert c.public_visibility(blocked, [])[0] is False
    assert c.public_visibility(shown, ["near_copy_of_another_reporters_text"])[0] is False  # an open flag holds it back


def test_a_few_reports_never_make_a_trend_and_a_larger_set_still_states_its_selection():
    few = [make(i, fiscal_year=2026) for i in range(1, 5)]
    s = c.summarize(few)
    assert s["generalizable"] is False and s["formats"] is None and "傾向とは言えません" in s["statement"] and s["n"] == 4
    many = [make(i, outcome="passed" if i % 2 else None) for i in range(1, 8)]
    s2 = c.summarize(many)
    assert s2["generalizable"] is False and s2["formats"] == {"individual": 7} and "偏りがあり得ます" in s2["statement"] and "特定の質問が出る" in s2["statement"]
    assert s2["outcomes"]["not_given"] == 3 and s2["outcomes"]["passed"] == 4
    assert not re.search(r"頻出|傾向がある|よく出る|必ず", s["statement"] + s2["statement"])


# ------------------------------------------------------------------------------------------------ closed value sets are checked at run time (PR #93 / Issue #75 finding)
import pytest  # noqa: E402


@pytest.mark.parametrize("field,bad", [("interview_format", "fake"), ("interview_format", "Individual"), ("phase", "third_stage"), ("overall_certainty", "always"), ("verification", "verified"),
                                       ("age_band", "adult"), ("outcome", "accepted"), ("interview_format", 3), ("overall_certainty", ["sure"]), ("phase", True)])
def test_an_undefined_value_is_refused_by_the_contract_itself_not_only_by_an_adapter(field, bad):
    codes = c.validate(make(**{field: bad}))
    assert codes == [f"invalid_value_{field}"], codes  # a direct function call is checked, and the code names the field


def test_a_blank_or_missing_required_choice_is_a_different_problem_from_an_undefined_one():
    for field in ("interview_format", "phase", "overall_certainty", "verification", "age_band"):
        assert c.validate(make(**{field: ""})) == [f"missing_{field}"]
        assert c.validate(make(**{field: None})) == [f"missing_{field}"]


def test_unknown_and_declining_to_answer_are_values_and_are_never_refused():
    declined = make(interview_format="unknown", phase="unknown", overall_certainty="unknown", outcome="prefer_not_to_say",
                    questions=(Question("覚えている質問です。", certainty="unknown"),), duration_minutes=None, interviewers=None)
    assert c.validate(declined) == []
    assert c.validate(make(outcome=None)) == [] and make(outcome=None).outcome is None  # optional: left empty, never filled in


def test_an_undefined_certainty_on_a_question_names_the_question():
    bad = make(questions=(Question("志望理由は？", certainty="sure"), Question("きっかけは？", is_followup=True, followup_of=0, certainty="maybe")))
    assert c.validate(bad) == ["question_1_invalid_value_certainty"]
    assert c.validate(make(questions=(Question("質問です。", certainty=""),))) == ["question_0_missing_certainty"]


@pytest.mark.parametrize("consent", [Consent(public="false", given_at="2026-11-02"), Consent(school_internal=1, given_at="2026-11-02"), Consent(sogh_internal="true", given_at="2026-11-02"),
                                     Consent(public=None, given_at="2026-11-02")])
def test_a_permission_that_is_not_exactly_true_or_false_is_refused_and_never_read_as_a_permission(consent):
    codes = c.validate(make(consent=consent))
    assert codes and all(code.startswith("consent_") and code.endswith("_must_be_true_or_false") for code in codes)
    assert c.public_visibility(make(consent=consent), [])[0] is False


@pytest.mark.parametrize("over", [{"fiscal_year": "2026"}, {"fiscal_year": True}, {"duration_minutes": "10"}, {"duration_minutes": 10.5}, {"interviewers": True}, {"reward_requested": "no"}, {"guardian_consent": 0}])
def test_a_wrong_type_for_a_number_or_a_flag_is_refused_before_any_range_check(over):
    codes = c.validate(make(**over))
    assert codes and all(code.endswith(("_must_be_an_integer", "_must_be_true_or_false")) for code in codes)


def test_an_invalid_value_never_makes_a_report_visible_and_never_crashes_the_label_step():
    bad = make(overall_certainty="always", consent=Consent(public=True, given_at="2026-11-02"))
    visible, labels = c.public_visibility(bad, [])  # used to raise KeyError on the label lookup
    assert visible is False and "記憶の確かさは不明" in labels


def test_the_value_sets_are_the_literal_types_so_adding_a_value_in_one_place_cannot_be_forgotten():
    from typing import get_args
    assert set(c._REQUIRED_CHOICES["interview_format"]) == set(get_args(c.InterviewFormat)) and {"unknown", "other"} <= set(get_args(c.InterviewFormat))
    assert set(c._OPTIONAL_CHOICES["outcome"]) == set(get_args(c.Outcome)) and "prefer_not_to_say" in c._OPTIONAL_CHOICES["outcome"]


def test_the_duplicate_check_uses_only_the_pseudonym_the_target_and_the_question_text_never_the_outcome_or_the_age():
    a, b = make(1, outcome="passed", age_band="under18"), make(1, outcome="failed", age_band="18plus")  # one pseudonym, one target, two submissions
    assert c.cross_checks([a, b]) == {0: ["duplicate_submission_same_reporter_and_target"], 1: ["duplicate_submission_same_reporter_and_target"]}
    x, y = make(1, outcome="passed"), make(2, outcome="failed", questions=(Question("全く別の質問です。"),))  # different reporters: no outcome-based link
    assert c.cross_checks([x, y]) == {0: [], 1: []}


def test_a_missing_outcome_is_counted_as_not_given_never_as_a_failure():
    reports = [make(i, outcome=o) for i, o in enumerate([None, None, "prefer_not_to_say", "passed", None], 1)]
    s = c.summarize(reports)
    assert s["outcomes"]["not_given"] == 3 and s["outcomes"]["failed"] == 0 and s["outcomes"]["prefer_not_to_say"] == 1


def test_the_contract_module_touches_no_network_file_or_database():
    tree = ast.parse((ROOT / "sandbox" / "experience_report" / "contract.py").read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert not (mods & {"sqlite3", "socket", "urllib", "http", "requests", "subprocess", "shutil", "tempfile", "os", "pathlib", "json"}), mods
