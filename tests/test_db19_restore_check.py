"""SELF_TEST (Claude) for src/db_contract/restore_check.py (DB-19 spec, appendix of docs/M1_SIX_GATE_PATH_2026-11-08.md). SYNTHETIC rows in a disposable database that went through the real chain
0002-0010. No signature is verified here (the verifier's result is an ARGUMENT) and nothing is restored in any real database. Not an acceptance of g3."""
import json
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S  # noqa: E402
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402
from src.db_contract.historical_read import digest_of  # noqa: E402
from src.db_contract.restore_check import verify_restore_records  # noqa: E402

A, SD = "a" * 64, "b" * 64
ROW = {"evidence_id": "E1", "case_id": "case", "source_sha256": "c" * 64, "fact_key": "quota", "value_json": "{}", "record_json": "{}"}
RHASH = "e" * 64
MANIFESTS = {"R1": {"archive_sha256": A, "source_db_sha256": SD, "approval_ref": "ref1", "signature_verified": True}}
ARCHIVE = {A: frozenset({RHASH})}


def fresh(tmp_path, upto=None):
    path, _p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "backup.sqlite")
    ad.apply(path, confirm_disposable_copy=True, only=upto)
    return path


@pytest.fixture
def db(tmp_path):
    path = fresh(tmp_path)
    c = S.app_connect(path)
    yield c
    c.close()


def restore(c):
    c.execute("INSERT INTO restore_events VALUES ('R1','f2_recovery',?,?,'owner','2026-11-08T00:00:00Z','ref1')", (A, SD))
    c.execute("INSERT INTO restored_articles VALUES ('ART1','R1')")
    c.execute("INSERT INTO evidence_history_versions VALUES ('V1','E1','case',?,?,?,?,'R1')", ("c" * 64, json.dumps(ROW, sort_keys=True), digest_of(ROW), RHASH))
    c.execute("INSERT INTO article_history_pins VALUES ('ART1','E1','V1','case','scope-a',?,?,'R1')", ("c" * 64, digest_of(ROW)))
    c.commit()


def check(c, **kw):
    kw.setdefault("manifests", MANIFESTS)
    kw.setdefault("archive_rows", ARCHIVE)
    return verify_restore_records(c, **kw)


def test_a_database_without_0010_is_not_applicable(tmp_path):
    path = fresh(tmp_path, upto=tuple(m[0] for m in ad.MIGRATIONS if ad._seq(m[0]) < 10))
    with closing(sqlite3.connect(path)) as c:
        r = verify_restore_records(c)
    assert r["status"] == "not_applicable"


def test_empty_tables_mean_no_restore_and_pass(db):
    assert verify_restore_records(db) == {"status": "pass", "problems": []}


def test_a_consistent_signed_restore_passes(db):
    restore(db)
    assert check(db) == {"status": "pass", "problems": []}


def test_the_check_reads_only(db):
    restore(db)
    before = [db.execute(f"SELECT * FROM {t}").fetchall() for t in ("restore_events", "evidence_history_versions", "article_history_pins")]
    check(db)
    assert before == [db.execute(f"SELECT * FROM {t}").fetchall() for t in ("restore_events", "evidence_history_versions", "article_history_pins")]


@pytest.mark.parametrize("kwargs,expect", [
    ({"manifests": {}}, "no signed approval manifest"),
    ({"manifests": None}, "no signed approval manifest"),
    ({"manifests": {"R1": {**MANIFESTS["R1"], "signature_verified": False}}}, "signature is not verified"),
    ({"manifests": {"R1": {**MANIFESTS["R1"], "signature_verified": "yes"}}}, "signature is not verified"),
    ({"manifests": {"R1": {**MANIFESTS["R1"], "archive_sha256": "9" * 64}}}, "archive_sha256 differs"),
    ({"manifests": {"R1": {**MANIFESTS["R1"], "source_db_sha256": "9" * 64}}}, "source_db_sha256 differs"),
    ({"manifests": {"R1": {**MANIFESTS["R1"], "approval_ref": "other"}}}, "approval_ref differs"),
    ({"archive_rows": {}}, "no external baseline"),
    ({"archive_rows": {A: frozenset({"0" * 64})}}, "not a row of the archive"),
])
def test_a_restore_that_the_outside_world_does_not_explain_fails(db, kwargs, expect):
    restore(db)
    r = check(db, **kwargs)
    assert r["status"] == "fail" and any(expect in p for p in r["problems"]), r


def tamper(c, statement):
    """The 20 guards stop UPDATE and DELETE, so a tamper is simulated the way a hostile file would arrive: the guards are dropped first."""
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg\\_%' ESCAPE '\\'").fetchall():
        if name.startswith(("trg_restore", "trg_restored", "trg_evidence_history", "trg_article_history")):
            c.execute(f"DROP TRIGGER {name}")
    c.executescript(statement)
    c.commit()


@pytest.mark.parametrize("statement,expect", [
    ("UPDATE evidence_history_versions SET row_json = replace(row_json, '\"quota\"', '\"fee\"')", "does not reproduce its digest"),
    ("UPDATE evidence_history_versions SET row_json = 'not json'", "not JSON"),
    ("UPDATE evidence_history_versions SET archive_row_sha256 = '0000000000000000000000000000000000000000000000000000000000000000'", "not a row of the archive"),
    ("UPDATE evidence_history_versions SET case_id = 'other'", "names another evidence id, case or source"),
    ("UPDATE evidence_history_versions SET restore_id = 'R9'", "restore 'R9' does not exist"),
    ("UPDATE article_history_pins SET scope = 'UNKNOWN'", "scope is empty or UNKNOWN"),
    ("UPDATE article_history_pins SET case_id = 'other'", "differ from its stored version"),
    ("UPDATE article_history_pins SET version_id = 'V9'", "version 'V9' does not exist"),
    ("UPDATE article_history_pins SET restore_id = 'R9'", "names restore 'R9'"),
    ("DELETE FROM article_history_pins", "no history pin"),
    ("DELETE FROM restored_articles", "not registered as restored"),
    ("INSERT INTO restore_revocations VALUES ('R9','x','t','r')", "no such restore event"),
    ("UPDATE restored_articles SET restore_id = 'R9'", "restore 'R9' does not exist"),
])
def test_a_tampered_history_fails_with_the_reason(db, statement, expect):
    restore(db)
    assert check(db)["status"] == "pass"
    tamper(db, statement)
    r = check(db)
    assert r["status"] == "fail" and any(expect in p for p in r["problems"]), r


def test_a_restore_event_without_any_article_or_version_still_needs_its_signed_approval(db):
    db.execute("INSERT INTO restore_events VALUES ('R2','f2_recovery',?,?,'owner','t','ref2')", (A, SD))
    db.commit()
    assert any("R2" in p for p in check(db)["problems"])


def test_a_revoked_restore_is_history_not_a_failure(db):
    restore(db)
    db.execute("INSERT INTO restore_revocations VALUES ('R1','owner','2026-11-09T00:00:00Z','withdrawn')")
    db.commit()
    assert check(db) == {"status": "pass", "problems": []}  # the read contract refuses to serve it; the audit only asks that the records are explained


def test_a_missing_table_is_a_failure_not_a_pass(db):
    for t in ("article_history_pins",):
        for (name,) in db.execute(f"SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='{t}'").fetchall():
            db.execute(f"DROP TRIGGER {name}")
        db.execute(f"DROP TABLE {t}")
    db.commit()
    r = check(db)
    assert r["status"] == "fail" and any("article_history_pins" in p for p in r["problems"])
