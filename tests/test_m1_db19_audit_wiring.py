"""SELF_TEST (Claude) for the DB-19 wiring in src/integration/db_audit.py (M1 gate g3). SYNTHETIC rows in disposable databases; no signature is verified here (the verifier's result is an ARGUMENT)."""
import json
import sqlite3
from contextlib import closing

from tests import db_support as S  # noqa: E402
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402
from src.db_contract.historical_read import digest_of  # noqa: E402
from src.integration import db_audit  # noqa: E402

A, SD, RHASH = "a" * 64, "b" * 64, "e" * 64
ROW = {"evidence_id": "E1", "case_id": "case", "source_sha256": "c" * 64, "fact_key": "quota", "value_json": "{}", "record_json": "{}"}
MANIFESTS = {"R1": {"archive_sha256": A, "source_db_sha256": SD, "approval_ref": "ref1", "signature_verified": True}}
ARCHIVE = {A: frozenset({RHASH})}


def fresh(tmp_path, upto=None):
    path, _p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "backup.sqlite")
    ad.apply(path, confirm_disposable_copy=True, only=upto)
    return path


def restore(path):
    c = S.app_connect(path)
    c.execute("INSERT INTO restore_events VALUES ('R1','f2_recovery',?,?,'owner','2026-11-08T00:00:00Z','ref1')", (A, SD))
    c.execute("INSERT INTO restored_articles VALUES ('ART1','R1')")
    c.execute("INSERT INTO evidence_history_versions VALUES ('V1','E1','case',?,?,?,?,'R1')", ("c" * 64, json.dumps(ROW, sort_keys=True), digest_of(ROW), RHASH))
    c.execute("INSERT INTO article_history_pins VALUES ('ART1','E1','V1','case','scope-a',?,?,'R1')", ("c" * 64, digest_of(ROW)))
    c.commit()
    c.close()


def test_pre_0010_database_is_not_run(tmp_path):
    path = fresh(tmp_path, upto=tuple(m[0] for m in ad.MIGRATIONS if ad._seq(m[0]) < 10))
    r = db_audit.audit(path)["invariants"]["DB-19"]
    assert r["status"] == "not_run"


def test_empty_tables_pass(tmp_path):
    path = fresh(tmp_path)
    r = db_audit.audit(path)["invariants"]["DB-19"]
    assert r["status"] == "pass" and r["problems"] == []


def test_forged_restore_row_without_manifest_evidence_fails_closed(tmp_path):
    path = fresh(tmp_path)
    restore(path)
    rep = db_audit.audit(path)
    r = rep["invariants"]["DB-19"]
    assert r["status"] == "fail" and not rep["ok"]
    assert any("no signed approval manifest" in p["what"] for p in r["problems"])


def test_row_matching_supplied_evidence_passes(tmp_path):
    path = fresh(tmp_path)
    restore(path)
    r = db_audit.audit(path, restore_manifests=MANIFESTS, restore_archive_rows=ARCHIVE)["invariants"]["DB-19"]
    assert r["status"] == "pass", r


def test_unverified_signature_or_wrong_archive_fails(tmp_path):
    path = fresh(tmp_path)
    restore(path)
    bad = {"R1": dict(MANIFESTS["R1"], signature_verified=False)}
    assert db_audit.audit(path, restore_manifests=bad, restore_archive_rows=ARCHIVE)["invariants"]["DB-19"]["status"] == "fail"
    assert db_audit.audit(path, restore_manifests=MANIFESTS, restore_archive_rows={A: frozenset({"0" * 64})})["invariants"]["DB-19"]["status"] == "fail"


def test_missing_archive_baseline_fails_closed(tmp_path):
    path = fresh(tmp_path)
    restore(path)
    assert db_audit.audit(path, restore_manifests=MANIFESTS)["invariants"]["DB-19"]["status"] == "fail"


def test_partial_history_tables_fail(tmp_path):
    path = fresh(tmp_path)
    with closing(sqlite3.connect(path)) as c:
        c.execute("PRAGMA writable_schema=OFF")
        for t in ("article_history_pins",):
            c.execute(f"DROP TABLE {t}")
        c.commit()
    assert db_audit.audit(path)["invariants"]["DB-19"]["status"] == "fail"


def test_existing_invariant_ids_unchanged(tmp_path):
    path = fresh(tmp_path)
    ids = set(db_audit.audit(path)["invariants"])
    assert {i[0] for i in db_audit.INVARIANTS} <= ids and "DB-19" in ids and "DB-17" in ids and "DB-18" in ids
