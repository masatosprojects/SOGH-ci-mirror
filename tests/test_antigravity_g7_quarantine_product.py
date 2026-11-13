"""Self-test suite for M1.g7 Diverse Formats & Quarantine Staging Product Implementation Candidate.
"""
from __future__ import annotations

import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db_contract.quarantine_staging import (
    RefusalCode,
    evaluate_html_structure_format,
    evaluate_table_cell_format,
    init_quarantine_schema,
    promote_candidate,
    register_authorized_reviewers,
    reject_candidate,
    review_candidate,
    stage_candidate,
)


def get_db_conn():
    conn = sqlite3.connect(":memory:")
    init_quarantine_schema(conn)
    return conn


def test_quarantine_staging_lifecycle():
    """Test standard quarantine -> review -> promotion lifecycle."""
    db_conn = get_db_conn()
    staging_id = stage_candidate(
        db_conn,
        staging_id="stg_001",
        source_id="src_doc_01",
        format_type="PDF_TABLE",
        extracted_key="admission_quota",
        extracted_value="35",
        isolation_reason="Initial ingestion",
        staged_by="stager_01",
    )
    assert staging_id == "stg_001"

    # Verify staged
    row = db_conn.execute(
        "SELECT quarantine_status, review_status FROM quarantine_staging_candidates WHERE staging_id = ?",
        ("stg_001",),
    ).fetchone()
    assert row[0] == "QUARANTINED"
    assert row[1] == "PENDING"

    # Promotion without review approval must be blocked
    unapproved_blocked = False
    try:
        promote_candidate(db_conn, "stg_001", fact_id="fact_001")
    except sqlite3.IntegrityError as e:
        unapproved_blocked = True
        assert "Promotion requires verified review_status APPROVED" in str(e)
    assert unapproved_blocked, "Expected promotion without approval to fail"

    # Review and approve
    register_authorized_reviewers(["auditor_01"])
    approved = review_candidate(db_conn, "stg_001", decision="APPROVED", reviewer="auditor_01")
    assert approved is True

    # Promote to canonical
    promoted = promote_candidate(db_conn, "stg_001", fact_id="fact_001")
    assert promoted is True

    # Verify canonical entry
    can_row = db_conn.execute(
        "SELECT key, value FROM canonical_facts_staging_target WHERE fact_id = ?",
        ("fact_001",),
    ).fetchone()
    assert can_row == ("admission_quota", "35")


def test_guard_reject_mutation_immutability():
    """Test trigger guard preventing mutation of REJECTED records."""
    db_conn = get_db_conn()
    stage_candidate(
        db_conn,
        staging_id="stg_rej",
        source_id="src_doc_01",
        format_type="PDF_TABLE",
        extracted_key="admission_quota",
        extracted_value="999",
    )
    reject_candidate(db_conn, "stg_rej", reason="Schema mismatch")

    # Attempting to mutate REJECTED status back to QUARANTINED must be aborted
    raised = False
    try:
        db_conn.execute(
            "UPDATE quarantine_staging_candidates SET quarantine_status = 'QUARANTINED' WHERE staging_id = 'stg_rej'"
        )
    except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
        raised = True
        assert "Cannot mutate status of REJECTED candidate" in str(e)
    assert raised, "Expected abort on mutating REJECTED candidate"

    # Attempting to mutate REJECTED status to PROMOTED must also be aborted
    raised_prom = False
    try:
        db_conn.execute(
            "UPDATE quarantine_staging_candidates SET quarantine_status = 'PROMOTED' WHERE staging_id = 'stg_rej'"
        )
    except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
        raised_prom = True
        assert "G-07 VIOLATION" in str(e)
    assert raised_prom, "Expected abort on promoting REJECTED candidate"


def test_guard_block_unquarantined_canonical_insert():
    """Test trigger guard blocking unquarantined writes into canonical target."""
    db_conn = get_db_conn()
    # Attempt direct insert without staging record
    raised = False
    try:
        db_conn.execute(
            "INSERT INTO canonical_facts_staging_target (fact_id, staging_id, key, value, promoted_at) VALUES ('f_fake', 'non_existent_stg', 'key', 'val', '2026-11-09T00:00:00Z')"
        )
    except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
        raised = True
        assert "G-07 VIOLATION" in str(e)
    assert raised, "Expected error on direct canonical insert"


def test_transactional_rollback_on_failed_promotion():
    """Test atomic rollback when canonical insert collides mid-flight."""
    register_authorized_reviewers(["reviewer"])
    db_conn = get_db_conn()
    stg1 = stage_candidate(db_conn, "stg_1", "src_1", "PDF", "k1", "v1", staged_by="stager_01")
    review_candidate(db_conn, "stg_1", "APPROVED", "reviewer")
    promote_candidate(db_conn, "stg_1", fact_id="fact_dup")

    stg2 = stage_candidate(db_conn, "stg_2", "src_1", "PDF", "k2", "v2", staged_by="stager_01")
    review_candidate(db_conn, "stg_2", "APPROVED", "reviewer")

    # Attempt to promote stg2 with duplicate fact_dup
    raised = False
    try:
        promote_candidate(db_conn, "stg_2", fact_id="fact_dup")
    except sqlite3.IntegrityError:
        raised = True
    assert raised

    # Status of stg_2 must be rolled back to QUARANTINED, NOT left as PROMOTED
    status = db_conn.execute(
        "SELECT quarantine_status FROM quarantine_staging_candidates WHERE staging_id = 'stg_2'"
    ).fetchone()[0]
    assert status == "QUARANTINED"


def test_table_refusal_matrix_ambiguous_multi_year():
    """Test refusal of table context containing multiple ambiguous fiscal years."""
    table_data = {
        "headers": ["学科", "2026年度", "2027年度募集人員"],
        "rows": [["物理学科", "20", "25"]],
        "context_text": "本表は令和8年度（2026年度）および令和9年度（2027年度）の定員比較を示す",
        "target_key": "admission_quota",
        "raw_cell_value": "25",
    }
    result = evaluate_table_cell_format(table_data)
    assert result.decision == "REFUSE"
    assert result.code == RefusalCode.AMBIGUOUS_MULTI_YEAR


def test_table_refusal_matrix_unknown_schema_key():
    """Test refusal when key is not in approved fact catalog."""
    table_data = {
        "headers": ["項目", "値"],
        "rows": [["サークル数", "120"]],
        "context_text": "2026年度 サークル一覧",
        "target_key": "unapproved_club_count",
        "raw_cell_value": "120",
    }
    result = evaluate_table_cell_format(table_data)
    assert result.decision == "REFUSE"
    assert result.code == RefusalCode.UNKNOWN_SCHEMA_KEY


def test_table_refusal_matrix_layout_collapse():
    """Test refusal on row column count mismatch."""
    table_data = {
        "headers": ["学部", "学科", "定員"],
        "rows": [["理学部", "15"]],  # Missing one column
        "context_text": "2026年度 募集人員",
        "target_key": "admission_quota",
        "raw_cell_value": "15",
    }
    result = evaluate_table_cell_format(table_data)
    assert result.decision == "REFUSE"
    assert result.code == RefusalCode.LAYOUT_COLLAPSE


def test_table_refusal_matrix_valid_acceptance():
    """Test valid table cell passes refusal check."""
    table_data = {
        "headers": ["学科", "募集人員"],
        "rows": [["数学科", "30"]],
        "context_text": "令和8年度（2026年度）学生募集要項 数学科募集人員",
        "target_key": "admission_quota",
        "raw_cell_value": "30",
    }
    result = evaluate_table_cell_format(table_data)
    assert result.decision == "ACCEPT"
    assert result.code == RefusalCode.ACCEPTED
    assert result.normalized_value == "30"


def test_html_structure_format():
    """Test HTML layout acceptance and draft class refusal."""
    draft_elem = {
        "tag": "div",
        "text": "出願締切: 10月15日",
        "attributes": {"class": "schedule-box draft-notice"},
    }
    assert evaluate_html_structure_format(draft_elem).decision == "REFUSE"

    valid_elem = {
        "tag": "span",
        "text": "募集人員: 40名",
        "attributes": {"class": "official-quota-value"},
    }
    res = evaluate_html_structure_format(valid_elem)
    assert res.decision == "ACCEPT"
    assert res.normalized_value == "募集人員: 40名"


if __name__ == "__main__":
    tests = [
        test_quarantine_staging_lifecycle,
        test_guard_reject_mutation_immutability,
        test_guard_block_unquarantined_canonical_insert,
        test_transactional_rollback_on_failed_promotion,
        test_table_refusal_matrix_ambiguous_multi_year,
        test_table_refusal_matrix_unknown_schema_key,
        test_table_refusal_matrix_layout_collapse,
        test_table_refusal_matrix_valid_acceptance,
        test_html_structure_format,
    ]
    passed = 0
    for t in tests:
        t()
        passed += 1
        print(f"  PASS: {t.__name__}")
    print(f"\nAll {passed}/{len(tests)} self-tests PASSED (100%).")

