"""G-07 (the evidence VERSIONS a revised article cites, as rows) and G-11 (why a batch changed things), as the frozen migrations 0005 and 0006. SELF_VALIDATED; synthetic databases; Work's store code (with the
stage-1 patch) is driven under the full chain. Expected values come from the contract (docs/G07_G11_CONTRACT.md and docs/architecture/M1_UNIFIED_DATA_ARCHITECTURE_RFC.md §7-8), not from the implementation."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date

import pytest

from tests import db_support as S
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.revisions import RevisionStore
from src.db_contract import additive_schema as ad

H = "e" * 64
H2 = "d" * 64


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    return path, p, store, tmp_path


def q(path, sql, *a):
    with closing(sqlite3.connect(path)) as c:
        return c.execute(sql, a).fetchall()


def run(path, sql, *a):
    """The way SOGH's own code writes (capability registered): the guards of 0004 refuse any other connection."""
    with closing(S.app_connect(path)) as c:
        c.execute(sql, a)
        c.commit()


def migrate(path):
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"] and {"0005-g07-revised-article-evidence", "0006-g11-revision-reasons"} <= set(r["applied"]), r
    return r


def cited(record_json):
    return sorted(json.loads(record_json)["evidence_ids"])


def fail_rows(path):
    return {k: v["status"] for k, v in S.audit(path)["invariants"].items() if v["status"] == "fail"}


# ------------------------------------------------------------------------------------------------------ the chain
def test_the_whole_chain_applies_in_order_is_verified_clean_and_leaves_no_old_row_changed(world):
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    tables = ("facts", "article_versions", "article_evidence", "evidence_revisions", "revised_articles", "evidence_heads", "article_heads", "update_batches", "update_events", "batch_evidence")
    before = {t: q(path, f"select * from {t} order by 1") for t in tables}
    preview = ad.plan(path)
    assert preview["can_apply"] and [m["migration"] for m in preview["migrations"] if m["would_apply"]] == [m[0] for m in ad.MIGRATIONS]  # every pending migration would apply, tried on a copy
    migrate(path)
    assert {t: q(path, f"select * from {t} order by 1") for t in tables} == before
    assert ad.plan(path)["drift"] == [] and fail_rows(path) == {} and q(path, "pragma user_version") == [(ad._seq(ad.MIGRATIONS[-1][0]),)]
    assert ad.apply(path, confirm_disposable_copy=True)["applied"] == []  # a second run changes nothing


# ------------------------------------------------------------------------------------------------------ G-07
def test_existing_revised_articles_are_backfilled_from_what_their_records_state_and_nothing_else(world):
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    migrate(path)
    aid, rec = q(path, "select article_id, record_json from revised_articles")[0]
    assert sorted(x[0] for x in q(path, "select evidence_id from revised_article_evidence where article_id=?", aid)) == cited(rec)
    assert q(path, "select * from v_revised_article_evidence_mismatch") == []


def test_a_new_approval_after_the_migration_fills_the_relation_without_any_change_to_works_code(world):
    path, p, store, tmp = world
    migrate(path)
    S.approve(store, S.notice(p), S.base_article(store))
    aid, rec = q(path, "select article_id, record_json from revised_articles")[0]
    assert sorted(x[0] for x in q(path, "select evidence_id from revised_article_evidence where article_id=?", aid)) == cited(rec)
    assert all(c == "case" for (c,) in q(path, "select case_id from revised_article_evidence")) and q(path, "select * from v_revised_article_evidence_mismatch") == []


def test_a_record_citing_unknown_evidence_is_refused_whole_nothing_half_written(world):
    path, p, store, tmp = world
    migrate(path)
    base = q(path, "select article_id from article_versions")[0][0]
    run(path, "insert into update_batches values(?,?,?,?,?,?,?,?)", "b-x", "i" * 64, "candidate", "t", "{}", "{}", "r" * 64, "{}")
    n = q(path, "select count(*) from revised_articles")[0][0]
    with pytest.raises(sqlite3.DatabaseError, match="unknown or belongs to another case"):
        run(path, "insert into revised_articles values(?,?,?,?)", "rev-bad", base, "b-x", json.dumps({"evidence_ids": ["EV-case-1", "EV-NO-SUCH"]}))
    assert q(path, "select count(*) from revised_articles")[0][0] == n and q(path, "select count(*) from revised_article_evidence")[0][0] == 0


def test_evidence_of_another_case_is_refused(world):
    path, p, store, tmp = world
    migrate(path)
    f = q(path, "select evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification from facts")[0]
    cyc = q(path, "select university,faculty,department,admission_method,fiscal_year,exam_year from admission_cycles")[0]
    run(path, "insert into admission_cycles(case_id,university,faculty,department,admission_method,fiscal_year,exam_year) values('case-two',?,?,?,?,?,?)", cyc[0], "別の学部", cyc[2], cyc[3], cyc[4], cyc[5])
    run(path, "insert into facts values(?,?,?,?,?,?,?)", "EV-two-1", "case-two", f[2], f[3], f[4], f[5], f[6])
    base = q(path, "select article_id from article_versions")[0][0]
    run(path, "insert into update_batches values(?,?,?,?,?,?,?,?)", "b-y", "i" * 64, "candidate", "t", "{}", "{}", "r" * 64, "{}")
    with pytest.raises(sqlite3.DatabaseError, match="another case"):
        run(path, "insert into revised_articles values(?,?,?,?)", "rev-cross", base, "b-y", json.dumps({"evidence_ids": ["EV-two-1"]}))


def test_the_relation_refuses_an_unknown_article_an_alias_a_duplicate_and_any_edit_and_the_gate_refuses_a_bare_connection(world):
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    migrate(path)
    aid = q(path, "select article_id from revised_articles")[0][0]
    root, case, key = q(path, "select evidence_id, case_id, fact_key from facts")[0]
    run(path, "insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,kind,reason,created_at) values('EV-LEG',?,?,?,'legacy_compat_id','legacy','t')", root, case, key)
    for args, text in ((("no-such-article", root, "case"), "unknown or belongs"), ((aid, "EV-LEG", "case"), "never an alias"), ((aid, root, "case"), "UNIQUE")):
        with pytest.raises(sqlite3.DatabaseError, match=text):
            run(path, "insert into revised_article_evidence values(?,?,?)", *args)
    for stmt in ("update revised_article_evidence set case_id='x'", "delete from revised_article_evidence"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            run(path, stmt)
    with closing(sqlite3.connect(path)) as c:  # another program
        with pytest.raises(sqlite3.OperationalError, match="no such function: sogh_write_ok"):
            c.execute("insert into revised_article_evidence values(?,?,?)", (aid, "EV-U-1", "case"))


def test_a_revision_of_the_evidence_leaves_the_citations_of_the_older_article_as_they_were_and_both_are_found_by_the_root(world):
    path, p, store, tmp = world
    migrate(path)
    S.approve(store, S.notice(p), S.base_article(store))  # article 1 cites EV-U-1
    first = q(path, "select article_id from revised_articles")[0][0]
    rows_first = q(path, "select evidence_id from revised_article_evidence where article_id=? order by 1", first)
    store2 = RevisionStore(path, tmp / "b2.sqlite")
    rec = S.notice(p, eid="EV-U-2", logical="notice", parent_evidence_id="EV-U-1", sentences=["訂正後の文。"], value={"allowed": "訂正後"})
    S.approve(store2, rec, S.base_article(store2), previous_id=first)
    assert q(path, "select evidence_id from revised_article_evidence where article_id=? order by 1", first) == rows_first  # the old article still names the old version
    with closing(sqlite3.connect(path)) as c:
        found = {(a, e) for a, k, e in ad.impacted_articles(c, "EV-U-2")}
        assert any(a == first and e == "EV-U-1" for a, e in found) and len({a for a, _ in found}) == 2  # the root of EV-U-2 is the root of EV-U-1
        assert ad.root_of(c, "EV-U-2") == ad.root_of(c, "EV-U-1")
        old = ad.cited_version(c, first, "EV-U-1")
        assert old["cited_evidence_id"] == "EV-U-1" and old["follows_head"] is False  # the version cited is never the head (EV-U-2 is the head now)
        assert q(path, "select evidence_id from evidence_heads") == [("EV-U-2",)]
        with pytest.raises(ad.AliasError, match="does not cite"):
            ad.cited_version(c, first, "EV-U-2")  # an article does not silently cite what it did not cite


def test_the_first_version_article_and_the_revised_one_appear_together_in_the_citation_view(world):
    path, p, store, tmp = world
    migrate(path)
    S.approve(store, S.notice(p), S.base_article(store))
    assert {k for (k,) in q(path, "select article_kind from v_article_citations")} == {"base", "revised"}


def test_a_difference_between_the_record_and_the_relation_is_shown_never_silently_resolved(world):
    path, p, store, tmp = world
    migrate(path)
    S.approve(store, S.notice(p), S.base_article(store))
    aid = q(path, "select article_id from revised_articles")[0][0]
    with closing(sqlite3.connect(path)) as c:  # someone who can change the schema removes the protection first (DB-17 and plan then report it)
        c.execute("drop trigger trg_rae_append_only_delete")
        gone = c.execute("select evidence_id from revised_article_evidence where article_id=? limit 1", (aid,)).fetchone()[0]
        c.execute("delete from revised_article_evidence where article_id=? and evidence_id=?", (aid, gone))
        c.commit()
    assert q(path, "select article_id, kind, evidence_id from v_revised_article_evidence_mismatch") == [(aid, "in_record_not_in_relation", gone)]
    assert any("'trg_rae_append_only_delete'" in d and "missing" in d for d in ad.plan(path)["drift"]) and "DB-17" in fail_rows(path)


def test_the_backfill_registers_no_guess_for_unknown_evidence_and_the_view_shows_what_was_left_out(world):
    path, p, store, tmp = world
    base = q(path, "select article_id from article_versions")[0][0]
    run(path, "insert into update_batches values(?,?,?,?,?,?,?,?)", "b-old", "i" * 64, "approved", "t", "{}", "{}", "r" * 64, "{}")  # a past record that cites something that no longer exists
    run(path, "insert into revised_articles values(?,?,?,?)", "rev-old", base, "b-old", json.dumps({"evidence_ids": ["EV-case-1", "EV-GONE"]}))
    migrate(path)
    assert q(path, "select evidence_id from revised_article_evidence where article_id='rev-old'") == [("EV-case-1",)]
    assert q(path, "select article_id, kind, evidence_id from v_revised_article_evidence_mismatch") == [("rev-old", "in_record_not_in_relation", "EV-GONE")]


def test_an_alias_given_to_the_impact_lookup_is_resolved_to_its_root_and_an_unknown_id_is_an_error(world):
    path, p, store, tmp = world
    S.approve(store, S.notice(p), S.base_article(store))
    migrate(path)
    root, case, key = q(path, "select evidence_id, case_id, fact_key from facts")[0]
    run(path, "insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,kind,reason,created_at) values('EV-LEG',?,?,?,'legacy_compat_id','legacy','t')", root, case, key)
    with closing(sqlite3.connect(path)) as c:
        assert ad.impacted_articles(c, "EV-LEG") == ad.impacted_articles(c, root) and ad.impacted_articles(c, root)
        with pytest.raises(ad.AliasError):
            ad.impacted_articles(c, "EV-NOTHING")


# ------------------------------------------------------------------------------------------------------ G-11
def candidate(store, p, eid="EV-U-1", logical="notice"):
    return store.stage([S.notice(p, eid=eid, logical=logical)], S.REGISTRY)


def reason(path, batch_id, **over):
    kw = {"reason_class": "source_changed", "reason_text": "公式の文が改訂された", "source_changed": "yes", "actor": "claude-temporary", "source_sha256_before": H, "source_sha256_after": H2}
    kw.update(over)
    with closing(sqlite3.connect(path)) as c:  # record_reason registers the capability itself (the sanctioned writer)
        ad.record_reason(c, batch_id, **kw)
        c.commit()


def test_a_new_batch_keeps_its_reason_through_approval_and_rollback_and_works_ledger_free_through_works_finalize(world):
    path, p, store, tmp = world
    migrate(path)
    batch = candidate(store, p)
    revised = revise_article(S.base_article(store), store.effective_records(batch), date(2026, 11, 1))
    qa = {"success": True, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(S.canonical([revised]).encode()).hexdigest()}
    assert store.finalize(batch, [revised], qa, S.REGISTRY, reason={"reason_class": "source_changed", "reason_text": "公式の文が改訂された", "source_changed": "yes", "actor": "revise_notices", "source_sha256_before": H, "source_sha256_after": H2})
    assert q(path, "select reason_class, source_changed, actor from revision_reasons") == [("source_changed", "yes", "revise_notices")]  # written by Work's finalize (the stage-1 patch) in the same transaction
    RevisionStore(path, tmp / "b3.sqlite").rollback_batch(batch["batch_id"])
    assert q(path, "select state from update_batches where batch_id=?", batch["batch_id"]) == [("rolled_back",)] and q(path, "select count(*) from revision_reasons")[0][0] == 1
    assert dict(q(path, "select batch_id, reason_status from v_batch_reason_status"))[batch["batch_id"]] == "recorded"


@pytest.mark.parametrize("over,text", [
    ({"reason_text": "   "}, "CHECK"), ({"actor": ""}, "CHECK"),
    ({"reason_class": "locator_correction", "source_changed": "yes"}, "CHECK"),  # a locator correction cannot claim that the source changed
    ({"reason_class": "source_changed", "source_changed": "no", "source_sha256_after": None}, "CHECK"),  # a source change needs the new source
    ({"source_changed": "yes", "source_sha256_after": H, "source_sha256_before": H}, "CHECK"),  # a changed source differs from the old one
    ({"source_sha256_after": "short"}, "CHECK"),
])
def test_an_empty_or_contradictory_reason_is_refused(world, over, text):
    path, p, store, tmp = world
    migrate(path)
    batch = candidate(store, p)
    with pytest.raises(sqlite3.DatabaseError, match=text):
        reason(path, batch["batch_id"], **over)
    assert q(path, "select count(*) from revision_reasons")[0][0] == 0


def test_an_unknown_class_is_refused_by_the_code_and_a_bare_connection_cannot_write_a_reason_by_sql(world):
    path, p, store, tmp = world
    migrate(path)
    batch = candidate(store, p)
    with pytest.raises(ValueError, match="unknown reason class"):
        with closing(sqlite3.connect(path)) as c:
            ad.record_reason(c, batch["batch_id"], reason_class="because", reason_text="x", source_changed="no", actor="a")
    with closing(sqlite3.connect(path)) as c:
        with pytest.raises(sqlite3.OperationalError, match="no such function: sogh_write_ok"):
            c.execute("insert into revision_reasons values(?,?,?,?,?,?,?,?)", (batch["batch_id"], "other", "x", "no", None, None, "a", "t"))


def test_locator_correction_and_source_change_are_two_different_recorded_things(world):
    path, p, store, tmp = world
    migrate(path)
    b1 = candidate(store, p)
    reason(path, b1["batch_id"], reason_class="locator_correction", reason_text="引用位置の訂正", source_changed="no", source_sha256_before=None, source_sha256_after=None)
    b2 = candidate(store, p, eid="EV-U-9", logical="n9")
    reason(path, b2["batch_id"])
    assert dict(q(path, "select batch_id, reason_class || '/' || source_changed from revision_reasons")) == {b1["batch_id"]: "locator_correction/no", b2["batch_id"]: "source_changed/yes"}


def test_a_reason_is_written_once_never_replaced_or_deleted_and_never_for_a_batch_that_cannot_change_anything(world):
    path, p, store, tmp = world
    migrate(path)
    batch = candidate(store, p)
    reason(path, batch["batch_id"])
    with pytest.raises(sqlite3.IntegrityError):
        reason(path, batch["batch_id"], reason_text="すり替えた理由")
    for stmt in ("update revision_reasons set reason_text='x'", "delete from revision_reasons"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            run(path, stmt)
    store.finalize(batch, [], {"success": False}, S.REGISTRY)  # now rejected
    other = candidate(store, p, eid="EV-U-8", logical="n8")
    store.finalize(other, [], {"success": False}, S.REGISTRY)
    with pytest.raises(sqlite3.DatabaseError, match="only for a candidate or approved"):
        reason(path, other["batch_id"])  # a rejected batch can no longer be given a reason


def test_a_mistake_in_a_reason_is_corrected_by_a_numbered_new_row_and_the_first_reason_stays(world):
    path, p, store, tmp = world
    migrate(path)
    batch = candidate(store, p)
    reason(path, batch["batch_id"], reason_class="wording", reason_text="言い回しの整理", source_changed="no", source_sha256_before=None, source_sha256_after=None)
    with closing(sqlite3.connect(path)) as c:
        n1 = ad.correct_reason(c, batch["batch_id"], reason_class="source_changed", reason_text="実は公式の文が改訂されていた", source_changed="yes", source_sha256_before=H, source_sha256_after=H2, correction_note="原典の比較で誤りに気づいた", actor="claude-temporary")
        n2 = ad.correct_reason(c, batch["batch_id"], reason_class="source_changed", reason_text="改訂箇所の説明を補足", source_changed="yes", source_sha256_before=H, source_sha256_after=H2, correction_note="補足", actor="claude-temporary")
        c.commit()
    assert (n1, n2) == (1, 2)
    assert q(path, "select reason_class, reason_text from revision_reasons") == [("wording", "言い回しの整理")]  # what was first written is untouched
    assert q(path, "select reason_class, reason_text, corrections from v_batch_reason_current") == [("source_changed", "改訂箇所の説明を補足", 2)]  # the current reading
    with pytest.raises(sqlite3.DatabaseError, match="numbered one after another"):
        run(path, "insert into revision_reason_corrections values(?,?,?,?,?,?,?,?,?,?)", batch["batch_id"], 5, "other", "x", "no", None, None, "n", "a", "t")
    for stmt in ("update revision_reason_corrections set reason_text='x'", "delete from revision_reason_corrections"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            run(path, stmt)
    with pytest.raises(sqlite3.DatabaseError, match="CHECK"):  # a correction obeys the same contradiction rules as a reason
        with closing(sqlite3.connect(path)) as c:
            ad.correct_reason(c, batch["batch_id"], reason_class="locator_correction", reason_text="x", source_changed="yes", correction_note="n", actor="a", source_sha256_after=H2)


def test_the_status_view_never_invents_a_reason_for_the_past_and_marks_a_missing_one(world):
    path, p, store, tmp = world
    old = candidate(store, p, eid="EV-OLD", logical="old")  # a batch before the contract existed
    migrate(path)
    new = candidate(store, p, eid="EV-NEW", logical="new")  # a batch after it, without a reason
    done = candidate(store, p, eid="EV-DONE", logical="done")
    reason(path, done["batch_id"])
    status = dict(q(path, "select batch_id, reason_status from v_batch_reason_status"))
    assert status[old["batch_id"]] == "not_recorded_before_the_contract" and status[new["batch_id"]] == "missing" and status[done["batch_id"]] == "recorded"
    assert q(path, "select count(*) from revision_reasons where batch_id=?", old["batch_id"])[0][0] == 0  # nothing was filled in for the past
    assert q(path, "select last_batch_rowid_before from revision_reason_contract") == [(1,)]  # the boundary is a row position, recorded once


def test_an_unchanged_retry_adds_no_reason_and_is_not_asked_for_one(world):
    path, p, store, tmp = world
    migrate(path)
    b = store.stage([S.notice(p)], S.REGISTRY)
    store.finalize(b, [], {"success": False}, S.REGISTRY)
    again = store.stage([S.notice(p)], S.REGISTRY)
    assert q(path, "select count(*) from revision_reasons")[0][0] == 0
    if again["state"] == "no_change":
        assert dict(q(path, "select batch_id, reason_status from v_batch_reason_status"))[again["batch_id"]] == "not_applicable"


def test_a_database_that_already_has_a_table_of_these_names_stops_the_run_and_stays_as_it_was(world):
    path, p, store, tmp = world
    run(path, "create table revision_reasons(x)")
    before = path.read_bytes()
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["rolled_back"] and "0006-g11-revision-reasons" in r["blocked"] and path.read_bytes() == before
