"""Behaviour of Work's update path with the M1 stage-1 patch (patches/m1-stage1/work-pipeline-stage1.patch). SELF_VALIDATED; synthetic databases only.

This file is NOT collected by a normal run (its name does not match test_*.py): tests/test_work_stage1_patch.py starts it in a subprocess against a COPY of Work's pipeline
(SOGH_PIPELINE_ROOT) in one of two modes, so that both sides of the dependency are proven:
  SOGH_STAGE1_MODE=patched    the copy carries the patch: the update path must work under the final guards (frozen migration 0004) (capability gate, approved-only heads, recursive triggers)
  SOGH_STAGE1_MODE=unpatched  the delivered copy: the same guard rules must REFUSE its update path (that is why the patch has to come before the database side)
The guard rules used here are a test-local rendering of docs/architecture/M1_UNIFIED_DATA_ARCHITECTURE_RFC.md §9 (the frozen migrations come in a later PR, which
re-runs this file against them). Nothing is written to Work's directories or to any database file other than a temporary one.
"""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

MODE = os.environ.get("SOGH_STAGE1_MODE")
if MODE not in ("patched", "unpatched") or not os.environ.get("SOGH_PIPELINE_ROOT"):  # this file is not collected by a normal run (its name does not match test_*.py)
    raise RuntimeError("run it through tests/test_work_stage1_patch.py: SOGH_STAGE1_MODE=patched|unpatched and SOGH_PIPELINE_ROOT=<a copy of Work's pipeline>")


def only(mode):
    """Define the test only for one mode (no skip marker: a test that is not defined cannot be mistaken for a pass; the wrapper counts the passes)."""
    return (lambda f: f) if MODE == mode else (lambda f: None)


from tests import db_support as S  # noqa: E402
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.store import EvidenceStore, canonical  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402

@pytest.fixture
def world(tmp_path, monkeypatch):
    path, p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "backup.sqlite")
    assert not ad.apply(path, confirm_disposable_copy=True)["rolled_back"]
    if MODE == "unpatched":  # give the delivered code the capability so that the ONLY remaining difference is the order of its statements
        def connect_with_capability(self):
            import contextlib

            @contextlib.contextmanager
            def cm():
                db = sqlite3.connect(self.path, timeout=20)
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys=ON")
                db.create_function("sogh_write_ok", 0, lambda: 1)
                try:
                    yield db
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                finally:
                    db.close()
            return cm()
        monkeypatch.setattr(EvidenceStore, "connect", connect_with_capability)
    return path, p, tmp_path


def q(path, sql, *a):
    with closing(sqlite3.connect(path)) as c:
        return c.execute(sql, a).fetchall()


def raw(path, sql, *a, pragma=None):
    """Any other program: no capability function."""
    try:
        with closing(sqlite3.connect(path)) as c:
            if pragma:
                c.execute(pragma)
            c.execute(sql, a)
            c.commit()
        return "ACCEPTED"
    except sqlite3.DatabaseError as e:
        return "refused: " + str(e)


# ---------------------------------------------------------------------------------------------------------------------- the dependency, both sides
@only("unpatched")
def test_the_delivered_update_path_is_refused_by_the_approved_only_head_rule(world):
    """The delivered `finalize` moves the heads BEFORE it marks the batch approved: the approved-only rule refuses it, atomically. This is the dependency of PR-2 on stage 1."""
    path, p, tmp = world
    store = RevisionStore(path, tmp / "b2.sqlite")
    with pytest.raises(sqlite3.DatabaseError, match="approved batch"):
        S.approve(store, S.notice(p), S.base_article(store))
    assert S.heads(path) == {"evidence": {}, "articles": {}}  # nothing half done
    assert q(path, "select state from update_batches") == [("candidate",)]


@only("unpatched")
def test_the_delivered_connection_has_neither_the_capability_nor_recursive_triggers(tmp_path):
    path, p = S.make_native(tmp_path)
    with EvidenceStore(path).connect() as db:
        assert db.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError, match="no such function"):
            db.execute("select sogh_write_ok()")


@only("patched")
def test_the_patched_connection_registers_the_capability_and_turns_recursive_triggers_on(tmp_path):
    path, p = S.make_native(tmp_path)
    with EvidenceStore(path).connect() as db:
        assert db.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("select sogh_write_ok()").fetchone()[0] == 1


# ---------------------------------------------------------------------------------------------------------------------- the update path under the final guards (frozen migration 0004)
@only("patched")
def test_stage_finalize_and_the_approved_state_work_under_the_guard_rules(world):
    path, p, tmp = world
    store = RevisionStore(path, tmp / "b2.sqlite")
    batch, revised, qa, ok = S.approve(store, S.notice(p), S.base_article(store))
    assert ok and q(path, "select state from update_batches where batch_id=?", batch["batch_id"]) == [("approved",)]
    assert S.heads(path)["evidence"] == {"notice": "EV-U-1"} and S.heads(path)["articles"] == {revised["base_article_id"]: revised["article_id"]}
    assert S.failing(path) == {}  # db_audit: no invariant fails


@only("patched")
def test_a_second_update_then_rollbacks_in_order_work_and_rolled_back_heads_cannot_be_reinstated(world):
    path, p, tmp = world
    s1 = RevisionStore(path, tmp / "b1.sqlite")
    b1, *_ = S.approve(s1, S.notice(p), S.base_article(s1))
    s2 = RevisionStore(path, tmp / "b2.sqlite")
    b2, *_ = S.approve(s2, S.notice(p, eid="EV-U-2", logical="notice", parent_evidence_id="EV-U-1", sentences=["訂正後。"], value={"allowed": "訂正"}), S.base_article(s2))
    assert S.heads(path)["evidence"] == {"notice": "EV-U-2"}
    s3 = RevisionStore(path, tmp / "b3.sqlite")
    s3.rollback_batch(b2["batch_id"])
    assert S.heads(path)["evidence"] == {"notice": "EV-U-1"}
    s4 = RevisionStore(path, tmp / "b4.sqlite")
    s4.rollback_batch(b1["batch_id"])
    assert S.heads(path) == {"evidence": {}, "articles": {}}
    assert q(path, "select state from update_batches order by rowid") == [("rolled_back",), ("rolled_back",)]
    # D3: the evidence of a rolled back batch can no longer become a head, not even through the store's own connection
    with EvidenceStore(path).connect() as db:
        with pytest.raises(sqlite3.DatabaseError, match="approved batch"):
            db.execute("insert into evidence_heads values('notice','EV-U-1')")


@only("patched")
def test_recover_candidates_and_a_rejected_batch_work_under_the_guard_rules(world):
    path, p, tmp = world
    store = RevisionStore(path, tmp / "b2.sqlite")
    cand = store.stage([S.notice(p, eid="EV-U-C")], S.REGISTRY)
    assert store.recover_candidates() == [cand["batch_id"]]
    assert q(path, "select state from update_batches") == [("interrupted",)] and S.heads(path)["evidence"] == {}
    cand2 = store.stage([S.notice(p, eid="EV-U-D", logical="other")], S.REGISTRY)
    assert store.finalize(cand2, [], {"success": False}, S.REGISTRY) is False
    assert q(path, "select state from update_batches order by rowid") == [("interrupted",), ("rejected",)]


@only("patched")
def test_a_direct_sql_head_for_a_candidate_a_forged_approval_and_a_foreign_connection_are_all_refused(world):
    """D1 / D2 / D3 / the capability: what the delivered guards could not stop (tests/test_unified_design_falsification.py characterises it)."""
    path, p, tmp = world
    store = RevisionStore(path, tmp / "b2.sqlite")
    S.approve(store, S.notice(p), S.base_article(store))
    cand = store.stage([S.notice(p, eid="EV-U-CAND", logical="notice", parent_evidence_id="EV-U-1", sentences=["未承認の文。"], value={"allowed": "候補"})], S.REGISTRY)
    with store.connect() as db:  # even WITH the capability (the application's own connection) a candidate cannot become a head: D1
        with pytest.raises(sqlite3.DatabaseError, match="approved batch"):
            db.execute("update evidence_heads set evidence_id='EV-U-CAND' where logical_id='notice'")
    assert S.heads(path)["evidence"] == {"notice": "EV-U-1"}
    for sql in ("update update_batches set state='approved', after_json='{}', qa_json='{\"success\": true}' where batch_id='" + cand["batch_id"] + "'",  # D2 from outside
                "update evidence_heads set evidence_id='EV-U-CAND' where logical_id='notice'", "delete from evidence_heads", "update facts set value_json='{}'",
                "insert or replace into facts select * from facts"):
        refusal = raw(path, sql)  # another program: the gate refuses a write; an UPDATE or DELETE of an append-only table is refused by its own trigger on ANY connection
        assert refusal.startswith("refused:") and ("no such function: sogh_write_ok" in refusal or "append-only" in refusal), (sql, refusal)
    assert q(path, "select state from update_batches where batch_id=?", cand["batch_id"]) == [("candidate",)]


@only("patched")
def test_insert_or_replace_is_refused_only_because_recursive_triggers_is_on(world):
    """D4: with the capability but WITHOUT the pragma a REPLACE overwrites a fact; the patched connection (pragma ON) refuses it. So both parts of the patch are needed."""
    path, p, tmp = world
    f = q(path, "select evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification from facts")[0]
    with closing(sqlite3.connect(path)) as c:  # an application connection that forgot the pragma
        c.create_function("sogh_write_ok", 0, lambda: 1)
        c.execute("insert or replace into facts values(?,?,?,?,?,?,?)", (f[0], f[1], f[2], f[3], '{"x":1}', f[5], f[6]))
        c.rollback()
    with EvidenceStore(path).connect() as db:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("insert or replace into facts values(?,?,?,?,?,?,?)", (f[0], f[1], f[2], f[3], '{"x":1}', f[5], f[6]))
    assert q(path, "select value_json from facts where evidence_id=?", f[0]) == [(f[4],)]


# ---------------------------------------------------------------------------------------------------------------------- the reason of a batch (G-11)
@only("patched")
def test_finalize_records_the_reason_the_caller_gives_and_nothing_when_it_gives_none(world):
    path, p, tmp = world
    reason = {"reason_class": "new_fact", "reason_text": "FAQの新しい説明を追加", "source_changed": "no", "actor": "revise_notices"}
    store, batch, revised, qa = _stage_for_reason(path, p, tmp)
    assert store.finalize(batch, [revised], qa, S.REGISTRY, reason=reason)
    rows = q(path, "select batch_id, reason_class, reason_text, source_changed, actor from revision_reasons")
    assert rows == [(batch["batch_id"], "new_fact", "FAQの新しい説明を追加", "no", "revise_notices")]
    # no reason given: no row is invented (the audit shows the batch as missing)
    s2 = RevisionStore(path, tmp / "b3.sqlite")
    S.approve(s2, S.notice(p, eid="EV-U-2", logical="notice", parent_evidence_id="EV-U-1", sentences=["訂正後。"], value={"allowed": "訂正"}), S.base_article(s2))
    assert q(path, "select count(*) from revision_reasons") == [(1,)]


def _stage_for_reason(path, p, tmp):
    from admissions_pipeline.notice_articles import revise_article
    from datetime import date
    store = RevisionStore(path, tmp / "b9.sqlite")
    batch = store.stage([S.notice(p)], S.REGISTRY)
    revised = revise_article(S.base_article(store), store.effective_records(batch), date(2026, 11, 1), None)
    qa = {"success": True, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    return store, batch, revised, qa


@only("patched")
def test_a_reason_that_cannot_be_recorded_makes_the_whole_approval_roll_back(world):
    path, p, tmp = world
    # a database without migration 0006 (it has no revision_reasons table): a reason was asked for, the database cannot keep it, so the approval must not happen without it
    older = tmp / "without_g11"
    older.mkdir()
    path0, p0 = S.make_native(older)
    RevisionStore(path0, older / "backup.sqlite")
    chain = [m[0] for m in ad.MIGRATIONS]
    assert not ad.apply(path0, confirm_disposable_copy=True, only=tuple(m for m in chain if m < "0006"))["rolled_back"]
    store0, batch0, revised0, qa0 = _stage_for_reason(path0, p0, older)
    with pytest.raises(ValueError, match="no revision_reasons table"):
        store0.finalize(batch0, [revised0], qa0, S.REGISTRY, reason={"reason_class": "new_fact", "reason_text": "x", "source_changed": "no", "actor": "a"})
    assert q(path0, "select state from update_batches") == [("candidate",)] and S.heads(path0) == {"evidence": {}, "articles": {}}
    store, batch, revised, qa = _stage_for_reason(path, p, tmp)
    contradiction = {"reason_class": "locator_correction", "reason_text": "位置訂正", "source_changed": "yes", "source_sha256_after": "c" * 64, "actor": "a"}
    with pytest.raises(sqlite3.IntegrityError):  # a locator correction that claims a source change
        store.finalize(batch, [revised], qa, S.REGISTRY, reason=contradiction)
    assert q(path, "select state from update_batches") == [("candidate",)] and S.heads(path) == {"evidence": {}, "articles": {}}
    assert q(path, "select count(*) from revision_reasons") == [(0,)] and q(path, "select count(*) from revised_articles") == [(0,)]
    assert store.finalize(batch, [revised], qa, S.REGISTRY, reason={"reason_class": "new_fact", "reason_text": "追加", "source_changed": "no", "actor": "a"})  # and it can still be approved afterwards


# ---------------------------------------------------------------------------------------------------------------------- the other write paths
def test_promote_candidate_writes_the_main_database_through_a_configured_connection(world):
    """generic.promote_candidate opens its own connection to the main database and merges a candidate with INSERT OR IGNORE (every row fires the guards)."""
    from admissions_pipeline.generic import fingerprint, promote_candidate
    path, p, tmp = world
    candidate = tmp / "candidate.sqlite"
    with closing(sqlite3.connect(path)) as src, closing(sqlite3.connect(candidate)) as dst:
        src.backup(dst)
    cstore = EvidenceStore(candidate) if MODE == "patched" else None
    if MODE == "patched":
        S.ingest_cycle(cstore, "case-2", S.profile(university="別の試験大学", sha="d" * 64), tmp)
        with closing(sqlite3.connect(path)) as c:
            before = fingerprint(c)
        promote_candidate(candidate, path, before)
        assert q(path, "select count(*) from admission_cycles") == [(2,)] and q(path, "select count(*) from facts where case_id='case-2'") == [(1,)]
        assert S.failing(path) == {}
    else:  # the delivered connection cannot call the capability: the merge into a guarded database fails loudly and changes nothing
        with closing(sqlite3.connect(candidate)) as c:
            c.create_function("sogh_write_ok", 0, lambda: 1)
            c.execute("insert into admission_cycles values('case-2','別','x',NULL,'y',2027,2026)")
            c.commit()
        with closing(sqlite3.connect(path)) as c:
            before = fingerprint(c)
        with pytest.raises(sqlite3.DatabaseError, match="no such function"):
            promote_candidate(candidate, path, before)
        assert q(path, "select count(*) from admission_cycles") == [(1,)]


def test_the_inventory_of_sqlite_connections_in_work_s_pipeline_is_what_this_patch_was_written_against():
    """Every `sqlite3.connect(` of the pipeline, by file. A new or removed connection changes this list on purpose: each must be classified (write path -> configure_connection;
    read-only, backup target, or another database file -> not). Read on 2026-11-01 from research/inbox/work-faq-v3/pipeline."""
    root = Path(S.PIPELINE) / "admissions_pipeline"
    found = {f.name: len(re.findall(r"sqlite3\.connect\(", f.read_text(encoding="utf-8"))) for f in sorted(root.glob("*.py"))}
    found = {k: v for k, v in found.items() if v}
    assert found == {"__main__.py": 1, "collector.py": 2, "generic.py": 4, "legacy.py": 1, "monitor.py": 1, "revisions.py": 2, "store.py": 2}, found
    if MODE == "patched":
        text = {n: (root / n).read_text(encoding="utf-8") for n in found}
        assert "configure_connection(db)" in text["store.py"] and "configure_connection(db)" in text["generic.py"]
        # the remaining connections: read-only URIs, backup targets (no trigger runs), the checks of a snapshot, and two other database files
        assert text["legacy.py"].count("mode=ro") == 1 and text["revisions.py"].count("mode=ro") == 1
        assert "collection.sqlite" in text["collector.py"] and "monitor.sqlite" in text["monitor.py"]
