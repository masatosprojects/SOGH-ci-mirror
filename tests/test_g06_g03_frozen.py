"""G-06 (source metadata and verification events) and G-03 (lookup indexes) as the frozen migrations 0007 and 0008. SELF_VALIDATED; synthetic databases. What is NOT claimed: that any real source
document was verified (the real copy has no verification event), a performance figure at national scale (NOT_RUN), or the registration of the three unregistered sources of the audited copy."""
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
from src.db_contract import additive_schema as ad


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "backup.sqlite")
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"] and "0008-g03-lookup-indexes" in r["applied"], r
    sha = sqlite3.connect(path).execute("select sha256 from source_documents").fetchone()[0]
    return path, sha, tmp_path


def q(path, sql, *a):
    with closing(sqlite3.connect(path)) as c:
        return c.execute(sql, a).fetchall()


def app(path):
    return S.app_connect(path)


# ------------------------------------------------------------------------------------------------------ G-06 metadata
def test_an_unknown_publication_date_stays_unknown_and_is_never_guessed(world):
    path, sha, tmp = world
    with closing(app(path)) as c:
        n = ad.record_source_metadata(c, sha, source_kind="admission_guide", title="架空の募集要項", basis="保存した PDF の表紙に日付がない", recorded_by="claude-temporary")
        c.commit()
    assert n == 1 and q(path, "select published_at, published_at_certainty from v_source_document_current") == [(None, "unknown")]
    for bad in ({"published_at": "2026-04-01", "published_at_certainty": "unknown"}, {"published_at": None, "published_at_certainty": "exact"}):
        with closing(app(path)) as c, pytest.raises(sqlite3.IntegrityError):  # a date with certainty "unknown", or a certainty without a date
            ad.record_source_metadata(c, sha, source_kind="faq", title="x", basis="b", recorded_by="a", **bad)


def test_a_new_version_is_a_new_row_the_latest_is_a_view_and_the_earlier_ones_stay(world):
    path, sha, tmp = world
    with closing(app(path)) as c:
        ad.record_source_metadata(c, sha, source_kind="admission_guide", title="架空の募集要項", basis="表紙に日付なし", recorded_by="a")
        n2 = ad.record_source_metadata(c, sha, source_kind="admission_guide", title="架空の募集要項（確認後）", basis="大学の公開ページの更新日", recorded_by="a", published_at="2026-07", published_at_certainty="month", applies_to_fiscal_year=2027)
        c.commit()
    assert n2 == 2 and q(path, "select meta_version, published_at, applies_to_fiscal_year from v_source_document_current") == [(2, "2026-07", 2027)]
    assert q(path, "select count(*) from source_document_metadata")[0][0] == 2  # version 1 is still there
    for stmt in ("update source_document_metadata set title='x'", "delete from source_document_metadata"):
        with closing(app(path)) as c, pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute(stmt)
    with closing(app(path)) as c, pytest.raises(sqlite3.DatabaseError, match="numbered one after another"):
        c.execute("insert into source_document_metadata values(?,?,?,?,?,?,?,?,?,?)", (sha, 9, None, "unknown", "other", "t", "n", "b", "a", "t"))


def test_metadata_needs_a_stored_source_a_known_kind_and_a_basis_and_a_bare_connection_is_refused(world):
    path, sha, tmp = world
    with closing(app(path)) as c:
        with pytest.raises(sqlite3.DatabaseError, match="not stored"):
            ad.record_source_metadata(c, "f" * 64, source_kind="faq", title="t", basis="b", recorded_by="a")  # works even with foreign keys off
        with pytest.raises(ValueError, match="unknown source kind"):
            ad.record_source_metadata(c, sha, source_kind="rumour", title="t", basis="b", recorded_by="a")
        with pytest.raises(sqlite3.IntegrityError):
            ad.record_source_metadata(c, sha, source_kind="faq", title="t", basis="  ", recorded_by="a")
    with closing(sqlite3.connect(path)) as c, pytest.raises(sqlite3.OperationalError, match="no such function: sogh_write_ok"):
        c.execute("insert into source_document_metadata values(?,?,?,?,?,?,?,?,?,?)", (sha, 1, None, "unknown", "other", "t", None, "b", "a", "t"))


# ------------------------------------------------------------------------------------------------------ G-06 verification
def test_a_stored_copy_is_never_called_verified_without_the_check_that_would_make_it_so(world):
    path, sha, tmp = world
    assert q(path, "select * from v_source_verification_status") == [(sha, "not_run", "not_run", "not_run", "not_run")]  # nothing was checked: every level says so
    with closing(app(path)) as c:
        ad.record_verification(c, sha, level="bytes_match_recorded_sha", outcome="pass", evidence="保存ファイルの SHA-256 が記録と一致", performed_by="claude-temporary")
        ad.record_verification(c, sha, level="stored_file_matches_record", outcome="pass", evidence="ページ数と抽出文が記録と一致", performed_by="claude-temporary")
        c.commit()
    status = q(path, "select bytes_match_recorded_sha, stored_file_matches_record, official_site_authenticity, content_meaning_checked from v_source_verification_status")[0]
    assert status == ("pass", "pass", "not_run", "not_run")  # bytes and record agree; authenticity at the official site and the meaning were NOT checked


def test_each_level_has_its_own_latest_outcome_and_a_later_failure_is_not_hidden(world):
    path, sha, tmp = world
    with closing(app(path)) as c:
        ad.record_verification(c, sha, level="official_site_authenticity", outcome="pass", evidence="大学の公開ページの同じ版と照合した（架空）", performed_by="a")
        ad.record_verification(c, sha, level="official_site_authenticity", outcome="fail", evidence="後日、公開ページの版が変わっていた（架空）", performed_by="a")
        ad.record_verification(c, sha, level="content_meaning_checked", outcome="not_run", evidence="QA はまだ", performed_by="a")
        c.commit()
    assert q(path, "select official_site_authenticity, content_meaning_checked from v_source_verification_status") == [("fail", "not_run")]
    assert q(path, "select count(*) from source_verification_events")[0][0] == 3  # the earlier pass is still on record
    with closing(app(path)) as c:
        with pytest.raises(sqlite3.IntegrityError):
            ad.record_verification(c, sha, level="official_site_authenticity", outcome="pass", evidence=" ", performed_by="a")  # a check without its evidence is not recorded
        with pytest.raises(ValueError, match="unknown verification level"):
            ad.record_verification(c, sha, level="looks_fine", outcome="pass", evidence="e", performed_by="a")
        with pytest.raises(sqlite3.IntegrityError):
            ad.record_verification(c, sha, level="content_meaning_checked", outcome="verified", evidence="e", performed_by="a")
        with pytest.raises(sqlite3.DatabaseError, match="not stored"):
            ad.record_verification(c, "e" * 64, level="content_meaning_checked", outcome="pass", evidence="e", performed_by="a")
    for stmt in ("update source_verification_events set outcome='pass'", "delete from source_verification_events"):
        with closing(app(path)) as c, pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute(stmt)


def test_the_source_documents_themselves_are_untouched_by_the_metadata_work(world):
    path, sha, tmp = world
    before = q(path, "select * from source_documents")
    with closing(app(path)) as c:
        ad.record_source_metadata(c, sha, source_kind="notice", title="t", basis="b", recorded_by="a")
        ad.record_verification(c, sha, level="bytes_match_recorded_sha", outcome="pass", evidence="e", performed_by="a")
        c.commit()
    assert q(path, "select * from source_documents") == before and S.audit(path)["invariants"]["DB-17"]["status"] == "pass"


# ------------------------------------------------------------------------------------------------------ G-03 indexes
INDEXED = {"evidence_revisions": ("parent_evidence_id", "logical_id"), "article_evidence": ("evidence_id",), "facts": ("source_sha256",), "update_events": ("batch_id",), "batch_evidence": ("evidence_id",), "revised_article_evidence": ("evidence_id",)}


def test_the_seven_lookups_each_use_an_index_the_planner_is_asked_about_every_one(world):
    path, sha, tmp = world
    with closing(sqlite3.connect(path)) as c:
        for table, cols in INDEXED.items():
            for col in cols:
                plan = " ".join(r[3] for r in c.execute(f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE {col} = ?", ("x",)))
                assert "USING INDEX" in plan or "USING COVERING INDEX" in plan, (table, col, plan)
                assert "SCAN" not in plan, (table, col, plan)
        names = {r[0] for r in c.execute("select name from sqlite_master where type='index' and name like 'ix_%'")}
    assert len(names) == 7  # nothing else was indexed


def test_an_existing_index_of_the_same_name_stops_the_run_and_the_file_stays_as_it_was(tmp_path):
    path, p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "backup.sqlite")
    with closing(sqlite3.connect(path)) as c:
        c.execute("create index ix_facts_source on facts(case_id)")
        c.commit()
    before = path.read_bytes()
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["rolled_back"] and "0008-g03-lookup-indexes" in r["blocked"] and path.read_bytes() == before


def test_the_whole_chain_is_clean_idempotent_and_verified_by_the_audit(world):
    path, sha, tmp = world
    assert ad.plan(path)["drift"] == [] and ad.apply(path, confirm_disposable_copy=True)["applied"] == []
    assert S.audit(path)["invariants"]["DB-17"]["status"] == "pass" and q(path, "pragma user_version") == [(ad._seq(ad.MIGRATIONS[-1][0]),)]
