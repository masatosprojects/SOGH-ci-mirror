"""The audit's structural side: copy identity, schema listing, schema diff, triggers, indexes, the list of inputs. Synthetic databases."""
import hashlib
import shutil
import sqlite3
from contextlib import closing

import pytest

from src.integration import db_audit as da
from tests.test_db_audit import SCHEMA, build, sql


@pytest.fixture
def good(tmp_path):
    return build(tmp_path / "good.sqlite")


def test_the_report_records_which_file_was_audited(good):
    r = da.audit(good, None, "synthetic")
    assert r["copy_identity"] == {"file_name": "good.sqlite", "sha256": hashlib.sha256(good.read_bytes()).hexdigest(), "bytes": good.stat().st_size}


def test_a_file_that_is_not_the_announced_copy_is_refused_before_anything_is_judged(good):
    announced = hashlib.sha256(good.read_bytes()).hexdigest()
    assert da.audit(good, None, "synthetic", expect_sha256=announced)["ok"]
    with pytest.raises(ValueError, match="not the copy that was announced"):
        da.audit(good, None, "synthetic", expect_sha256="0" * 64)
    sql(good, "UPDATE facts SET value_json='{}'")  # a changed file no longer has the announced hash
    with pytest.raises(ValueError):
        da.audit(good, None, "synthetic", expect_sha256=announced)


def test_the_schema_section_lists_tables_indexes_triggers_and_the_migration_state(good):
    schema = da.audit(good, None, "synthetic")["schema"]
    assert "facts" in schema["tables"] and schema["indexes"] == [] and schema["triggers"] == []
    assert schema["schema_versions"] == ["test"] and schema["user_version"] == 0 and schema["has_schema_migrations"] is False


def test_append_only_tables_without_triggers_are_a_warning_not_a_pass(good):
    r = da.audit(good, None, "synthetic")
    assert r["ok"] and r["invariants"]["DB-14"]["status"] == "warn"
    tables = {p["table"] for p in r["invariants"]["DB-14"]["problems"]}
    assert {"facts", "article_versions", "evidence_revisions", "revised_articles"} <= tables


def test_a_table_guarded_by_update_and_delete_triggers_is_no_longer_listed(good):
    with closing(sqlite3.connect(good)) as db:
        for kind in ("UPDATE", "DELETE"):
            db.execute(f"CREATE TRIGGER facts_no_{kind.lower()} BEFORE {kind} ON facts BEGIN SELECT RAISE(ABORT, 'append-only'); END")
        db.commit()
    tables = {p["table"] for p in da.audit(good, None, "synthetic")["invariants"]["DB-14"]["problems"]}
    assert "facts" not in tables and "article_versions" in tables
    with closing(sqlite3.connect(good)) as db:  # and the guard really refuses
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM facts")


def test_a_trigger_that_guards_only_one_of_update_and_delete_still_counts_as_missing(good):
    with closing(sqlite3.connect(good)) as db:
        db.execute("CREATE TRIGGER facts_no_update BEFORE UPDATE ON facts BEGIN SELECT RAISE(ABORT, 'append-only'); END")
        db.commit()
    probs = [p for p in da.audit(good, None, "synthetic")["invariants"]["DB-14"]["problems"] if p["table"] == "facts"]
    assert probs and probs[0]["missing"] == ["DELETE"]


def test_lookup_columns_without_an_index_are_a_warning_and_an_index_clears_it(good):
    r = da.audit(good, None, "synthetic")
    assert r["invariants"]["DB-15"]["status"] == "warn"
    # facts(case_id) is already covered by the UNIQUE(case_id, source_sha256, fact_key) auto-index; evidence_revisions(case_id) is not
    assert any(p["table"] == "evidence_revisions" and p["column"] == "case_id" for p in r["invariants"]["DB-15"]["problems"])
    assert not any(p["table"] == "facts" for p in r["invariants"]["DB-15"]["problems"])
    sql(good, "CREATE INDEX ix_rev_case ON evidence_revisions(case_id)")
    after = da.audit(good, None, "synthetic")["invariants"]["DB-15"]["problems"]
    assert not any(p["table"] == "evidence_revisions" for p in after)


def test_the_schema_diff_against_the_baseline_names_what_was_added(good, tmp_path):
    backup = tmp_path / "before.sqlite"
    shutil.copy(good, backup)
    sql(good, "CREATE INDEX ix_facts_case ON facts(case_id)")
    sql(good, "ALTER TABLE source_documents ADD COLUMN published_at TEXT")
    sql(good, "CREATE TABLE schema_migrations(version TEXT PRIMARY KEY)")
    r = da.audit(good, backup, "synthetic")
    diff = r["schema"]["diff_from_baseline"]
    assert diff["indexes_added"] == ["ix_facts_case"] and diff["columns_added"] == {"source_documents": ["published_at"]}
    assert diff["tables_added"] == ["schema_migrations"] and diff["tables_removed"] == [] and r["ok"]
    assert r["schema"]["baseline_identity"]["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()


def test_the_schema_diff_names_what_was_removed_and_the_audit_fails(good, tmp_path):
    backup = tmp_path / "before.sqlite"
    shutil.copy(good, backup)
    sql(good, "DROP TABLE article_evidence")
    r = da.audit(good, backup, "synthetic")
    assert r["schema"]["diff_from_baseline"]["tables_removed"] == ["article_evidence"] and not r["ok"]


def test_without_a_baseline_there_is_no_diff_and_the_preservation_check_is_not_run(good):
    r = da.audit(good, None, "synthetic")
    assert "diff_from_baseline" not in r["schema"] and r["invariants"]["DB-09"]["status"] == "not_run"


def test_describe_inputs_lists_what_is_needed_and_says_not_run_is_never_a_pass(capsys):
    assert da.main(["--describe-inputs"]) == 0
    out = capsys.readouterr().out
    for needle in (".backup", "SHA-256", ".schema", "--baseline", "not_run is never a pass", "Never send the live database"):
        assert needle in out, needle


def test_the_cli_requires_a_database_and_a_target_kind(tmp_path, capsys):
    with pytest.raises(SystemExit):
        da.main([])
    with pytest.raises(SystemExit):
        da.main([str(tmp_path / "x.sqlite")])  # no --target-kind


def test_an_empty_real_style_database_proves_nothing_beyond_its_structure(tmp_path):
    path = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.commit()
    r = da.audit(path, None, "copied_real_db")
    assert r["target_kind"] == "copied_real_db" and r["summary"]["pass"] == ["DB-01"] and len(r["summary"]["not_run"]) == 15
