"""SELF_TEST (Claude, contract owner) for the frozen migration 0012-g02-faq-unconfirmed-evidence: the append-only storage of the evidence of an official FAQ whose applicability (year / faculty / method) is UNKNOWN
(STR-100 H2=A, approved 2026-11-10; implementation approved 2026-11-11, U6). SYNTHETIC databases only; applied to no operational database. Not an acceptance of g2 (the article that cites this evidence is PR #286; the
independent QA is another party's).

What is proven: the frozen file is pinned and creates ONE EMPTY append-only table and its five guards and changes no other row; the table is NOT a fact (no applicability column, scope_status fixed to 'unknown', no promotion
path, an evidence id that is already a fact cannot be filed); no UPDATE / DELETE / REPLACE / negative rowid; the history, the schema state and DB-17 (including the table allow-list) see it; a pre-existing table of that name
stops the migration."""
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests import db_support as S  # noqa: E402  (puts Work's pipeline on the path)
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402

SQL = Path(ad.MIGRATION_DIR) / "0012_g02_faq_unconfirmed_evidence.sql"
PIN = "923a27852978363e0047a245ce7638476af1fe756d59f575c490d0b8a4ce084d"
ID = "0012-g02-faq-unconfirmed-evidence"
TABLE = "faq_unconfirmed_evidence"
Q = "a" * 64
ROW = dict(evidence_id="EV-FAQ-1", storage_case_id="case", source_sha256="a" * 64, question_sha256=Q, quote="提出書類は大学の指定様式で", normalized_start=10, normalized_end=24, page=1,
           recorded_by="claude", recorded_at="2026-11-11T00:00:00Z")


def native(tmp_path):
    path, _p = S.make_native(tmp_path, "n.sqlite")
    RevisionStore(path, tmp_path / "n.backup")
    return path


@pytest.fixture
def migrated(tmp_path):
    path = native(tmp_path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"] and ID in r["applied"]
    return path


def add(path, **over):
    row = {**ROW, **over}
    with closing(S.app_connect(path)) as c:
        c.execute(f"INSERT INTO {TABLE}({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        c.commit()


def test_the_frozen_file_is_byte_pinned():
    assert hashlib.sha256(SQL.read_bytes()).hexdigest() == PIN


def test_0012_is_in_the_chain_and_the_history_and_the_schema_state_are_clean(migrated):
    assert ID in [m[0] for m in ad.MIGRATIONS]
    with closing(sqlite3.connect(migrated)) as c:
        assert ad.verify_history(c) == [] and ad.verify_schema_state(c) == []


def test_it_creates_one_empty_table_and_five_guards_and_changes_no_other_row(tmp_path):
    path = native(tmp_path)
    r0 = ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS if int(m[0].split("-", 1)[0]) < 12))
    assert not r0["rolled_back"]
    def counts(p):
        with closing(sqlite3.connect(p)) as c:
            names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations' ORDER BY 1")]
            return {n: c.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}
    before = counts(path)
    r = ad.apply(path, confirm_disposable_copy=True, only=(ID,))
    assert not r["rolled_back"] and r["applied"] == [ID]
    after = counts(path)
    assert after.pop(TABLE) == 0 and after == before
    with closing(sqlite3.connect(path)) as c:
        assert len([x for x in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE ?", (f"trg_{TABLE}_%",))]) == 5


def test_the_table_has_no_applicability_column_and_scope_status_is_fixed_to_unknown(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({TABLE})")]
    assert not {"fiscal_year", "faculty", "department", "admission_method", "case_id", "year"} & set(cols)
    add(migrated)
    with closing(sqlite3.connect(migrated)) as c:
        assert c.execute(f"SELECT scope_status FROM {TABLE}").fetchone()[0] == "unknown"
    with pytest.raises(sqlite3.IntegrityError):
        add(migrated, evidence_id="EV-FAQ-2", scope_status="verified")  # no promotion path (STR-102)


@pytest.mark.parametrize("bad", [dict(question_sha256="x"), dict(quote="  "), dict(normalized_start=-1), dict(normalized_end=10), dict(page=0), dict(recorded_by=" "), dict(evidence_id=" ")])
def test_malformed_rows_are_refused(migrated, bad):
    with pytest.raises(sqlite3.IntegrityError):
        add(migrated, **bad)


def test_an_evidence_id_that_is_already_a_fact_cannot_be_filed_here(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        fact_id = c.execute("SELECT evidence_id FROM facts LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.DatabaseError, match="already a fact"):
        add(migrated, evidence_id=fact_id)


def test_the_storage_reference_must_be_a_real_cycle_and_the_source_a_stored_document(migrated):
    with closing(S.app_connect(migrated)) as c:
        c.execute("PRAGMA foreign_keys=ON")
        for over in (dict(storage_case_id="no-such-cycle"), dict(source_sha256="b" * 64)):
            row = {**ROW, "evidence_id": "EV-FK", **over}
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(f"INSERT INTO {TABLE}({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))


def test_a_row_is_append_only(migrated):
    add(migrated)
    with closing(S.app_connect(migrated)) as c:
        for sql in (f"UPDATE {TABLE} SET quote='x'", f"DELETE FROM {TABLE}", f"UPDATE {TABLE} SET evidence_id='EV-OTHER'"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                c.execute(sql)
        row = {**ROW, "quote": "replaced"}
        for verb in ("INSERT", "INSERT OR REPLACE", "REPLACE"):
            with pytest.raises(sqlite3.DatabaseError):
                c.execute(f"{verb} INTO {TABLE}({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        row = {**ROW, "evidence_id": "EV-NEG"}
        with pytest.raises(sqlite3.DatabaseError):
            c.execute(f"INSERT INTO {TABLE}(rowid,{','.join(row)}) VALUES (-5,{','.join('?' * len(row))})", tuple(row.values()))
        c.rollback()
        assert c.execute(f"SELECT count(*), min(quote) FROM {TABLE}").fetchone() == (1, ROW["quote"])


def test_a_table_of_that_name_that_exists_already_stops_the_migration(tmp_path):
    path = native(tmp_path)
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS if int(m[0].split("-", 1)[0]) < 12))
    with closing(sqlite3.connect(path)) as c:
        c.execute(f"CREATE TABLE {TABLE}(x)")
        c.commit()
        assert any("already exist" in p for p in ad.preflight_g02_faq_unconfirmed(c))  # the pre-flight alone refuses it ...
    before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    # ... and since the DB-17 table allow-list (D1) the stray table is DRIFT already: apply() stops before any migration, names the table, and writes nothing
    with pytest.raises(ad.MigrationError, match=TABLE):
        ad.apply(path, confirm_disposable_copy=True)
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before


def test_a_tamper_of_the_table_is_drift_for_the_schema_state(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        c.execute(f"DROP TRIGGER trg_{TABLE}_no_update")
        assert any(f"trg_{TABLE}_no_update" in p for p in ad.verify_schema_state(c))
