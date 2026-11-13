"""G-02 (the migration history contract) and G-09 (append-only triggers). SELF_VALIDATED; synthetic databases only; Work's own store code is driven AFTER the migration
to prove that the legitimate update path still works. The triggers guard future writes: they never repair F-2 (the v03->v04 history) and they do not accept it."""
import hashlib
import sqlite3
from contextlib import closing
from datetime import date

import pytest

from tests import db_support as S
from admissions_pipeline.notice_articles import revise_article  # noqa: E402
from admissions_pipeline.process_lock import ProcessLock  # noqa: E402
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.store import canonical  # noqa: E402
from src.db_contract import additive_schema as ad

CHAIN = [m[0] for m in ad.MIGRATIONS]


def qa_for(batch, articles, success=True):
    return {"success": success, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical(articles).encode()).hexdigest()}


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    return path, p, store, tmp_path


@pytest.fixture
def migrated(world):
    path, p, store, tmp = world
    assert ad.apply(path, confirm_disposable_copy=True)["applied"] == CHAIN
    return path, p, store, tmp


def fetch(path, sql, *a):
    with closing(S.app_connect(path)) as c:
        return c.execute(sql, a).fetchall()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ G-02: the history contract
def test_the_history_has_the_requested_columns_and_the_user_version_follows_it(migrated):
    path, *_ = migrated
    cols = [r[1] for r in fetch(path, "pragma table_info(schema_migrations)")]
    assert cols[:4] == ["version", "from_version", "applied_at", "checksum"]
    rows = fetch(path, "select version, from_version, seq from schema_migrations order by seq")
    assert [r[0] for r in rows] == CHAIN and [r[1] for r in rows[1:]] == CHAIN[:-1]
    assert fetch(path, "pragma user_version")[0][0] == ad._seq(CHAIN[-1]) and ad.plan(path)["drift"] == []


def test_the_first_from_version_is_what_schema_versions_said_never_an_invented_baseline(migrated):
    path, *_ = migrated
    last = fetch(path, "select version from schema_versions order by rowid desc limit 1")
    first = fetch(path, "select from_version from schema_migrations order by seq limit 1")[0][0]
    assert first == (last[0][0] if last else None) and fetch(path, "select count(*) from schema_migrations where version like '0001%'")[0][0] == 0


def test_a_migration_edited_after_it_was_applied_is_refused(migrated, monkeypatch):
    path, *_ = migrated
    edited = tuple((m[0], m[1], m[2], m[3], m[4] + " -- edited") if m[0] == CHAIN[0] else m for m in ad.MIGRATIONS)
    monkeypatch.setattr(ad, "MIGRATIONS", edited)
    assert any("checksum mismatch" in d for d in ad.plan(path)["drift"])
    before = sha(path)
    with pytest.raises(ad.MigrationError, match="checksum mismatch"):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before


def test_an_applied_migration_unknown_to_the_code_is_refused(migrated, monkeypatch):
    path, *_ = migrated
    monkeypatch.setattr(ad, "MIGRATIONS", ad.MIGRATIONS[:2])  # an older code meeting a newer database
    with pytest.raises(ad.MigrationError, match="unknown to this code"):
        ad.apply(path, confirm_disposable_copy=True)


def test_a_skipped_or_out_of_order_history_is_refused(world):
    path, *_ = world
    with closing(S.app_connect(path)) as c:  # a history that has 0003 but not 0002 (made by hand on a throw-away file)
        c.execute(ad.SCHEMA_MIGRATIONS)
        known = {m[0]: m for m in ad.MIGRATIONS}
        c.execute("insert into schema_migrations values(?,?,?,?,?,?,?,?)", (CHAIN[1], None, "t", ad._sha(known[CHAIN[1]][4]), "d", 3, "0" * 64, "[]"))
        c.execute("pragma user_version = 3")
        c.commit()
    assert any("prefix of the chain" in d for d in ad.plan(path)["drift"])
    with pytest.raises(ad.MigrationError):
        ad.apply(path, confirm_disposable_copy=True)


def test_a_user_version_that_disagrees_with_the_history_is_detected(migrated):
    path, *_ = migrated
    with closing(S.app_connect(path)) as c:
        c.execute("pragma user_version = 1")
        c.commit()
    assert any("user_version" in d for d in ad.plan(path)["drift"])
    with pytest.raises(ad.MigrationError, match="user_version"):
        ad.apply(path, confirm_disposable_copy=True)


def test_only_may_name_just_the_next_pending_migrations_in_order(world):
    path, *_ = world
    before = sha(path)
    with pytest.raises(ad.MigrationError):
        ad.apply(path, confirm_disposable_copy=True, only=(CHAIN[1],))
    assert sha(path) == before
    assert ad.apply(path, confirm_disposable_copy=True, only=(CHAIN[0],))["applied"] == [CHAIN[0]] and fetch(path, "pragma user_version")[0][0] == 2
    assert ad.apply(path, confirm_disposable_copy=True)["applied"] == CHAIN[1:] and fetch(path, "pragma user_version")[0][0] == ad._seq(CHAIN[-1])


def test_the_draft_layout_of_the_history_table_is_not_silently_accepted(world):
    path, *_ = world
    with closing(S.app_connect(path)) as c:
        c.execute("CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, description TEXT, statements_sha256 TEXT, applied_at TEXT)")
        c.commit()
    with pytest.raises(ad.MigrationError, match="another layout"):
        ad.apply(path, confirm_disposable_copy=True)


def test_a_failure_leaves_neither_a_history_row_nor_a_changed_user_version(world, monkeypatch):
    path, *_ = world
    before = sha(path)
    bad = ad.MIGRATIONS[:1] + (("0003-broken", "x", lambda db: ("CREATE TABLE half(x)", "CREATE TABLE nonsense("), lambda db: [], "broken"),)
    monkeypatch.setattr(ad, "MIGRATIONS", bad)
    with pytest.raises(sqlite3.OperationalError):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before and fetch(path, "pragma user_version")[0][0] == 0


# ------------------------------------------------------------------ G-09: append-only triggers
def first_column(path, table):
    return fetch(path, f'pragma table_info("{table}")')[0][1]


APPEND_ONLY = ad.TABLE_CLASS["A"]


def test_every_append_only_table_that_has_a_row_refuses_update_and_delete_and_keeps_its_rows(migrated):
    path, p, store, _ = migrated
    S.approve(store, S.notice(p), S.base_article(store))  # makes update_events / batch_evidence / evidence_revisions / revised_articles non-empty
    checked = []
    for table in APPEND_ONLY:
        if not fetch(path, "select 1 from sqlite_master where type='table' and name=?", table):
            continue  # a table of a later lineage (the synthetic store of the older pipeline lacks it)
        n = fetch(path, f'select count(*) from "{table}"')[0][0]
        if not n:
            continue
        col = first_column(path, table)
        before = fetch(path, f'select * from "{table}" order by 1')
        for stmt in (f'update "{table}" set "{col}" = "{col}"', f'delete from "{table}"'):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                with closing(S.app_connect(path)) as c:  # a fresh connection: foreign_keys is OFF here
                    c.execute(stmt)
                    c.commit()
        assert fetch(path, f'select * from "{table}" order by 1') == before
        checked.append(table)
    assert {"facts", "article_versions", "evidence_revisions", "revised_articles", "update_events", "batch_evidence", "source_documents"} <= set(checked)
    assert fetch(path, "select count(*) from sqlite_master where type='trigger' and name like 'trg_ao_%'")[0][0] == 2 * sum(1 for t in APPEND_ONLY if fetch(path, f"select 1 from sqlite_master where name='{t}'"))


def test_a_new_row_is_still_accepted_by_an_append_only_table(migrated):
    path, p, store, _ = migrated
    f = fetch(path, "select evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification from facts")[0]
    with closing(S.app_connect(path)) as c:
        c.execute("insert into facts values(?,?,?,?,?,?,?)", ("EV-NEW-1", f[1], f[2], "online_period", f[4], f[5], f[6]))
        c.commit()
    assert fetch(path, "select count(*) from facts")[0][0] == 2


def test_the_triggers_do_not_depend_on_foreign_keys_or_on_the_connection(migrated):
    path, *_ = migrated
    with closing(S.app_connect(path)) as c:
        assert c.execute("pragma foreign_keys").fetchone()[0] == 0
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("update article_versions set title='tampered'")
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("delete from facts")
    with closing(S.app_connect(path)) as c:
        c.execute("pragma foreign_keys=ON")
        c.execute("pragma recursive_triggers=ON")
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("update facts set value_json='{}'")


def test_the_cycle_identity_cannot_be_rewritten_and_no_cycle_is_deleted_but_other_columns_are_left_alone(migrated):
    path, *_ = migrated
    with closing(S.app_connect(path)) as c:
        for col, val in (("university", "x"), ("faculty", "x"), ("department", "x"), ("admission_method", "x"), ("fiscal_year", 2030), ("exam_year", 2030)):
            with pytest.raises(sqlite3.DatabaseError, match="identity columns"):
                c.execute(f"update admission_cycles set {col}=?", (val,))
        with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
            c.execute("delete from admission_cycles")


def batch_row(path, state="candidate", bid="b1"):
    with closing(S.app_connect(path)) as c:
        c.execute("insert into update_batches values(?,?,?,?,?,?,?,?)", (bid, "i" * 64, state, "t", "{}", "{}", "r" * 64, "{}"))
        c.commit()


def upd(path, sql, *a):
    with closing(S.app_connect(path)) as c:
        c.execute(sql, a)
        c.commit()


def test_update_batches_allow_exactly_the_transitions_the_update_path_uses(migrated):
    path, *_ = migrated
    batch_row(path, "candidate", "b1")
    upd(path, "update update_batches set state='interrupted' where batch_id='b1'")  # recover_candidates
    batch_row(path, "candidate", "b2")
    upd(path, "update update_batches set state='rejected', qa_json='{\"success\": false}' where batch_id='b2'")  # QA failure
    batch_row(path, "candidate", "b3")
    upd(path, "update update_batches set state='approved', after_json='{\"x\":1}', qa_json='{\"success\": true}' where batch_id='b3'")  # finalize
    upd(path, "update update_batches set state='rolled_back' where batch_id='b3'")  # rollback_batch
    assert [r[0] for r in fetch(path, "select state from update_batches order by batch_id")] == ["interrupted", "rejected", "rolled_back"]


@pytest.mark.parametrize("sql", [
    "update update_batches set state='candidate' where batch_id='b3'",  # approved -> candidate
    "update update_batches set state='approved' where batch_id='b2'",  # rejected -> approved: the QA verdict cannot be reversed
    "update update_batches set state='approved' where batch_id='b1'",  # interrupted -> approved
    "update update_batches set before_json='{\"tampered\":1}' where batch_id='b4'",
    "update update_batches set batch_id='other' where batch_id='b4'",
    "update update_batches set input_sha='" + "0" * 64 + "' where batch_id='b4'",
    "update update_batches set qa_json='{\"success\": true}' where batch_id='b4'",  # a QA result written without a decision
    "update update_batches set after_json='{\"x\":2}' where batch_id='b3'",  # an approved batch's after state is fixed
    "delete from update_batches where batch_id='b3'",
])
def test_every_other_change_of_an_update_batch_is_refused(migrated, sql):
    path, *_ = migrated
    batch_row(path, "interrupted", "b1"); batch_row(path, "rejected", "b2"); batch_row(path, "approved", "b3"); batch_row(path, "candidate", "b4")
    with pytest.raises(sqlite3.DatabaseError):
        upd(path, sql)


def revision(path, rid, logical, root, bid="bx", state="approved"):
    f = fetch(path, "select case_id,fact_key,source_sha256 from facts where evidence_id=?", root)[0]
    with closing(S.app_connect(path)) as c:
        c.execute("insert into evidence_revisions values(?,?,?,?,?,?,?)", (rid, logical, f[0], f[1], f[2], root, "{}"))
        if not fetch(path, "select 1 from update_batches where batch_id=?", bid):
            c.execute("insert into update_batches values(?,?,?,?,?,?,?,?)", (bid, "i" * 64, state, "t", "{}", "{}", "r" * 64, "{}"))
        c.execute("insert into batch_evidence values(?,?)", (bid, rid))
        c.commit()


def test_a_head_must_be_a_revision_of_its_own_logical_id_that_belongs_to_a_batch(migrated):
    path, *_ = migrated
    root = fetch(path, "select evidence_id from facts")[0][0]
    revision(path, "EV-R1", "logical-a", root)
    with closing(S.app_connect(path)) as c:
        c.execute("insert into evidence_heads values('logical-a','EV-R1')")  # right
        c.commit()
    for logical, eid in (("logical-b", "EV-R1"), ("logical-a", "EV-NOT-A-REVISION")):
        with pytest.raises(sqlite3.DatabaseError, match="head must be"):
            upd(path, "insert into evidence_heads values(?,?)", logical, eid)
    with closing(S.app_connect(path)) as c:  # a revision that no batch ever carried
        c.execute("insert into evidence_revisions values('EV-ORPHAN','logical-a',?,?,?,?,'{}')", fetch(path, "select case_id,fact_key,source_sha256,evidence_id from facts")[0])
        c.commit()
    with pytest.raises(sqlite3.DatabaseError, match="head must be"):
        upd(path, "update evidence_heads set evidence_id='EV-ORPHAN' where logical_id='logical-a'")
    with closing(S.app_connect(path)) as c:
        c.execute("delete from evidence_heads")  # a rollback may delete heads: class B
        c.commit()


def test_the_heads_of_the_normal_path_and_their_rollback_still_work(migrated):
    path, p, store, tmp = migrated
    batch, revised, qa, ok = S.approve(store, S.notice(p), S.base_article(store))
    assert ok and S.heads(path)["evidence"] == {"notice": "EV-U-1"}
    store2 = RevisionStore(path, tmp / "backup-after.sqlite")
    store2.rollback_batch(batch["batch_id"])
    assert S.heads(path) == {"evidence": {}, "articles": {}}
    assert fetch(path, "select state from update_batches where batch_id=?", batch["batch_id"]) == [("rolled_back",)]


# ------------------------------------------------------------------ the legitimate update path after the migration
def test_candidate_finalize_qa_rejection_recovery_and_rollback_all_work_on_a_migrated_database(migrated):
    path, p, store, tmp = migrated
    # QA rejection
    batch = store.stage([S.notice(p, eid="EV-U-R")], S.REGISTRY)
    assert store.finalize(batch, [], {"success": False}, S.REGISTRY) is False
    assert fetch(path, "select state from update_batches where batch_id=?", batch["batch_id"]) == [("rejected",)] and S.heads(path) == {"evidence": {}, "articles": {}}
    # an approved update (the normal path) and a recovered candidate
    b2, revised, qa, ok = S.approve(store, S.notice(p), S.base_article(store))
    assert ok
    b3 = store.stage([S.notice(p, eid="EV-U-2", logical="notice-two", sentences=["別の文。"], value={"allowed": "別"})], S.REGISTRY)
    again = RevisionStore(path, tmp / "backup-recover.sqlite")
    with ProcessLock(tmp / "x.lock"):
        assert again.recover_candidates() == [b3["batch_id"]]
    assert S.heads(path)["evidence"] == {"notice": "EV-U-1"}
    audit = S.audit(path)
    assert audit["ok"] and audit["invariants"]["DB-09"]["status"] in ("pass", "not_run")


def test_a_failure_in_the_middle_of_the_approval_still_rolls_everything_back_under_the_triggers(migrated):
    path, p, store, tmp = migrated
    batch = store.stage([S.notice(p)], S.REGISTRY)
    good = revise_article(S.base_article(store), store.effective_records(batch), date(2026, 11, 1))
    bad = dict(good, article_id="broken", base_article_id="no-such-base")
    with pytest.raises(ValueError):
        store.finalize(batch, [good, bad], qa_for(batch, [good, bad]), S.REGISTRY)
    assert S.heads(path) == {"evidence": {}, "articles": {}} and S.counts(path)["revised_articles"] == 0
    assert fetch(path, "select state from update_batches where batch_id=?", batch["batch_id"]) == [("candidate",)]


def test_the_alias_work_and_the_triggers_coexist_and_a_second_migration_run_changes_nothing(migrated):
    path, p, store, tmp = migrated
    root = fetch(path, "select evidence_id from facts")[0][0]
    f = fetch(path, "select case_id,fact_key from facts where evidence_id=?", root)[0]
    with closing(S.app_connect(path)) as c:
        c.execute("insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,kind,reason,created_at) values('EV-LEG',?,?,?,'legacy_compat_id','legacy','t')", (root, f[0], f[1]))
        c.commit()
    before = sha(path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"] == [] and sha(path) == before
    for stmt in ("update evidence_aliases set reason='x'", "delete from evidence_aliases"):
        with pytest.raises(sqlite3.DatabaseError):
            upd(path, stmt)


def test_the_triggers_never_rewrite_or_hide_the_past(world):
    path, p, store, tmp = world
    before = {t: fetch(path, f'select * from "{t}"') for t in ("facts", "article_versions", "article_evidence", "update_batches")}
    ad.apply(path, confirm_disposable_copy=True)
    assert {t: fetch(path, f'select * from "{t}"') for t in before} == before  # not a row changed by adding the protection


def test_insert_or_replace_is_refused_on_a_sogh_connection_and_the_residual_limit_is_recorded(migrated):
    """D4: SQLite does not run DELETE triggers for the implicit delete of INSERT OR REPLACE unless recursive_triggers is ON on that connection. A SOGH connection turns it on (the patch of
    stage 1), so the append-only DELETE trigger refuses the replacement; any other connection is refused by the capability gate. The RESIDUAL limit: a connection that has the capability but forgot
    the pragma can still replace a row (nothing but db_audit DB-09 catches that afterwards): it is recorded, not counted as protection."""
    path, *_ = migrated
    f = fetch(path, "select evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification from facts")[0]
    row = (f[0], f[1], f[2], f[3], '{"overwritten": true}', f[5], f[6])
    with closing(S.app_connect(path)) as c:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute("insert or replace into facts values(?,?,?,?,?,?,?)", row)
    with closing(sqlite3.connect(path)) as c:
        with pytest.raises(sqlite3.OperationalError, match="no such function: sogh_write_ok"):
            c.execute("insert or replace into facts values(?,?,?,?,?,?,?)", row)
    assert fetch(path, "select value_json from facts where evidence_id=?", f[0]) == [(f[4],)]
    with closing(sqlite3.connect(path)) as c:  # the residual limit
        c.create_function("sogh_write_ok", 0, lambda: 1)
        c.execute("insert or replace into facts values(?,?,?,?,?,?,?)", row)
        c.commit()
    assert fetch(path, "select value_json from facts where evidence_id=?", f[0]) == [('{"overwritten": true}',)]
