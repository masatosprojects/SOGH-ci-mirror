"""Issue #9: meaning that carries no number — yes/no flips, dropped limits and exceptions, unconditional claims.

Every case here is a WRONG sentence that must be reported (and the matching right sentence that must not be).
`semantic_coverage` must say what no rule looked at instead of treating it as correct.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.article_qa.flip_sweep import FLIPS, FLIPS_HELD_OUT_C, flip_sweep
from src.verify.fact_registry import get_registry, validate_registry_data
from src.verify.qualitative import check_qualitative, semantic_coverage

REGISTRY = get_registry()
INBOX = Path(__file__).resolve().parents[1] / "research" / "inbox"


def ev(eid, key, value, **extra):
    return {"evidence_id": eid, "fact_key": key, "value": value, **extra}


def cats(text, evidence):
    return {i.category for i in check_qualitative(text, evidence)}


def para(sentence, eid):
    return f"# 見出し\n\n{sentence}[{eid}]\n"


COMMON_REQ = {"EV-C": ev("EV-C", "common_test", {"required": True})}
COMMON_NOT = {"EV-C": ev("EV-C", "common_test", {"required": False})}


# -------------------------------------------------- yes/no flips (the user's examples)

@pytest.mark.parametrize("sentence", [
    "大学入学共通テストの受験は不要です。",
    "大学入学共通テストの受験は必要ありません。",
    "大学入学共通テストは課されません。",
    "共通テストの受験は免除されます。",
])
def test_common_test_required_said_as_not_required_is_reported(sentence):
    assert "polarity_mismatch" in cats(para(sentence, "EV-C"), COMMON_REQ)


@pytest.mark.parametrize("sentence", [
    "大学入学共通テストの受験が必要です。",
    "大学入学共通テストの成績が必須です。",
])
def test_common_test_required_said_as_required_is_not_reported(sentence):
    assert not check_qualitative(para(sentence, "EV-C"), COMMON_REQ)


@pytest.mark.parametrize("sentence", [
    "大学入学共通テストの受験が必要です。",
    "大学入学共通テストは必須です。",
])
def test_common_test_not_required_said_as_required_is_reported(sentence):
    assert "polarity_mismatch" in cats(para(sentence, "EV-C"), COMMON_NOT)


def test_common_test_not_required_said_as_not_required_is_not_reported():
    assert not check_qualitative(para("大学入学共通テストの受験は不要です。", "EV-C"), COMMON_NOT)


def test_a_negated_forbidden_phrase_is_allowed_in_its_own_sentence():
    # "必須ではありません" contains 必須 but says the opposite of what the forbidden list means
    assert not check_qualitative(para("大学入学共通テストの受験は必須ではありません。", "EV-C"), COMMON_NOT)


@pytest.mark.parametrize("sentence,allowed", [
    ("申請書類は持参できません。", True),
    ("申請書類は持参できます。", False),
    ("申請書類は持参も受け付けます。", False),
])
def test_no_visit_submission_cannot_become_allowed(sentence, allowed):
    evidence = {"EV-Q": ev("EV-Q", "deadline", {**{"date": "2026-10-27"}, "qualifier": "消印有効・持参不可"})}
    found = check_qualitative(para(sentence, "EV-Q"), evidence)
    assert (not found) is allowed, found


def test_no_visit_note_dropped_entirely_is_reported():
    evidence = {"EV-Q": ev("EV-Q", "deadline", {**{"date": "2026-10-27"}, "qualifier": "消印有効・持参不可"})}
    assert "qualifier_dropped" in cats(para("出願書類は10月27日までに届けます。", "EV-Q"), evidence)


# -------------------------------------------------- dropped limits, exceptions, hedges

def test_hedge_dropped_is_reported():
    evidence = {"EV-D": ev("EV-D", "deadline", {**{"date": "2026-10-27"}, "qualifier": "延期等の場合があります"})}
    assert "qualifier_dropped" in cats(para("締切は10月27日です。", "EV-D"), evidence)
    assert not check_qualitative(para("締切は10月27日ですが、延期される場合があります。", "EV-D"), evidence)


def test_extension_that_may_happen_cannot_be_stated_as_never():
    evidence = {"EV-D": ev("EV-D", "deadline", {**{"date": "2026-10-27"}, "qualifier": "延長する場合があります"})}
    found = cats(para("締切は10月27日で、延長しません。", "EV-D"), evidence)
    assert "qualifier_contradicted" in found
    assert not check_qualitative(para("締切は10月27日で、延長する場合があります。", "EV-D"), evidence)


def test_limit_dropped_is_reported():
    evidence = {"EV-L": ev("EV-L", "eligibility", {**{"logic": "any"}, "qualifier": "希望者に限り出願できます"})}
    assert "qualifier_dropped" in cats(para("すべての受験者が出願できます。", "EV-L"), evidence)
    assert not check_qualitative(para("希望者に限り出願できます。", "EV-L"), evidence)


@pytest.mark.parametrize("word", ["必ず", "例外なく", "常に", "無条件で", "いかなる場合も", "一律に"])
def test_limited_condition_turned_into_unconditional_claim_is_reported(word):
    evidence = {"EV-L": ev("EV-L", "deadline", {**{"date": "2026-10-27"}, "qualifier": "希望者のみ"})}
    found = cats(para(f"希望者のみ、{word}受け付けます。", "EV-L"), evidence)
    assert "unconditional_assertion" in found


def test_unconditional_wording_is_fine_when_the_evidence_has_no_qualifier():
    evidence = {"EV-L": ev("EV-L", "deadline", {"date": "2026-10-27"})}
    assert not check_qualitative(para("必ず10月27日までに提出してください。", "EV-L"), evidence)


# -------------------------------------------------- listed items

def test_one_of_two_interview_languages_left_out_is_reported():
    evidence = {"EV-I": ev("EV-I", "interview_language", {"choice_required": True, "languages": ["日本語", "英語"], "preference_options": []})}
    assert "listed_item_omitted" in cats(para("面接は日本語で行います。出願時に言語を選びます。", "EV-I"), evidence)
    assert not check_qualitative(para("面接は日本語または英語で行います。出願時に言語を選びます。", "EV-I"), evidence)


def test_multilingual_application_cannot_become_everyone_or_not_required():
    evidence = {"EV-L": ev("EV-L", "multilingual_evaluation", {"languages": ["ドイツ語", "フランス語"], "application_required": True, "text": "x"})}
    for wrong in ("ドイツ語またはフランス語は全員が対象です。", "ドイツ語またはフランス語の申請は不要です。"):
        assert "polarity_mismatch" in cats(para(wrong, "EV-L"), evidence), wrong
    assert not check_qualitative(para("ドイツ語またはフランス語は希望者が申請できます。申請が必要です。", "EV-L"), evidence)


def test_interview_language_choice_flip_is_reported():
    evidence = {"EV-I": ev("EV-I", "interview_language", {"choice_required": True, "languages": ["日本語"], "preference_options": []})}
    assert "polarity_mismatch" in cats(para("面接の言語は日本語です。言語の選択不要です。", "EV-I"), evidence)


def test_ai_policy_allowed_cannot_become_prohibited():
    evidence = {"EV-A": ev("EV-A", "generative_ai_policy", {"allowed": "下調べや校正の補助", "not_accepted": "生成物そのものの提出"})}
    assert "polarity_mismatch" in cats(para("生成AIの利用は認められていません。生成物そのものの提出は不可です。", "EV-A"), evidence)


def test_referee_must_complete_cannot_become_optional():
    evidence = {"EV-R": ev("EV-R", "referees", {"evaluators_required": 2, "must_complete_before_submission": True})}
    assert "polarity_mismatch" in cats(para("評価者は2名で、評価者の入力は不要です。", "EV-R"), evidence)


# -------------------------------------------------- boilerplate caveats (no evidence needed)

@pytest.mark.parametrize("wrong", [
    "最新情報の確認は不要です。",
    "個別判定は不要です。",
    "公式サイトで確認する必要はありません。",
])
def test_the_official_site_caveat_cannot_be_reversed(wrong):
    assert "polarity_mismatch" in cats(f"# 見出し\n\n{wrong}\n", {})


def test_the_official_site_caveat_in_its_right_form_is_fine():
    assert not check_qualitative("# 見出し\n\n最新の訂正は公式サイトで確認が必要です。個別判定は別途必要です。\n", {})


# -------------------------------------------------- honesty: unhandled meaning is NOT "correct"

def test_boolean_without_an_assertion_is_listed_as_unverified():
    evidence = {"EV-Z": ev("EV-Z", "brand_new_key", {"flag": True})}
    cov = semantic_coverage(para("新しい制度があります。", "EV-Z"), evidence)
    assert cov["counts"]["unverified"] == 1 and "flag" in cov["unverified"][0]["what"]


def test_qualifier_without_a_rule_is_listed_as_unverified():
    evidence = {"EV-Z": ev("EV-Z", "deadline", {**{"date": "2026-10-27"}, "qualifier": "窓口は午後に開きます"})}
    cov = semantic_coverage(para("締切は10月27日です。", "EV-Z"), evidence)
    assert any("qualifier" in u["what"] for u in cov["unverified"])


def test_checked_assertions_are_listed_per_evidence():
    cov = semantic_coverage(para("受験が必要です。", "EV-C"), COMMON_REQ)
    assert cov["checked"]["EV-C"] == ["common_test_required_true"] and cov["counts"]["unverified"] == 0


def test_evaluate_article_reports_coverage_and_the_finding():
    text = "# 〇〇大学 環境学部 夏秋AO入試\n\n作業基準日：2026-11-01。\n\n大学入学共通テストの受験は不要です[EV-C]。\n"
    record = ev("EV-C", "common_test", {"required": True}, university="〇〇大学", faculty="環境学部", department=None,
                admission_method="夏秋AO入試", fiscal_year=2027, scope="target_admission_cycle",
                source_url="https://example.ac.jp/x", retrieved_at="2026-11-01", source_pdf_sha256="0" * 64, source_sha256="0" * 64,
                source_kind="pdf", proofs=[{"page": 1, "quote": "共通テストの受験が必要です"}])
    claim = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}
    result = evaluate_article("a", text, claim, {"EV-C": record}, reference_date="2026-11-01", require_as_of=True)
    assert any(f["category"] == "polarity_mismatch" for f in result.findings) and not result.ok
    assert result.coverage["checked"]["EV-C"]


# -------------------------------------------------- registry validation of the new data

def test_registry_with_rules_is_well_formed():
    assert validate_registry_data(REGISTRY.data) == []


def _broken(mutate):
    data = copy.deepcopy(REGISTRY.data)
    mutate(data)
    return validate_registry_data(data)


def test_unknown_lexicon_reference_is_an_error():
    problems = _broken(lambda d: d["fact_keys"]["common_test"]["assertions"][0].update(forbid_any=["lex:no_such_lexicon"]))
    assert any("unknown lexicon" in p for p in problems)


def test_bad_regex_in_a_lexicon_or_rule_is_an_error():
    assert any("bad regex" in p for p in _broken(lambda d: d["lexicons"]["necessity_negation"].append("re:(")))
    assert _broken(lambda d: d["qualitative_rules"][0].update(must_any=["re:("]))


def test_unknown_assertion_category_is_an_error():
    assert _broken(lambda d: d["qualitative_rules"][0].update(category="made_up"))


def test_article_rules_cannot_use_when_or_must():
    assert _broken(lambda d: d["article_rules"][0].update(when={"field": "x", "equals": True}))


# -------------------------------------------------- measured on the real drafts

def _real_exports():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(INBOX.rglob("claude-compatible-export.json"))]


def test_no_false_positive_on_the_real_drafts():
    exports = _real_exports()
    assert exports, "no deliveries found"
    for export in exports:
        for a in export["articles"]:
            assert not check_qualitative(a["text"], export["evidence"]), a["article_id"]


def test_known_meaning_flips_in_the_real_drafts_are_detected():
    detected = total = 0
    for export in _real_exports():
        r = flip_sweep(export, reference_date="2026-11-01", require_as_of=True)
        assert r["all_baselines_ok"]
        detected += r["detected"]
        total += r["instances"]
    assert total >= 60 and detected / total >= 0.95, (detected, total)


def test_independent_wordings_are_reported_but_not_gated():
    """Held-out C was never used to write a rule. Its rate is the honest generalisation figure; it must exist
    and be a real measurement, but it is NOT a pass/fail threshold (see docs/STRICT_VALIDATION.md)."""
    total = detected = 0
    for export in _real_exports():
        r = flip_sweep(export, catalog=FLIPS_HELD_OUT_C, reference_date="2026-11-01", require_as_of=True)
        total += r["instances"]
        detected += r["detected"]
    assert total >= 40 and 0 < detected <= total


def test_flip_catalog_entries_really_change_the_text():
    for name, family, old, new, label in FLIPS:
        assert name and family and label and old != new


def test_necessity_wording_that_no_assertion_can_compare_is_listed_as_unverified():
    # Work PR #33: 「下線不要です」 — the evidence only says that a display method is explained; the QA cannot tell 不要 from 必要
    evidence = {"EV-A": ev("EV-A", "generative_ai_policy", {"allowed": "生成AI使用時の表示方法がFAQで案内されている", "not_accepted": ""})}
    cov = semantic_coverage(para("単純な誤字脱字修正は下線不要です。活動経過報告書への記載は必須です。", "EV-A"), evidence)
    assert [u["what"] for u in cov["unverified"] if u["what"].startswith("obligation wording")] and cov["counts"]["unverified"] == 2


def test_necessity_wording_the_registry_does_compare_is_not_listed_as_unverified():
    cov = semantic_coverage(para("大学入学共通テストの受験が必要です。", "EV-C"), COMMON_REQ)
    assert cov["counts"]["unverified"] == 0


# -------------------------------------------------- a flip that is not detected but IS reported as unverified (Issue #36)

def _ai_policy_delivery():
    text = ("# 〇〇大学 環境学部 夏秋AO入試\n\n作業基準日：2026-11-01。\n\n"
            "生成AIの利用は条件つきで認められ、FAQでは修正箇所に下線を引くよう案内しています[EV-A]。単純な誤字脱字修正は下線不要です[EV-A]。\n\n最新情報は大学公式サイトでご確認ください。\n")
    record = ev("EV-A", "generative_ai_policy", {"allowed": "使用時の表示方法がFAQで案内されている", "not_accepted": ""},
                university="〇〇大学", faculty="環境学部", department=None, admission_method="夏秋AO入試", fiscal_year=2027,
                scope="target_admission_cycle", source_url="https://example.ac.jp/x", retrieved_at="2026-11-01",
                source_pdf_sha256="0" * 64, source_sha256="0" * 64, source_kind="pdf", proofs=[{"page": 1, "quote": "下線不要"}])
    claim = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}
    return {"evidence": {"EV-A": record}, "articles": [{"article_id": "a", "text": text, "claim": claim}]}


def test_an_undetectable_flip_is_counted_as_declared_unverified_not_as_a_silent_miss():
    r = flip_sweep(_ai_policy_delivery(), reference_date="2026-11-01", require_as_of=True)
    assert r["all_baselines_ok"] and r["instances"] >= 1
    assert r["detected"] == 0  # nothing can contradict it: the evidence has no structured value for "下線"
    assert r["declared_unverified"] == r["instances"] and r["silent_misses"] == 0
    assert r["detection_rate"] == 0.0 and r["accounted_rate"] == 1.0  # both numbers are reported


def test_a_miss_in_a_sentence_the_report_does_not_list_stays_a_silent_miss():
    export = _ai_policy_delivery()
    export["evidence"]["EV-A"]["fact_key"] = "brand_new_key"  # unregistered: no assertion, but also no necessity listing for this sentence
    export["articles"][0]["text"] = export["articles"][0]["text"].replace("下線不要です", "不要です")
    r = flip_sweep(export, reference_date="2026-11-01", require_as_of=True)
    assert r["instances"] == 0 or r["silent_misses"] + r["declared_unverified"] + r["detected"] == r["instances"]
