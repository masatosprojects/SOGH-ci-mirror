"""Issue #7: a valid citation id is not enough — the article's values, dates,
units and scope must match the cited evidence. Each negative case edits one
thing in an otherwise-correct article and expects a specific finding.

All data here is synthetic (〇〇大学); nothing is a real admissions fact.
"""
import json
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.verify.strict_claims import extract_quantities

URL = "https://example.ac.jp/x.pdf"


def _ev(eid, key, value, scope="target_admission_cycle", page=8, **extra):
    record = {
        "evidence_id": eid,
        "university": "〇〇大学",
        "faculty": "環境学部",
        "department": None,
        "admission_method": "夏秋AO入試",
        "fiscal_year": 2027,
        "source_url": URL,
        "fact_key": key,
        "value": value,
        "scope": scope,
        "proofs": [{"page": page, "quote": "x"}],
    }
    record.update(extra)
    return record


EVIDENCE = {
    "EV-Q": _ev("EV-Q", "quota", {"count": 150, "unit": "名", "period": "all_AO_held_in_2026",
                                  "entry_months": [4, 9], "summer_autumn_only_count": None},
                scope="faculty_annual_AO_aggregate", quota=150),
    "EV-M": _ev("EV-M", "entry", {"months": ["2027-04", "2027-09"]}),
    "EV-P": _ev("EV-P", "online_period", {"start": "2026-08-03T10:00:00+09:00", "end": "2026-09-01T15:00:00+09:00"}),
    "EV-D": _ev("EV-D", "second_stage_date", {"dates": ["2026-10-24", "2026-10-25"], "selection": "one_of_not_both"}),
    "EV-R": _ev("EV-R", "final_result", {"date": "2026-11-02", "time": "11:00", "timezone": "Asia/Tokyo"}),
    "EV-I": _ev("EV-I", "interview", {"minutes": 30, "type": "allocated_time_window_not_net_question_time"}),
    "EV-S": _ev("EV-S", "personal_statement", {"essay_max_ja_chars": 2000, "essay_max_en_chars": 4000,
                                               "free_format_a4_pages_max": 2, "free_format_max_mb": 10}),
    "EV-O": _ev("EV-O", "optional_materials", {"max_items": 10}),
    "EV-F": _ev("EV-F", "fee", {"amount": 17000, "currency": "JPY"}),
}
CLAIM = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}

BASE = """# 【2027年度入学】〇〇大学 環境学部 夏秋AO入試｜出願の要点

作業基準日：2026-11-01。保存した公式要項の内容を整理した草案です。

募集人員は150名[EV-Q]です。この人数は、2026年度に実施するAO入試（4月入学・9月入学）の合計です。夏秋AO単独の募集枠として読み替えないよう注意してください。

入学時期は2027年4月または2027年9月です。[EV-M]

オンライン申請期間は2026年8月3日 10:00〜2026年9月1日 15:00です。[EV-P]

第2次選考日は2026年10月24日・2026年10月25日のいずれかです。[EV-D]

最終合格発表は2026年11月2日 11:00からです。[EV-R]

面接試験の実施時間の枠は一人30分程度[EV-I]です。これは実施時間枠であり、実質的な質疑時間が同じ長さだとは断定できません。

志望理由書は日本語2000字以内、英語4000字以内です。自由記述はA4サイズ2枚以内、10メガバイト以内のPDFです。[EV-S]

任意提出資料は10点まで提出できます。[EV-O]

検定料は17,000円です。[EV-F]

最新情報は大学公式サイトでご確認ください。

## 根拠資料

- [EV-Q] 公式募集要項 PDF p.8：https://example.ac.jp/x.pdf#page=8
- [EV-D] 公式募集要項 PDF p.8：https://example.ac.jp/x.pdf#page=8
"""


def categories(text: str, evidence=EVIDENCE) -> set[str]:
    return {f["category"] for f in evaluate_article("a", text, CLAIM, evidence).findings}


def edit(old: str, new: str) -> str:
    assert old in BASE, f"test setup: {old!r} not in base article"
    return BASE.replace(old, new, 1)


def test_base_article_is_clean():
    report = evaluate_article("base", BASE, CLAIM, EVIDENCE)
    assert report.ok, report.findings


@pytest.mark.parametrize(
    "old,new,expected",
    [
        # 募集人数
        ("募集人員は150名[EV-Q]", "募集人員は999名[EV-Q]", "quantity_mismatch"),
        ("募集人員は150名[EV-Q]", "募集人員は15名[EV-Q]", "quantity_mismatch"),
        ("募集人員は150名[EV-Q]", "募集人員は百五十名[EV-Q]", None),  # kanji, same value: fine
        ("募集人員は150名[EV-Q]", "募集人員は九百九十九名[EV-Q]", "quantity_mismatch"),
        ("募集人員は150名[EV-Q]", "募集人員は150[EV-Q]名です", None),  # bare number, same value
        ("募集人員は150名[EV-Q]", "募集人員は151[EV-Q]名です", "quantity_not_in_evidence"),
        # 出願期間 / 試験日 / 合格発表日
        ("2026年10月24日・2026年10月25日", "2026年10月24日・2026年10月26日", "date_mismatch"),
        ("2026年10月24日・2026年10月25日", "2026年10月24日・2027年10月25日", "date_mismatch"),
        ("2026年8月3日 10:00〜2026年9月1日 15:00", "2026年8月4日 10:00〜2026年9月1日 15:00", "date_mismatch"),
        ("2026年8月3日 10:00〜2026年9月1日 15:00", "2026年9月1日 15:00〜2026年8月3日 10:00", "period_order_mismatch"),
        ("2026年11月2日 11:00", "2026年11月3日 11:00", "date_mismatch"),
        ("2026年11月2日 11:00", "2026年11月2日 12:00", "time_mismatch"),
        ("2026年11月2日 11:00", "令和8年11月2日 11:00", None),  # 令和8 == 2026
        ("2026年11月2日 11:00", "令和7年11月2日 11:00", "date_mismatch"),
        ("2026年11月2日 11:00", "2026年11月2日（月）11:00", None),
        ("2026年11月2日 11:00", "2026年11月2日（火）11:00", "weekday_mismatch"),
        ("2026年11月2日 11:00", "2026-11-03 11:00", "date_mismatch"),
        ("2026年10月24日・2026年10月25日", "2026年10月24日 9:00・2026年10月25日", "time_mismatch"),  # time not in evidence
        ("2026年10月24日・2026年10月25日", "2026年11月2日・2026年10月25日", "date_mismatch"),  # other fact's date
        # 面接の実施時間
        ("一人30分程度", "一人45分程度", "quantity_mismatch"),
        ("一人30分程度", "一人0.5時間程度", None),
        # 提出書類の文字数・枚数・容量・点数
        ("日本語2000字以内", "日本語3000字以内", "quantity_mismatch"),
        ("英語4000字以内", "英語800語以内", "quantity_not_in_evidence"),  # words are not characters
        ("A4サイズ2枚以内", "A4サイズ3枚以内", "quantity_mismatch"),
        ("10メガバイト以内", "100メガバイト以内", "quantity_mismatch"),
        ("10点まで提出できます", "20点まで提出できます", "quantity_mismatch"),
        # 金額
        ("17,000円", "27,000円", "quantity_mismatch"),
        ("17,000円", "1万7000円", None),
        ("17,000円", "一万七千円", None),
        ("17,000円", "1万8000円", "quantity_mismatch"),
        # 入学年度と試験実施年度
        ("【2027年度入学】", "【2026年度入学】", "entry_year_mismatch"),
        ("2026年度に実施するAO入試", "2027年度に実施するAO入試", "exam_year_mismatch"),
        ("2027年4月または2027年9月", "2027年5月または2027年9月", "date_mismatch"),
        ("2027年4月または2027年9月", "2026年4月または2027年9月", "date_mismatch"),
        ("（4月入学・9月入学）", "（4月入学・10月入学）", "entry_month_mismatch"),
        # 募集枠の適用範囲
        ("この人数は、2026年度に実施するAO入試（4月入学・9月入学）の合計です。", "", "scope_reinterpretation"),
        ("夏秋AO単独の募集枠として読み替えないよう注意してください。", "夏秋AO単独の募集枠です。", "scope_reinterpretation"),
        (
            "面接試験の実施時間の枠は一人30分程度[EV-I]です。これは実施時間枠であり、実質的な質疑時間が同じ長さだとは断定できません。",
            "面接の質疑時間は30分程度[EV-I]です。",
            "scope_reinterpretation",
        ),
        ("いずれかです", "両日です", "scope_reinterpretation"),
        # 出典リスト
        ("[EV-Q] 公式募集要項 PDF p.8", "[EV-Q] 公式募集要項 PDF p.9", "source_page_mismatch"),
        ("https://example.ac.jp/x.pdf#page=8\n- [EV-D]", "https://example.org/other.pdf#page=8\n- [EV-D]", "source_url_mismatch"),
    ],
)
def test_single_edit(old, new, expected):
    found = categories(edit(old, new))
    if expected is None:
        assert not found, found
    else:
        assert expected in found, found


def test_unsourced_date_and_amount_appended_to_article_are_flagged():
    assert "uncited_quantity" in categories(BASE + "\n申込は2027年2月28日までです。\n")
    assert "uncited_quantity" in categories(BASE + "\n受験料は5,000円です。\n")


def test_value_on_wrong_evidence_is_flagged():
    # a real value, attached to the wrong fact's citation
    text = edit("任意提出資料は10点まで提出できます。[EV-O]", "任意提出資料は2000字以内です。[EV-O]")
    assert "quantity_not_in_evidence" in categories(text)


def test_unknown_citation_is_not_reported_twice():
    text = edit("募集人員は150名[EV-Q]", "募集人員は150名[EV-NOPE]")
    findings = evaluate_article("a", text, CLAIM, EVIDENCE).findings
    assert [f["category"] for f in findings].count("unknown_citation") == 1
    assert not {"quantity_mismatch", "quantity_not_in_evidence"} & {f["category"] for f in findings}


def test_list_numbering_and_unkeyed_stage_words_are_not_treated_as_exam_facts():
    text = edit(
        "任意提出資料は10点まで提出できます。[EV-O]",
        "任意提出資料は10点まで提出できます。手順は（1）から（3）で、第2次選考の前に行います。[EV-O]",
    )
    assert not categories(text)


# --- references, ordinals, logic, omitted dates, periods, citation topic ---

LOGIC = {
    "EV-L": _ev("EV-L", "eligibility", {"logic": "any_of_1_to_3", "details_page": 6}, page=6),
    "EV-A": _ev("EV-A", "eligibility", {"logic": "all_of_1_to_4", "details_page": 10}, page=10),
    "EV-F1": _ev("EV-F1", "first_stage", {"text": "書類選考"}),
    "EV-S2": _ev("EV-S2", "second_stage_date", {"dates": ["2026-10-08"], "selection": "specified_day"}),
    "EV-PP": _ev("EV-PP", "postal_period", {"start": "2026-09-01", "end": "2026-09-02"}),
    "EV-C": _ev("EV-C", "common_test", {"required": False}),
    "EV-S": EVIDENCE["EV-S"],
}
LOGIC_BASE = """# 【2027年度入学】〇〇大学 環境学部 夏秋AO入試

出願資格は募集要項p.6の（1）〜（3）のいずれかに該当することが条件です。[EV-L]

共通条件は募集要項p.10の（1）〜（4）を全て満たす必要があります。[EV-A]

第1次選考は書類で行います。[EV-F1]

第2次選考日は2026年10月8日です。[EV-S2]

郵送書類の提出期間は2026年9月1日〜9月2日です。[EV-PP]

共通テストの受験は必要ありません。[EV-C]

自由記述はA4サイズ2枚以内です。[EV-S]

最新情報は大学公式サイトでご確認ください。
"""


def logic_categories(text: str) -> set[str]:
    return {f["category"] for f in evaluate_article("l", text, CLAIM, LOGIC).findings}


def test_logic_base_is_clean():
    assert not logic_categories(LOGIC_BASE)


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ("募集要項p.6の", "募集要項p.7の", "page_reference_mismatch"),
        ("p.10の（1）〜（4）", "p.10の（1）〜（5）", "item_range_mismatch"),
        ("p.6の（1）〜（3）のいずれか", "p.6の（2）〜（3）のいずれか", "item_range_mismatch"),
        ("（1）〜（3）のいずれかに該当する", "（1）〜（3）を全て満たす", "logic_mismatch"),  # OR turned into AND
        ("（1）〜（4）を全て満たす必要があります", "（1）〜（4）のいずれかに該当すれば足ります", "logic_mismatch"),  # AND turned into OR
        ("第1次選考は書類で", "第2次選考は書類で", "stage_mismatch"),
        ("第2次選考日は2026年10月8日", "第1次選考日は2026年10月8日", "stage_mismatch"),
        ("A4サイズ", "A5サイズ", "paper_size_mismatch"),
        ("2026年9月1日〜9月2日", "2026年9月2日〜9月2日", "period_mismatch"),  # one end silently changed
        ("2026年9月1日〜9月2日", "2026年9月2日〜9月1日", "period_order_mismatch"),
        ("2026年9月1日〜9月2日", "2026年9月1日〜9月3日", "period_mismatch"),
        ("共通テストの受験は必要ありません。[EV-C]", "共通テストの受験は必要ありません。[EV-S2]", "citation_topic_mismatch"),
        ("共通テストの受験は必要ありません。[EV-C]", "共通テストの受験は必要ありません。[EV-NOPE]", "unknown_citation"),
    ],
)
def test_reference_ordinal_logic_period_and_topic_edits(old, new, expected):
    assert old in LOGIC_BASE, old
    assert expected in logic_categories(LOGIC_BASE.replace(old, new, 1)), expected


def test_omitted_candidate_date_is_flagged():
    # EVIDENCE["EV-D"] lists 10/24 and 10/25: listing one twice drops the other
    text = edit("2026年10月24日・2026年10月25日", "2026年10月25日・2026年10月25日")
    assert "date_omitted" in categories(text)


def test_unknown_citation_far_from_any_number_is_flagged_once():
    text = edit("入学時期は2027年4月または2027年9月です。[EV-M]", "入学時期は2027年4月または2027年9月です。[EV-GHOST]")
    findings = evaluate_article("a", text, CLAIM, EVIDENCE).findings
    assert [f["category"] for f in findings].count("unknown_citation") == 1


def test_extract_quantities_units():
    q = {x.kind: x.value for _, x in extract_quantities("30分野の研究、2000字以内、A4サイズ2枚、1万2000円、一人30分")}
    assert "minutes" in q and q["minutes"] == 30  # 一人30分 yes, 30分野 no
    assert q["chars"] == 2000 and q["pages"] == 2 and q["yen"] == 12000
    assert [x.kind for _, x in extract_quantities("30分野の研究")] == []


def test_issue_7_original_reproduction_with_legacy_quota_only_evidence():
    """The exact case from Issue #7: 30名 -> 999名 with a valid citation and
    old-style evidence that only carries `quota`."""
    fixture = json.loads((Path(__file__).parent / "fixtures" / "sample_articles.json").read_text(encoding="utf-8"))
    article = next(a for a in fixture["articles"] if a["article_id"] == "sample-clean")
    assert evaluate_article("c", article["text"], article["claim"], fixture["evidence"]).ok
    tampered = article["text"].replace("30名", "999名")
    report = evaluate_article("t", tampered, article["claim"], fixture["evidence"])
    assert not report.ok
    assert "quantity_mismatch" in {f["category"] for f in report.findings}


# ---- Work's real export (PR #6, merged: the data is in the repository). Never skipped:
# if the file were missing, collection fails loudly instead of a quiet skip.
_WORK_EXPORT = Path(__file__).parent.parent / "research/inbox/work-db-v02-20261101/samples/claude-compatible-export.json"
assert _WORK_EXPORT.is_file(), f"Work's handoff is missing: {_WORK_EXPORT}"


def test_work_real_drafts_pass_strict_validation():
    data = json.loads(_WORK_EXPORT.read_text(encoding="utf-8"))
    assert len(data["articles"]) == 4
    for a in data["articles"]:
        report = evaluate_article(a["article_id"], a["text"], a["claim"], data["evidence"])
        assert report.ok, (a["article_id"], report.findings)


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ("募集人員は5名", "募集人員は50名", "quantity_mismatch"),
        ("募集人員は150名", "募集人員は15名", "quantity_mismatch"),
        ("2026年10月8日と要項", "2026年10月9日と要項", "date_mismatch"),
        ("2026年10月24日・2026年10月25日", "2026年10月24日・2026年10月26日", "date_mismatch"),
        ("一人30分程度", "一人40分程度", "quantity_mismatch"),
        ("800字以内", "1000字以内", "quantity_mismatch"),
        ("2000字以内、英語4000字以内", "2000字以内、英語4000語以内", "quantity_not_in_evidence"),
        ("2026年11月2日 11:00", "2027年11月2日 11:00", "date_mismatch"),
        ("2026年度に実施", "2027年度に実施", "exam_year_mismatch"),
    ],
)
def test_work_real_drafts_detect_edits(old, new, expected):
    data = json.loads(_WORK_EXPORT.read_text(encoding="utf-8"))
    hits = 0
    for a in data["articles"]:
        if old in a["text"]:
            hits += 1
            found = {f["category"] for f in evaluate_article(a["article_id"], a["text"].replace(old, new), a["claim"], data["evidence"]).findings}
            assert expected in found, (a["article_id"], found)
    assert hits, f"{old!r} not present in any draft"
