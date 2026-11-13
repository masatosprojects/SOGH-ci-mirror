"""Falsification tests for the unified M1 data architecture review (docs/architecture/M1_UNIFIED_DATA_ARCHITECTURE_RFC.md). SELF_VALIDATED; synthetic databases only.

Two kinds of test live here:
  * test_known_defect_* / test_known_limit_*  CHARACTERISE what the merged / proposed migrations (PR #70, #71, #72) really do today. They pass while the defect exists.
    When a fix is adopted the test must be flipped on purpose (that is the point: no safety claim stays untested).
  * test_prototype_*  prove that the fix recommended in the RFC is feasible. Nothing here is written to src/ or applied to any database file other than a temporary one.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad


ROOT_VIEW = (
    "CREATE VIEW IF NOT EXISTS v_evidence_root AS WITH RECURSIVE chain(evidence_id, root_evidence_id) AS ("
    " SELECT evidence_id, evidence_id FROM facts"
    " UNION ALL SELECT evidence_id, evidence_id FROM evidence_revisions WHERE parent_evidence_id IS NULL"
    "   OR parent_evidence_id NOT IN (SELECT evidence_id FROM facts UNION SELECT evidence_id FROM evidence_revisions)"
    " UNION ALL SELECT r.evidence_id, c.root_evidence_id FROM evidence_revisions r JOIN chain c ON r.parent_evidence_id = c.evidence_id)"
    " SELECT evidence_id, root_evidence_id FROM chain")


def with_root_view(path):
    """The PROPOSED recursive root view (the same text the unapproved PR #72 carries), created in the throw-away test database only."""
    with closing(sqlite3.connect(path)) as c:
        c.execute(ROOT_VIEW)
        c.commit()


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"]
    return path, p, store, tmp_path


def q(path, sql, *a):
    with closing(sqlite3.connect(path)) as c:
        return c.execute(sql, a).fetchall()


def run(path, sql, *a, pragma=None, app=True):
    """`app=True`: a connection the way SOGH's own code opens one (capability registered, recursive triggers ON); `app=False`: any other program (no capability)."""
    try:
        with closing(S.app_connect(path) if app else sqlite3.connect(path)) as c:
            if pragma:
                c.execute(pragma)
            c.execute(sql, a)
            c.commit()
        return "ACCEPTED"
    except sqlite3.DatabaseError as e:
        return "refused: " + str(e)


def fact(path):
    return q(path, "select evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification from facts")[0]


# ===================================================================== known defects of the merged / proposed code
def test_fixed_d1_a_head_cannot_point_at_an_unapproved_candidate_revision_not_even_with_the_capability(world):
    """D1 (fixed by 0004 + the stage-1 patch): the head rule needs an APPROVED batch, and the delivered order of Work's finalize (heads first) is replaced by approve-then-heads."""
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    cand = store.stage([S.notice(p, eid="EV-U-CAND", logical="notice", parent_evidence_id="EV-U-1", sentences=["未承認の文。"], value={"allowed": "候補"})], S.REGISTRY)
    assert q(path, "select state from update_batches where batch_id=?", cand["batch_id"]) == [("candidate",)]
    sql = "update evidence_heads set evidence_id='EV-U-CAND' where logical_id='notice'"
    assert "approved batch" in run(path, sql)  # a SOGH connection: refused by the head rule
    assert run(path, sql, app=False).startswith("refused: no such function: sogh_write_ok")  # any other program: refused by the gate
    assert S.heads(path)["evidence"]["notice"] == "EV-U-1"


def test_known_limit_d2_only_a_holder_of_the_capability_can_forge_an_approval_and_signatures_are_the_remaining_step(world):
    """INV-06 / INV-12: another program can no longer move a batch to approved (gate). A program that registers the capability still can, with any qa_json: the database cannot tell a real QA result
    from a forged one. Recorded as the residual limit (G-08: signed QA results; the approval of the data is not a publication approval)."""
    path, p, store, tmp = world
    cand = store.stage([S.notice(p, eid="EV-U-F", logical="forged")], S.REGISTRY)
    sql = "update update_batches set state='approved', after_json='{}', qa_json='{\"success\": true, \"forged\": 1}' where batch_id=?"
    assert run(path, sql, cand["batch_id"], app=False).startswith("refused: no such function: sogh_write_ok")
    assert q(path, "select state from update_batches where batch_id=?", cand["batch_id"]) == [("candidate",)]
    assert run(path, sql, cand["batch_id"]) == "ACCEPTED"  # the residual limit (D2): a capability holder
    assert q(path, "select state from update_batches where batch_id=?", cand["batch_id"]) == [("approved",)]


def test_fixed_d3_a_head_cannot_point_at_the_evidence_of_a_rolled_back_batch(world):
    path, p, store, tmp = world
    batch, *_ = S.approve(store, S.notice(p), S.base_article(store))
    RevisionStore(path, tmp / "b2.sqlite").rollback_batch(batch["batch_id"])
    assert S.heads(path)["evidence"] == {}
    assert "approved batch" in run(path, "insert into evidence_heads values('notice','EV-U-1')")  # 'rolled_back' is no longer an allowed state of the head rule
    assert S.heads(path)["evidence"] == {}


def test_fixed_d4_insert_or_replace_cannot_overwrite_append_only_tables_approved_batches_or_article_versions(world):
    """D4 (fixed): a SOGH connection runs with recursive_triggers ON, so the implicit delete of a REPLACE fires the append-only delete trigger; any other connection is refused by the gate."""
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    f = fact(path)
    b = q(path, "select * from update_batches")[0]
    a = q(path, "select article_id,case_id,input_hash,series,title,body,artifact_path,publish_allowed from article_versions")[0]
    cases = [("insert or replace into facts values(?,?,?,?,?,?,?)", (f[0], f[1], f[2], f[3], '{"x":1}', f[5], f[6])),
             ("insert or replace into update_batches values(?,?,?,?,?,?,?,?)", (b[0], b[1], b[2], b[3], '{"tampered":1}', b[5], b[6], b[7])),
             ("insert or replace into article_versions values(?,?,?,?,?,?,?,?)", (a[0], a[1], a[2], a[3], "改ざん", a[5], a[6], a[7]))]
    for sql, args in cases:
        assert "never" in run(path, sql, *args) or "append-only" in run(path, sql, *args), sql  # a SOGH connection
        assert run(path, sql, *args, app=False).startswith("refused: no such function: sogh_write_ok"), sql  # another program
    assert q(path, "select value_json from facts where evidence_id=?", f[0]) == [(f[4],)] and q(path, "select before_json from update_batches")[0][0] == b[4]


def test_fixed_d5_a_dropped_or_weakened_protection_is_reported_by_the_runner(world):
    """D5 (fixed by the schema-state check, PR-2 of the M1 plan): the history says applied, and the schema that is really there is compared with it."""
    path, *_ = world
    assert ad.plan(path)["drift"] == []  # a clean migrated database
    run(path, "drop trigger trg_ao_facts_update")
    run(path, "drop trigger trg_alias_is_append_only_update")
    run(path, "create trigger trg_alias_is_append_only_update before update on evidence_aliases begin select 1; end")  # weakened, not dropped
    plan = ad.plan(path)
    assert plan["can_apply"] is False
    assert any("'trg_ao_facts_update'" in d and "missing" in d for d in plan["drift"]) and any("'trg_alias_is_append_only_update'" in d and "differs" in d for d in plan["drift"])
    with pytest.raises(ad.MigrationError):
        ad.apply(path, confirm_disposable_copy=True)
    run(path, "create trigger trg_unlisted_rule before insert on facts begin select 1; end")  # an object in the namespace that no migration created
    assert any("trg_unlisted_rule" in d and "not created by any applied migration" in d for d in ad.plan(path)["drift"])


def test_fixed_d5_the_applied_sql_hash_is_compared_with_the_code(world, monkeypatch):
    """G-02 (fixed): the definition checksum still covers the frozen file, and the recorded hash of the SQL that was APPLIED is compared with the SQL the code holds for it: a statement that the code
    now says differently is reported even when the database itself is untouched."""
    path, *_ = world
    assert ad.plan(path)["drift"] == []
    chain = tuple(ad.MIGRATIONS)
    altered = tuple((st.replace("b.state = 'approved'", "b.state IN ('candidate', 'approved')") if "CREATE TRIGGER trg_head_evidence_insert" in st else st, needs) for st, needs in ad._PARSED_0004)
    monkeypatch.setattr(ad, "MIGRATIONS", tuple((m[0], m[1], ad._frozen_statements(altered) if m[0].startswith("0004") else m[2], m[3], m[4]) for m in chain))
    drift = ad.plan(path)["drift"]
    assert any("0004" in d and "differs from the SQL that was applied" in d for d in drift) and any("'trg_head_evidence_insert'" in d and "differs" in d for d in drift)


def test_fixed_d6_the_root_of_a_revision_is_the_root_of_its_series_not_the_revision_itself(world):
    path, p, store, tmp = world
    root = fact(path)[0]
    f = fact(path)
    with closing(S.app_connect(path)) as c:
        c.execute("insert into evidence_revisions values('EV-R1','l',?,?,?,?,'{}')", (f[1], f[3], f[2], root))
        c.execute("insert into evidence_revisions values('EV-R2','l',?,?,?,'EV-R1','{}')", (f[1], f[3], f[2]))
        c.commit()
        assert ad.resolve(c, "EV-R2")["root"] == root and ad.root_of(c, "EV-R2") == root and ad.root_of(c, root) == root
        assert c.execute("select root_evidence_id from v_evidence_root where evidence_id='EV-R2'").fetchone()[0] == root
        assert ad.read_version(c, "EV-R2")["resolved_evidence_id"] == "EV-R2"  # a revision id names its own version: the root and the version to read are different questions


def deep_chain(path, n):
    f = fact(path)
    prev = f[0]
    with closing(S.app_connect(path)) as c:
        for i in range(1, n + 1):
            c.execute("insert into evidence_revisions values(?,?,?,?,?,?,'{}')", (f"EV-G{i}", "gen", f[1], f[3], f[2], prev))
            prev = f"EV-G{i}"
        c.commit()
    return f


def alias(path, name, pinned, f, pragma=None):
    return run(path, "insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,pinned_evidence_id,kind,reason,created_at) values(?,?,?,?,?,'legacy_compat_id','x','t')", name, f[0], f[1], f[3], pinned, pragma=pragma)


def test_fixed_d6_the_pinned_alias_check_accepts_any_depth_and_refuses_a_foreign_root(world):
    path, *_ = world
    f = deep_chain(path, 100)
    assert alias(path, "EV-AL3", "EV-G3", f) == "ACCEPTED" and alias(path, "EV-AL6", "EV-G6", f) == "ACCEPTED" and alias(path, "EV-AL100", "EV-G100", f) == "ACCEPTED"
    run(path, "insert into facts(evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification) values(?,?,?,?,?,?,?)", "EV-OTHER", f[1], f[2], f[3] + "2", f[4], f[5], f[6])
    run(path, "insert into evidence_revisions values('EV-OTHER-R1','o',?,?,?,?,'{}')", f[1], f[3] + "2", f[2], "EV-OTHER")
    assert alias(path, "EV-ALX", "EV-OTHER-R1", f).startswith("refused")  # another root's revision
    assert alias(path, "EV-ALY", f[0], f).startswith("refused")  # the root itself is not a revision


def test_fixed_d6_a_cyclic_revision_series_is_listed_as_orphans_and_has_no_root(world):
    path, *_ = world
    f = fact(path)
    with closing(S.app_connect(path)) as c:
        c.execute("insert into evidence_revisions values('EV-CY1','cy',?,?,?,'EV-CY2','{}')", (f[1], f[3], f[2]))
        c.execute("insert into evidence_revisions values('EV-CY2','cy',?,?,?,'EV-CY1','{}')", (f[1], f[3], f[2]))
        c.commit()
    assert q(path, "select root_evidence_id from v_evidence_root where evidence_id in ('EV-CY1','EV-CY2')") == []  # the view still has no root for them ...
    assert sorted(r[0] for r in q(path, "select evidence_id from v_evidence_orphans")) == ["EV-CY1", "EV-CY2"]  # ... but they are no longer silent
    with closing(sqlite3.connect(path)) as c:
        with pytest.raises(ad.AliasError, match="no root"):
            ad.root_of(c, "EV-CY1")


def test_fixed_d7_the_offering_identity_has_no_source_so_a_revised_document_is_not_a_second_offering(tmp_path):
    from tests.test_additive_schema import OFFERINGS
    path, p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "b.sqlite")
    run(path, OFFERINGS)
    assert not ad.apply(path, confirm_disposable_copy=True)["rolled_back"]
    case = q(path, "select case_id from admission_cycles")[0][0]
    ins = lambda oid, src: run(path, "insert into admission_offerings(offering_id,case_id,round_name,entry_month,scope_json,source_sha256) values(?,?,?,?,?,?)", oid, case, "夏秋AO", 4, '{"x":1}', src)
    assert ins("o1", "a" * 64) == "ACCEPTED" and ins("o2", "b" * 64).startswith("refused")  # one real offering, one row (the second document is linked by offering_sources)
    assert q(path, "select count(*) from admission_offerings")[0][0] == 1


def test_safe_the_same_cycle_identity_under_another_case_id_fails_loudly_in_the_ingest_path(world):
    path, p, store, tmp = world
    with pytest.raises(sqlite3.IntegrityError):  # the cycle row is dropped by INSERT OR IGNORE, the fact then violates the foreign key: loud, atomic
        S.ingest_cycle(store, "case-dup", S.profile(), tmp / "dup")
    assert q(path, "select count(*) from admission_cycles")[0][0] == 1 and q(path, "select count(*) from facts where case_id='case-dup'")[0][0] == 0


# ===================================================================== prototypes of the recommended fixes
def test_prototype_a_view_based_pinned_check_is_what_the_migration_now_carries(world):
    """Kept as the bridge to the RFC: the view-based check that was a prototype is trigger trg_alias_pinned_version_descends of the frozen 0003 (see test_fixed_d6_*)."""
    path, *_ = world
    assert "v_evidence_root" in q(path, "select sql from sqlite_master where name='trg_alias_pinned_version_descends'")[0][0]


def test_prototype_comparing_the_recorded_applied_sql_hash_with_the_code_detects_changed_generated_sql(world):
    path, *_ = world
    with closing(sqlite3.connect(path)) as c:
        for mid, desc, stmts, pre, definition in ad.MIGRATIONS:
            rec = c.execute("select statements_applied_sha256 from schema_migrations where version=?", (mid,)).fetchone()[0]
            assert rec == hashlib.sha256("\n".join(stmts(c)).encode()).hexdigest(), mid  # clean: every applied hash equals what this code would generate now


def test_prototype_heads_can_be_rebuilt_from_the_approved_batches_so_an_as_of_view_is_possible(world):
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    store2 = RevisionStore(path, tmp / "b2.sqlite")
    batch2, *_ = S.approve(store2, S.notice(p, eid="EV-U-2", logical="notice", parent_evidence_id="EV-U-1", sentences=["訂正後。"], value={"allowed": "訂正"}), S.base_article(store2))
    RevisionStore(path, tmp / "b3.sqlite").rollback_batch(batch2["batch_id"])  # the second one is rolled back: the replay must skip it
    ev, ar = {}, {}
    for state, after in q(path, "select state, after_json from update_batches order by rowid"):
        if state == "approved":
            a = json.loads(after)
            ev.update(a.get("evidence", {}))
            ar.update(a.get("articles", {}))
    assert ev == S.heads(path)["evidence"] and ar == S.heads(path)["articles"]
