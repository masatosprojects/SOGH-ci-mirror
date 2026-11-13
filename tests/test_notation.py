"""Issue #13: the same date / year / number written another way must get the same verdict.

Every variant that is RIGHT must pass; every variant that is WRONG must be reported.
What cannot be classified is reported as `unclassified_number` (a notice), never guessed.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.article_qa.notation_sweep import NOTATIONS, notation_sweep
from src.regression.checks import delivery_reference_date
from src.verify.notation import find_ranges, kanji_to_int, normalize_notation, unclassified_numbers
from src.verify.strict_claims import extract_quantities
from tests.test_strict_claims import BASE, CLAIM, EVIDENCE

INBOX = Path(__file__).resolve().parents[1] / "research" / "inbox"
WD = "月火水木金土日"


def run(text):
    return evaluate_article("t", text, CLAIM, EVIDENCE, reference_date="2026-11-01", require_as_of=True)


def cats(text):
    return {f["category"] for f in run(text).findings}


def notice_cats(text):
    return [n["category"] for n in run(text).notices]


def swap(old, new):
    assert old in BASE, old
    return BASE.replace(old, new, 1)


def test_the_base_article_is_clean():
    r = run(BASE)
    assert r.ok and not [n for n in r.notices if n["category"] == "unclassified_number"], (r.findings, r.notices)


# ------------------------------------------------------------ dates

RIGHT_DATES = ["2026年11月2日", "令和8年11月2日", "令和八年十一月二日", "R8.11.2", "R8/11/2", "2026/11/2", "2026.11.2",
               "2026-11-2", "２０２６年１１月２日", "二〇二六年十一月二日"]


@pytest.mark.parametrize("written", RIGHT_DATES)
def test_a_right_date_in_any_notation_passes(written):
    assert run(swap("2026年11月2日 11:00", f"{written} 11:00")).ok


@pytest.mark.parametrize("written", ["2026年11月3日", "令和8年11月3日", "令和八年十一月三日", "R8.11.3", "R8/11/3", "2026/11/3",
                                     "2026.11.3", "2026-11-3", "二〇二六年十一月三日", "令和9年11月2日", "R9.11.2"])
def test_a_wrong_date_in_any_notation_is_reported(written):
    assert "date_mismatch" in cats(swap("2026年11月2日 11:00", f"{written} 11:00")), written


def test_a_wrong_time_after_a_date_in_japanese_style_is_reported():
    assert run(swap("2026年11月2日 11:00", "2026年11月2日11時")).ok
    assert run(swap("2026年11月2日 11:00", "2026年11月2日午前11時")).ok
    assert "time_mismatch" in cats(swap("2026年11月2日 11:00", "2026年11月2日午後2時"))
    assert "time_mismatch" in cats(swap("2026年11月2日 11:00", "2026年11月2日12時"))


def test_month_day_without_year_in_kanji_and_slash_form():
    base = swap("2026年11月2日 11:00", "11月2日 11:00")
    assert run(base).ok
    assert run(swap("2026年11月2日 11:00", "十一月二日 11:00")).ok
    assert "date_mismatch" in cats(swap("2026年11月2日 11:00", "十一月三日 11:00"))


def test_slash_month_day_is_a_date_only_with_a_weekday_or_a_date_word():
    weekday = WD[datetime.date(2026, 11, 2).weekday()]
    assert run(swap("2026年11月2日 11:00", f"11/2({weekday}) 11:00")).ok
    assert "date_mismatch" in cats(swap("2026年11月2日 11:00", f"11/3({WD[datetime.date(2026, 11, 3).weekday()]}) 11:00"))
    assert run(swap("最終合格発表は2026年11月2日 11:00から", "最終合格発表は11/2 11:00から")).ok
    assert "date_mismatch" in cats(swap("最終合格発表は2026年11月2日 11:00から", "最終合格発表は11/3 11:00から"))


def test_a_slash_number_with_no_date_context_is_not_guessed_to_be_a_date():
    text = swap("任意提出資料は10点まで提出できます。[EV-O]", "任意提出資料は10点まで提出できます。うち3/4は写しでも構いません。[EV-O]")
    assert "date_mismatch" not in cats(text)
    assert "unclassified_number" in notice_cats(text)
    assert [u.raw for u in unclassified_numbers("うち3/4は")] == ["3/4"]


def test_a_wrong_weekday_is_still_reported_in_a_variant_notation():
    wrong = WD[(datetime.date(2026, 11, 2).weekday() + 1) % 7]
    assert "weekday_mismatch" in cats(swap("2026年11月2日 11:00", f"R8.11.2({wrong}) 11:00"))


def test_normalization_is_idempotent_and_does_not_touch_plain_text():
    for s in ["令和8年11月2日", "R8.11.2", "十一月二日", "2026/11/2", "3.5倍の競争率", "A4サイズ2枚", "https://example.ac.jp/2026/11/2.pdf"]:
        once = normalize_notation(s).text
        assert normalize_notation(once).text == once
    assert normalize_notation("3.5倍の競争率").text == "3.5倍の競争率" and normalize_notation("A4サイズ2枚").text == "A4サイズ2枚"


def test_kanji_numbers():
    assert [kanji_to_int(s) for s in ("三十", "十", "二十五", "九百九十九", "二〇二六", "一万二千")] == [30, 10, 25, 999, 2026, 12000]


# ------------------------------------------------------------ years: 年度 / 実施年 / 入学年 stay apart

def test_era_fiscal_year_is_read_exactly_like_the_gregorian_one():
    # EV-M says entry 2027; the article's claim is fiscal_year 2027
    assert extract_quantities("令和9年度入試")[0][1].kind == "year_entry" == extract_quantities("2027年度入試")[0][1].kind
    assert extract_quantities("令和9年度入試")[0][1].value == 2027
    assert extract_quantities("R8年度に実施")[0][1].kind == "year_exam"
    assert extract_quantities("R8年度に実施")[0][1].value == 2026


def test_a_wrong_fiscal_year_is_reported_in_era_notation():
    ok = swap("2026年度に実施するAO入試", "令和8年度に実施するAO入試")
    assert run(ok).ok
    assert "exam_year_mismatch" in cats(swap("2026年度に実施するAO入試", "令和9年度に実施するAO入試"))
    assert "entry_year_mismatch" in cats(swap("【2027年度入学】", "【令和8年度入学】"))
    assert run(swap("【2027年度入学】", "【令和9年度入学】")).ok


def test_entry_year_and_exam_year_are_not_interchangeable_in_era_notation():
    # 令和8年度 (=2026) is the exam year here; calling it the entry year must fail
    assert "entry_year_mismatch" in cats(swap("2026年度に実施するAO入試", "令和8年度入学のAO入試"))


# ------------------------------------------------------------ head counts and other units

@pytest.mark.parametrize("written", ["150名", "１５０名", "150 名", "150人", "百五十名", "約150名", "約150人"])
def test_right_quota_in_any_notation_passes(written):
    assert run(swap("募集人員は150名[EV-Q]です。", f"募集人員は{written}[EV-Q]です。")).ok


@pytest.mark.parametrize("written", ["151名", "１５１名", "百五十一名", "約151人", "約15名", "1500名"])
def test_wrong_quota_in_any_notation_is_reported(written):
    assert "quantity_mismatch" in cats(swap("募集人員は150名[EV-Q]です。", f"募集人員は{written}[EV-Q]です。"))


def test_thousands_separators_and_fullwidth_digits():
    assert run(swap("検定料は17,000円です。", "検定料は１７，０００円です。")).ok
    assert run(swap("検定料は17,000円です。", "検定料は1万7000円です。")).ok
    assert run(swap("検定料は17,000円です。", "検定料は一万七千円です。")).ok
    assert "quantity_mismatch" in cats(swap("検定料は17,000円です。", "検定料は18,000円です。"))
    assert "quantity_mismatch" in cats(swap("検定料は17,000円です。", "検定料は一万八千円です。"))


# ------------------------------------------------------------ ranges

def test_ranges_are_found_with_both_ends():
    assert [(r.kind, r.lo, r.hi) for r in find_ranges(normalize_notation("800〜1000字、2~3枚、30名から40名、800字〜1000字").text)] == [
        ("chars", 800, 1000), ("pages", 2, 3), ("persons", 30, 40), ("chars", 800, 1000)]
    assert find_ranges("2026-10-8") == [] and find_ranges("10月1日〜10月8日") == [] and find_ranges("9:00〜17:00") == []


def test_range_upper_end_is_checked_and_an_unrecorded_lower_end_is_a_notice_not_a_pass():
    ok = swap("日本語2000字以内", "日本語1000〜2000字")
    r = run(ok)
    assert r.ok
    assert any(n["category"] == "range_end_unverified" and "1000" in n["detail"] for n in r.notices)


@pytest.mark.parametrize("written", ["1000〜2200字", "1000〜1999字", "２０００〜３０００字", "1000字〜2500字"])
def test_a_range_whose_upper_end_is_wrong_is_reported(written):
    assert "quantity_mismatch" in cats(swap("日本語2000字以内", f"日本語{written}"))


def test_pages_range_in_either_wording():
    assert run(swap("A4サイズ2枚以内", "A4サイズ1〜2枚")).ok
    assert "quantity_mismatch" in cats(swap("A4サイズ2枚以内", "A4サイズ1〜3枚"))
    assert "quantity_mismatch" in cats(swap("A4サイズ2枚以内", "A4サイズ１〜３枚"))


# ------------------------------------------------------------ unit-less numbers

def test_a_number_without_a_unit_is_unclassified_and_never_read_as_persons():
    text = swap("募集人員は150名[EV-Q]です。", "募集人員は150名[EV-Q]です。補欠の定員は30。[EV-Q]")
    r = run(text)
    assert r.ok  # not a finding: the QA cannot say what 30 is
    notes = [n for n in r.notices if n["category"] == "unclassified_number"]
    assert notes and "'30'" in notes[0]["detail"] and "根拠にこの数値は無い" in notes[0]["detail"]
    assert all(q.kind != "persons" for _, q in extract_quantities("補欠の定員は30。"))


def test_an_unclassified_number_that_the_evidence_also_has_says_so():
    text = swap("募集人員は150名[EV-Q]です。", "募集人員は150名[EV-Q]です。定員は150。[EV-Q]")
    note = [n for n in run(text).notices if n["category"] == "unclassified_number"]
    assert note and "同じ数値がある" in note[0]["detail"]


def test_headings_and_urls_and_citations_are_not_unclassified_numbers():
    text = swap("# 【2027年度入学】〇〇大学 環境学部 夏秋AO入試｜出願の要点", "# 【2027年度入学】〇〇大学 2026夏秋AO入試｜出願の要点")
    assert not [n for n in run(text).notices if n["category"] == "unclassified_number"]


# ------------------------------------------------------------ the sweep and the real drafts

def _exports():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(INBOX.rglob("claude-compatible-export.json"))]


def test_every_notation_in_the_sweep_is_distinct_from_the_original():
    d = datetime.date(2026, 11, 3)
    assert len({w(d) for w in NOTATIONS.values()}) == len(NOTATIONS)


def test_real_drafts_have_no_false_positive_and_no_unclassified_number():
    exports = _exports()
    assert exports
    for e in exports:
        ref = delivery_reference_date(e)
        for a in e["articles"]:
            r = evaluate_article(a["article_id"], a["text"], a["claim"], e["evidence"], reference_date=ref, require_as_of=True)
            assert r.ok and not [n for n in r.notices if n["category"] in ("unclassified_number", "range_end_unverified")], a["article_id"]


def test_real_drafts_dates_survive_every_notation_and_a_moved_date_is_caught():
    inv = det = 0
    total_i = total_d = 0
    for e in _exports():
        r = notation_sweep(e, reference_date=delivery_reference_date(e), require_as_of=True)
        assert r["all_baselines_ok"] and not r["false_positives"], r["false_positives"][:3]
        inv += r["invariance"][0]
        total_i += r["invariance"][1]
        det += r["detection"][0]
        total_d += r["detection"][1]
        assert not r["survivors"], r["survivors"][:3]
    assert total_i >= 300 and inv == total_i and det == total_d, (inv, total_i, det, total_d)
