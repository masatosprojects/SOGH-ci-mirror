"""DB v1 acceptance contract: the read-only audit (src/integration/db_audit.py) on independent, synthetic SQLite databases.

The schema is the one Work delivered (research/inbox/work-updates-v2/database-schema.sql); every row below is invented.
Each negative case damages ONE thing in an otherwise valid database and expects that invariant, and only it, to fail.
No real database is opened; the audit itself opens databases read-only.
"""
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.integration import db_audit as da

SCHEMA = (Path(__file__).resolve().parents[1] / "research" / "inbox" / "work-updates-v2" / "database-schema.sql").read_text(encoding="utf-8")
SHA = "a" * 64
SHA2 = "b" * 64


def j(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def fact_record(eid="EV-1", year=2027, method="試験方式", count=16, **extra):
    return {"evidence_id": eid, "key": "quota", "fact_key": "quota", "value": {"count": count}, "fiscal_year": year, "admission_method": method,
            "university": "試験大学", "faculty": "試験学部", **extra}


def build(path: Path) -> Path:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO schema_versions VALUES ('test')")
        db.execute("INSERT INTO admission_cycles VALUES ('case','試験大学','試験学部',NULL,'試験方式',2027,2026)")
        db.execute("INSERT INTO admission_cycles VALUES ('other','試験大学','試験学部',NULL,'別方式',2027,2026)")
        db.execute("INSERT INTO source_documents VALUES (?,?,?,?,?)", (SHA, "https://example.ac.jp/a.pdf", "x", "2026-11-01", "not_cleared"))
        db.execute("INSERT INTO source_pages VALUES (?,?,?,?)", (SHA, 1, "募集人員は16名です。", hashlib.sha256("募集人員は16名です。".encode()).hexdigest()))
        db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?)", ("EV-1", "case", SHA, "quota", j({"count": 16}), j(fact_record()), "source_checked_for_saved_version"))
        db.execute("INSERT INTO article_versions VALUES (?,?,?,?,?,?,?,0)", ("art", "case", "h" * 64, "overview", "t", "募集人員は16名[EV-1]です。", "p"))
        db.execute("INSERT INTO article_evidence VALUES ('art','EV-1')")
        db.commit()
    return path


def add_revision(path: Path, eid="EV-U-1", parent=None, **over):
    rec = {"evidence_id": eid, "logical_id": "notice", "case_id": "case", "fact_key": "generative_ai_policy", "fiscal_year": 2027,
           "admission_method": "試験方式", "value": {"allowed": "x", "not_accepted": ""}}
    rec.update(over.pop("record", {}))
    with closing(sqlite3.connect(path)) as db:
        db.execute("INSERT INTO evidence_revisions VALUES (?,?,?,?,?,?,?)",
                   (eid, over.get("logical", "notice"), over.get("case_id", "case"), over.get("fact_key", "generative_ai_policy"), SHA, parent, j(rec)))
        db.commit()


def sql(path: Path, statement: str, *args):
    with closing(sqlite3.connect(path)) as db:
        db.execute(statement, args)
        db.commit()


def failing(path: Path, baseline: Path | None = None) -> dict:
    r = da.audit(path, baseline)
    return {k: v for k, v in r["invariants"].items() if v["status"] == "fail"}


@pytest.fixture
def good(tmp_path):
    return build(tmp_path / "good.sqlite")


def test_a_valid_database_passes_and_what_could_not_run_is_not_a_pass(good):
    r = da.audit(good)
    assert r["ok"] and r["summary"]["fail"] == []
    assert r["original_source_comparison"] == "not_run"
    assert r["invariants"]["DB-09"]["status"] == "not_run"  # no baseline given
    for iid in ("DB-05", "DB-07", "DB-08"):  # this database has no update tables yet
        assert r["invariants"][iid]["status"] == "not_run" and r["invariants"][iid]["status"] != "pass", iid
    assert r["table_row_counts"]["facts"] == 1


def test_the_audit_never_writes_to_the_database(good):
    before = hashlib.sha256(good.read_bytes()).hexdigest()
    da.audit(good)
    assert hashlib.sha256(good.read_bytes()).hexdigest() == before
    with closing(sqlite3.connect(f"{good.resolve().as_uri()}?mode=ro", uri=True)) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM facts")


# ------------------------------------------------------------------ year / method / school mix-ups
@pytest.mark.parametrize("field,value", [("fiscal_year", 2026), ("admission_method", "別方式"), ("university", "△△大学"), ("faculty", "文学部")])
def test_a_fact_whose_record_disagrees_with_its_cycle_fails(good, field, value):
    rec = fact_record()
    rec[field] = value
    sql(good, "UPDATE facts SET record_json=? WHERE evidence_id='EV-1'", j(rec))
    assert set(failing(good)) == {"DB-04"}


def test_a_fact_whose_value_json_differs_from_its_record_fails(good):
    sql(good, "UPDATE facts SET value_json=? WHERE evidence_id='EV-1'", j({"count": 17}))
    assert set(failing(good)) == {"DB-04"}


def test_a_record_id_that_is_not_its_key_fails(good):
    sql(good, "UPDATE facts SET record_json=? WHERE evidence_id='EV-1'", j(fact_record(eid="EV-OTHER")))
    assert "DB-04" in failing(good)


def test_an_article_citing_evidence_of_another_cycle_fails(good):
    sql(good, "INSERT INTO facts VALUES (?,?,?,?,?,?,?)", "EV-2", "other", SHA, "quota", j({"count": 9}), j(fact_record("EV-2", method="別方式", count=9)),
        "source_checked_for_saved_version")
    sql(good, "UPDATE article_versions SET body='募集人員は9名[EV-2]です。' WHERE article_id='art'")
    assert set(failing(good)) == {"DB-06"}


def test_an_article_citing_evidence_that_does_not_exist_fails(good):
    sql(good, "UPDATE article_versions SET body='募集人員は16名[EV-NOWHERE]です。' WHERE article_id='art'")
    assert set(failing(good)) == {"DB-06"}


# ------------------------------------------------------------------ sources and duplicates
def test_a_page_text_that_does_not_match_its_hash_fails(good):
    sql(good, "UPDATE source_pages SET text='募集人員は160名です。' WHERE page=1")
    assert set(failing(good)) == {"DB-03"}


def test_a_source_with_a_malformed_hash_fails(tmp_path):
    path = build(tmp_path / "x.sqlite")
    sql(path, "INSERT INTO source_documents VALUES (?,?,?,?,?)", "Z" * 64, "https://example.ac.jp/b.pdf", "x", "2026-11-01", "c")
    assert set(failing(path)) == {"DB-03"}


def test_a_dangling_foreign_key_fails(good):
    sql(good, "INSERT INTO article_evidence VALUES ('art','EV-GONE')")
    assert "DB-01" in failing(good)


def test_the_same_cycle_twice_with_a_null_department_fails(good):
    sql(good, "INSERT INTO admission_cycles VALUES ('case2','試験大学','試験学部',NULL,'試験方式',2027,2026)")  # UNIQUE does not see NULLs as equal
    assert "DB-02" in failing(good)


def test_an_exam_year_far_from_the_entry_year_is_only_a_warning(good):
    sql(good, "UPDATE admission_cycles SET exam_year=2020 WHERE case_id='other'")
    r = da.audit(good)
    assert r["ok"] and r["invariants"]["DB-02"]["status"] == "warn"


# ------------------------------------------------------------------ revisions, heads, batches
def with_updates(path: Path) -> Path:
    add_revision(path)
    sql(path, "INSERT INTO evidence_heads VALUES ('notice','EV-U-1')")
    sql(path, "INSERT INTO update_batches VALUES ('b1',?,?,?,?,?,?,?)", "in", "approved", "2026-11-01", "{}", j({"evidence": {"notice": "EV-U-1"}, "articles": {}}), "r", j({"success": True, "batch_input_sha": "in"}))
    sql(path, "INSERT INTO update_events(batch_id,event,created_at,detail_json) VALUES ('b1','approved','2026-11-01','{}')")
    return path


def test_a_valid_update_history_passes(good):
    r = da.audit(with_updates(good))
    assert r["ok"], r["summary"]
    assert r["invariants"]["DB-05"]["status"] == "pass" and r["invariants"]["DB-07"]["status"] == "pass"


def test_a_head_pointing_at_nothing_or_the_wrong_logical_fact_fails(good):
    path = with_updates(good)
    sql(path, "UPDATE evidence_heads SET evidence_id='EV-GONE'")
    assert "DB-05" in failing(path)
    path2 = with_updates(build(path.parent / "second.sqlite"))
    sql(path2, "UPDATE evidence_heads SET logical_id='other-fact'")
    assert "DB-05" in failing(path2)


def test_a_revision_parent_from_another_fact_or_missing_or_cyclic_fails(good):
    path = build(good.parent / "p1.sqlite")
    add_revision(path, "EV-U-1")
    add_revision(path, "EV-U-2", parent="EV-1", fact_key="generative_ai_policy")  # parent is the quota fact: another fact_key
    assert "DB-05" in failing(path)
    path = build(good.parent / "p2.sqlite")
    add_revision(path, "EV-U-1", parent="EV-MISSING")
    assert "DB-05" in failing(path)
    path = build(good.parent / "p3.sqlite")
    add_revision(path, "EV-U-1", parent="EV-U-2")
    add_revision(path, "EV-U-2", parent="EV-U-1")
    assert any(p["what"] == "revision ancestry cycle" for p in failing(path)["DB-05"]["problems"])


def test_a_revision_record_for_another_year_fails(good):
    path = build(good.parent / "y.sqlite")
    add_revision(path, record={"fiscal_year": 2026})
    assert "DB-05" in failing(path)


def test_an_approved_batch_without_bound_qa_or_event_fails(good):
    path = with_updates(good)
    sql(path, "UPDATE update_batches SET qa_json=?", j({"success": False}))
    assert set(failing(path)) == {"DB-07"}
    path2 = with_updates(build(good.parent / "q2.sqlite"))
    sql(path2, "UPDATE update_batches SET qa_json=?", j({"success": True, "batch_input_sha": "something-else"}))
    assert set(failing(path2)) == {"DB-07"}
    path3 = with_updates(build(good.parent / "q3.sqlite"))
    sql(path3, "DELETE FROM update_events")
    assert set(failing(path3)) == {"DB-07"}


def test_a_crashed_candidate_is_a_warning_to_recover_not_a_pass(good):
    path = with_updates(good)
    sql(path, "INSERT INTO update_batches VALUES ('b2','in2','candidate','2026-11-01','{}','{}','r','{}')")
    r = da.audit(path)
    assert r["ok"] and r["invariants"]["DB-07"]["status"] == "warn" and "recover" in r["invariants"]["DB-07"]["problems"][0]["what"]


def test_two_revisions_with_identical_content_are_a_warning(good):
    path = build(good.parent / "d.sqlite")
    add_revision(path, "EV-U-1")
    add_revision(path, "EV-U-2")
    assert da.audit(path)["invariants"]["DB-08"]["status"] == "warn"


def test_a_revised_article_must_be_unpublishable_and_cite_its_own_cycle(good):
    path = with_updates(good)
    rec = {"article_id": "art:revision:0123456789abcdef", "text": "募集人員は16名[EV-1]です。", "publish_allowed": False, "revision_hash": "0123456789abcdef" + "0" * 48}
    sql(path, "INSERT INTO revised_articles VALUES (?,?,?,?)", "art:revision:0123456789abcdef", "art", "b1", j(rec))
    sql(path, "INSERT INTO article_heads VALUES ('art','art:revision:0123456789abcdef')")
    sql(path, "UPDATE update_batches SET after_json=?", j({"evidence": {"notice": "EV-U-1"}, "articles": {"art": "art:revision:0123456789abcdef"}}))  # the approval states the heads it produced (DB-18)
    assert da.audit(path)["ok"]
    sql(path, "UPDATE revised_articles SET record_json=?", j(dict(rec, publish_allowed=True)))
    assert set(failing(path)) == {"DB-06"}
    sql(path, "UPDATE revised_articles SET record_json=?", j(dict(rec, text="9名[EV-U-1]、[EV-GHOST]")))
    assert any("does not have" in p["what"] for p in failing(path)["DB-06"]["problems"])


def test_an_article_head_that_is_not_a_revision_of_its_base_fails(good):
    path = with_updates(good)
    sql(path, "INSERT INTO article_versions VALUES (?,?,?,?,?,?,?,0)", "art2", "case", "h" * 64, "overview", "t", "x", "p")
    rec = {"article_id": "art:revision:0123456789abcdef", "text": "x", "publish_allowed": False, "revision_hash": "0123456789abcdef" + "0" * 48}
    sql(path, "INSERT INTO revised_articles VALUES (?,?,?,?)", "art:revision:0123456789abcdef", "art", "b1", j(rec))
    sql(path, "INSERT INTO article_heads VALUES ('art2','art:revision:0123456789abcdef')")
    sql(path, "UPDATE update_batches SET after_json=?", j({"evidence": {"notice": "EV-U-1"}, "articles": {"art2": "art:revision:0123456789abcdef"}}))
    assert any("not a revision of its base" in p["what"] for p in failing(path)["DB-06"]["problems"])


# ------------------------------------------------------------------ history destruction / recovery (DB-09)
def test_an_unchanged_copy_and_an_appended_database_preserve_history(good, tmp_path):
    backup = tmp_path / "backup.sqlite"
    shutil.copy(good, backup)
    with_updates(good)  # an approved update only ADDS rows
    r = da.audit(good, backup)
    assert r["ok"] and r["invariants"]["DB-09"]["status"] == "pass"


@pytest.mark.parametrize("damage", [
    "UPDATE facts SET value_json='{\"count\": 99}'",
    "DELETE FROM facts",
    "DELETE FROM source_pages",
    "UPDATE article_versions SET body='書き換え'",
    "UPDATE admission_cycles SET fiscal_year=2028",
    "DROP TABLE article_evidence",
])
def test_changing_or_deleting_old_rows_fails_the_preservation_check(good, tmp_path, damage):
    backup = tmp_path / "backup.sqlite"
    shutil.copy(good, backup)
    sql(good, damage)
    assert "DB-09" in failing(good, backup)


def test_a_dropped_column_of_the_older_copy_fails(good, tmp_path):
    backup = tmp_path / "backup.sqlite"
    shutil.copy(good, backup)
    with closing(sqlite3.connect(good)) as db:
        db.execute("ALTER TABLE source_documents DROP COLUMN revision_clearance")
        db.commit()
    assert any("column" in p["what"] for p in failing(good, backup)["DB-09"]["problems"])


def test_restoring_the_backup_after_a_failed_update_gives_back_exactly_the_old_state(good, tmp_path):
    backup = tmp_path / "backup.sqlite"
    shutil.copy(good, backup)
    with_updates(good)
    sql(good, "UPDATE facts SET value_json='{\"count\": 99}'")  # an update that went wrong
    assert "DB-09" in failing(good, backup)
    restored = tmp_path / "restored.sqlite"
    shutil.copy(backup, restored)
    r = da.audit(restored, backup)
    assert r["ok"] and r["invariants"]["DB-09"]["status"] == "pass"


def test_a_database_with_a_corrupt_file_does_not_pass(tmp_path):
    path = tmp_path / "broken.sqlite"
    path.write_bytes(b"this is not a database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        da.audit(path)


# ------------------------------------------------------------------ the CLI
def test_cli_exit_codes_and_report(good, tmp_path, capsys):
    out = tmp_path / "r.json"
    assert da.main([str(good), "--target-kind", "synthetic", "--json-out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is True
    sql(good, "UPDATE facts SET value_json='{\"count\": 17}'")
    assert da.main([str(good), "--target-kind", "synthetic"]) == 1
    assert "DB-04" in capsys.readouterr().out


def test_the_audit_runs_on_the_real_delivered_schema_without_error(tmp_path):
    """The delivered schema file itself (no rows): every invariant runs; only what has no data is trivially clean."""
    path = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.commit()
    r = da.audit(path)
    assert r["ok"] and r["invariants"]["DB-01"]["status"] == "pass"
    # an EMPTY database examined nothing else: those invariants are not_run, never "pass"
    assert r["summary"]["pass"] == ["DB-01"] and len(r["summary"]["not_run"]) == 15
    assert set(r["invariants"]) == {f"DB-{i:02d}" for i in range(1, 13)} | {"DB-14", "DB-15", "DB-16", "DB-17", "DB-18", "DB-19"}
    assert r["summary"]["warn"] == ["DB-14", "DB-15"]  # structure alone: no triggers, no indexes in the delivered schema (G-09, G-03)
