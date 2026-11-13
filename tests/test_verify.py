import datetime
import hashlib
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.verify import consistency, date_year, pdf_hash, schema, url_check


# --- schema ---

def test_valid_evidence_passes_schema():
    record = {
        "evidence_id": "EV-0001",
        "university": "〇〇大学",
        "faculty": "理学部",
        "department": "数学科",
        "admission_method": "総合型選抜",
        "fiscal_year": 2026,
        "quota": 30,
        "source_url": "https://example.ac.jp/admissions/2026.pdf",
        "source_pdf_sha256": "a" * 64,
        "retrieved_at": "2026-10-01",
    }
    assert schema.validate_evidence(record) == []


def test_invalid_evidence_fails_schema():
    record = {"university": "〇〇大学"}  # missing required fields
    errors = schema.validate_evidence(record)
    assert errors


def test_malformed_source_url_rejected_by_format_check():
    record = {
        "evidence_id": "EV-0003",
        "university": "〇〇大学",
        "faculty": "理学部",
        "admission_method": "総合型選抜",
        "fiscal_year": 2026,
        "source_url": "not a valid uri at all",
        "retrieved_at": "2026-10-01",
    }
    errors = schema.validate_evidence(record)
    assert errors


def test_malformed_retrieved_at_rejected_by_format_check():
    record = {
        "evidence_id": "EV-0004",
        "university": "〇〇大学",
        "faculty": "理学部",
        "admission_method": "総合型選抜",
        "fiscal_year": 2026,
        "source_url": "https://example.ac.jp/x.pdf",
        "retrieved_at": "not-a-date",
    }
    errors = schema.validate_evidence(record)
    assert errors


def test_invalid_pdf_hash_format_rejected():
    record = {
        "evidence_id": "EV-0002",
        "university": "〇〇大学",
        "faculty": "理学部",
        "admission_method": "総合型選抜",
        "fiscal_year": 2026,
        "source_url": "https://example.ac.jp/x.pdf",
        "source_pdf_sha256": "not-a-hash",
        "retrieved_at": "2026-10-01",
    }
    assert schema.validate_evidence(record)


# --- date_year ---

def test_fiscal_year_boundary_april():
    assert date_year.japanese_fiscal_year(datetime.date(2026, 3, 31)) == 2025
    assert date_year.japanese_fiscal_year(datetime.date(2026, 4, 1)) == 2026


def test_plausible_fiscal_year_ok():
    result = date_year.check_fiscal_year_plausible(2026, datetime.date(2025, 11, 1))
    assert result.ok


def test_implausible_future_fiscal_year_flagged():
    result = date_year.check_fiscal_year_plausible(2040, datetime.date(2025, 11, 1))
    assert not result.ok


def test_claim_year_mismatch_flagged():
    result = date_year.check_claim_matches_evidence_year(2026, [2025])
    assert not result.ok


def test_claim_year_match_ok():
    result = date_year.check_claim_matches_evidence_year(2026, [2026, 2026])
    assert result.ok


# --- url_check ---

def test_https_url_format_ok():
    assert url_check.check_url_format("https://example.ac.jp/page").ok


def test_http_url_format_flagged_as_insecure():
    assert not url_check.check_url_format("http://example.ac.jp/page").ok


def test_malformed_url_flagged():
    assert not url_check.check_url_format("not a url").ok


def _mock_response(status: int):
    resp = MagicMock()
    resp.status = status
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_reachable_ok_on_200():
    with patch("src.verify.url_check.urllib.request.urlopen", return_value=_mock_response(200)):
        result = url_check.check_url_reachable("https://example.ac.jp/page")
    assert result.ok
    assert result.status_code == 200


def test_reachable_flags_404():
    error = urllib.error.HTTPError("https://example.ac.jp/page", 404, "Not Found", {}, None)
    with patch("src.verify.url_check.urllib.request.urlopen", side_effect=error):
        result = url_check.check_url_reachable("https://example.ac.jp/page")
    assert not result.ok
    assert result.status_code == 404


def test_reachable_falls_back_to_get_when_head_rejected():
    head_error = urllib.error.HTTPError("https://example.ac.jp/page", 405, "Method Not Allowed", {}, None)

    def fake_urlopen(req, timeout):
        if req.get_method() == "HEAD":
            raise head_error
        return _mock_response(200)

    with patch("src.verify.url_check.urllib.request.urlopen", side_effect=fake_urlopen):
        result = url_check.check_url_reachable("https://example.ac.jp/page")
    assert result.ok
    assert result.status_code == 200


def test_reachable_network_error_flagged():
    with patch(
        "src.verify.url_check.urllib.request.urlopen",
        side_effect=urllib.error.URLError("name resolution failed"),
    ):
        result = url_check.check_url_reachable("https://example.ac.jp/page")
    assert not result.ok
    assert "unreachable" in result.reason


def test_reachable_skips_network_call_for_insecure_url():
    with patch("src.verify.url_check.urllib.request.urlopen") as mock_urlopen:
        result = url_check.check_url_reachable("http://example.ac.jp/page")
    assert not result.ok
    mock_urlopen.assert_not_called()


# --- pdf_hash ---

def test_pdf_hash_match(tmp_path: Path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4 fake content")
    expected = hashlib.sha256(p.read_bytes()).hexdigest()
    result = pdf_hash.verify_pdf_hash(p, expected)
    assert result.ok


def test_pdf_hash_mismatch(tmp_path: Path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4 fake content")
    result = pdf_hash.verify_pdf_hash(p, "0" * 64)
    assert not result.ok


def test_pdf_hash_missing_expected(tmp_path: Path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4 fake content")
    result = pdf_hash.verify_pdf_hash(p, None)
    assert not result.ok


# --- consistency ---

EVIDENCE = {
    "university": "〇〇大学",
    "faculty": "理学部",
    "department": "数学科",
    "admission_method": "総合型選抜",
    "fiscal_year": 2026,
    "quota": 30,
}


def test_quota_scope_match_ok():
    claim = {"university": "〇〇大学", "faculty": "理学部", "admission_method": "総合型選抜", "fiscal_year": 2026}
    assert consistency.check_quota_scope(claim, EVIDENCE) is None


def test_quota_scope_mismatch_detected():
    claim = {"university": "〇〇大学", "faculty": "工学部", "admission_method": "総合型選抜", "fiscal_year": 2026}
    issue = consistency.check_quota_scope(claim, EVIDENCE)
    assert issue is not None
    assert issue.category == "quota_scope_mismatch"


def test_entity_confusion_detected():
    claim_text = "工学部の総合型選抜について紹介します。"
    issue = consistency.check_entity_confusion(claim_text, EVIDENCE)
    assert issue is not None
    assert issue.category == "entity_mismatch"


def test_entity_confusion_not_flagged_when_consistent():
    claim_text = "〇〇大学理学部の総合型選抜の募集人数は30名です。"
    assert consistency.check_entity_confusion(claim_text, EVIDENCE) is None


def test_numeric_without_citation_flagged():
    text = "募集人数は約30名です。"
    issues = consistency.check_numeric_citation_traceability(text, known_evidence_ids={"EV-0001"})
    assert any(i.category == "unsupported_number" for i in issues)


def test_numeric_with_valid_citation_ok():
    text = "募集人数は約30名[EV-0001]です。"
    issues = consistency.check_numeric_citation_traceability(text, known_evidence_ids={"EV-0001"})
    assert issues == []


def test_numeric_with_unknown_citation_flagged():
    text = "募集人数は約30名[EV-9999]です。"
    issues = consistency.check_numeric_citation_traceability(text, known_evidence_ids={"EV-0001"})
    assert any(i.category == "unknown_citation" for i in issues)
