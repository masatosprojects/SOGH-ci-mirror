"""Independent review of Work's 0010 SQL candidate (PR #96: `research/inbox/work-f2-recovery-candidate/0010-work-f2-archive-candidate.sql`) against Claude's G-2 contract (docs/F2_G2_MIGRATION_AND_DB17_CONTRACT.md).

Claude-owned QA. DEFINED ONLY when Work's SQL file exists (absent, not skipped, until PR #96 is merged). SYNTHETIC_ONLY: disposable synthetic databases in a temporary directory; no real rows, no real database. Work's SQL is READ as text and
registered in this process only, through Claude's own mechanism (the monkeypatched registry of tests/test_f2_archive_db17_prototype.py): nothing is added to src/db_contract/migrations and Work's harness is not called.
Passing accepts nothing: the registry change and the ownership prefix are Claude's change to make after the agreement, and the archive is not the F-2 restoration."""
import hashlib
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_F2_DIR") or REPO / "research" / "inbox" / "work-f2-recovery-candidate")
SQL = WORK / "0010-work-f2-archive-candidate.sql"

if SQL.exists():
    MID = "0015-work-f2-archive-candidate"
    TEXT = SQL.read_text(encoding="utf-8")
    STATEMENTS = tuple(s.strip().rstrip(";").strip() for s in re.split(r"^-- @@\s*$", TEXT, flags=re.M)[1:])
    GUARD_ARGS = 9

    def preflight(db):
        return [f"preexisting unregistered archive object {n!r}" for (n,) in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'work!_f2!_%' ESCAPE '!'")]

    @pytest.fixture
    def registered(monkeypatch):
        entry = (MID, "F-2 archive candidate (Work)", lambda db: STATEMENTS, preflight, TEXT)
        monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS + (entry,))
        monkeypatch.setattr(ad, "_OWNED_PREFIXES", ad._OWNED_PREFIXES + ("work_f2_",))

    def fresh(tmp_path, name="m.sqlite"):
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

    def run(path, *statements, capability=False):
        with closing(sqlite3.connect(path)) as db:
            db.create_function("sogh_write_ok", 0, lambda: 1)
            if capability:
                db.create_function("work_f2_insert_allowed", GUARD_ARGS, lambda *a: 1)
            for s in statements:
                db.execute(s)
            db.commit()

    ROW = "INSERT INTO work_f2_recovered_rows VALUES('" + "a" * 64 + "','article_versions','" + "b" * 64 + "',1,'[]','[]','CREATE TABLE t(x)','missing_in_new','archive_candidate_not_active')"

    def test_the_candidate_is_structure_only_five_statements_and_no_rows():
        assert len(STATEMENTS) == 5 and STATEMENTS[0].startswith("CREATE TABLE work_f2_recovered_rows")
        assert sum(1 for s in STATEMENTS if s.startswith("CREATE TRIGGER")) == 4
        assert not re.search(r"\bINSERT\b", TEXT.split("-- @@", 1)[0]) and "INSERT INTO" not in "\n".join(STATEMENTS)
        verbs = [x.split(None, 1)[0].upper() for x in STATEMENTS]
        assert verbs == ["CREATE"] * 5, verbs  # every statement creates; none drops, alters or touches another object
        stray = [x[:60] for x in STATEMENTS if not (re.search(r"work_f2_recovered_rows", x) or x.startswith("CREATE TRIGGER work_f2_"))]
        assert stray == [], stray

    def test_only_the_owned_namespace_is_created(registered, tmp_path):
        base = migrated(tmp_path)
        with closing(sqlite3.connect(base)) as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'work!_f2!_%' ESCAPE '!'")}
        assert names == {"work_f2_recovered_rows", "work_f2_no_update", "work_f2_no_delete", "work_f2_no_replace", "work_f2_insert_guard"}

    def test_applying_it_reaches_0010_with_history_checksum_user_version_and_db17_pass(registered, tmp_path):
        path = migrated(tmp_path)
        with closing(sqlite3.connect(path)) as db:
            hist = ad.history(db)
            assert hist[-1][0] == MID and hist[-1][1] == hashlib.sha256(TEXT.encode()).hexdigest()
            assert db.execute("PRAGMA user_version").fetchone()[0] == 12
            assert ad.verify_history(db) == [] and ad.verify_schema_state(db) == []
        assert db17(path) == "pass"

    def test_frozen_0002_to_0009_are_unchanged_by_adding_it(registered):
        assert [m[0] for m in ad.MIGRATIONS[:-1]][-1] == "0011-g05-alias-provenance" and len(ad.MIGRATIONS) == 11

    @pytest.mark.parametrize("attack,statements", [
        ("a guard trigger is dropped", ("DROP TRIGGER work_f2_no_delete",)),
        ("the insert guard is dropped", ("DROP TRIGGER work_f2_insert_guard",)),
        ("the replace guard is dropped", ("DROP TRIGGER work_f2_no_replace",)),
        ("a guard is replaced by a weaker one", ("DROP TRIGGER work_f2_no_update", "CREATE TRIGGER work_f2_no_update BEFORE UPDATE ON work_f2_recovered_rows BEGIN SELECT 1; END")),
        ("the table is replaced by an unguarded copy", ("DROP TABLE work_f2_recovered_rows", "CREATE TABLE work_f2_recovered_rows(seq INTEGER PRIMARY KEY, payload TEXT)")),
        ("an extra object of the owned namespace appears", ("CREATE INDEX work_f2_extra ON work_f2_recovered_rows(row_sha256)",)),
        ("user_version is rewound", ("PRAGMA user_version=11",)),
    ])
    def test_db17_detects_every_tamper_once_the_objects_are_owned(registered, tmp_path, attack, statements):
        path = migrated(tmp_path)
        assert db17(path) == "pass"
        run(path, *statements)
        assert db17(path) == "fail", attack

    def test_without_the_registry_entry_and_prefix_db17_cannot_see_the_objects(tmp_path):
        """The present state (G-2). The candidate's objects exist only when the migration is registered; a copy that carries them is flagged as drift by an owner-aware DB-17 and invisible without it."""
        path = migrated(tmp_path)  # the frozen chain only: the candidate is NOT registered here
        run(path, *STATEMENTS)  # created by hand, as in Work's earlier non-migration archive
        assert db17(path) == "pass"  # the frozen DB-17 does not see work_f2_* (G-2)

    def test_a_bare_connection_cannot_insert_and_the_capability_has_nine_arguments(registered, tmp_path):
        path = migrated(tmp_path)
        with closing(sqlite3.connect(path)) as db:
            with pytest.raises(sqlite3.DatabaseError, match="no such function|insert"):
                db.execute(ROW)
        with closing(sqlite3.connect(path)) as db:
            db.create_function("work_f2_insert_allowed", 4, lambda *a: 1)  # a capability with the wrong arity is not the capability
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(ROW)

    def test_with_the_capability_a_row_goes_in_and_update_delete_replace_are_refused(registered, tmp_path):
        path = migrated(tmp_path)
        run(path, ROW, capability=True)
        for stmt in ("UPDATE work_f2_recovered_rows SET loss_kind='x'", "DELETE FROM work_f2_recovered_rows",
                     ROW.replace("INSERT INTO", "INSERT OR REPLACE INTO"), ROW):
            with closing(sqlite3.connect(path)) as db:
                db.create_function("work_f2_insert_allowed", GUARD_ARGS, lambda *a: 1)
                with pytest.raises(sqlite3.DatabaseError):
                    db.execute(stmt)
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT count(*) FROM work_f2_recovered_rows").fetchone()[0] == 1

    def test_an_insert_cannot_claim_an_active_restoration_state(registered, tmp_path):
        path = migrated(tmp_path)
        with closing(sqlite3.connect(path)) as db:
            db.create_function("work_f2_insert_allowed", GUARD_ARGS, lambda *a: 1)
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(ROW.replace("archive_candidate_not_active", "restored"))

    def test_the_archive_moves_no_canonical_row_head_or_approval(registered, tmp_path):
        path = migrated(tmp_path)
        before_counts, before_heads = S.counts(path), S.heads(path)
        run(path, ROW, capability=True)
        after = S.counts(path)
        assert {k: v for k, v in after.items() if not k.startswith("work_f2")} == {k: v for k, v in before_counts.items() if not k.startswith("work_f2")}
        assert S.heads(path) == before_heads and db17(path) == "pass"

    def test_a_database_that_already_holds_an_unguarded_archive_is_refused_and_left_byte_identical(registered, tmp_path):
        path = fresh(tmp_path, "pre.sqlite")
        ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS[:-1]))
        run(path, "CREATE TABLE work_f2_recovered_rows(seq INTEGER PRIMARY KEY, payload TEXT)")
        before = sha(path)
        with pytest.raises(ad.MigrationError, match="not created by any applied migration"):
            ad.apply(path, confirm_disposable_copy=True)
        assert sha(path) == before

    def test_a_failure_inside_the_migration_rolls_everything_back(monkeypatch, tmp_path):
        bad = STATEMENTS + ("CREATE TABLE work_f2_recovered_rows(x)",)
        entry = (MID, "x", lambda db: bad, preflight, "\n".join(bad))
        monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS + (entry,))
        monkeypatch.setattr(ad, "_OWNED_PREFIXES", ad._OWNED_PREFIXES + ("work_f2_",))
        path = fresh(tmp_path, "rb.sqlite")
        ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS[:-1]))
        before = sha(path)
        with pytest.raises(sqlite3.DatabaseError):
            ad.apply(path, confirm_disposable_copy=True)
        assert sha(path) == before

    def test_a_second_run_is_a_no_op_and_the_plan_is_read_only(registered, tmp_path):
        path = migrated(tmp_path)
        before = sha(path)
        assert ad.apply(path, confirm_disposable_copy=True)["applied"] == []
        assert ad.plan(path)["can_apply"] and sha(path) == before

    def test_the_sql_text_equals_what_the_recovery_module_generates():
        """The candidate must not be hand-edited away from the reviewed constants it claims to be generated from (a hand-edited trigger would be a different guard)."""
        import importlib.util
        import sys
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("pr96_recover_history", WORK / "recover_history.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        generated = [mod.DDL.replace(" IF NOT EXISTS", "")] + list(mod.TRIGGERS.values())
        assert [ad._norm(s) for s in STATEMENTS] == [ad._norm(s) for s in generated]
