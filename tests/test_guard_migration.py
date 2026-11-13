"""Migration 0004 (G-09), frozen: the file is exactly what its renderer produces, and the guards hold on every guarded table, for every kind of connection. SELF_VALIDATED; synthetic databases.
What is NOT claimed: protection against someone who rewrites the file or registers the capability function (that is DETECTED by DB-17 / plan, not prevented) and the authenticity of a QA result (G-08)."""
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
from src.db_contract import additive_schema as ad
from src.db_contract import guard_sql as gs

GUARDED_WITH_ROWS = {"facts", "source_documents", "source_pages", "evidence_revisions", "article_versions", "revised_articles", "article_evidence", "batch_evidence", "update_events",
                     "schema_versions", "evidence_heads", "article_heads", "update_batches", "admission_cycles"}


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    assert not ad.apply(path, confirm_disposable_copy=True)["rolled_back"]
    S.approve(store, S.notice(p), S.base_article(store))
    return path, p, store, tmp_path


def raw_outcome(path, sql):
    try:
        with closing(sqlite3.connect(path)) as c:
            c.execute(sql)
            c.commit()
        return "ACCEPTED"
    except sqlite3.DatabaseError as e:
        return str(e)


def app_outcome(path, sql):
    try:
        with closing(S.app_connect(path)) as c:
            c.execute(sql)
            c.commit()
        return "ACCEPTED"
    except sqlite3.DatabaseError as e:
        return str(e)


def test_the_frozen_file_is_exactly_what_the_renderer_produces_and_every_statement_parses():
    text = (ad.MIGRATION_DIR / "0004_g09_append_only_and_head_integrity.sql").read_bytes().decode("utf-8")
    assert text == gs.render() and ad._TEXT_0004 == text
    parsed = ad.parse_frozen(text)
    assert len(parsed) == len(gs.statements()) == 62 and all(st.startswith("CREATE TRIGGER trg_") for st, _ in parsed)
    assert len({st.split()[2] for st, _ in parsed}) == len(parsed)  # no trigger name twice


def test_every_guarded_table_with_rows_refuses_every_write_of_a_connection_that_has_no_capability(world):
    path, *_ = world
    covered = set()
    with closing(sqlite3.connect(path)) as c:
        tables = [r[0] for r in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        rows = {t: c.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables}
    gated = (set(gs.APPEND_ONLY) - set(gs.UNGATED)) | set(gs.OWN_APPEND_ONLY_LINK_TABLES) | {"evidence_heads", "article_heads", "update_batches"} | set(gs.IDENTITY_TABLES)
    for t in sorted(gated):
        if t not in tables or not rows[t]:
            continue
        out = raw_outcome(path, f'insert or ignore into "{t}" select * from "{t}"')  # BEFORE INSERT fires for every row, ignored or not
        assert "no such function: sogh_write_ok" in out, (t, out)
        covered.add(t)
    assert covered >= GUARDED_WITH_ROWS - {"admission_offerings"}, GUARDED_WITH_ROWS - covered
    assert S.counts(path) == S.counts(path)  # reading stays possible for any connection (db_audit, exports)
    assert S.audit(path)["invariants"]["DB-17"]["status"] == "pass"


def test_even_a_connection_with_the_capability_cannot_update_or_delete_a_row_of_an_append_only_table(world):
    path, *_ = world
    with closing(sqlite3.connect(path)) as c:
        tables = [t for t in gs.APPEND_ONLY if c.execute("select 1 from sqlite_master where type='table' and name=?", (t,)).fetchone() and c.execute(f'select count(*) from "{t}"').fetchone()[0]]
    assert {"facts", "evidence_revisions", "article_versions", "revised_articles", "update_events", "batch_evidence", "schema_migrations"} <= set(tables)
    for t in tables:
        col = sqlite3.connect(path).execute(f'pragma table_info("{t}")').fetchall()[0][1]
        assert "append-only" in app_outcome(path, f'update "{t}" set "{col}"="{col}"'), t
        assert "append-only" in app_outcome(path, f'delete from "{t}"'), t
        assert "append-only" in raw_outcome(path, f'delete from "{t}"'), t  # the append-only triggers do not depend on the gate: no connection can delete


def test_the_head_rule_needs_an_approved_batch_for_insert_and_update_for_evidence_and_articles(world):
    path, p, store, tmp = world
    cand = store.stage([S.notice(p, eid="EV-U-C2", logical="other")], S.REGISTRY)
    assert "approved batch" in app_outcome(path, "insert into evidence_heads values('other','EV-U-C2')")
    assert "approved batch" in app_outcome(path, "update evidence_heads set evidence_id='EV-U-C2' where logical_id='notice'")
    assert "approved batch" in app_outcome(path, "insert into article_heads select base_article_id, 'no-such-article' from article_heads")
    assert S.heads(path)["evidence"] == {"notice": "EV-U-1"} and cand["state"] == "candidate"
    # deleting heads stays possible for a SOGH connection (rollback) and is refused for any other program
    assert app_outcome(path, "delete from article_heads where 0") == "ACCEPTED"
    assert "no such function" in raw_outcome(path, "delete from evidence_heads")


def test_a_database_whose_head_already_points_at_an_unapproved_batch_stops_the_migration_and_stays_as_it_was(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    cand = store.stage([S.notice(p, eid="EV-U-C3")], S.REGISTRY)
    with closing(sqlite3.connect(path)) as c:  # an unguarded database: the draft allowed a head for a candidate
        c.execute("insert into evidence_heads values('notice','EV-U-C3')")
        c.commit()
    before = path.read_bytes()
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["rolled_back"] and "0004-g09-append-only-and-head-integrity" in r["blocked"] and "APPROVED" in " ".join(r["blocked"]["0004-g09-append-only-and-head-integrity"])
    assert path.read_bytes() == before and cand["state"] == "candidate"


def test_a_dropped_gate_is_detected_but_not_prevented_which_is_the_stated_limit(world):
    path, *_ = world
    assert ad.plan(path)["drift"] == []
    with closing(sqlite3.connect(path)) as c:  # someone who can change the schema removes one gate trigger
        c.execute("drop trigger trg_gate_facts_insert")
        c.commit()
    assert any("'trg_gate_facts_insert'" in d and "missing" in d for d in ad.plan(path)["drift"])  # detected (plan, apply refuses, DB-17 fails)
    assert S.audit(path)["invariants"]["DB-17"]["status"] == "fail"
    with pytest.raises(ad.MigrationError):
        ad.apply(path, confirm_disposable_copy=True)


def test_the_runner_and_the_alias_writer_are_the_only_other_holders_of_the_capability_and_a_rerun_changes_nothing(world):
    path, *_ = world
    again = ad.apply(path, confirm_disposable_copy=True)
    assert again["applied"] == [] and not again["rolled_back"]
    with closing(sqlite3.connect(path)) as c:  # a bare connection cannot register an alias by SQL, ad.register_alias is the sanctioned writer
        out = c.execute("select count(*) from evidence_aliases").fetchone()[0]
        with pytest.raises(sqlite3.OperationalError, match="no such function"):
            c.execute("insert or ignore into evidence_aliases select * from evidence_aliases union select 'a','x','c','k',null,'legacy_compat_id','r','t'")
        assert out == 0
