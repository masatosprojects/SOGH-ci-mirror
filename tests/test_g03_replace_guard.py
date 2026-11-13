"""SELF_TEST (Claude, contract owner) for the proposed history DDL's protection against ``INSERT OR REPLACE``.  SYNTHETIC rows, in-memory SQLite, no file, no network.  NOT an acceptance of g3 and not
a registered migration: ``historical_read.history_ddl`` is a PROPOSAL for 0010 / DB-17 / DB-19, and where the final form lives is the owner's decision.

Found by Work (issue #55 comment 6714222911: the update / delete triggers are bypassed by ``INSERT OR REPLACE`` while ``recursive_triggers`` is OFF) and widened by an independent probe:
  * with the unguarded proposal all 12 replace paths succeed (every unique key of the 5 tables, and an explicit rowid on each table);
  * a BEFORE INSERT guard that tests only the key columns (Work's trial guard) still lets an INSERT that names an existing ROWID replace the row, on all 5 tables.
"""
import hashlib
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from src.db_contract import historical_read as hr  # noqa: E402

H = {c: c * 64 for c in "abcdef"}
FIX = {
    "restore_events": [("R1", "f2_recovery", H["a"], H["b"], "who", "t", "ref1"), ("R2", "f2_recovery", H["a"], H["b"], "who", "t", "ref2")],
    "restore_revocations": [("R2", "who", "t", "reason")],
    "restored_articles": [("A1", "R1")],
    "evidence_history_versions": [("V1", "E1", "case", H["c"], "{}", H["d"], H["e"], "R1"), ("V2", "E2", "case", H["c"], "{}", H["e"], H["e"], "R1")],
    "article_history_pins": [("A1", "E2", "V2", "case", "scope", H["c"], H["e"], "R1")],
}
COLLISIONS = [   # (table, which unique key collides, a replacement row that changes the provenance)
    ("restore_events", ("restore_id",), ("R1", "f2_recovery", H["a"], H["b"], "ATTACKER", "t", "forged")),
    ("restore_revocations", ("restore_id",), ("R2", "ATTACKER", "t", "forged")),
    ("restored_articles", ("article_id",), ("A1", "R2")),
    ("evidence_history_versions", ("version_id",), ("V1", "E9", "case", H["c"], "{}", H["f"], H["e"], "R2")),
    ("evidence_history_versions", ("row_digest",), ("V9", "E9", "case", H["c"], "{}", H["d"], H["e"], "R2")),
    ("evidence_history_versions", ("restore_id", "evidence_id"), ("V9", "E1", "case", H["c"], "{}", H["f"], H["e"], "R1")),
    ("article_history_pins", ("article_id", "evidence_id"), ("A1", "E2", "V1", "case", "forged", H["c"], H["e"], "R1")),
]
ROWID_ROWS = {   # a row with a NEW key (nothing collides but the rowid)
    "restore_events": ("NEWKEY", "f2_recovery", H["a"], H["b"], "ATTACKER", "t", "forged"),
    "restore_revocations": ("NEWKEY", "ATTACKER", "t", "forged"),
    "restored_articles": ("NEWKEY", "R2"),
    "evidence_history_versions": ("NEWKEY", "E7", "case", H["c"], "{}", "9" * 64, H["e"], "R2"),
    "article_history_pins": ("NEWKEY", "E7", "V1", "case", "forged", H["c"], H["e"], "R1"),
}


def make(ddl, recursive=False):
    db = sqlite3.connect(":memory:")
    db.execute(f"PRAGMA recursive_triggers={int(recursive)}")
    db.executescript(ddl)
    for table, rows in FIX.items():
        for row in rows:
            db.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in row)})", row)
    db.commit()
    return db


def snapshot(db):
    return {t: db.execute(f"SELECT rowid,* FROM {t} ORDER BY rowid").fetchall() for t in hr.APPEND_ONLY_TABLES}


def attempt(db, verb, table, row, rowid=None):
    before = snapshot(db)
    try:
        if rowid is None:
            db.execute(f"{verb} INTO {table} VALUES ({','.join('?' for _ in row)})", row)
        else:
            cols = [c[1] for c in db.execute(f"PRAGMA table_info({table})")]
            db.execute(f"{verb} INTO {table}(rowid,{','.join(cols)}) VALUES (?,{','.join('?' for _ in row)})", (rowid, *row))
        db.commit()
        accepted = True
    except sqlite3.Error:
        db.rollback()
        accepted = False
    return accepted, snapshot(db) != before


@pytest.mark.parametrize("recursive", [False, True])
@pytest.mark.parametrize("verb", ["INSERT OR REPLACE", "REPLACE"])
@pytest.mark.parametrize("table,key,row", COLLISIONS, ids=[f"{t}:{'+'.join(k)}" for t, k, _ in COLLISIONS])
def test_G1_no_unique_key_can_be_used_to_replace_a_history_row(table, key, row, verb, recursive):
    db = make(hr.history_ddl(True), recursive)
    accepted, changed = attempt(db, verb, table, row)
    assert not accepted and not changed


@pytest.mark.parametrize("recursive", [False, True])
@pytest.mark.parametrize("table", sorted(ROWID_ROWS))
def test_G2_naming_an_existing_rowid_cannot_replace_a_row_whatever_its_keys(table, recursive):
    db = make(hr.history_ddl(True), recursive)
    accepted, changed = attempt(db, "INSERT OR REPLACE", table, ROWID_ROWS[table], rowid=1)
    assert not accepted and not changed


def test_G3_the_existing_protection_and_ordinary_appends_still_work():
    db = make(hr.history_ddl(True))
    for stmt in ("DELETE FROM restore_events WHERE restore_id='R1'", "UPDATE restore_events SET approved_by='X' WHERE restore_id='R1'", "UPDATE OR REPLACE restore_events SET restore_id='R2' WHERE restore_id='R1'"):
        before = snapshot(db)
        with pytest.raises(sqlite3.Error):
            db.execute(stmt)
        db.rollback()
        assert snapshot(db) == before
    db.execute("INSERT INTO restore_events VALUES ('R3','f2_recovery',?,?,'who','t','ref3')", (H["a"], H["b"]))      # a new, different row is appended
    db.execute("INSERT INTO restore_events(rowid,restore_id,kind,archive_sha256,source_db_sha256,approved_by,approved_at,approval_ref) VALUES (500,'R4','f2_recovery',?,?,'who','t','ref4')", (H["a"], H["b"]))  # even with a free rowid
    db.commit()
    assert [r[0] for r in db.execute("SELECT restore_id FROM restore_events ORDER BY rowid")] == ["R1", "R2", "R3", "R4"]


def test_G4_the_key_list_of_the_guard_is_exactly_what_sqlite_reports():
    db = sqlite3.connect(":memory:")
    db.executescript(hr.HISTORY_DDL)
    for table in hr.APPEND_ONLY_TABLES:
        actual = {tuple(c[2] for c in db.execute(f"PRAGMA index_info({idx[1]})")) for idx in db.execute(f"PRAGMA index_list({table})") if idx[2]}
        assert actual == set(hr.HISTORY_UNIQUE_KEYS[table]), table
    assert set(hr.HISTORY_UNIQUE_KEYS) == set(hr.APPEND_ONLY_TABLES)


def test_G5_the_unguarded_variant_for_the_tampered_file_simulation_is_unchanged():
    ddl = hr.history_ddl(False)
    assert ddl == hr.HISTORY_DDL and "TRIGGER" not in ddl
    db = make(ddl)
    accepted, changed = attempt(db, "INSERT OR REPLACE", "restore_events", COLLISIONS[0][2])
    assert accepted and changed            # the tests that need a damaged file still can make one


def test_G6_every_table_gets_all_four_triggers_and_nothing_else_is_added():
    db = sqlite3.connect(":memory:")
    db.executescript(hr.history_ddl(True))
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert names == {f"trg_{t}_{k}" for t in hr.APPEND_ONLY_TABLES for k in ("no_update", "no_delete", "no_replace", "no_negative_rowid")}


# ------------------------------------------------------------------ found by Work's independent QA of PR #261 at 58cc52b (27 PASS / 5 FAIL)
NULL_ROWS = {   # the identifier is NULL, everything else is valid
    "restore_events": (None, "f2_recovery", H["a"], H["b"], "who", "t", "ref9"),
    "restore_revocations": (None, "who", "t", "reason"),
    "restored_articles": (None, "R1"),
    "evidence_history_versions": (None, "E9", "case", H["c"], "{}", H["f"], H["e"], "R1"),
    "article_history_pins": (None, "E9", "V1", "case", "scope", H["c"], H["e"], "R1"),
}


@pytest.mark.parametrize("table", sorted(NULL_ROWS))
def test_G7_a_null_identifier_is_refused_on_every_table(table):
    db = make(hr.history_ddl(True))
    accepted, changed = attempt(db, "INSERT", table, NULL_ROWS[table])
    assert not accepted and not changed


def _db_with_negative_rowid():
    """A file that already holds a row with rowid -1 (written before the triggers existed), then the triggers are added."""
    db = sqlite3.connect(":memory:")
    db.executescript(hr.HISTORY_DDL)
    db.execute("INSERT INTO restore_events(rowid,restore_id,kind,archive_sha256,source_db_sha256,approved_by,approved_at,approval_ref) VALUES (-1,'RNEG','f2_recovery',?,?,'who','t','refneg')", (H["a"], H["b"]))
    db.commit()
    db.executescript(hr.history_ddl(True)[len(hr.HISTORY_DDL):])
    return db


def test_G8_an_existing_negative_rowid_does_not_block_an_ordinary_append_and_cannot_be_replaced():
    db = _db_with_negative_rowid()
    db.execute("INSERT INTO restore_events VALUES ('R5','f2_recovery',?,?,'who','t','ref5')", (H["a"], H["b"]))      # rowid left out: appended
    db.commit()
    assert [r[0] for r in db.execute("SELECT restore_id FROM restore_events ORDER BY rowid")] == ["RNEG", "R5"]
    before = snapshot(db)
    assert db.execute("SELECT rowid FROM restore_events WHERE restore_id='R5'").fetchone()[0] == 0                   # the next automatic rowid after -1
    for rowid in (-1, 0, -7):                                                                                        # naming -1 / -7 is refused after the insert; naming 0 collides with the appended row
        with pytest.raises(sqlite3.Error):
            db.execute("INSERT OR REPLACE INTO restore_events(rowid,restore_id,kind,archive_sha256,source_db_sha256,approved_by,approved_at,approval_ref) VALUES (?,'RX','f2_recovery',?,?,'ATTACKER','t','forged')",
                       (rowid, H["a"], H["b"]))
        db.rollback()
        assert snapshot(db) == before


@pytest.mark.parametrize("table", sorted(ROWID_ROWS))
def test_G9_no_table_accepts_a_row_with_a_negative_rowid(table):
    db = make(hr.history_ddl(True))
    for rowid in (-1, -5):
        accepted, changed = attempt(db, "INSERT", table, ROWID_ROWS[table], rowid=rowid)
        assert not accepted and not changed


# ------------------------------------------------------------------ found by Work's re-QA of PR #261 at 92ec19e: a legacy table whose largest rowid is -7 refuses ordinary appends (the next automatic rowid is -6)
def _legacy_db(rowids=(-7, -9), loose=False):
    """A hand-made file: the tables exist WITHOUT the guards and hold rows whose rowids are all negative; only afterwards would the guards be considered."""
    db = sqlite3.connect(":memory:")
    ddl = hr.HISTORY_DDL.replace("NOT NULL PRIMARY KEY", "PRIMARY KEY") if loose else hr.HISTORY_DDL
    db.executescript(ddl)
    for i, rowid in enumerate(rowids):
        db.execute("INSERT INTO restore_events(rowid,restore_id,kind,archive_sha256,source_db_sha256,approved_by,approved_at,approval_ref) VALUES (?,?,'f2_recovery',?,?,'who','t','ref')", (rowid, f"RL{i}", H["a"], H["b"]))
    db.commit()
    return db


def test_G10_a_legacy_table_with_negative_rowids_is_refused_before_the_guards_are_installed_and_nothing_is_changed():
    db = _legacy_db()
    before = snapshot(db)
    problems = hr.history_preflight(db)
    assert problems and "restore_events" in problems[0] and "negative rowid" in problems[0]
    assert snapshot(db) == before                                                      # read only
    # the reason for the refusal, shown: with the guards installed anyway, the next automatic rowid (-6) is refused
    db.executescript(hr.history_ddl(True)[len(hr.HISTORY_DDL):])
    with pytest.raises(sqlite3.Error):
        db.execute("INSERT INTO restore_events VALUES ('RNEW','f2_recovery',?,?,'who','t','refnew')", (H["a"], H["b"]))
    db.rollback()
    assert snapshot(db) == before


@pytest.mark.parametrize("rowids", [(-1,), (-7,), (-7, -9), (3, -2)])
def test_G11_any_negative_rowid_is_reported_and_an_ordinary_file_is_not(rowids):
    assert hr.history_preflight(_legacy_db(rowids))
    assert hr.history_preflight(make(hr.history_ddl(True))) == []                      # a file built with the contract, with rows in it
    assert hr.history_preflight(make(hr.HISTORY_DDL)) == []
    # (a file without the history tables is NOT clean any more: see test_G16)


def test_G12_the_preflight_reports_a_null_key_in_a_table_made_without_not_null_and_changes_nothing():
    db = _legacy_db(rowids=(1,), loose=True)
    db.execute("INSERT INTO restore_events(rowid,restore_id,kind,archive_sha256,source_db_sha256,approved_by,approved_at,approval_ref) VALUES (2,NULL,'f2_recovery',?,?,'who','t','ref2')", (H["a"], H["b"]))
    db.commit()
    before = snapshot(db)
    problems = hr.history_preflight(db)
    assert any("NULL in the key column restore_id" in x for x in problems)
    assert snapshot(db) == before


def test_G13_the_preflight_works_on_a_read_only_connection_of_a_file(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as w:
        w.executescript(hr.HISTORY_DDL)
        w.execute("INSERT INTO restore_events(rowid,restore_id,kind,archive_sha256,source_db_sha256,approved_by,approved_at,approval_ref) VALUES (-7,'RL','f2_recovery',?,?,'who','t','ref')", (H["a"], H["b"]))
    digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    ro = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        assert hr.history_preflight(ro)
    finally:
        ro.close()
    assert __import__("hashlib").sha256(path.read_bytes()).hexdigest() == digest


def test_G14_guards_for_an_existing_file_are_returned_only_when_the_preflight_is_clean_and_nothing_is_executed():
    clean = make(hr.HISTORY_DDL)
    sql = hr.history_guards_for(clean)
    assert sql == hr.history_ddl(True)[len(hr.HISTORY_DDL):] and "trg_restore_events_no_replace" in sql
    assert not clean.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchall()          # returning the SQL installed nothing
    for rowids in ((-1,), (-7,), (-7, -9)):
        legacy = _legacy_db(rowids)
        before = snapshot(legacy)
        with pytest.raises(ValueError, match="negative rowid"):
            hr.history_guards_for(legacy)
        assert snapshot(legacy) == before
        assert not legacy.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchall()


def test_G15_a_null_key_in_an_existing_file_is_refused_in_the_same_way():
    db = _legacy_db(rowids=(1,), loose=True)
    db.execute("INSERT INTO restore_events(rowid,restore_id,kind,archive_sha256,source_db_sha256,approved_by,approved_at,approval_ref) VALUES (2,NULL,'f2_recovery',?,?,'who','t','ref2')", (H["a"], H["b"]))
    db.commit()
    with pytest.raises(ValueError, match="NULL in the key column"):
        hr.history_guards_for(db)


# ------------------------------------------------------------------ found by Work's independent re-QA of PR #261 at b6b582e (5 PASS / 2 FAIL): no table, or only some tables
def _file_with(ddl, tmp_path, name="f.sqlite"):
    path = tmp_path / name
    with closing(sqlite3.connect(path)) as w:
        w.executescript(ddl)
        w.commit()
    return path


def _ro(path):
    c = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    c.execute("PRAGMA query_only=ON")
    return c


PARTIAL = hr.HISTORY_DDL.split("CREATE TABLE restore_revocations")[0]


@pytest.mark.parametrize("name,ddl,missing", [
    ("no tables", "", list(hr.APPEND_ONLY_TABLES)),
    ("only restore_events", PARTIAL, [t for t in hr.APPEND_ONLY_TABLES if t != "restore_events"]),
    ("everything but the pins", hr.HISTORY_DDL.split("CREATE TABLE article_history_pins")[0], ["article_history_pins"]),
])
def test_G16_a_file_without_all_five_history_tables_is_refused_with_the_reason_and_nothing_is_returned(tmp_path, name, ddl, missing):
    path = _file_with(ddl, tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ro = _ro(path)
    try:
        problems = hr.history_preflight(ro)
        for table in missing:
            assert any(x.startswith(f"{table}: the table does not exist") for x in problems), (name, table)
        assert len(problems) == len(missing)
        with pytest.raises(ValueError, match="the table does not exist"):
            hr.history_guards_for(ro)
        assert ro.total_changes == 0
    finally:
        ro.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_G17_a_table_that_lacks_a_key_column_is_refused():
    db = sqlite3.connect(":memory:")
    db.executescript(hr.HISTORY_DDL)
    db.execute("DROP TABLE article_history_pins")
    db.execute("CREATE TABLE article_history_pins(article_id TEXT NOT NULL PRIMARY KEY, version_id TEXT NOT NULL)")      # another layout: no evidence_id in the key
    problems = hr.history_preflight(db)
    assert any("article_history_pins: the table lacks the key column(s) evidence_id" in x for x in problems)
    with pytest.raises(ValueError, match="lacks the key column"):
        hr.history_guards_for(db)


def test_G18_a_half_installed_file_is_refused_and_a_fully_protected_one_has_nothing_to_install():
    half = sqlite3.connect(":memory:")
    half.executescript(hr.HISTORY_DDL)
    half.executescript(hr.history_ddl(True)[len(hr.HISTORY_DDL):])
    half.execute("DROP TRIGGER trg_restore_events_no_replace")
    problems = hr.history_preflight(half)
    assert len(problems) == 1 and "19 of the 20 guard triggers already exist" in problems[0]
    with pytest.raises(ValueError, match="half protected"):
        hr.history_guards_for(half)
    full = sqlite3.connect(":memory:")
    full.executescript(hr.history_ddl(True))
    assert hr.history_preflight(full) == [] and hr.history_guards_for(full) == ""


def test_G19_the_returned_sql_really_installs_the_guards_on_a_complete_file_and_the_result_is_protected():
    db = make(hr.HISTORY_DDL)                                                          # a complete file with rows and no guards
    sql = hr.history_guards_for(db)
    assert sql and sql.count("CREATE TRIGGER") == 20
    db.executescript(sql)                                                              # applied to a SYNTHETIC in-memory file only
    assert hr.history_preflight(db) == [] and hr.history_guards_for(db) == ""
    accepted, changed = attempt(db, "INSERT OR REPLACE", "restore_events", COLLISIONS[0][2])
    assert not accepted and not changed
