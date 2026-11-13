"""Issue #12: a record may say which selection stage it is about (`stage`: 1, 2 or "final"), so a sentence about
"第1次選考の合格者には、面接を…" cannot be turned into "第2次" without being noticed even when the cited fact_key
(interview, ...) has no fixed stage. Optional: records without `stage` behave exactly as before.
"""
import pytest

from src.article_qa.evaluate import evaluate_article
from src.verify.fact_registry import get_registry
from src.verify.strict_claims import check_article_strict

REGISTRY = get_registry()
CLAIM = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}


_ABSENT = object()


def interview(stage=_ABSENT, **extra):
    record = {"evidence_id": "EV-I", "university": "〇〇大学", "faculty": "環境学部", "department": None, "admission_method": "夏秋AO入試",
              "fiscal_year": 2027, "fact_key": "interview", "value": {"minutes": 30, "type": "allocated_time_window_not_net_question_time"},
              "scope": "target_admission_cycle", "source_url": "https://example.ac.jp/x", "retrieved_at": "2026-11-01",
              "source_pdf_sha256": "0" * 64, "source_sha256": "0" * 64, "source_kind": "pdf", "proofs": [{"page": 3, "quote": "面接は30分"}]}
    if stage is not _ABSENT:
        record["stage"] = stage
    record.update(extra)
    return record


def stage_issues(sentence, record):
    text = f"# 〇〇大学\n\n{sentence}[EV-I]\n"
    return [i for i in check_article_strict(text, CLAIM, {"EV-I": record}) if i.category == "stage_mismatch"]


S2 = "第2次選考の合格者には、面接を一人30分程度行います。"
S1 = "第1次選考の合格者には、面接を一人30分程度行います。"


def test_a_record_with_stage_2_accepts_the_second_stage_and_rejects_the_first():
    assert stage_issues(S2, interview(2)) == []
    assert stage_issues(S1, interview(2))


def test_a_record_with_stage_1_rejects_the_second_stage():
    assert stage_issues(S1, interview(1)) == [] and stage_issues(S2, interview(1))


def test_without_stage_nothing_changes_for_this_key():
    assert stage_issues(S1, interview()) == [] and stage_issues(S2, interview()) == []


def test_final_is_accepted_and_does_not_check_the_ordinal():
    assert stage_issues(S1, interview("final")) == [] and stage_issues(S2, interview("final")) == []


def test_a_key_with_a_fixed_stage_is_still_checked_without_the_record_field():
    record = interview()
    record.update(fact_key="first_stage_result", value={"date": "2026-10-08", "time": "11:00"})
    assert stage_issues("第2次選考の結果発表は2026年10月8日 11:00です。", record)


def issues_of(record):
    return {(i.severity, i.category) for i in REGISTRY.check_record(record, "EV-I")}


@pytest.mark.parametrize("bad", [0, 3, "second", None, True, 1.5, [], [1, 3], [True]])
def test_an_invalid_stage_is_a_registry_error(bad):
    assert ("error", "stage_invalid") in issues_of(interview(bad))


@pytest.mark.parametrize("stage", [1, 2, "final", [1, 2], [1, "final"]])
def test_valid_stages_are_accepted_by_the_registry(stage):
    assert not [i for i in issues_of(interview(stage)) if i[0] == "error"]


def test_a_stage_that_contradicts_the_fixed_stage_of_the_key_is_a_registry_error():
    record = interview(2)
    record.update(fact_key="first_stage_result", value={"date": "2026-10-08", "time": "11:00"})
    assert ("error", "stage_conflict") in issues_of(record)
    record["stage"] = 1
    assert ("error", "stage_conflict") not in issues_of(record)


def test_the_check_is_part_of_the_article_qa():
    text = f"# 〇〇大学\n\n作業基準日：2026-11-01。\n\n{S1}[EV-I]\n\n最新情報は大学公式サイトでご確認ください。\n"
    wrong = evaluate_article("a", text, CLAIM, {"EV-I": interview(2)}, reference_date="2026-11-01", require_as_of=True)
    assert any(f["category"] == "stage_mismatch" for f in wrong.findings)
    right = evaluate_article("a", text, CLAIM, {"EV-I": interview(1)}, reference_date="2026-11-01", require_as_of=True)
    assert not any(f["category"] == "stage_mismatch" for f in right.findings)


def test_a_list_of_stages_allows_each_of_them_and_nothing_else():
    assert stage_issues(S1, interview([1, 2])) == [] and stage_issues(S2, interview([1, 2])) == []
    assert stage_issues("第3次選考の合格者には、面接を一人30分程度行います。", interview([1, 2]))
    assert stage_issues(S2, interview([1]))


def test_the_correct_wording_for_an_interview_after_the_first_stage_needs_the_stage_the_sentence_names():
    # "第1次選考の合格者には面接を行います" names stage 1 (the stage whose passers are interviewed): the record must say [1] (or [1, 2]).
    # With stage=2 (the stage the interview BELONGS to) this correct sentence would be reported — see docs/STRICT_VALIDATION.md.
    assert stage_issues(S1, interview([1])) == [] and stage_issues(S1, interview(2))


# ===================================================================== test base for Work's real assignment (Issue #12)
import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

from src.regression.handoffs import find_exports  # noqa: E402

S2_CORRECT = "第2次選考では、面接を一人30分程度行います。"
BOTH = "第1次選考の合格者は、第2次選考で面接を一人30分程度受けます。"


def test_first_to_second_and_second_to_first_conversions_are_each_caught():
    assert stage_issues(S2, interview([1])) and stage_issues(S1, interview([2]))
    assert stage_issues(S1.replace("第1次", "第2次"), interview([1])) and stage_issues(S2_CORRECT.replace("第2次", "第1次"), interview([2]))


def test_the_correct_first_stage_and_second_stage_sentences_pass_with_their_own_stage():
    assert stage_issues(S1, interview([1])) == [] and stage_issues(S2_CORRECT, interview([2])) == []


def test_a_sentence_that_names_both_stages_needs_both_in_the_record():
    assert stage_issues(BOTH, interview([1, 2])) == []
    assert stage_issues(BOTH, interview([1])) and stage_issues(BOTH, interview([2]))


def test_full_width_and_the_other_wording_of_the_ordinal_are_read_the_same():
    assert stage_issues("第２次選考の合格者には、面接を一人30分程度行います。", interview([1]))
    assert stage_issues("２次選考では、面接を一人30分程度行います。", interview([1]))
    assert stage_issues("２次選考では、面接を一人30分程度行います。", interview([2])) == []


def test_a_broad_stage_on_a_key_with_a_fixed_stage_is_a_warning_not_an_error():
    record = interview([1, 2])
    record.update(fact_key="first_stage_result", value={"date": "2026-10-08", "time": "11:00"})
    found = issues_of(record)
    assert ("warning", "stage_overbroad") in found and not [i for i in found if i[0] == "error"]
    record["stage"] = [1]
    assert ("warning", "stage_overbroad") not in issues_of(record)
    record["stage"] = 1
    assert ("warning", "stage_overbroad") not in issues_of(record)


def test_known_limit_two_relations_in_one_sentence_are_checked_as_one_set_of_ordinals():
    """Documented limit, not a promise: when ONE sentence cites a stage-1 and a stage-2 record, the ordinals it may use are the
    union, so swapping which date belongs to which stage inside that sentence is not seen (the dates themselves still are)."""
    first = interview(); first.update(evidence_id="EV-1", fact_key="first_stage_result", value={"date": "2026-10-08", "time": "11:00"})
    second = interview(); second.update(evidence_id="EV-2", fact_key="second_stage_date", value={"dates": ["2026-10-24"], "selection": "one_of_not_both"})
    swapped = "第2次選考の結果発表は2026年10月8日 11:00[EV-1]、第1次選考日は2026年10月24日[EV-2]です。"
    text = f"# 〇〇大学\n\n{swapped}\n"
    found = [i for i in check_article_strict(text, CLAIM, {"EV-1": first, "EV-2": second}) if i.category == "stage_mismatch"]
    assert found == []


def test_a_record_without_stage_behaves_exactly_as_before_for_every_real_sentence():
    """Backward compatibility on the real deliveries: no record carries `stage` yet, and none is rejected for lacking it."""
    refs = find_exports()
    assert refs
    for ref in refs:
        for record in ref.load()["evidence"].values():
            assert "stage" not in record or isinstance(record["stage"], (int, str, list))
            assert not [i for i in REGISTRY.check_record(record, record["evidence_id"]) if i.category.startswith("stage_")]


ORDINAL = re.compile(r"第([12])次")


def _ordinal_flips_detected(export, assign):
    """Flip every 第1次 <-> 第2次 in the real drafts; return (detected, instances). `assign` is applied to a COPY of the
    evidence in memory only: Work's data is never edited."""
    from src.article_qa.evaluate import evaluate_article
    evidence = json.loads(json.dumps(export["evidence"]))
    for eid, stage in assign.items():
        if eid in evidence:
            evidence[eid]["stage"] = stage
    detected = instances = 0
    for a in export["articles"]:
        for m in ORDINAL.finditer(a["text"]):
            flipped = a["text"][:m.start()] + "第" + ("2" if m.group(1) == "1" else "1") + "次" + a["text"][m.end():]
            r = evaluate_article(a["article_id"], flipped, a["claim"], evidence)
            instances += 1
            detected += any(f["category"] == "stage_mismatch" for f in r.findings)
    return detected, instances


# Work's records that have no fixed stage in the registry but are cited by a sentence that names an ordinal
# (read-only scan of every delivery + whole view). This is what Work is asked to add, as sentence-ordinals (option A).
WORK_NEEDS_STAGE = {"EV-T27-04-49cb4d": [1], "EV-U-2895dfe26d3b": [1]}


def test_simulated_assignment_closes_the_ordinal_flips_the_real_drafts_could_not_see():
    refs = [r for r in find_exports() if r.handoff.startswith("work-db-v02")]
    assert refs
    export = refs[0].load()
    before = _ordinal_flips_detected(export, {})
    after = _ordinal_flips_detected(export, WORK_NEEDS_STAGE)
    assert before[1] == after[1] and before[1] >= 4
    assert after[0] > before[0], (before, after)  # the interview sentence (第1次選考の合格者には…) is now seen
    assert after[0] == after[1], (before, after)  # every ordinal flip in the real drafts is detected once the stage is recorded


def test_the_real_whole_view_has_no_stage_yet_and_the_two_records_work_must_stamp_exist():
    from src.regression.fullview import find_views
    views = find_views()
    assert views
    seen = {}
    for p in views:
        for eid, rec in json.loads(p.read_text(encoding="utf-8"))["evidence"].items():
            seen[eid] = rec
    for eid in WORK_NEEDS_STAGE:
        assert eid in seen or eid.startswith("EV-U-"), eid  # the fee-refund id changes with each Work revision


# ---- the kanji spellings of the ordinal (found by the independent audit of PR #61: a flip to 第二次 / 二次選考 was not seen)
def test_kanji_ordinals_are_read_like_the_digit_forms():
    assert stage_issues("第二次選考の合格者には、面接を一人30分程度行います。", interview([1]))
    assert stage_issues("二次選考では、面接を一人30分程度行います。", interview([1]))
    assert stage_issues("第一次選考の合格者には、面接を一人30分程度行います。", interview([2]))
    assert stage_issues("一次選考では、面接を一人30分程度行います。", interview([2]))


def test_kanji_ordinals_that_match_the_record_stage_pass():
    assert stage_issues("第二次選考の合格者には、面接を一人30分程度行います。", interview([2])) == []
    assert stage_issues("一次選考では、面接を一人30分程度行います。", interview([1])) == []
    assert stage_issues("第二次選考の合格者には、面接を一人30分程度行います。", interview([1, 2])) == []
    assert stage_issues("第二次選考の合格者には、面接を一人30分程度行います。", interview("final")) == []


def test_a_kanji_ordinal_inside_an_unrelated_word_is_not_a_stage():
    for text in ("第二次世界大戦の歴史に関心があります。面接を一人30分程度行います。", "一次情報を確認します。面接を一人30分程度行います。", "二次元の表現を学びます。面接を一人30分程度行います。"):
        assert stage_issues(text, interview([1])) == [], text


def test_without_a_stage_the_kanji_ordinals_change_nothing():
    assert stage_issues("第二次選考の合格者には、面接を一人30分程度行います。", interview()) == []
