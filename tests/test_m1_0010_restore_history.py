"""SELF_TEST (Claude, contract owner) for the frozen migration 0010-g03-restore-history: the append-only storage of restored history (candidate C, approved by the owner 2026-11-08).

SYNTHETIC databases only. Not an acceptance of g3 (the restore itself, F-2 state B, and its signed approval are other steps); applied to no real database by this file.
What is proven: the frozen file is byte-pinned and equals the SQL that PR #261 tested; it creates five EMPTY tables and their 20 guards and changes no other row; the guards hold on the migrated
database (no UPDATE, no DELETE, no REPLACE on any unique key or a named rowid, no negative rowid); the preflight stops on a table or trigger of those names that already exists; a database that stops at
0009 (candidate A) takes 0010 as the next step; the history, the schema state, DB-17 and the acceptance gate all see 0010 and see a tamper of it.
"""
import hashlib
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests import db_support as S  # noqa: E402  (puts Work's pipeline on the path)
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402
from src.db_contract import historical_read as hr  # noqa: E402
from tests.test_g03_replace_guard import COLLISIONS, FIX, ROWID_ROWS

SQL = Path(ad.MIGRATION_DIR) / "0010_g03_restore_history.sql"
PIN = "35d2a68fb2f4348f2674aca196596bb34e0446d4457b7ed523bfeeb7bd1a5ec2"
ID = "0010-g03-restore-history"
TABLES = hr.APPEND_ONLY_TABLES
BEFORE_0010 = tuple(m[0] for m in ad.MIGRATIONS if ad._seq(m[0]) < 10)
LAST = ad.MIGRATIONS[-1][0]  # 0011 and any later migration come after 0010: these tests are about 0010 and the chain that contains it
ENTRY = next(m for m in ad.MIGRATIONS if m[0] == ID)


def native(tmp_path, name="native.sqlite"):
    path, _p = S.make_native(tmp_path, name)
    RevisionStore(path, tmp_path / (name + ".backup"))
    return path


def old_rows(path):
    with closing(sqlite3.connect(path)) as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
        return {n: sorted(map(repr, c.execute(f'SELECT * FROM "{n}"').fetchall())) for n in names if n not in TABLES and n not in ("schema_migrations", "faq_unconfirmed_evidence", "quarantine_staging_candidates", "_quarantine_approval_seals", "canonical_facts_staging_target", "source_document_series_editions", "series_revision_article_impacts", "alias_provenance_bundles", "source_representations")}


def history_rows(path):
    with closing(sqlite3.connect(path)) as c:
        return [tuple(r) for r in c.execute("SELECT * FROM schema_migrations ORDER BY seq")]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def at_0009(tmp_path):
    path = native(tmp_path)
    r = ad.apply(path, confirm_disposable_copy=True, only=BEFORE_0010)
    assert not r["rolled_back"] and ad.verify_history(sqlite3.connect(path)) == []
    return path, tmp_path


@pytest.fixture
def migrated(at_0009):
    path, tmp = at_0009
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"][0] == ID and not r["rolled_back"]
    return path, tmp


# ------------------------------------------------------------------ the frozen file
def test_the_frozen_file_is_pinned_and_is_the_last_of_the_chain():
    assert hashlib.sha256(SQL.read_bytes()).hexdigest() == PIN
    assert b"\r" not in SQL.read_bytes()  # committed bytes (.gitattributes: migrations/** -text) have no CR
    assert [m[0] for m in ad.MIGRATIONS][8] == ID and ad._seq(ID) == 10
    assert ENTRY[4] == SQL.read_bytes().decode("utf-8")  # the definition that the checksum is made from


def test_the_frozen_statements_are_exactly_what_pr261_tested():
    frozen = [ad._norm(s) for s, _needs in ad.parse_frozen(SQL.read_bytes().decode("utf-8"))]
    db = sqlite3.connect(":memory:")
    proposal, buf = [], ""
    for line in hr.history_ddl(True).splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            proposal.append(ad._norm(buf.strip().rstrip(";").strip()))
            buf = ""
    assert frozen == proposal and len(frozen) == 25 and not buf.strip()
    db.close()


def test_the_file_only_creates_and_holds_no_row_no_drop_no_alter():
    statements = [s for s, _ in ad.parse_frozen(SQL.read_bytes().decode("utf-8"))]
    assert sum(s.startswith("CREATE TABLE") for s in statements) == 5 and sum(s.startswith("CREATE TRIGGER") for s in statements) == 20
    for st in statements:
        assert st.startswith(("CREATE TABLE ", "CREATE TRIGGER ")) and not re.search(r"\b(INSERT\s+INTO|DROP|ALTER|DELETE\s+FROM|UPDATE\s+\w+\s+SET)\b", st, re.I)
    assert all(t in ad.RESTORE_HISTORY_TABLES for t in TABLES) and ad.RESTORE_HISTORY_TABLES == TABLES


# ------------------------------------------------------------------ the migration
def test_it_adds_five_empty_tables_and_twenty_guards_and_changes_no_other_row(at_0009):
    path, _ = at_0009
    before, hist_before = old_rows(path), history_rows(path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"][0] == ID and r["skipped"] and not r["rolled_back"]
    assert old_rows(path) == before  # every old table, row for row
    after = history_rows(path)
    assert after[:len(hist_before)] == hist_before and [row[0] for row in after][len(hist_before)] == ID  # the earlier history rows are untouched; one row is added
    with closing(sqlite3.connect(path)) as c:
        assert [c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES] == [0] * 5
        triggers = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert hr.GUARD_TRIGGER_NAMES <= triggers and len(hr.GUARD_TRIGGER_NAMES) == 20
        assert c.execute("PRAGMA user_version").fetchone()[0] == ad._seq(LAST) and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert hr.history_preflight(c) == [] and hr.history_guards_for(c) == ""  # fully protected: nothing more to install
        assert ad.verify_history(c) == [] and ad.verify_schema_state(c) == [] and ad.verify_history_provenance(c) == []


def test_a_fresh_database_reaches_0010_in_one_run_and_the_gate_sees_the_whole_chain(tmp_path):
    path = native(tmp_path)
    with closing(sqlite3.connect(path)) as c:
        witness = ad.history_witness(c)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"] == [m[0] for m in ad.MIGRATIONS] and not r["rolled_back"]
    with closing(sqlite3.connect(path)) as c:
        assert ad.verify_history_for_acceptance(c, before=witness, expected_new=tuple(m[0] for m in ad.MIGRATIONS)) == []
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(ad.MIGRATIONS)


def test_a_copy_that_stops_at_0009_is_still_valid_for_its_own_chain_and_incomplete_for_the_whole_one(at_0009):
    path, _ = at_0009
    with closing(sqlite3.connect(path)) as c:
        witness = ad.history_witness(c)
        assert ad.verify_history_for_acceptance(c, before=witness, through="0009-m14-head-history") == []
        gate = ad.verify_history_for_acceptance(c, before=witness)
        assert gate and "missing 0010-g03-restore-history" in gate[0]  # the candidate A copy is not mistaken for a complete history


def test_a_second_run_is_a_no_op_and_the_plan_names_nothing_to_do(migrated):
    path, _ = migrated
    before = sha(path)
    p = ad.plan(path)
    assert p["drift"] == [] and not any(m["would_apply"] for m in p["migrations"]) and sha(path) == before
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"] == [] and ID in r["skipped"]


def test_the_plan_for_a_copy_at_0009_is_read_only_and_names_0010(at_0009):
    path, _ = at_0009
    before = sha(path)
    p = ad.plan(path)
    assert p["can_apply"] and [m["migration"] for m in p["migrations"] if m["would_apply"]][0] == ID and sha(path) == before


# ------------------------------------------------------------------ the preflight: nothing existing is adopted
@pytest.mark.parametrize("what,statement", [
    ("a table of that name", "CREATE TABLE restore_events(x)"),
    ("another history table", "CREATE TABLE article_history_pins(x)"),
    ("one guard trigger", "CREATE TRIGGER trg_restored_articles_no_update BEFORE UPDATE ON facts BEGIN SELECT 1; END"),
])
def test_an_existing_object_of_those_names_stops_the_migration_and_the_file_is_unchanged(at_0009, what, statement):
    path, _ = at_0009
    with closing(sqlite3.connect(path)) as c:
        c.execute(statement)
        c.commit()
    before = sha(path)
    try:  # a table is stopped by the preflight, a trigger of the owned namespace is drift: either way nothing is applied
        r = ad.apply(path, confirm_disposable_copy=True)
        assert ID not in r["applied"] and (r["blocked"] or r["rolled_back"])
    except ad.MigrationError:
        pass
    assert sha(path) == before  # nothing was created, nothing was adopted


def test_a_failure_inside_the_migration_rolls_everything_back(at_0009, monkeypatch):
    path, _ = at_0009
    before = sha(path)
    bad = ad.MIGRATIONS[:8] + ((ID, "x", lambda db: ad.statements_g03_history(db)[:7] + ("CREATE TABLE nonsense(",), ad.preflight_g03_history, ad._TEXT_0010),)
    monkeypatch.setattr(ad, "MIGRATIONS", bad)
    with pytest.raises(sqlite3.OperationalError):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before  # the five tables are all or nothing, byte for byte


# ------------------------------------------------------------------ the guards hold on the migrated database
def fill(db):
    for t in TABLES:
        for row in FIX[t]:
            db.execute(f"INSERT INTO {t} VALUES ({','.join('?' * len(row))})", row)


def cols(db, t):
    return [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]


def test_valid_rows_append_and_nothing_else_changes(migrated):
    path, _ = migrated
    with closing(sqlite3.connect(path)) as db:
        fill(db)
        db.commit()
        assert [db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES] == [len(FIX[t]) for t in TABLES]


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("recursive", [0, 1])
def test_no_update_and_no_delete_on_any_table(migrated, table, recursive):
    path, _ = migrated
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        fill(db)
        db.commit()
        col = cols(db, table)[1]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(f"UPDATE {table} SET {col}={col}")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(f"DELETE FROM {table}")


@pytest.mark.parametrize("recursive", [0, 1])
@pytest.mark.parametrize("table,key,row", COLLISIONS, ids=[f"{t}:{'+'.join(k)}" for t, k, _ in COLLISIONS])
def test_no_replace_on_any_unique_key(migrated, table, key, row, recursive):
    path, _ = migrated
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        fill(db)
        db.commit()
        before = db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        for verb in ("INSERT OR REPLACE", "REPLACE", "INSERT"):
            stmt = f"{verb} INTO {table} VALUES ({','.join('?' * len(row))})" if verb != "REPLACE" else f"REPLACE INTO {table} VALUES ({','.join('?' * len(row))})"
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(stmt, row)
        assert db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() == before


@pytest.mark.parametrize("table", TABLES)
def test_no_replace_by_naming_an_existing_rowid_and_no_negative_rowid(migrated, table):
    path, _ = migrated
    with closing(sqlite3.connect(path)) as db:
        fill(db)
        db.commit()
        names = cols(db, table)
        before = db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        rowid = db.execute(f"SELECT rowid FROM {table} ORDER BY rowid LIMIT 1").fetchone()[0]
        marks = ",".join("?" * (len(names) + 1))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"INSERT OR REPLACE INTO {table}(rowid,{','.join(names)}) VALUES ({marks})", (rowid, *ROWID_ROWS[table]))
        with pytest.raises(sqlite3.IntegrityError, match="negative"):
            db.execute(f"INSERT INTO {table}(rowid,{','.join(names)}) VALUES ({marks})", (-5, *ROWID_ROWS[table]))
        assert db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() == before


@pytest.mark.parametrize("table,row", [
    ("restore_events", ("RX", "other_kind", "a" * 64, "b" * 64, "who", "t", "ref")),
    ("restore_events", ("RX", "f2_recovery", "a" * 63, "b" * 64, "who", "t", "ref")),
    ("restore_events", ("RX", "f2_recovery", "a" * 64, "b" * 64, "  ", "t", "ref")),
    ("restore_events", ("RX", "f2_recovery", "a" * 64, "b" * 64, "who", "t", "")),
    ("evidence_history_versions", ("VX", "E1", "case", "c" * 64, "{}", "d" * 63, "e" * 64, "R1")),
    ("evidence_history_versions", ("VX", "E1", "case", "c" * 63, "{}", "d" * 64, "e" * 64, "R1")),
    ("article_history_pins", ("A1", "E2", "V2", "case", " ", "c" * 64, "e" * 64, "R1")),
    ("restored_articles", (None, "R1")),
    ("restore_events", (None, "f2_recovery", "a" * 64, "b" * 64, "who", "t", "ref")),
])
def test_the_column_checks_and_not_nulls_hold_on_the_migrated_tables(migrated, table, row):
    path, _ = migrated
    with closing(sqlite3.connect(path)) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row)
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_the_pins_and_versions_are_readable_through_the_read_contract_after_the_migration(migrated):
    """The reader of PR #261/#193 works on the migrated tables (smoke only: the read contract has its own tests)."""
    path, _ = migrated
    with closing(sqlite3.connect(path)) as db:
        assert set(TABLES) <= {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with pytest.raises(hr.ReadContractError):
            hr.read_cited_evidence(db, "no-such-article", "no-such-evidence")  # a refusal with a code, not a crash on a missing table


# ------------------------------------------------------------------ DB-17 and the acceptance gate see a tamper of 0010
def db17(path):
    return S.audit(path)["invariants"]["DB-17"]["status"]


@pytest.mark.parametrize("tamper", [
    "DROP TRIGGER trg_restore_events_no_update",
    "DROP TRIGGER trg_article_history_pins_no_replace",
    "DROP TRIGGER trg_evidence_history_versions_no_negative_rowid",
    "DROP TRIGGER trg_restored_articles_no_delete; CREATE TRIGGER trg_restored_articles_no_delete BEFORE DELETE ON restored_articles WHEN 0 BEGIN SELECT 1; END",
    "CREATE TRIGGER trg_extra_on_restore BEFORE INSERT ON restore_events BEGIN SELECT 1; END",
])
def test_db17_and_the_schema_state_detect_a_tamper(migrated, tamper):
    path, _ = migrated
    assert db17(path) == "pass"
    with closing(sqlite3.connect(path)) as c:
        c.executescript(tamper)
        assert ad.verify_schema_state(c) != []
    assert db17(path) == "fail"


def test_db17_passes_on_the_migrated_database_and_db09_keeps_every_old_row(at_0009):
    path, tmp = at_0009
    baseline = tmp / "baseline.sqlite"
    baseline.write_bytes(Path(path).read_bytes())
    ad.apply(path, confirm_disposable_copy=True)
    res = S.audit(path, baseline)["invariants"]
    assert res["DB-17"]["status"] == "pass" and res["DB-09"]["status"] == "pass"


def test_a_frozen_file_that_differs_from_the_one_applied_is_refused_by_the_gate(migrated, monkeypatch):
    path, _ = migrated
    with closing(sqlite3.connect(path)) as c:
        witness = ad.history_witness(c)
        assert ad.verify_history_for_acceptance(c, before=witness) == []
        idx = [m[0] for m in ad.MIGRATIONS].index(ID)
        last = tuple(ad.MIGRATIONS[idx][:4]) + (ad.MIGRATIONS[idx][4] + chr(10) + "-- edited",)
        monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS[:idx] + (last,) + ad.MIGRATIONS[idx + 1:])
        problems = ad.verify_history_for_acceptance(c, before=witness)
    assert problems and any("checksum mismatch" in p for p in problems)
