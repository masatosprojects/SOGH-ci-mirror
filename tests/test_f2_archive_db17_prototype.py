"""Executable specification of the G-2 contract (docs/F2_G2_MIGRATION_AND_DB17_CONTRACT.md): what DB-17 must do once the F-2 archive objects belong to a reviewed migration after 0009.

SYNTHETIC_ONLY and a PROTOTYPE. Nothing here is a migration of the repository: the prototype migration `0015-f2-archive-prototype` exists only inside these tests (a monkeypatched, in-memory entry of the
registry), runs on disposable copies in a temporary directory and creates stand-in objects with the owned prefix `work_f2_`. No SQL file is added to `src/db_contract/migrations`, the frozen
0002-0010 are untouched, nothing is applied to any real database. Its job is to prove the mechanism (history, checksum, user_version, ownership, drift detection, pre-flight, rollback) so that the
real migration can be reviewed against these same assertions. Passing accepts nothing."""
import hashlib
import shutil
import sqlite3
from contextlib import closing

import pytest

from src.db_contract import additive_schema as ad
from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore  # noqa: E402

TABLE = """CREATE TABLE work_f2_recovered_rows(
    seq INTEGER PRIMARY KEY, source_copy_sha256 TEXT NOT NULL, source_table TEXT NOT NULL, occurrence INTEGER NOT NULL, row_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
    UNIQUE(source_copy_sha256, source_table, occurrence))"""
TRIGGERS = (
    "CREATE TRIGGER work_f2_no_update BEFORE UPDATE ON work_f2_recovered_rows BEGIN SELECT RAISE(ABORT, 'work_f2_recovered_rows is append-only'); END",
    "CREATE TRIGGER work_f2_no_delete BEFORE DELETE ON work_f2_recovered_rows BEGIN SELECT RAISE(ABORT, 'work_f2_recovered_rows is append-only'); END",
    "CREATE TRIGGER work_f2_insert_guard BEFORE INSERT ON work_f2_recovered_rows WHEN work_f2_insert_allowed(NEW.source_copy_sha256, NEW.source_table, NEW.occurrence, NEW.row_sha256) IS NOT 1 "
    "BEGIN SELECT RAISE(ABORT, 'insert not allowed'); END",
)
MIGRATION_ID = "0015-f2-archive-prototype"
STATEMENTS = (TABLE,) + TRIGGERS


def preflight(db):
    """Refuse a database that already holds objects of the owned namespace that this migration did not create (an unguarded candidate archive converted in place is never accepted)."""
    present = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'work\\_f2\\_%' ESCAPE '\\'")]
    return [f"incompatible pre-existing object {n!r}: use a new disposable copy" for n in present]


@pytest.fixture
def registered(monkeypatch):
    entry = (MIGRATION_ID, "F-2 archive: the append-only table of recovered rows and its three guards (prototype)", lambda db: STATEMENTS, preflight, "\n".join(STATEMENTS))
    monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS + (entry,))
    monkeypatch.setattr(ad, "_OWNED_PREFIXES", ad._OWNED_PREFIXES + ("work_f2_",))


def fresh(tmp_path, name="m.sqlite"):
    """A v0.3-style copy with the revision tables (as the tests of migration 0004 build it), before any migration."""
    path, _ = S.make_native(tmp_path, name)
    RevisionStore(path, tmp_path / (name + ".backup"))
    return path


def migrated(tmp_path, name="m.sqlite"):
    path = fresh(tmp_path, name)
    ad.apply(path, confirm_disposable_copy=True)
    return path


def db17(path):
    return S.audit(path)["invariants"]["DB-17"]["status"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drop_and_run(path, *statements):
    with closing(sqlite3.connect(path)) as db:
        db.create_function("sogh_write_ok", 0, lambda: 1)
        for s in statements:
            db.execute(s)
        db.commit()


def test_with_the_prototype_registered_a_fresh_copy_reaches_0015_with_history_checksum_and_user_version(registered, tmp_path):
    path = migrated(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        hist = ad.history(db)
        assert [h[0] for h in hist][-1] == MIGRATION_ID and hist[-1][1] == hashlib.sha256("\n".join(STATEMENTS).encode()).hexdigest()
        assert db.execute("PRAGMA user_version").fetchone()[0] == 15
        assert ad.verify_history(db) == [] and ad.verify_schema_state(db) == []
    assert db17(path) == "pass"


def test_the_frozen_migrations_are_unchanged_when_0015_is_added(registered, tmp_path):
    before_path, _ = S.make_native(tmp_path, "before.sqlite")
    RevisionStore(before_path, tmp_path / "b.backup")
    before = ad.MIGRATIONS[:-1]
    after = ad.MIGRATIONS
    assert [m[0] for m in before] == [m[0] for m in after[:-1]] and all(a[4] == b[4] for a, b in zip(before, after[:-1]))
    ad.apply(before_path, confirm_disposable_copy=True)
    with closing(sqlite3.connect(before_path)) as db:
        first_nine = [(h[0], h[1]) for h in ad.history(db)][:len(before)]
    assert [v for v, _ in first_nine] == [m[0] for m in before]
    assert [c for _, c in first_nine] == [hashlib.sha256(m[4].encode()).hexdigest() for m in before]


@pytest.mark.parametrize("attack,statements", [
    ("a guard trigger is dropped", ("DROP TRIGGER work_f2_no_delete",)),
    ("the insert guard is dropped", ("DROP TRIGGER work_f2_insert_guard",)),
    ("a guard is replaced by a weaker one", ("DROP TRIGGER work_f2_no_update", "CREATE TRIGGER work_f2_no_update BEFORE UPDATE ON work_f2_recovered_rows BEGIN SELECT 1; END")),
    ("the table is replaced by an unguarded copy", ("DROP TABLE work_f2_recovered_rows", "CREATE TABLE work_f2_recovered_rows(seq INTEGER PRIMARY KEY, payload_json TEXT)")),
    ("an extra object of the owned namespace appears", ("CREATE INDEX work_f2_extra ON work_f2_recovered_rows(row_sha256)",)),
    ("an extra trigger of the owned namespace appears", ("CREATE TRIGGER work_f2_sneaky AFTER INSERT ON work_f2_recovered_rows BEGIN SELECT 1; END",)),
    ("user_version is rewound", ("PRAGMA user_version=11",)),
])
def test_db17_detects_every_tamper_of_the_archive_objects_once_they_are_owned(registered, tmp_path, attack, statements):
    path = migrated(tmp_path)
    assert db17(path) == "pass"
    drop_and_run(path, *statements)
    assert db17(path) == "fail", attack


def test_without_the_ownership_the_same_tamper_is_invisible_to_db17_which_is_why_the_prefix_must_be_registered(monkeypatch, tmp_path):
    """The present state (G-2): only the migration entry is added, the prefix `work_f2_` is NOT owned. The objects exist (the migration created them), but an extra or edited object of that name is not reported."""
    entry = (MIGRATION_ID, "prototype", lambda db: STATEMENTS, preflight, "\n".join(STATEMENTS))
    monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS + (entry,))
    path = migrated(tmp_path)
    drop_and_run(path, "CREATE INDEX work_f2_extra ON work_f2_recovered_rows(row_sha256)")
    assert db17(path) == "pass"  # an unexpected object is only reported inside the owned namespace


def test_a_database_that_already_holds_an_unguarded_archive_is_refused_and_left_byte_identical(registered, tmp_path):
    """Once the prefix is owned, an unguarded `work_f2_recovered_rows` made before the migration is DRIFT: the runner refuses before it tries 0012 (the pre-flight is the second line of defence)."""
    path = fresh(tmp_path, "pre.sqlite")
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS[:-1]))
    drop_and_run(path, "CREATE TABLE work_f2_recovered_rows(seq INTEGER PRIMARY KEY, payload_json TEXT)")
    before = sha(path)
    with pytest.raises(ad.MigrationError, match="not created by any applied migration"):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before
    assert any("work_f2_recovered_rows" in p for p in ad.plan(path)["drift"])  # the read-only plan says so too


def test_the_preflight_alone_also_refuses_an_incompatible_object_when_the_prefix_is_not_yet_owned(monkeypatch, tmp_path):
    entry = (MIGRATION_ID, "prototype", lambda db: STATEMENTS, preflight, "\n".join(STATEMENTS))
    monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS + (entry,))
    path = fresh(tmp_path, "pre2.sqlite")
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS[:-1]))
    drop_and_run(path, "CREATE TABLE work_f2_recovered_rows(seq INTEGER PRIMARY KEY, payload_json TEXT)")
    before = sha(path)
    # the pre-flight alone refuses the stray table (the prefix is not owned yet) ...
    with closing(sqlite3.connect(path)) as c:
        assert any("incompatible pre-existing object" in p for p in preflight(c))
    # ... and since the DB-17 table allow-list (decision D1, 2026-11-11) the stray table is DRIFT already, so apply() stops before any migration, naming the table, and writes nothing
    with pytest.raises(ad.MigrationError, match="work_f2_recovered_rows.*outside the migration chain"):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before


def test_a_failure_inside_the_migration_rolls_back_everything_including_the_table(monkeypatch, tmp_path):
    bad = STATEMENTS + ("CREATE TABLE work_f2_recovered_rows(x)",)  # the second CREATE of the same name fails
    entry = (MIGRATION_ID, "prototype", lambda db: bad, preflight, "\n".join(bad))
    monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS + (entry,))
    monkeypatch.setattr(ad, "_OWNED_PREFIXES", ad._OWNED_PREFIXES + ("work_f2_",))
    path = fresh(tmp_path, "rb.sqlite")
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS[:-1]))
    before = sha(path)
    with pytest.raises(sqlite3.DatabaseError):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'work\\_f2\\_%' ESCAPE '\\'").fetchone()[0] == 0 and db.execute("PRAGMA user_version").fetchone()[0] == 14


def test_the_plan_is_read_only_and_names_0015_as_the_next_step(registered, tmp_path):
    path = fresh(tmp_path, "plan.sqlite")
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS[:-1]))
    before = sha(path)
    plan = ad.plan(path)
    assert sha(path) == before and plan["can_apply"] and plan["migrations"][-1]["migration"] == MIGRATION_ID and plan["migrations"][-1]["would_apply"]


def test_a_second_run_is_a_no_op(registered, tmp_path):
    path = migrated(tmp_path)
    before = sha(path)
    again = ad.apply(path, confirm_disposable_copy=True)
    assert again["applied"] == [] and sha(path) == before


def test_the_archive_has_no_effect_on_heads_events_or_the_existing_audit_when_a_row_is_added_through_the_capability(registered, tmp_path):
    path = migrated(tmp_path)
    baseline = S.counts(path)
    heads_before = S.heads(path)
    with closing(sqlite3.connect(path)) as db:
        db.create_function("work_f2_insert_allowed", 4, lambda *a: 1)  # the sanctioned recovery connection (a capability, not an authentication)
        db.execute("INSERT INTO work_f2_recovered_rows(source_copy_sha256, source_table, occurrence, row_sha256, payload_json) VALUES('a','article_versions',1,'b','{}')")
        db.commit()
    after = S.counts(path)
    assert {k: v for k, v in after.items() if not k.startswith("work_f2")} == {k: v for k, v in baseline.items() if not k.startswith("work_f2")}
    assert S.heads(path) == heads_before and db17(path) == "pass"
    for stmt in ("UPDATE work_f2_recovered_rows SET payload_json='x'", "DELETE FROM work_f2_recovered_rows"):
        with closing(sqlite3.connect(path)) as db:
            db.create_function("work_f2_insert_allowed", 4, lambda *a: 1)
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                db.execute(stmt)


def test_a_bare_connection_cannot_insert_into_the_archive(registered, tmp_path):
    path = migrated(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        with pytest.raises(sqlite3.DatabaseError, match="no such function|insert not allowed"):
            db.execute("INSERT INTO work_f2_recovered_rows(source_copy_sha256, source_table, occurrence, row_sha256, payload_json) VALUES('a','t',1,'b','{}')")


def test_db17_in_an_unrelated_database_is_not_affected_by_the_owned_prefix(registered, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    path = fresh(other, "o.sqlite")
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS[:-1]))
    assert db17(path) == "pass"  # a database that stops at 0009 has no work_f2_ objects and no complaint
    shutil.rmtree(other)
