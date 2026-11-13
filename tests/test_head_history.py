"""Head history (M-14): the heads of any past time are replayed from the recorded approval and rollback events (migration 0009 and additive_schema.heads_as_of / read_as_of), and the replay up to
now must equal the current heads (db_audit DB-18). SELF_VALIDATED; synthetic databases. What it does not do: an `effective_at` argument of the public update API (not implemented), and a
reconstruction for a lineage that never recorded its approvals (that is a warning, not a replay)."""
import sqlite3
import time
from contextlib import closing

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
from src.db_contract import additive_schema as ad


def fix_clock(monkeypatch):
    """The events carry real timestamps: make each step distinguishable by sleeping a hair (ISO strings compare as time)."""
    time.sleep(0.01)


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    assert not ad.apply(path, confirm_disposable_copy=True)["rolled_back"]
    return path, p, store, tmp_path


def now(path):
    with closing(sqlite3.connect(path)) as c:
        return c.execute("select max(created_at) from update_events").fetchone()[0]


def test_the_heads_of_each_past_moment_are_replayed_from_the_approvals_and_the_rollback(world, monkeypatch):
    path, p, store, tmp = world
    t0 = "0000-01-01"  # before anything
    b1, a1, *_ = S.approve(store, S.notice(p), S.base_article(store))
    fix_clock(monkeypatch)
    t1 = now(path)
    time.sleep(0.01)
    s2 = RevisionStore(path, tmp / "b2.sqlite")
    b2, *_ = S.approve(s2, S.notice(p, eid="EV-U-2", logical="notice", parent_evidence_id="EV-U-1", sentences=["訂正後。"], value={"allowed": "訂正"}), S.base_article(s2))
    t2 = now(path)
    time.sleep(0.01)
    RevisionStore(path, tmp / "b3.sqlite").rollback_batch(b2["batch_id"])
    t3 = now(path)
    with closing(sqlite3.connect(path)) as c:
        assert ad.heads_as_of(c, t0) == {"evidence": {}, "articles": {}}  # before any approval nothing was a head
        assert ad.read_as_of(c, "notice", t0) is None
        assert ad.read_as_of(c, "notice", t1) == "EV-U-1"
        assert ad.read_as_of(c, "notice", t2) == "EV-U-2"  # the correction was the head between its approval and its rollback
        assert ad.read_as_of(c, "notice", t3) == "EV-U-1"  # the rollback restored the earlier head
        assert ad.read_as_of(c, "other", t3) is None  # a logical id that never had a head
        assert ad.heads_as_of(c, "9999-12-31") == {"evidence": S.heads(path)["evidence"], "articles": S.heads(path)["articles"]}  # the replay up to now equals the current heads
        assert [r[0] for r in c.execute("select event from v_head_events order by event_id")] == ["approved", "approved", "rolled_back"]


def test_a_candidate_an_interrupted_and_a_rejected_batch_never_appear_in_the_history(world):
    path, p, store, tmp = world
    cand = store.stage([S.notice(p, eid="EV-U-C", logical="c1")], S.REGISTRY)
    store.recover_candidates()
    rej = store.stage([S.notice(p, eid="EV-U-D", logical="c2")], S.REGISTRY)
    store.finalize(rej, [], {"success": False}, S.REGISTRY)
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("select count(*) from v_head_events").fetchone()[0] == 0
        assert ad.heads_as_of(c, "9999-12-31") == {"evidence": {}, "articles": {}}
    assert cand["state"] == "candidate" and S.audit(path)["invariants"]["DB-18"]["status"] in ("pass", "not_run")


def test_the_audit_checks_the_replay_against_the_current_heads_and_fails_on_a_contradiction(world):
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    assert S.audit(path)["invariants"]["DB-18"]["status"] == "pass"
    with closing(sqlite3.connect(path)) as c:  # a program that registers the capability rewrites a head: the approvals no longer explain it (D2's residual limit is DETECTED here)
        c.create_function("sogh_write_ok", 0, lambda: 1)
        c.execute("PRAGMA recursive_triggers=ON")
        c.execute("DELETE FROM evidence_heads")
        c.commit()
    r = S.audit(path)["invariants"]["DB-18"]
    assert r["status"] == "fail" and r["problems"][0]["key"] == "notice" and r["problems"][0]["replay"] == "EV-U-1" and r["problems"][0]["current"] is None


def test_a_lineage_that_never_recorded_its_approvals_is_not_run_never_a_pass(tmp_path):
    path, p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "backup.sqlite")
    with closing(sqlite3.connect(path)) as c:
        c.execute("insert into evidence_revisions values('EV-X','x','case','quota','" + "a" * 64 + "',NULL,'{}')")
        c.execute("insert into evidence_heads values('x','EV-X')")
        c.commit()
    r = S.audit(path)["invariants"]["DB-18"]
    assert r["status"] == "not_run" and "update_events has no rows" in r["reason"]  # heads with no recorded approval at all: nothing is examined, and it is said so (never a pass)


def test_the_view_changes_no_row_and_is_part_of_the_verified_schema(world):
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    assert ad.plan(path)["drift"] == [] and S.audit(path)["invariants"]["DB-17"]["status"] == "pass"
    assert "0009-m14-head-history" in [m[0] for m in ad.MIGRATIONS] and q(path) == [(ad._seq(ad.MIGRATIONS[-1][0]),)]


def q(path):
    with closing(sqlite3.connect(path)) as c:
        return c.execute("pragma user_version").fetchall()
