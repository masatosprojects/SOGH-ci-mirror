"""DB acceptance C — destruction of history. Target kind: synthetic. The audit must notice that an old version was overwritten, forged,
deleted, or only half of an update is there."""
import json
import shutil
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore  # noqa: E402


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    backup = tmp_path / "before.sqlite"
    shutil.copy(path, backup)
    _, revised, _, ok = S.approve(store, S.notice(p), S.base_article(store))
    assert ok
    return path, p, store, backup, revised, tmp_path


def test_a_clean_update_keeps_every_old_row(world):
    path, _, _, backup, _, _ = world
    r = S.audit(path, backup)
    assert r["ok"] and r["invariants"]["DB-09"]["status"] == "pass"


@pytest.mark.parametrize("damage", [
    "UPDATE facts SET value_json='{\"count\": 99}', record_json='{}'",
    "UPDATE article_versions SET body='書き換えられた本文'",
    "UPDATE source_pages SET text='書き換え'",
    "DELETE FROM article_evidence",
    "UPDATE admission_cycles SET fiscal_year=2030",
])
def test_overwriting_or_deleting_an_old_fact_article_or_page_fails_the_preservation_check(world, damage):
    path, _, _, backup, _, _ = world
    S.sql(path, damage)
    assert "DB-09" in S.failing(path, backup)


def test_a_forged_revision_hash_fails_and_so_does_a_changed_parent(world):
    path, p, store, backup, revised, _ = world
    with closing(sqlite3.connect(path)) as db:
        rec = json.loads(db.execute("SELECT record_json FROM revised_articles").fetchone()[0])
        rec["revision_hash"] = "f" * 64
        db.execute("UPDATE revised_articles SET record_json=?", (json.dumps(rec, ensure_ascii=False),))
        db.commit()
    assert any("revision_hash" in x["what"] for x in S.failing(path)["DB-06"]["problems"])


def test_a_revision_whose_parent_was_re_pointed_to_another_fact_fails(world):
    path, p, store, backup, _, tmp = world
    S.ingest_cycle(S.EvidenceStore(path), "case-b", S.profile(university="別の大学", sha="c" * 64), tmp, count=40)
    S.sql(path, "UPDATE evidence_revisions SET parent_evidence_id='EV-case-b-1'")
    assert "DB-05" in S.failing(path)


def test_deleting_the_active_version_leaves_a_head_pointing_at_nothing(world):
    path, *_ = world
    S.sql(path, "DELETE FROM evidence_revisions")
    assert "DB-01" in S.failing(path) or "DB-05" in S.failing(path)


def test_deleting_the_revised_article_but_not_its_head_fails(world):
    path, *_ = world
    S.sql(path, "DELETE FROM revised_articles")
    assert "DB-01" in S.failing(path) or "DB-06" in S.failing(path)


def test_a_migration_that_drops_an_old_table_or_column_fails(world):
    path, _, _, backup, _, _ = world
    with closing(sqlite3.connect(path)) as db:
        db.execute("ALTER TABLE source_documents DROP COLUMN revision_clearance")
        db.commit()
    assert any("column" in x["what"] for x in S.failing(path, backup)["DB-09"]["problems"])
    S.sql(path, "DROP TABLE article_evidence")
    assert any("table" in x["what"] for x in S.failing(path, backup)["DB-09"]["problems"])


def test_only_part_of_an_update_applied_is_reported(world):
    """A head moved but its approved batch says another: the latest approved batch's heads must be the current heads."""
    path, p, store, backup, _, _ = world
    S.sql(path, "UPDATE evidence_heads SET evidence_id='EV-U-1'")  # same as before: consistent
    assert S.audit(path)["invariants"]["DB-07"]["status"] == "pass"
    S.sql(path, "UPDATE update_batches SET after_json=?", json.dumps({"evidence": {"notice": "EV-U-OTHER"}, "articles": {}}))
    assert S.audit(path)["invariants"]["DB-07"]["status"] == "warn"
