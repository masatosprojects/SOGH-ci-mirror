"""SELF_TEST (Claude, contract owner) for the DB-17 table allow-list (decision D1, approved 2026-11-11; design docs/DB17_MIGRATION_DESIGN_DRAFT_20261111.md).

``verify_schema_state`` used to report only objects with an owned name prefix (trg_ ux_ ix_ v_) that no applied migration creates, so a TABLE created outside the migration chain was invisible
(the quarantine / series tables of PR #306 were five such tables). It now also reports every table that is neither in the v06 base schema (BASE_TABLES) nor created by an applied migration.
SYNTHETIC databases only; nothing here touches a real database. Not an independent QA (the author is Claude)."""
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S  # noqa: E402  (puts Work's pipeline on the path)
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402


@pytest.fixture
def migrated(tmp_path):
    path, _p = S.make_native(tmp_path, "n.sqlite")
    RevisionStore(path, tmp_path / "n.backup")
    assert not ad.apply(path, confirm_disposable_copy=True)["rolled_back"]
    return path


def test_a_migrated_database_has_no_unknown_table(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        assert ad.verify_schema_state(c) == []


def test_every_table_of_the_synthetic_native_schema_is_in_the_base_tables(tmp_path):
    path, _p = S.make_native(tmp_path, "n.sqlite")
    RevisionStore(path, tmp_path / "n.backup")
    with closing(sqlite3.connect(path)) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert tables <= ad.BASE_TABLES  # the base list must not drift from the schema the pipeline creates


def test_a_table_created_outside_the_chain_is_reported_by_name(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        c.execute("CREATE TABLE stray_notes(staging_id TEXT PRIMARY KEY)")
        problems = ad.verify_schema_state(c)
    assert any("stray_notes" in p and "outside the migration chain" in p for p in problems)


def test_several_unknown_tables_are_each_reported(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        for t in ("stray_series", "_stray_seals", "stray_target"):
            c.execute(f'CREATE TABLE "{t}"(x TEXT)')
        problems = ad.verify_schema_state(c)
    assert len([p for p in problems if p.startswith("table ")]) == 3


def test_tables_created_by_the_migrations_are_not_reported(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"restore_events", "evidence_aliases", "revision_reasons", "schema_migrations"} <= names
        assert not [p for p in ad.verify_schema_state(c) if p.startswith("table ")]


def test_an_unmigrated_database_is_not_judged_by_this_check(tmp_path):
    path, _p = S.make_native(tmp_path, "n.sqlite")
    RevisionStore(path, tmp_path / "n.backup")
    with closing(sqlite3.connect(path)) as c:
        c.execute("CREATE TABLE anything(x)")
        assert ad.verify_schema_state(c) == []  # no migration history: nothing to compare against (apply() has its own pre-flight)


def test_an_unknown_table_makes_the_acceptance_gate_fail_too(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        c.execute("CREATE TABLE stray(x)")
        problems = ad.verify_history_for_acceptance(c, before=None)
    assert any("stray" in p for p in problems)
