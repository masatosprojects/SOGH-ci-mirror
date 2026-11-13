"""Issue #11: the as-of date (作業基準日) and the time-relative wording around it.

Every date here is fixed: nothing reads the clock. "Now" is the `reference_date`
argument, and without it the "as-of date is in the future" check does not run."""
import copy
import datetime
import json
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.verify import fact_registry as fr
from src.verify.as_of import check_as_of, event_end, extract_as_of

REPO = Path(__file__).parent.parent
REF = datetime.date(2026, 11, 1)  # a fixed "today" for the tests
CLAIM = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}


def ev(eid, key, value, retrieved_at="2026-10-30"):
    return {"evidence_id": eid, "university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試",
            "fiscal_year": 2027, "fact_key": key, "value": value, "scope": "target_admission_cycle",
            "retrieved_at": retrieved_at, "proofs": [{"page": 3, "quote": "x"}]}


EVIDENCE = {
    "EV-P": ev("EV-P", "online_period", {"start": "2026-08-03T10:00:00+09:00", "end": "2026-09-02T09:00:00+09:00"}),
    "EV-D": ev("EV-D", "second_stage_date", {"dates": ["2026-10-24", "2026-10-25"], "selection": "one_of_not_both"}),
    "EV-R": ev("EV-R", "final_result", {"date": "2026-11-02", "time": "11:00"}),
}


def article(as_of="作業基準日：2026-11-01。", notice="記載する出願期間・面接日は既に経過しています。", extra=""):
    return (f"# 【2027年度入学】〇〇大学 環境学部 夏秋AO入試\n\n{as_of}{notice}\n\n"
            "オンライン申請期間は2026年8月3日〜2026年9月2日です。[EV-P]\n\n"
            "第2次選考日は2026年10月24日・2026年10月25日のいずれかです。[EV-D]\n\n"
            "最終合格発表は2026年11月2日です。[EV-R]\n\n" + extra + "最新情報は大学公式サイトでご確認ください。\n")


def cats(text, **kw):
    return {i.category for i in check_as_of(text, EVIDENCE, **kw)}


# --------------------------------------------------------- the clean case

def test_a_correct_article_has_no_as_of_findings():
    assert check_as_of(article(), EVIDENCE, reference_date=REF, require_as_of=True) == []


@pytest.mark.parametrize("as_of", ["作業基準日：2026-11-01。", "作業基準日：２０２６年１１月１日。", "作業基準日：2026年11月1日。",
                                   "作業基準日：令和8年11月1日。", "作業基準日: 2026-11-01。"])
def test_every_date_format_is_read_the_same(as_of):
    assert extract_as_of(as_of)[0] == [datetime.date(2026, 11, 1)]
    assert check_as_of(article(as_of=as_of), EVIDENCE, reference_date=REF, require_as_of=True) == []


# --------------------------------------------------- 1. date in the future

def test_an_as_of_date_after_today_is_flagged():
    assert "as_of_in_future" in cats(article(as_of="作業基準日：2026-11-05。"), reference_date=REF)


def test_the_future_check_needs_a_reference_date_and_never_reads_the_clock():
    text = article(as_of="作業基準日：2099-01-01。")
    assert "as_of_in_future" not in cats(text)  # no reference date given: not checked, not guessed
    assert "as_of_in_future" in cats(text, reference_date="2026-11-01")  # an ISO string works too
    assert "as_of_in_future" not in cats(article(as_of="作業基準日：2026-11-01。"), reference_date=datetime.date(2026, 11, 1))  # same day: fine


# ---------------------------------------------- 2. before the retrieval date

def test_an_as_of_date_before_the_evidence_was_retrieved_is_flagged():
    assert "as_of_before_retrieval" in cats(article(as_of="作業基準日：2026-10-29。"), reference_date=REF)
    assert "as_of_before_retrieval" not in cats(article(as_of="作業基準日：2026-10-30。"), reference_date=REF)  # the same day is fine
    assert "as_of_before_retrieval" not in cats(article(as_of="作業基準日：2026-10-31。"), reference_date=REF)


def test_evidence_without_a_retrieval_date_is_not_guessed_at():
    evidence = copy.deepcopy(EVIDENCE)
    for record in evidence.values():
        record.pop("retrieved_at")
    assert not [i for i in check_as_of(article(as_of="作業基準日：2020-01-01。"), evidence, reference_date=REF)
                if i.category == "as_of_before_retrieval"]


# ------------------------------------ 3. "already over" when it is not yet

def test_claiming_a_deadline_has_passed_when_it_has_not_is_flagged():
    # as of 2026-09-01 the online period (ends 09-02) and the interviews (10-24/25) are still ahead
    text = article(as_of="作業基準日：2026-09-01。")
    found = check_as_of(text, EVIDENCE, reference_date=REF)
    flagged = {i.detail.split("、")[1].split("（")[0] for i in found if i.category == "elapsed_claim_mismatch"}
    assert flagged == {"EV-P", "EV-D"}


def test_a_cited_sentence_saying_it_is_over_is_checked_against_its_own_evidence():
    text = article(as_of="作業基準日：2026-08-20。", notice="", extra="オンライン申請の受付は終了しました。[EV-P]\n\n")
    assert "elapsed_claim_mismatch" in cats(text, reference_date=REF)


def test_the_same_day_is_never_flagged_a_date_cannot_tell_if_09_00_has_passed():
    text = article(as_of="作業基準日：2026-09-02。", notice="", extra="オンライン申請の受付は終了しました。[EV-P]\n\n")
    assert "elapsed_claim_mismatch" not in cats(text, reference_date=REF)


# ------------------------------------- 4. "still ahead" when it is over

def test_saying_something_is_still_ahead_when_it_is_over_is_flagged():
    text = article(notice="", extra="第2次選考はこれから実施されます。[EV-D]\n\n")  # interviews were 10/24-25, as-of 11/01
    assert "upcoming_claim_mismatch" in cats(text, reference_date=REF)


def test_saying_something_is_still_ahead_when_it_is_is_fine():
    text = article(notice="", extra="最終合格発表はこれから行われます。[EV-R]\n\n")  # 11/02 is after 11/01
    assert "upcoming_claim_mismatch" not in cats(text, reference_date=REF)
    text = article(notice="", extra="最終合格発表は間近です。[EV-R]\n\n")
    assert "upcoming_claim_mismatch" not in cats(text, reference_date=REF)


def test_upcoming_wording_about_an_event_that_ended_is_flagged_even_for_an_application_deadline():
    text = article(notice="", extra="締切までに書類を整えましょう。[EV-P]\n\n")  # the period ended 09/02, as-of 11/01
    assert "upcoming_claim_mismatch" in cats(text, reference_date=REF)


# ---------------------------------- a sentence with no citation

def test_an_uncited_sentence_is_matched_to_evidence_only_through_registered_keywords():
    # 出願期間 -> online_period (ended), 面接日 -> second_stage_date: both before 11/01: true statement
    assert cats(article(), reference_date=REF) == set()
    # 合格発表 -> final_result (11/02): "already over" is false as of 11/01
    assert "elapsed_claim_mismatch" in cats(article(notice="合格発表は既に終了しました。"), reference_date=REF)
    # a sentence with no keyword for any cited fact is left alone (cannot be verified, so it is not guessed)
    assert cats(article(notice="すべて既に終了しました。"), reference_date=REF) == set()


# ------------------------------------------------- 5. missing / malformed

def test_a_missing_as_of_date_is_flagged_only_when_required():
    text = article(as_of="", notice="")
    assert cats(text, require_as_of=True) == {"as_of_missing"}
    assert cats(text) == set()  # older drafts without one keep working
    assert check_as_of("定員は50名です。", EVIDENCE, require_as_of=True) == []  # nothing cited, nothing to date


@pytest.mark.parametrize("as_of", ["作業基準日：近日。", "作業基準日：2026-02-30。", "作業基準日：。"])
def test_an_unreadable_as_of_date_is_flagged(as_of):
    assert "as_of_unparsable" in cats(article(as_of=as_of, notice=""), reference_date=REF)


def test_two_different_as_of_dates_conflict():
    text = article() + "\n作業基準日：2026-10-31。\n"
    assert "as_of_conflict" in cats(text, reference_date=REF)
    assert "as_of_conflict" not in cats(article() + "\n作業基準日：2026-11-01。\n", reference_date=REF)  # the same date twice is fine


# ----------------------------------------------------------- helpers

def test_event_end_takes_the_end_the_date_or_the_latest_of_the_dates():
    assert event_end(EVIDENCE["EV-P"]) == datetime.date(2026, 9, 2)
    assert event_end(EVIDENCE["EV-D"]) == datetime.date(2026, 10, 25)
    assert event_end(EVIDENCE["EV-R"]) == datetime.date(2026, 11, 2)
    assert event_end(ev("E", "common_test", {"required": False})) is None
    assert event_end({"evidence_id": "E"}) is None


# --------------------------------- through evaluate_article / the registry

def test_evaluate_article_runs_the_as_of_checks_only_when_asked_so_old_articles_are_unaffected():
    text = article(as_of="作業基準日：2026-11-05。")
    assert "as_of_in_future" not in {f["category"] for f in evaluate_article("a", text, CLAIM, EVIDENCE).findings}
    report = evaluate_article("a", text, CLAIM, EVIDENCE, reference_date=REF)
    assert "as_of_in_future" in {f["category"] for f in report.findings} and not report.ok


def test_a_new_fact_key_gets_temporal_checks_from_data_alone():
    data = json.loads(fr.DEFAULT_PATH.read_text(encoding="utf-8"))
    data["fact_keys"]["waitlist_notice"] = {
        "description": "補欠繰り上げの連絡", "status": "proposed", "since": "1.3.0", "scopes": ["*"],
        "topic_keywords": ["補欠"], "temporal_keywords": ["補欠の連絡"],
        "value": {"date": {"type": "iso_date", "required": True}}}
    registry = fr.Registry(data)
    evidence = {"EV-W": ev("EV-W", "waitlist_notice", {"date": "2026-12-01"})}
    text = "作業基準日：2026-11-01。補欠の連絡は既に終了しました。\n\n補欠の連絡は2026年12月1日です。[EV-W]\n"
    assert "elapsed_claim_mismatch" in {i.category for i in check_as_of(text, evidence, reference_date=REF, registry=registry)}
    # the shipped registry does not know that wording, so the uncited sentence is left alone
    assert check_as_of(text, evidence, reference_date=REF) == []


# --------------------------------------- Work's real drafts: no false alarms

EXPORTS = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
           for p in sorted((REPO / "research" / "inbox").rglob("claude-compatible-export.json"))}


@pytest.mark.parametrize("name", list(EXPORTS))
def test_work_drafts_have_no_as_of_findings(name):
    export = EXPORTS[name]
    for a in export["articles"]:
        assert extract_as_of(a["text"])[0] == [datetime.date(2026, 11, 1)]
        assert check_as_of(a["text"], export["evidence"], reference_date="2026-11-01", require_as_of=True) == [], a["article_id"]


def test_the_template_sentence_is_flagged_when_misapplied_to_dates_that_are_still_ahead():
    """Niigata's schedule is in November (after the 2026-11-01 as-of): Work's own wording
    "出願期間・面接日は既に経過しています" would be false there — this check must catch it."""
    export = EXPORTS["humanities"]
    text = next(a["text"] for a in export["articles"] if ":overview:" in a["article_id"])
    wrong = text.replace("作業基準日：2026-11-01。", "作業基準日：2026-11-01。記載する出願期間・面接日は既に経過しています。", 1)
    found = {i.category for i in check_as_of(wrong, export["evidence"], reference_date="2026-11-01")}
    assert "elapsed_claim_mismatch" in found


def test_the_real_tsukuba_wording_is_true_as_of_its_date_and_false_a_little_earlier():
    export = EXPORTS["samples"]
    text = next(a["text"] for a in export["articles"] if a["article_id"].startswith("tsukuba") and ":overview:" in a["article_id"])
    assert "既に経過しています" in text
    earlier = text.replace("作業基準日：2026-11-01", "作業基準日：2026-09-01")  # the application period was still open
    found = {i.category for i in check_as_of(earlier, export["evidence"], reference_date="2026-11-01")}
    assert "elapsed_claim_mismatch" in found
    before_retrieval = text.replace("作業基準日：2026-11-01", "作業基準日：2026-10-31")
    assert "as_of_before_retrieval" in {i.category for i in check_as_of(before_retrieval, export["evidence"], reference_date="2026-11-01")}
