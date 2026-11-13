"""Issue #28: the three notice keys Work proposed (maintenance_notice, multilingual_evaluation,
fee_refund) and the HTML source contract (source_pdf_sha256 = null, source_sha256, source_kind =
html, one logical page). Structures mirror what Work described; the data is synthetic."""
import datetime

import pytest

from src.article_qa.evaluate import evaluate_article
from src.integration import audit_handoff
from src.integration.validate_export import validate_records
from src.regression.checks import evaluate_export, Thresholds
from src.verify.as_of import check_as_of, event_end
from src.verify.fact_registry import get_registry
from src.versioning import impact
from src.versioning.snapshot import snapshot_from_evidence, source_hash

REGISTRY = get_registry()
PDF_SHA = "a" * 64
HTML_SHA = "b" * 64
CLAIM = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}
LOOSE = Thresholds(body_detection_min=0.0, citation_id_detection_min=0.0)


def rec(eid, key, value, quote, page=1, pdf=None, html=None, **extra):
    record = {"evidence_id": eid, "university": "〇〇大学", "faculty": "環境学部", "department": None,
              "admission_method": "夏秋AO入試", "fiscal_year": 2027, "fact_key": key, "value": value,
              "scope": "target_admission_cycle", "source_url": "https://example.ac.jp/x", "retrieved_at": "2026-11-01",
              "proofs": [{"page": page, "quote": quote}]}
    if html:
        record.update(source_pdf_sha256=None, source_sha256=html, source_kind="html")
    else:
        record.update(source_pdf_sha256=pdf, source_sha256=pdf, source_kind="pdf")
    record.update(extra)
    return record


def maintenance(**value):
    base = {"text": "出願システムの一時的なメンテナンス告知", "published_date": "2026-10-21", "outage_end": None}
    return rec("EV-M", "maintenance_notice", {**base, **value}, "公開日：2026.10.21 出願システムは一時的なメンテナンスを行います", html=HTML_SHA)


def multilingual(**value):
    base = {"languages": ["ドイツ語", "フランス語"], "application_required": True, "text": "申請と書類提出で追加の言語能力を評価"}
    return rec("EV-L", "multilingual_evaluation", {**base, **value}, "ドイツ語またはフランス語の運用能力を評価します", page=12, pdf=PDF_SHA)


def refund(**value):
    base = {"amount": 13000, "currency": "JPY", "deadline": "2026-10-27", "text": "第1次選考不合格者が請求書を提出する手続"}
    return rec("EV-F", "fee_refund", {**base, **value}, "検定料17,000円のうち13,000円を返還します 請求書は10月27日までに到着", pdf=PDF_SHA)


# ------------------------------------------------ the registry entries

def test_the_three_keys_are_registered_as_proposed_by_work():
    spec = {k: REGISTRY.lookup(k) for k in ("maintenance_notice", "multilingual_evaluation", "fee_refund")}
    assert all(s and s["status"] == "active" for s in spec.values()) and REGISTRY.version >= "1.3.0"
    m, ml, f = (spec[k]["value"] for k in ("maintenance_notice", "multilingual_evaluation", "fee_refund"))
    assert (m["text"]["type"], m["text"]["required"], m["published_date"]["type"], m["published_date"]["required"]) == ("string", True, "iso_date", True)
    assert m["outage_end"]["type"] == "iso_datetime" and m["outage_end"]["nullable"] and not m["outage_end"].get("required")
    assert (ml["languages"]["type"], ml["languages"]["required"], ml["application_required"]["type"], ml["application_required"]["required"],
            ml["text"]["required"]) == ("string_list", True, "boolean", True, True)
    assert (f["amount"]["type"], f["amount"]["kind"], f["amount"]["required"], f["deadline"]["type"], f["deadline"]["required"],
            f["text"]["required"]) == ("integer", "yen", True, "iso_date", True, True)
    assert set(spec["maintenance_notice"]["topic_keywords"]) == {"システム", "メンテナンス", "アクセス", "復旧"}
    assert set(spec["multilingual_evaluation"]["topic_keywords"]) == {"多言語", "ドイツ語", "フランス語", "評価"}
    assert set(spec["fee_refund"]["topic_keywords"]) == {"検定料", "返還", "請求", "期限"}
    assert all(REGISTRY.stage(k) is None for k in spec)  # no fixed selection stage


def test_work_shaped_records_pass_the_registry_and_the_gate():
    records = {r["evidence_id"]: r for r in (maintenance(), multilingual(), refund())}
    assert get_registry().check_evidence(records)["by_severity"] == {"error": 0, "warning": 0, "notice": 0}
    result = validate_records(records)
    assert result["invalid_count"] == 0 and result["unregistered_fact_keys"] == []


@pytest.mark.parametrize("record,category", [
    (refund(deadline="tomorrow"), "value_type_mismatch"),
    (refund(amount="13000"), "value_type_mismatch"),
    (refund(amount=None), "missing_required_field"),
    (maintenance(published_date="2026-13-01"), "value_type_mismatch"),
    (multilingual(application_required="yes"), "value_type_mismatch"),
    (multilingual(languages="ドイツ語"), "value_type_mismatch"),
])
def test_wrong_values_are_errors(record, category):
    assert category in {i.category for i in REGISTRY.check_record(record) if i.severity == "error"}


def test_a_missing_required_field_is_an_error_but_a_null_outage_end_is_fine():
    record = maintenance()
    record["value"].pop("published_date")
    assert "missing_required_field" in {i.category for i in REGISTRY.check_record(record)}
    assert REGISTRY.check_record(maintenance(outage_end=None)) == []
    assert REGISTRY.check_record(maintenance(outage_end="2026-11-10T18:00:00+09:00")) == []


def test_the_optional_fee_paid_field_is_accepted_and_checked_against_the_article():
    assert REGISTRY.check_record(refund(fee_paid=17000)) == []
    text = ("# 〇〇大学 環境学部 夏秋AO入試\n\n作業基準日：2026-11-01。\n\n"
            "納付した検定料17,000円のうち13,000円が返還されます。[EV-F]\n\n最新情報は大学公式サイトでご確認ください。\n")
    with_paid = evaluate_article("a", text, CLAIM, {"EV-F": refund(fee_paid=17000)}, reference_date="2026-11-01", require_as_of=True)
    assert with_paid.ok, with_paid.findings
    without = evaluate_article("a", text, CLAIM, {"EV-F": refund()}, reference_date="2026-11-01", require_as_of=True)
    assert "quantity_mismatch" in {f["category"] for f in without.findings}  # 17,000 is not in the evidence: not guessed


# --------------------------------------------- the HTML source contract

@pytest.mark.parametrize("change,category,severity", [
    ({"source_pdf_sha256": PDF_SHA}, "source_contract_violation", "error"),  # an html page presented as a PDF
    ({"source_sha256": None}, "source_contract_violation", "error"),
    ({"source_sha256": "xyz"}, "source_contract_violation", "error"),
    ({"proofs": [{"page": 2, "quote": "x"}]}, "source_contract_violation", "warning"),
    ({"source_kind": "docx"}, "unregistered_source_kind", "warning"),
])
def test_html_source_contract(change, category, severity):
    record = {**maintenance(), **change}
    hits = [i for i in REGISTRY.check_record(record) if i.category == category]
    assert hits and hits[0].severity == severity, [i.to_dict() for i in REGISTRY.check_record(record)]


def test_a_pdf_source_needs_its_hash_and_legacy_records_without_a_kind_are_untouched():
    assert "source_contract_violation" in {i.category for i in REGISTRY.check_record({**refund(), "source_pdf_sha256": None})}
    legacy = refund()
    for k in ("source_kind", "source_sha256"):
        legacy.pop(k)
    assert REGISTRY.check_record(legacy) == []


def test_source_hash_is_the_pdf_hash_else_the_page_body_hash():
    assert source_hash(refund()) == PDF_SHA and source_hash(maintenance()) == HTML_SHA
    assert source_hash({"source_pdf_sha256": None}) is None


# ---------------------------------- article checks use the new keys

EVIDENCE = {r["evidence_id"]: r for r in (maintenance(), multilingual(), refund())}
ARTICLE = ("# 〇〇大学 環境学部 夏秋AO入試｜追加の告知\n\n作業基準日：2026-11-01。\n\n"
           "公式サイトの告知（公開日2026年10月21日）で、出願システムのメンテナンスが案内されています。[EV-M]\n\n"
           "希望者はドイツ語またはフランス語の多言語評価を申請できます。申請が必要です。[EV-L]\n\n"
           "第1次選考の不合格者は、検定料のうち13,000円の返還を請求できます。請求書の到着期限は2026年10月27日です。[EV-F]\n\n"
           "最新情報は大学公式サイトでご確認ください。\n")


def categories(text, evidence=EVIDENCE, **kw):
    return {f["category"] for f in evaluate_article("a", text, CLAIM, evidence, reference_date="2026-11-01", require_as_of=True, **kw).findings}


def test_a_correct_article_on_the_new_keys_is_clean():
    report = evaluate_article("a", ARTICLE, CLAIM, EVIDENCE, reference_date="2026-11-01", require_as_of=True)
    assert report.ok and report.notices == [], (report.findings, report.notices)


@pytest.mark.parametrize("old,new,expected", [
    ("13,000円", "14,000円", "quantity_mismatch"),
    ("2026年10月27日", "2026年10月28日", "date_mismatch"),
    ("公開日2026年10月21日", "公開日2026年10月22日", "date_mismatch"),
    ("[EV-F]", "[EV-NOPE]", "unknown_citation"),
])
def test_edits_to_the_new_keys_are_detected(old, new, expected):
    assert expected in categories(ARTICLE.replace(old, new, 1))


def test_citing_a_notice_fact_in_an_unrelated_sentence_is_flagged():
    unrelated = ARTICLE.replace(
        "第1次選考の不合格者は、検定料のうち13,000円の返還を請求できます。請求書の到着期限は2026年10月27日です。[EV-F]",
        "面接の準備は2026年10月27日までに進めましょう。[EV-F]")
    assert "citation_topic_mismatch" in categories(unrelated)


# ------------------ the end date comes from the registered field (#11)

def test_event_end_uses_the_registered_end_field():
    assert event_end(refund()) == datetime.date(2026, 10, 27)
    assert event_end(maintenance(outage_end="2026-11-10T18:00:00+09:00")) == datetime.date(2026, 11, 10)
    assert event_end(maintenance()) is None  # outage_end null: no end known — published_date is NOT used instead


def test_refund_deadline_wording_is_checked_against_the_as_of_date():
    base = ARTICLE.replace("請求書の到着期限は2026年10月27日です。[EV-F]", "請求書の到着期限は2026年10月27日です。[EV-F]\n\n請求期限はこれから迎えます。[EV-F]")
    found = {i.category for i in check_as_of(base, EVIDENCE, reference_date="2026-11-01")}
    assert "upcoming_claim_mismatch" in found  # the deadline (10/27) is before the as-of date (11/01)
    early = ARTICLE.replace("2026-11-01", "2026-10-22").replace("[EV-F]", "[EV-F]\n\n返還請求は既に終了しました。[EV-F]", 1)
    assert "elapsed_claim_mismatch" in {i.category for i in check_as_of(early, EVIDENCE, reference_date="2026-11-01")}


def test_maintenance_wording_uses_outage_end_when_there_is_one():
    evidence = {**EVIDENCE, "EV-M": maintenance(outage_end="2026-11-10T18:00:00+09:00")}
    text = ARTICLE.replace("案内されています。[EV-M]", "案内されています。[EV-M]\n\nメンテナンスは既に終了しました。[EV-M]")
    assert "elapsed_claim_mismatch" in {i.category for i in check_as_of(text, evidence, reference_date="2026-11-01")}
    assert not [i for i in check_as_of(text, EVIDENCE, reference_date="2026-11-01") if i.category == "elapsed_claim_mismatch"]  # no end known: nothing guessed


# ------------------------- versioning, harness and audit with HTML sources

def test_versioning_follows_an_html_source_by_its_body_hash():
    html_only = {"EV-M": maintenance()}
    snap = snapshot_from_evidence(html_only, HTML_SHA, "keio-news", "2026-11-01")
    assert snap.pages[0].startswith("公開日")
    export = {"evidence": html_only, "articles": [{"article_id": "a", "text": "公式の告知です[EV-M]。"}]}
    assert impact.assess_export(export, [snap])["summary"]["evidence_intact"] == 1
    changed = snapshot_from_evidence({"EV-M": {**maintenance(), "proofs": [{"page": 1, "quote": "公開日：2026.10.22 出願システムは一時的なメンテナンスを行います"}]}},
                                     HTML_SHA, "keio-news", "2026-11-02")
    changed.sha256 = "c" * 64
    changed.supersedes = [HTML_SHA]
    result = impact.assess_export(export, [changed])
    assert result["evidence"]["EV-M"]["status"] == "value_change" and result["republish_required"] == ["a"]


def test_a_delivery_mixing_pdf_and_html_evidence_passes_every_harness_check():
    export = {"evidence": EVIDENCE, "articles": [{"article_id": "notices-art", "text": ARTICLE, "claim": CLAIM}]}
    result = evaluate_export("mixed", export, LOOSE)
    assert result["ok"], result["failures"]
    assert result["versioning"]["facts_checked"] == 3 and result["mutation"]["as_of"][0] == result["mutation"]["as_of"][1]


def test_the_pdf_audit_never_treats_html_evidence_as_a_pdf(tmp_path):
    export = {"evidence": EVIDENCE, "articles": []}
    assert audit_handoff.check_source_pdfs(export, None)["non_pdf_evidence"] == ["EV-M"]
    assert audit_handoff.check_source_pdfs(export, None)["status"] == "skipped"
    html_only = {"evidence": {"EV-M": maintenance()}, "articles": []}
    (tmp_path / "pdfs").mkdir()
    result = audit_handoff.check_source_pdfs(html_only, tmp_path / "pdfs")
    assert result["status"] == "skipped" and "no PDF-backed evidence" in result["reason"] and result["non_pdf_evidence"] == ["EV-M"]
