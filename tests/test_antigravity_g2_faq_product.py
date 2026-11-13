"""Self-test suite for M1.g2 FAQ Structured Extraction & STR-076 / STR-099 / STR-102 Policy."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.db_contract.faq_structured as fq
from src.db_contract.faq_structured import (
    FAQRecord,
    UNCONFIRMED_PREAMBLE_TEXT,
    UNCONFIRMED_SECTION_HEADING,
    parse_faq_candidate,
    render_unconfirmed_faq_section,
    verify_unconfirmed_faq_section,
)


def test_str076_unknown_scope_preservation() -> None:
    """Test STR-076 invariant: missing scope yields unknown status and None fields."""
    record = parse_faq_candidate(
        faq_id="faq_001",
        source_id="faq_html_doc",
        raw_question="他大学との併願は可能ですか？",
        raw_answer="総合選抜において他大学との併願は制限していません。",
        evidence_id="EV-FAQ-01",
        scope_context={},
    )
    assert record.scope_status == "unknown"
    assert record.fiscal_year is None
    assert record.faculty is None
    assert record.evidence_id == "EV-FAQ-01"
    assert record.source_sha256 is None


def test_str076_rejection_of_inferred_scope() -> None:
    """Test STR-076 invariant: unknown scope records cannot carry inferred year or faculty."""
    raised = False
    try:
        FAQRecord(
            faq_id="faq_bad",
            source_id="src_doc",
            question="Q",
            answer="A",
            exact_quote="A",
            evidence_id="EV-1",
            scope_status="unknown",
            fiscal_year=2026,
        )
    except ValueError as e:
        raised = True
        assert "STR-076 VIOLATION" in str(e)
    assert raised, "Expected ValueError on inferred fiscal_year with unknown scope"


def test_str102_no_verified_promotion_path() -> None:
    """Test STR-102 invariant: PR #286 is sole g2 baseline; no verified promotion path in PR #306."""
    assert not hasattr(fq, "build_scope_proof")
    assert not hasattr(fq, "_verify_scope_proof")

    rec = parse_faq_candidate(
        faq_id="faq_v01",
        source_id="src_doc",
        raw_question="理工学類の推薦要件は？",
        raw_answer="評定平均4.0以上を原則とします。",
        evidence_id="EV-FAQ-V01",
        scope_context={
            "fiscal_year": 2026,
            "faculty": "理工学類",
            "scope_verified_by_source": True,
            "scope_source_ref": "OFFICIAL_GUIDE_P12",
        },
    )
    assert rec.scope_status == "unknown"
    assert rec.fiscal_year is None
    assert rec.faculty is None
    assert rec.scope_source_ref is None

    raised = False
    try:
        FAQRecord(
            faq_id="faq_v02",
            source_id="src_doc",
            question="Q",
            answer="A",
            exact_quote="A",
            evidence_id="EV-FAQ-V02",
            scope_status="verified",
            fiscal_year=2026,
            faculty="理工学類",
            scope_source_ref="OFFICIAL_GUIDE_P12",
        )
    except ValueError as e:
        raised = True
        assert "STR-102" in str(e)
    assert raised


def test_unverified_context_retains_unknown_status() -> None:
    """Test STR-076 invariant: external year/faculty without source verification remains unknown."""
    rec = parse_faq_candidate(
        faq_id="faq_unverified_ctx",
        source_id="src_doc",
        raw_question="理工学類の推薦要件は？",
        raw_answer="評定平均4.0以上を原則とします。",
        evidence_id="EV-FAQ-V01",
        scope_context={
            "fiscal_year": 2026,
            "faculty": "理工学類",
        },
    )
    assert rec.scope_status == "unknown"
    assert rec.fiscal_year is None
    assert rec.faculty is None
    assert rec.scope_source_ref is None


def test_render_and_verify_unconfirmed_faq_section() -> None:
    """Test rendering of unconfirmed FAQ section with owner-adopted wording and full citations."""
    rec1 = parse_faq_candidate(
        faq_id="faq_01",
        source_id="html_doc",
        raw_question="検定料の支払期限はいつですか？",
        raw_answer="出願締切日の前日23:59までに入金してください。",
        evidence_id="EV-FAQ-01",
    )
    rec2 = parse_faq_candidate(
        faq_id="faq_02",
        source_id="html_doc",
        raw_question="調査書の再提出は必要ですか？",
        raw_answer="一度受理された書類の再提出は不要です。",
        evidence_id="EV-FAQ-02",
    )

    rendered = render_unconfirmed_faq_section([rec1, rec2])
    assert UNCONFIRMED_SECTION_HEADING in rendered
    assert UNCONFIRMED_PREAMBLE_TEXT in rendered
    assert "[EV-FAQ-01]" in rendered
    assert "[EV-FAQ-02]" in rendered

    valid, errors = verify_unconfirmed_faq_section(rendered, [rec1, rec2])
    assert valid, f"Verification failed: {errors}"


def test_tamper_detection_year_leak() -> None:
    """Test tamper detection if concrete fiscal year is improperly added to unconfirmed section."""
    rec = parse_faq_candidate(
        faq_id="faq_01",
        source_id="html_doc",
        raw_question="出願資格について",
        raw_answer="高等学校を卒業した者。",
        evidence_id="EV-FAQ-01",
    )
    rendered = render_unconfirmed_faq_section([rec])
    tampered = rendered + "\n注: 2026年度入試に適用されます。"

    valid, errors = verify_unconfirmed_faq_section(tampered, [rec])
    assert not valid
    assert any("STR-076 VIOLATION: Unauthorized fiscal year" in e for e in errors)


def test_tamper_detection_missing_citation() -> None:
    """Test tamper detection if evidence citation is omitted or altered."""
    rec = parse_faq_candidate(
        faq_id="faq_01",
        source_id="html_doc",
        raw_question="出願資格について",
        raw_answer="高等学校を卒業した者。",
        evidence_id="EV-FAQ-01",
    )
    rendered = render_unconfirmed_faq_section([rec])
    tampered = rendered.replace("[EV-FAQ-01]", "")

    valid, errors = verify_unconfirmed_faq_section(tampered, [rec])
    assert not valid
    assert any("Missing required evidence citation" in e for e in errors)


def test_segregation_unauthorized_evidence_tag_rejected() -> None:
    """Test that planted or unauthorized evidence tags in unconfirmed section are rejected."""
    unconfirmed = parse_faq_candidate(
        faq_id="faq_u",
        source_id="html_doc",
        raw_question="共通事項Q",
        raw_answer="共通回答A",
        evidence_id="EV-U",
    )
    rendered = render_unconfirmed_faq_section([unconfirmed])
    injected = rendered + "\n- [EV-V] 外部回答"
    valid, errors = verify_unconfirmed_faq_section(injected, [unconfirmed])
    assert not valid
    assert any("SEGREGATION VIOLATION" in e for e in errors)
