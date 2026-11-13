"""Behaviour of the third g2 patch (patches/g2-faq/work-store-0012-wiring.patch): EvidenceStore.record_unconfirmed_faq_evidence files the evidence of an official FAQ whose applicability is UNKNOWN
into the append-only table of migration 0012 (STR-100 H2=A). SELF_TEST (author Claude); synthetic FAQ page and DISPOSABLE databases only.

NOT collected by a normal run (the name does not match test_*.py): tests/test_g2_store_0012_patch.py runs it in a subprocess with SOGH_PIPELINE_ROOT pointing at a COPY of Work's pipeline that carries
the stage-1, the g2, the g2-unconfirmed and this patch (Work's directories are never written). tests.db_support then imports that copy.
"""
import hashlib
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S
from tests.behaviour_g2_faq import CASE, CYCLE, Q1, Q2, page, spec_for
from admissions_pipeline.extract import normalize
from admissions_pipeline.faq_policy import extract_conditions, structured_record
from admissions_pipeline.revisions import RevisionStore
from admissions_pipeline.store import EvidenceStore, configure_connection
from src.db_contract import additive_schema as ad

TABLE = "faq_unconfirmed_evidence"
WHEN = "2026-11-12T00:00:00Z"


def build(tmp_path, upto=None):
    path, _p = S.make_native(tmp_path, "n.sqlite")
    RevisionStore(path, tmp_path / "n.backup")
    only = None if upto is None else tuple(m[0] for m in ad.MIGRATIONS if int(m[0].split("-", 1)[0]) < upto)
    r = ad.apply(path, confirm_disposable_copy=True, **({"only": only} if only else {}))
    assert not r["rolled_back"]
    return path


@pytest.fixture
def faq(tmp_path):
    html = tmp_path / "faq.html"
    html.write_text(page(), encoding="utf-8")
    sha = hashlib.sha256(html.read_bytes()).hexdigest()
    record = {"kind": "html", "url": "https://fixture.ac.jp/faq", "local_path": str(html), "sha256": sha, "retrieved_at": "2026-11-01T05:31:11Z"}
    rec = structured_record(extract_conditions(record, spec_for(sha, unknown=True), None), None, "fixture-g2")
    return rec, sha


def with_source(path, sha):
    with closing(S.app_connect(path)) as c:
        c.execute("INSERT OR IGNORE INTO source_documents VALUES (?,?,?,?,?)", (sha, "https://fixture.ac.jp/faq", "faq.html", "2026-11-01", "not_cleared_for_publication"))
        c.commit()


def rows(path):
    with closing(sqlite3.connect(path)) as c:
        return c.execute(f"SELECT * FROM {TABLE} ORDER BY evidence_id").fetchall()


def test_it_files_one_row_per_proof_as_unknown_and_never_touches_facts(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    store = EvidenceStore(path)
    before = store.counts()
    ids = store.record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    assert ids == [rec["evidence_id"] + ":p" + str(n) for n in range(len(rec["proofs"]))] and len(ids) == 6
    got = rows(path)
    assert [r[0] for r in got] == sorted(ids) and {r[1] for r in got} == {"case"} and {r[2] for r in got} == {sha} and {r[8] for r in got} == {"unknown"}
    assert {r[3] for r in got} == {hashlib.sha256(normalize(q).encode("utf-8")).hexdigest() for q in (Q1, Q2)}  # the question each quote answers
    assert {(r[4], r[5], r[6], r[7]) for r in got} == {(p["quote"], p["normalized_start"], p["normalized_end"], p["page"]) for p in rec["proofs"]}
    assert store.counts() == before  # facts, cycles, documents, articles: not one row changed
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("SELECT count(*) FROM facts WHERE evidence_id LIKE ?", (rec["evidence_id"] + "%",)).fetchone()[0] == 0
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({TABLE})")]
    assert not {"fiscal_year", "faculty", "department", "admission_method"} & set(cols)  # the row cannot state an applicability


def test_the_filed_rows_are_append_only(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    EvidenceStore(path).record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    for statement in (f"UPDATE {TABLE} SET quote='x'", f"DELETE FROM {TABLE}", f"UPDATE {TABLE} SET scope_status='verified'"):
        with closing(S.app_connect(path)) as c, pytest.raises(sqlite3.DatabaseError):
            c.execute(statement)
    assert len(rows(path)) == 6


def test_running_twice_is_a_clean_refusal_and_writes_nothing(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    store = EvidenceStore(path)
    store.record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    first = rows(path)
    with pytest.raises(ValueError, match="duplicate"):
        store.record_unconfirmed_faq_evidence(rec, "case", "claude", "2026-11-13T00:00:00Z")
    assert rows(path) == first  # nothing replaced, nothing added


def test_a_partly_filed_record_is_refused_whole(tmp_path, faq):
    """One proof id already filed: the others are not written either (one transaction)."""
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    with closing(S.app_connect(path)) as c:
        c.execute(f"INSERT INTO {TABLE}(evidence_id,storage_case_id,source_sha256,question_sha256,quote,normalized_start,normalized_end,page,recorded_by,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (rec["evidence_id"] + ":p3", "case", sha, "a" * 64, "q", 1, 2, 1, "claude", WHEN))
        c.commit()
    with pytest.raises(ValueError, match="duplicate"):
        EvidenceStore(path).record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    assert len(rows(path)) == 1


@pytest.mark.parametrize("claim", [dict(fiscal_year=2027), dict(case_id=CASE), dict(faculty="知識情報・図書館学類"), dict(department="知識情報・図書館学類"),
                                   dict(exam_year=2026), dict(scope_status="verified"), dict(scope_status=None)])
def test_a_record_that_claims_a_year_faculty_or_verification_is_refused(tmp_path, faq, claim):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    store = EvidenceStore(path)
    bad = dict(rec, **claim)
    with pytest.raises(ValueError):
        store.record_unconfirmed_faq_evidence(bad, "case", "claude", WHEN)
    assert rows(path) == []


def test_a_method_or_university_named_by_the_record_is_never_stored(tmp_path, faq):
    """The delivered unknown record names the university and the method (they come from the spec); the module's rules allow that and the table has no column for them: they are NOT stored, scope stays unknown."""
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    EvidenceStore(path).record_unconfirmed_faq_evidence(dict(rec, admission_method="別方式", university="別大学"), "case", "claude", WHEN)
    flat = repr(rows(path))
    assert "別方式" not in flat and "別大学" not in flat and "アドミッションセンター入試" not in flat and {r[8] for r in rows(path)} == {"unknown"}


def test_a_case_bound_record_is_refused(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    bound = structured_record(extract_conditions(*_bound_inputs(tmp_path)), None, "fixture-g2")
    with pytest.raises(ValueError, match="unconfirmed-scope"):
        EvidenceStore(path).record_unconfirmed_faq_evidence(bound, "case", "claude", WHEN)
    assert rows(path) == []


def _bound_inputs(tmp_path):
    import copy
    html = tmp_path / "faq.html"
    sha = hashlib.sha256(html.read_bytes()).hexdigest()
    record = {"kind": "html", "url": "https://fixture.ac.jp/faq", "local_path": str(html), "sha256": sha, "retrieved_at": "2026-11-01T05:31:11Z"}
    return record, spec_for(sha, unknown=False), copy.deepcopy(CYCLE)


@pytest.mark.parametrize("what", ["case", "source", "by", "proof"])
def test_bad_storage_reference_source_actor_or_proof_is_refused(tmp_path, faq, what):
    rec, sha = faq
    path = build(tmp_path)
    if what != "source":
        with_source(path, sha)
    args = ["case", "claude"]
    if what == "case":
        args[0] = "no-such-cycle"
    if what == "by":
        args[1] = " "
    if what == "proof":
        rec = dict(rec, proofs=[dict(rec["proofs"][0], normalized_end=0)])
    with pytest.raises(ValueError):
        EvidenceStore(path).record_unconfirmed_faq_evidence(rec, *args, WHEN)
    assert rows(path) == []


def test_a_missing_table_is_a_clear_error_and_nothing_is_created(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path, upto=12)  # migrations 0002..0011 only
    with_source(path, sha)
    with pytest.raises(RuntimeError, match="migration 0012"):
        EvidenceStore(path).record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()[0] == 0


def test_a_connection_without_the_registered_functions_fails_closed(tmp_path, faq, monkeypatch):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    store = EvidenceStore(path)
    import admissions_pipeline.store as st
    monkeypatch.setattr(st, "configure_connection", lambda db: db)  # a store whose connections do not register sogh_write_ok
    with pytest.raises(RuntimeError, match="write capability"):
        store.record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    assert rows(path) == []


def test_a_table_without_its_guards_is_refused(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    with closing(S.app_connect(path)) as c:
        c.execute(f"DROP TRIGGER trg_{TABLE}_no_update")
        c.commit()
    with pytest.raises(RuntimeError, match="guards"):
        EvidenceStore(path).record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    assert rows(path) == []


def test_the_default_time_is_stamped_when_none_is_given(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    EvidenceStore(path).record_unconfirmed_faq_evidence(rec, "case", "claude")
    assert all(r[10] and r[10].startswith("20") for r in rows(path))


def test_the_database_still_passes_its_own_verification_after_filing(tmp_path, faq):
    rec, sha = faq
    path = build(tmp_path)
    with_source(path, sha)
    EvidenceStore(path).record_unconfirmed_faq_evidence(rec, "case", "claude", WHEN)
    with closing(sqlite3.connect(path)) as c:
        assert ad.verify_history(c) == [] and ad.verify_schema_state(c) == []
    assert S.failing(path) == {} or not S.failing(path)
