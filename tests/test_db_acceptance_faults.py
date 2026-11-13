"""DB acceptance D — fault injection. Target kind: synthetic. Work's store code is driven into the failure; the audit then judges the file.
Failures that need a network (a monitor losing its connection mid-update) are not DB failures: they are covered in tests/test_audit_work_v2.py."""
import copy
import hashlib
import shutil
import sqlite3
from contextlib import closing
from datetime import date

import pytest

from tests import db_support as S
from admissions_pipeline.notice_articles import revise_article  # noqa: E402
from admissions_pipeline.process_lock import ProcessLock  # noqa: E402
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.store import canonical  # noqa: E402

NOTHING = {"evidence": {}, "articles": {}}


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    return path, p, store, tmp_path


def qa_for(batch, articles, success=True):
    return {"success": success, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical(articles).encode()).hexdigest()}


def test_an_exception_in_the_middle_of_activation_rolls_the_whole_update_back(world):
    path, p, store, _ = world
    batch = store.stage([S.notice(p)], S.REGISTRY)
    good = revise_article(S.base_article(store), store.effective_records(batch), date(2026, 11, 1))
    bad = dict(good, article_id="broken", base_article_id="no-such-base")  # the second article makes finalize raise AFTER the first insert
    with pytest.raises(ValueError):
        store.finalize(batch, [good, bad], qa_for(batch, [good, bad]), S.REGISTRY)
    assert S.heads(path) == NOTHING and S.counts(path)["revised_articles"] == 0
    r = S.audit(path)
    assert r["ok"] and r["invariants"]["DB-07"]["status"] == "warn"  # the staged candidate is still there to recover


def test_a_crash_between_staging_and_approval_is_recovered_without_activating(world):
    path, p, store, _ = world
    batch = store.stage([S.notice(p)], S.REGISTRY)  # the process "dies" here
    reopened = RevisionStore(path, world[3] / "backup2.sqlite")
    assert reopened.recover_candidates() == [batch["batch_id"]] and S.heads(path) == NOTHING
    r = S.audit(path)
    assert r["ok"] and r["invariants"]["DB-07"]["status"] == "pass"  # no unrecovered candidate any more


def test_the_state_right_after_activation_is_consistent_for_a_second_reader(world):
    path, p, store, _ = world
    S.approve(store, S.notice(p), S.base_article(store))
    other_process = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)  # a reader that opens the file now
    try:
        assert other_process.execute("SELECT evidence_id FROM evidence_heads").fetchall() == [("EV-U-1",)]
    finally:
        other_process.close()
    assert S.audit(path)["ok"]


def test_two_updates_staged_from_the_same_heads_cannot_both_activate(world):
    path, p, store, _ = world
    base = S.base_article(store)
    first = store.stage([S.notice(p)], S.REGISTRY)
    second = store.stage([S.notice(p, eid="EV-U-2", logical="other-notice", value={"allowed": "別の告知"})], S.REGISTRY)
    r1 = revise_article(base, store.effective_records(first), date(2026, 11, 1))
    assert store.finalize(first, [r1], qa_for(first, [r1]), S.REGISTRY)
    r2 = revise_article(base, store.effective_records(second), date(2026, 11, 1))
    with pytest.raises(ValueError, match="concurrent"):
        store.finalize(second, [r2], qa_for(second, [r2]), S.REGISTRY)
    assert S.heads(path)["evidence"] == {"notice": "EV-U-1"} and S.audit(path)["ok"]


def test_a_second_process_cannot_start_while_one_holds_the_lock(tmp_path):
    with ProcessLock(tmp_path / "update.lock"):
        with pytest.raises(RuntimeError, match="another collection process"):
            with ProcessLock(tmp_path / "update.lock"):
                pass
    with ProcessLock(tmp_path / "update.lock"):  # released: a new start works
        pass


def test_an_incomplete_backup_is_noticed_and_does_not_restore_the_old_state(world):
    path, p, store, tmp = world
    backup = tmp / "backup.sqlite"
    S.approve(store, S.notice(p), S.base_article(store))
    truncated = tmp / "truncated.sqlite"
    truncated.write_bytes(backup.read_bytes()[: backup.stat().st_size // 3])
    with pytest.raises(sqlite3.DatabaseError):
        S.audit(truncated)  # not a valid database at all
    empty_tables = tmp / "empty-tables.sqlite"
    shutil.copy(backup, empty_tables)
    S.sql(empty_tables, "DELETE FROM facts")
    assert "DB-09" in S.failing(empty_tables, backup)  # restoring from a backup that lost rows is caught against the older copy


def test_a_rejected_qa_keeps_the_heads_and_marks_the_batch_rejected(world):
    path, p, store, _ = world
    batch = store.stage([S.notice(p)], S.REGISTRY)
    assert store.finalize(batch, [], {"success": False}, S.REGISTRY) is False
    assert S.heads(path) == NOTHING
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT state FROM update_batches").fetchone()[0] == "rejected"
    assert S.audit(path)["ok"]


def test_missing_approval_information_blocks_activation_and_a_forged_approval_is_caught(world):
    path, p, store, _ = world
    batch = store.stage([S.notice(p)], S.REGISTRY)
    revised = revise_article(S.base_article(store), store.effective_records(batch), date(2026, 11, 1))
    with pytest.raises(ValueError):
        store.finalize(batch, [revised], {"success": True}, S.REGISTRY)  # no binding to this input: refused
    assert S.heads(path) == NOTHING
    S.approve(RevisionStore(path, world[3] / "b2.sqlite"), S.notice(p, eid="EV-U-9", logical="n9"), S.base_article(store))
    S.sql(path, "UPDATE update_batches SET qa_json='{}' WHERE state='approved'")  # the approval record is wiped
    assert "DB-07" in S.failing(path)


def test_retrying_the_same_registration_never_duplicates_anything(world):
    path, p, store, _ = world
    S.approve(store, S.notice(p), S.base_article(store))
    after_first = S.counts(path)
    for _ in range(3):
        again = store.stage([S.notice(p)], S.REGISTRY)
        assert again["state"] == "no_change"
    after = S.counts(path)
    assert after["evidence_revisions"] == after_first["evidence_revisions"] and after["revised_articles"] == after_first["revised_articles"]
    assert S.audit(path)["ok"]
