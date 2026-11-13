"""Independent Adversarial QA Probes for Migrations 0012, 0013, and 0014 (Task A-17).

Target:
- 0012_g02_faq_unconfirmed_evidence.sql
- 0013_g07_quarantine_staging.sql
- 0014_g06_source_series.sql

Security Hypothesis:
All write-path restrictions, immutability guards, and append-only constraints
in migrations 0012-0014 must either:
1. HARD FAIL (raise IntegrityError/OperationalError via trigger RAISE(ABORT)), OR
2. BE DETECTED AS DRIFT by verify_schema_state() if the schema is tampered with (e.g. DROP TRIGGER / writable_schema).
Any evasion that mutates data without trigger abort AND without verify_schema_state() detection is a VULNERABILITY (FAIL).
"""

import hashlib
import sqlite3
from pathlib import Path
import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
from src.db_contract import additive_schema as ad
from src.versioning import series as sv


CASE_ID = "case"
SOURCE_SHA = "a" * 64
Q_SHA = "b" * 64


def configure_connection(conn: sqlite3.Connection):
    """Register necessary custom functions."""
    conn.create_function(
        "_g6_sha256_hex",
        1,
        lambda val: hashlib.sha256(val.encode("utf-8") if isinstance(val, str) else val).hexdigest() if val is not None else None
    )
    conn.create_function("_g7_verify_hmac_seal", 4, lambda *args: 0)
    conn.create_function("sogh_write_ok", 0, lambda: 1)


@pytest.fixture
def clean_migrated_db(tmp_path):
    """Create a fresh disposable DB migrated through 0014."""
    path, _p = S.make_native(tmp_path, "test_adversarial.sqlite")
    RevisionStore(path, tmp_path / "test_adversarial.backup")
    res = ad.apply(path, confirm_disposable_copy=True)
    assert not res["rolled_back"]
    assert "0012-g02-faq-unconfirmed-evidence" in res["applied"]
    assert "0013-g07-quarantine-staging" in res["applied"]
    assert "0014-g06-source-series" in res["applied"]
    return path


def test_probe_01_recursive_triggers_off_cannot_bypass_0012_immutability(clean_migrated_db):
    """PRAGMA recursive_triggers = OFF must not bypass 0012 append-only triggers."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)
    conn.execute("PRAGMA recursive_triggers = OFF;")

    conn.execute(
        """INSERT INTO faq_unconfirmed_evidence (
            evidence_id, storage_case_id, source_sha256, question_sha256, quote,
            normalized_start, normalized_end, recorded_by, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev_adv_01", CASE_ID, SOURCE_SHA, Q_SHA, "Original quote", 10, 20, "tester", "2026-11-12T00:00:00Z")
    )
    conn.commit()

    # 1. Try UPDATE
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="faq_unconfirmed_evidence is append-only"):
        conn.execute("UPDATE faq_unconfirmed_evidence SET quote = 'Tampered quote' WHERE evidence_id = 'ev_adv_01'")

    # 2. Try DELETE
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="faq_unconfirmed_evidence is append-only"):
        conn.execute("DELETE FROM faq_unconfirmed_evidence WHERE evidence_id = 'ev_adv_01'")
    conn.close()


def test_probe_02_insert_or_replace_on_0012_is_blocked(clean_migrated_db):
    """INSERT OR REPLACE on 0012 must trigger no_replace and abort."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    conn.execute(
        """INSERT INTO faq_unconfirmed_evidence (
            evidence_id, storage_case_id, source_sha256, question_sha256, quote,
            normalized_start, normalized_end, recorded_by, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev_adv_02", CASE_ID, SOURCE_SHA, Q_SHA, "Initial quote", 10, 20, "tester", "2026-11-12T00:00:00Z")
    )
    conn.commit()

    # Try REPLACE with same evidence_id
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="faq_unconfirmed_evidence is append-only: a row is never replaced"):
        conn.execute(
            """INSERT OR REPLACE INTO faq_unconfirmed_evidence (
                evidence_id, storage_case_id, source_sha256, question_sha256, quote,
                normalized_start, normalized_end, recorded_by, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("ev_adv_02", CASE_ID, SOURCE_SHA, Q_SHA, "Replaced quote", 10, 20, "tester", "2026-11-12T00:00:00Z")
        )
    conn.close()


def test_probe_03_insert_or_replace_on_0014_series_editions_is_blocked(clean_migrated_db):
    """INSERT OR REPLACE on 0014 source_document_series_editions must be blocked."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    content = "Document series edition 1"
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()

    conn.execute(
        """INSERT INTO source_document_series_editions (
            edition_id, series_id, university, document_title, rev_number, sha256_hash, content_text, supersedes_id, is_frozen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ed_01", "series_01", "Tsukuba", "Guidelines", 1, h, content, None, 0)
    )
    conn.commit()

    # Try REPLACE on existing series edition
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="G-06 VIOLATION:"):
        conn.execute(
            """INSERT OR REPLACE INTO source_document_series_editions (
                edition_id, series_id, university, document_title, rev_number, sha256_hash, content_text, supersedes_id, is_frozen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("ed_01", "series_01", "Tsukuba", "Guidelines", 1, h, "Tampered payload", None, 0)
        )
    conn.close()


def test_probe_04_quarantine_0013_payload_tampering_and_delete_blocked(clean_migrated_db):
    """quarantine_staging_candidates mutations and deletions must abort."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    conn.execute(
        """INSERT INTO quarantine_staging_candidates (
            staging_id, source_id, format_type, extracted_key, extracted_value, quarantine_status,
            review_status, staged_by, sha256_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("cand_01", "src_01", "PDF", "quota", "10", "QUARANTINED", "PENDING", "stager_1", "hash_01")
    )
    conn.commit()

    # Try UPDATE raw payload / key / value
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="G-07 VIOLATION: Staged candidate payload"):
        conn.execute("UPDATE quarantine_staging_candidates SET extracted_value = '999' WHERE staging_id = 'cand_01'")

    # Try DELETE
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="G-07 VIOLATION: Quarantine staging table is append-only; DELETE is prohibited"):
        conn.execute("DELETE FROM quarantine_staging_candidates WHERE staging_id = 'cand_01'")
    conn.close()


def test_probe_05_update_primary_key_is_blocked_on_all_tables(clean_migrated_db):
    """Updating primary key or identity columns must abort across 0012, 0013, 0014."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    # 0012
    conn.execute(
        """INSERT INTO faq_unconfirmed_evidence (
            evidence_id, storage_case_id, source_sha256, question_sha256, quote,
            normalized_start, normalized_end, recorded_by, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev_pk_01", CASE_ID, SOURCE_SHA, Q_SHA, "Quote", 10, 20, "tester", "2026-11-12T00:00:00Z")
    )
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="faq_unconfirmed_evidence is append-only"):
        conn.execute("UPDATE faq_unconfirmed_evidence SET evidence_id = 'ev_pk_02' WHERE evidence_id = 'ev_pk_01'")

    # 0014
    content = "Series PK test"
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()
    conn.execute(
        """INSERT INTO source_document_series_editions (
            edition_id, series_id, university, document_title, rev_number, sha256_hash, content_text, supersedes_id, is_frozen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ed_pk_01", "series_pk_01", "Tsukuba", "Guidelines", 1, h, content, None, 0)
    )
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="G-06 VIOLATION: Edition identity, labels, hash, and content are immutable"):
        conn.execute("UPDATE source_document_series_editions SET edition_id = 'ed_pk_02' WHERE edition_id = 'ed_pk_01'")
    conn.close()


def test_probe_06_drop_trigger_is_detected_as_drift(clean_migrated_db):
    """Dropping a trigger to bypass security must be detected by verify_schema_state."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    # Baseline check: 0 problems
    assert ad.verify_schema_state(conn) == []

    # Attacker drops 0012 update trigger
    conn.execute("DROP TRIGGER trg_faq_unconfirmed_evidence_no_update;")
    conn.commit()

    # verify_schema_state MUST catch this drift
    problems = ad.verify_schema_state(conn)
    assert any("trg_faq_unconfirmed_evidence_no_update" in p and "missing now" in p for p in problems)
    conn.close()


def test_probe_07_writable_schema_tampering_is_detected_as_drift(clean_migrated_db):
    """Directly tampering with sqlite_master via PRAGMA writable_schema must be caught."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    assert ad.verify_schema_state(conn) == []

    # Tamper with trigger SQL in sqlite_master
    conn.execute("PRAGMA writable_schema = ON;")
    conn.execute(
        "UPDATE sqlite_master SET sql = 'CREATE TRIGGER trg_series_editions_prevent_delete BEFORE DELETE ON source_document_series_editions BEGIN SELECT 1; END' WHERE name = 'trg_series_editions_prevent_delete'"
    )
    conn.commit()
    conn.execute("PRAGMA writable_schema = OFF;")

    problems = ad.verify_schema_state(conn)
    assert any("trg_series_editions_prevent_delete" in p and "differs from the SQL" in p for p in problems)
    conn.close()


def test_probe_08_attached_database_insert_still_enforces_triggers(clean_migrated_db, tmp_path):
    """Inserting invalid data from an ATTACHed external database must still trigger validation."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    evil_db_path = tmp_path / "evil.sqlite"
    conn_evil = sqlite3.connect(evil_db_path)
    conn_evil.execute(
        """CREATE TABLE evil_editions (
            edition_id, series_id, university, document_title, rev_number, sha256_hash, content_text, supersedes_id, is_frozen
        );"""
    )
    conn_evil.execute(
        """INSERT INTO evil_editions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ed_evil_01", "series_evil", "Tsukuba", "Evil Guide", 1, "mismatched_sha", "Evil content", None, 0)
    )
    conn_evil.commit()
    conn_evil.close()

    conn.execute(f"ATTACH DATABASE '{evil_db_path}' AS evil_db;")

    # Attempt to copy evil data into main table
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="G-06 VIOLATION: Edition content hash mismatch"):
        conn.execute(
            """INSERT INTO main.source_document_series_editions (
                edition_id, series_id, university, document_title, rev_number, sha256_hash, content_text, supersedes_id, is_frozen
            ) SELECT * FROM evil_db.evil_editions"""
        )
    conn.close()


def test_probe_09_fake_connection_function_tampering_caught_by_python_verification(clean_migrated_db):
    """If an attacker registers a fake _g6_sha256_hex function, Python verification must still catch it."""
    conn = sqlite3.connect(clean_migrated_db)

    # Attacker registers fake hash function that always returns 'fake_sha'
    conn.create_function("_g6_sha256_hex", 1, lambda val: "fake_sha")

    # Attacker inserts mismatched content using fake function
    conn.execute(
        """INSERT INTO source_document_series_editions (
            edition_id, series_id, university, document_title, rev_number, sha256_hash, content_text, supersedes_id, is_frozen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ed_spoof_01", "series_spoof", "Tsukuba", "Guide", 1, "fake_sha", "Content not matching fake_sha", None, 0)
    )
    conn.commit()

    # Now verify using Python series module (which uses hashlib.sha256 in Python)
    series_obj = sv.SourceSeries(
        series_id="series_spoof",
        university="Tsukuba",
        document_title="Guide",
        editions=[
            sv.SourceEdition(
                edition_id="ed_spoof_01",
                series_id="series_spoof",
                rev_number=1,
                sha256_hash="fake_sha",
                content_text="Content not matching fake_sha",
                supersedes_id=None,
                is_frozen=0
            )
        ]
    )
    # verify_series_against_rows computes sha256 in Python and detects the tampering!
    ok, errors = sv.verify_series_against_rows(conn, series_obj)
    assert not ok
    assert any("diverges" in e or "mismatch" in e for e in errors)
    conn.close()


def test_probe_10_negative_rowid_injection_blocked_in_0012(clean_migrated_db):
    """Injecting negative rowid into faq_unconfirmed_evidence must be blocked."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="rowid must not be negative"):
        conn.execute(
            """INSERT INTO faq_unconfirmed_evidence (
                rowid, evidence_id, storage_case_id, source_sha256, question_sha256, quote,
                normalized_start, normalized_end, recorded_by, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (-5, "ev_neg_rowid", CASE_ID, SOURCE_SHA, Q_SHA, "Negative rowid quote", 10, 20, "tester", "2026-11-12T00:00:00Z")
        )
    conn.close()


def test_probe_11_cross_table_collision_0012_against_facts_blocked(clean_migrated_db):
    """An evidence_id that already exists in facts must not be insertable into faq_unconfirmed_evidence."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    # Insert a fact first into facts table (using unique fact_key)
    conn.execute(
        """INSERT INTO facts (evidence_id, case_id, source_sha256, fact_key, value_json, record_json, verification)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("ev_existing_fact", CASE_ID, SOURCE_SHA, "quota_adversarial_test", "10", "{}", "source_checked_for_saved_version")
    )
    conn.commit()

    # Now attempt to insert same evidence_id into faq_unconfirmed_evidence
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="faq_unconfirmed_evidence: this evidence id is already a fact"):
        conn.execute(
            """INSERT INTO faq_unconfirmed_evidence (
                evidence_id, storage_case_id, source_sha256, question_sha256, quote,
                normalized_start, normalized_end, recorded_by, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("ev_existing_fact", CASE_ID, SOURCE_SHA, Q_SHA, "Duplicate fact quote", 10, 20, "tester", "2026-11-12T00:00:00Z")
        )
    conn.close()


def test_probe_12_canonical_staging_bypass_without_quarantine_blocked(clean_migrated_db):
    """Direct insert into canonical_facts_staging_target without quarantine promotion must abort."""
    conn = sqlite3.connect(clean_migrated_db)
    configure_connection(conn)

    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="G-07 VIOLATION: Canonical insert requires PROMOTED\\+APPROVED staging"):
        conn.execute(
            """INSERT INTO canonical_facts_staging_target (
                fact_id, staging_id, key, value, promoted_at
            ) VALUES (?, ?, ?, ?, ?)""",
            ("fact_direct", "cand_unquarantined", "quota", "10", "2026-11-12T00:00:00Z")
        )
    conn.close()
