"""G-02 / G-04 / G-05 additive schema proposals (SELF_VALIDATED: Claude wrote them and these tests; WORK_CONTRACT_REVIEW_PENDING). Synthetic databases only."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import tests.db_support as dbs
from src.db_contract import additive_schema as ad

NOW = "2026-11-01T00:00:00+00:00"


OFFERINGS = """CREATE TABLE IF NOT EXISTS admission_offerings(
 offering_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
 round_name TEXT NOT NULL,entry_month INTEGER CHECK(entry_month BETWEEN 1 AND 12),
 scope_json TEXT NOT NULL,source_sha256 TEXT NOT NULL)"""


def build(tmp: Path, offerings: bool = True) -> Path:
    path, _ = dbs.make_native(tmp)
    dbs.RevisionStore(path, tmp / "backup.sqlite")  # adds the v0.5 revision tables
    if offerings:  # the real v0.5+ copies have this table; the synthetic store of the older pipeline does not
        with closing(dbs.app_connect(path)) as c:
            c.execute(OFFERINGS)
            c.commit()
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, skip=("schema_migrations", "alias_provenance_bundles", "source_representations", "faq_unconfirmed_evidence", "quarantine_staging_candidates", "_quarantine_approval_seals", "canonical_facts_staging_target", "source_document_series_editions", "series_revision_article_impacts", "restore_events", "restore_revocations", "restored_articles", "evidence_history_versions", "article_history_pins", "evidence_aliases", "offering_sources", "revised_article_evidence", "revision_reasons", "revision_reason_corrections", "revision_reason_contract", "source_document_metadata", "source_verification_events")) -> dict:
    with closing(dbs.app_connect(path)) as c:
        names = [r[0] for r in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1")]
        return {n: sorted(map(repr, c.execute(f'select * from "{n}"').fetchall())) for n in names if n not in skip}


def run(path, sql, *args):
    with closing(dbs.app_connect(path)) as c:
        c.execute("PRAGMA foreign_keys=ON")
        c.execute(sql, args)
        c.commit()


def cycle(path):
    with closing(dbs.app_connect(path)) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute("select * from admission_cycles").fetchone())


def add_cycle(path, case_id, **over):
    row = {**cycle(path), "case_id": case_id, **over}
    run(path, "insert into admission_cycles(case_id,university,faculty,department,admission_method,fiscal_year,exam_year) values(?,?,?,?,?,?,?)",
        row["case_id"], row["university"], row["faculty"], row["department"], row["admission_method"], row["fiscal_year"], row["exam_year"])


# ---------------------------------------------------------------- the runner (G-02) and G-04
def test_plan_reads_only_and_lists_the_pending_migrations(tmp_path):
    path = build(tmp_path)
    before = sha(path)
    p = ad.plan(path)
    assert sha(path) == before and p["can_apply"] and [m["migration"] for m in p["migrations"]] == [m[0] for m in ad.MIGRATIONS]
    assert all(m["would_apply"] for m in p["migrations"])


def test_a_lineage_without_offerings_still_gets_the_cycle_identity(tmp_path):
    path = build(tmp_path, offerings=False)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"] and "0002-g04-cycle-and-offering-identity" in r["applied"]
    with closing(dbs.app_connect(path)) as c:
        names = {x[0] for x in c.execute("select name from sqlite_master where type='index'")}
    assert "ux_cycles_identity" in names and "ux_offerings_identity" not in names


def test_apply_needs_the_statement_that_the_file_is_a_disposable_copy_and_no_sidecar(tmp_path):
    path = build(tmp_path)
    with pytest.raises(PermissionError):
        ad.apply(path)
    (tmp_path / "native.sqlite-journal").write_bytes(b"x")
    with pytest.raises(ValueError):
        ad.apply(path, confirm_disposable_copy=True)


def test_apply_adds_objects_and_changes_no_existing_row(tmp_path):
    path = build(tmp_path)
    before = dump(path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"] == [m[0] for m in ad.MIGRATIONS] and not r["rolled_back"]
    assert dump(path) == before  # every old table, row for row
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("select count(*) from schema_migrations").fetchone()[0] == len(ad.MIGRATIONS) and c.execute("pragma user_version").fetchone()[0] == ad._seq(ad.MIGRATIONS[-1][0])
        assert c.execute("pragma integrity_check").fetchone()[0] == "ok" and c.execute("pragma foreign_key_check").fetchall() == []


def test_a_missing_and_an_empty_department_are_the_same_unspecified_department(tmp_path):
    path = build(tmp_path)
    ad.apply(path, confirm_disposable_copy=True)
    assert cycle(path)["department"] is None
    with pytest.raises(sqlite3.IntegrityError):
        add_cycle(path, "dup-null", department=None)
    with pytest.raises(sqlite3.IntegrityError):
        add_cycle(path, "dup-empty", department="")


def test_what_is_different_is_never_merged(tmp_path):
    path = build(tmp_path)
    ad.apply(path, confirm_disposable_copy=True)
    add_cycle(path, "other-department", department="情報学科")
    add_cycle(path, "other-year", fiscal_year=2028, exam_year=2027)
    add_cycle(path, "other-method", admission_method="別の方式")
    add_cycle(path, "other-faculty", faculty="別の学部")
    add_cycle(path, "other-university", university="別の大学")
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("select count(*) from admission_cycles").fetchone()[0] == 6


def test_an_existing_collision_stops_the_whole_run_and_leaves_the_file_as_it_was(tmp_path):
    path = build(tmp_path)
    add_cycle(path, "dup-null", department=None)  # allowed by the old UNIQUE (NULLs are distinct): the very problem G-04 names
    before = sha(path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["rolled_back"] and r["applied"] == [] and "0002-g04-cycle-and-offering-identity" in r["blocked"]
    assert sha(path) == before  # not a byte changed: no index, no schema_migrations table
    assert ad.plan(path)["can_apply"] is False


def offering(path, offering_id, month, scope="{}", source="a" * 64, round_name="round", case_id="case"):
    with closing(dbs.app_connect(path)) as c:
        c.execute("PRAGMA foreign_keys=OFF")
        c.execute("insert into admission_offerings(offering_id,case_id,round_name,entry_month,scope_json,source_sha256) values(?,?,?,?,?,?)", (offering_id, case_id, round_name, month, scope, source))
        c.commit()


def test_offerings_of_one_cycle_stay_apart_by_month_and_a_duplicate_is_refused_whatever_its_source(tmp_path):
    path = build(tmp_path)
    ad.apply(path, confirm_disposable_copy=True)
    offering(path, "o1", 4); offering(path, "o2", 9); offering(path, "o3", None)  # a spring and an autumn entry and an unspecified month: three offerings
    for dup, month, source in (("o5", 4, "a" * 64), ("o6", None, "a" * 64), ("o4", 4, "c" * 64)):  # the same offering announced in another document is the SAME offering (D7)
        with pytest.raises(sqlite3.IntegrityError):
            offering(path, dup, month, source=source)
    assert q1(path, "select count(*) from admission_offerings") == 3


def q1(path, sql, *a):
    with closing(dbs.app_connect(path)) as c:
        return c.execute(sql, a).fetchone()[0]


def test_a_second_document_for_the_same_offering_is_linked_not_duplicated_and_an_ignore_keeps_the_link(tmp_path):
    """Work's save_dimensions uses INSERT OR IGNORE: the revised document's offering row is ignored, and offering_sources keeps that the second document describes it too."""
    path = build(tmp_path)
    ad.apply(path, confirm_disposable_copy=True)
    for sha_ in ("a" * 64, "c" * 64):
        run(path, "insert or ignore into source_documents values(?,?,?,?,?)", sha_, "https://example.ac.jp/" + sha_[:4], "p", "2026-11-01", "not_cleared_for_publication")
    run(path, "insert or ignore into admission_offerings values('o1','case','round',4,'{}',?)", "a" * 64)
    run(path, "insert or ignore into admission_offerings values('o1-revised','case','round',4,'{}',?)", "c" * 64)
    assert q1(path, "select count(*) from admission_offerings") == 1
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("select offering_id, source_sha256 from offering_sources order by source_sha256").fetchall() == [("o1", "a" * 64), ("o1", "c" * 64)]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute("delete from offering_sources")


def test_the_offerings_that_exist_before_the_migration_get_their_source_link_and_no_row_changes(tmp_path):
    path = build(tmp_path)
    run(path, "insert or ignore into source_documents values(?,?,?,?,?)", "a" * 64, "https://example.ac.jp/a", "p", "2026-11-01", "not_cleared_for_publication")
    offering(path, "o1", 4)
    before = dump(path)
    assert not ad.apply(path, confirm_disposable_copy=True)["rolled_back"]
    assert dump(path) == before
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("select offering_id, source_sha256 from offering_sources").fetchall() == [("o1", "a" * 64)]


def test_two_documents_for_one_existing_offering_block_the_migration_and_change_nothing(tmp_path):
    path = build(tmp_path)
    offering(path, "o1", 4); offering(path, "o2", 4, source="c" * 64)  # the draft identity (with the source) let this exist
    before = sha(path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["rolled_back"] and "0002-g04-cycle-and-offering-identity" in r["blocked"] and sha(path) == before


def test_applying_twice_changes_nothing(tmp_path):
    path = build(tmp_path)
    ad.apply(path, confirm_disposable_copy=True)
    before = sha(path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"] == [] and set(r["skipped"]) == {m[0] for m in ad.MIGRATIONS} and sha(path) == before


def test_a_failure_in_the_middle_leaves_nothing_applied(tmp_path, monkeypatch):
    path = build(tmp_path)
    before = sha(path)
    bad = ad.MIGRATIONS + (("0099-broken", "ends in an error", lambda db: ("CREATE TABLE ok_so_far(x)", "CREATE TABLE nonsense("), lambda db: [], "broken"),)
    monkeypatch.setattr(ad, "MIGRATIONS", bad)
    with pytest.raises(sqlite3.OperationalError):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before
    with closing(dbs.app_connect(path)) as c:
        assert not {"schema_migrations", "ok_so_far", "evidence_aliases"} & {r[0] for r in c.execute("select name from sqlite_master")}


# ---------------------------------------------------------------- G-05
def facts(path):
    with closing(dbs.app_connect(path)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("select * from facts order by evidence_id")]


def revise(path, root, head_id="EV-U-head", logical="quota-root"):
    """A corrected version of a native fact: a revision whose parent is the native fact, approved and made the head (inserted directly: synthetic)."""
    f = next(x for x in facts(path) if x["evidence_id"] == root)
    rec = json.loads(f["record_json"])
    rec.update(evidence_id=head_id, logical_id=logical, parent_evidence_id=root)
    with closing(dbs.app_connect(path)) as c:
        c.execute("insert into evidence_revisions values(?,?,?,?,?,?,?)", (head_id, logical, f["case_id"], f["fact_key"], f["source_sha256"], root, dbs.canonical(rec)))
        c.execute("insert into update_batches values(?,?,?,?,?,?,?,?)", ("b-" + head_id, "i" * 64, "approved", NOW, "{}", "{}", "r" * 64, "{}"))  # a head belongs to an update batch
        c.execute("insert into batch_evidence values(?,?)", ("b-" + head_id, head_id))
        c.execute("insert into evidence_heads values(?,?)", (logical, head_id))
        c.commit()
    return rec


def alias_row(path, alias_id, root, kind="legacy_compat_id", reason="legacy id", pinned=None, case=None, key=None):
    f = next(x for x in facts(path) if x["evidence_id"] == root) if any(x["evidence_id"] == root for x in facts(path)) else {"case_id": "case", "fact_key": "quota"}
    run(path, "insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,pinned_evidence_id,kind,reason,created_at) values(?,?,?,?,?,?,?,?)",
        alias_id, root, case or f["case_id"], key or f["fact_key"], pinned, kind, reason, NOW)


@pytest.fixture
def migrated(tmp_path):
    path = build(tmp_path)
    root = facts(path)[0]["evidence_id"]
    ad.apply(path, confirm_disposable_copy=True)
    return path, root


def test_an_alias_resolves_to_the_root_and_a_corrected_root_resolves_to_its_current_head_not_the_old_position(migrated):
    path, root = migrated
    revise(path, root)
    alias_row(path, "EV-LEGACY-1", root)
    with closing(dbs.app_connect(path)) as c:
        r = ad.resolve(c, "EV-LEGACY-1")
        assert r["root"] == root and r["resolved_evidence_id"] == "EV-U-head" and r["kind"] == "alias" and r["cited_version_fixed"] is False
        assert ad.resolve(c, root)["resolved_evidence_id"] == root and ad.resolve(c, "EV-U-head")["kind"] == "evidence"  # real ids resolve to themselves


def test_a_root_that_was_never_revised_resolves_to_itself(migrated):
    path, root = migrated
    alias_row(path, "EV-LEGACY-2", root)
    with closing(dbs.app_connect(path)) as c:
        assert ad.resolve(c, "EV-LEGACY-2")["resolved_evidence_id"] == root


def test_a_pinned_alias_keeps_the_version_it_names(migrated):
    path, root = migrated
    revise(path, root)
    alias_row(path, "EV-LEGACY-3", root, pinned="EV-U-head")
    with closing(dbs.app_connect(path)) as c:
        r = ad.resolve(c, "EV-LEGACY-3")
        assert r["resolved_evidence_id"] == "EV-U-head" and r["cited_version_fixed"] is True


def test_unknown_ids_and_aliases_are_an_error_never_the_current_value(migrated):
    path, _ = migrated
    with closing(dbs.app_connect(path)) as c:
        with pytest.raises(ad.AliasError):
            ad.resolve(c, "EV-NOTHING")


@pytest.mark.parametrize("make", ["unknown_root", "case_mismatch", "fact_key_mismatch", "alias_equals_a_real_id", "alias_of_alias", "pinned_not_a_revision_of_the_root", "empty_reason", "bad_kind", "alias_is_its_own_root"])
def test_the_database_refuses_the_structural_negatives(migrated, make):
    path, root = migrated
    revise(path, root)
    other = "EV-OTHER-ROOT"
    with closing(dbs.app_connect(path)) as c:  # a second fact + revision of another root to pin wrongly
        f = facts(path)[0]
        c.execute("insert into facts(evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification) values(?,?,?,?,?,?,?)",
                  (other, f["case_id"], f["source_sha256"], "other_key", f["value_json"], f["record_json"], f["verification"]))
        c.execute("insert into evidence_revisions values(?,?,?,?,?,?,?)", ("EV-U-other", "other-root", f["case_id"], "other_key", f["source_sha256"], other, "{}"))
        c.commit()
    alias_row(path, "EV-FIRST", root)
    cases = {
        "unknown_root": lambda: alias_row(path, "EV-A1", "EV-NO-SUCH-ROOT", case="case", key="quota"),
        "case_mismatch": lambda: alias_row(path, "EV-A2", root, case="another-case"),
        "fact_key_mismatch": lambda: alias_row(path, "EV-A3", root, key="another_key"),
        "alias_equals_a_real_id": lambda: alias_row(path, root[:-1] + "X" if False else "EV-U-head", root),
        "alias_of_alias": lambda: alias_row(path, "EV-A5", "EV-FIRST"),
        "pinned_not_a_revision_of_the_root": lambda: alias_row(path, "EV-A6", root, pinned="EV-U-other"),
        "empty_reason": lambda: alias_row(path, "EV-A7", root, reason="   "),
        "bad_kind": lambda: alias_row(path, "EV-A8", root, kind="merge"),
        "alias_is_its_own_root": lambda: alias_row(path, root, root),
    }
    with pytest.raises(sqlite3.DatabaseError):
        cases[make]()


def test_aliases_are_append_only_and_a_new_evidence_id_cannot_take_an_alias_name(migrated):
    path, root = migrated
    alias_row(path, "EV-LEGACY-4", root)
    for stmt in ("update evidence_aliases set reason='x' where alias_id='EV-LEGACY-4'", "delete from evidence_aliases where alias_id='EV-LEGACY-4'"):
        with pytest.raises(sqlite3.DatabaseError):
            run(path, stmt)
    f = facts(path)[0]
    with pytest.raises(sqlite3.DatabaseError):
        run(path, "insert into facts(evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification) values(?,?,?,?,?,?,?)", "EV-LEGACY-4", f["case_id"], "z" * 64, "q", "{}", "{}", f["verification"])
    with pytest.raises(sqlite3.DatabaseError):
        run(path, "insert into evidence_revisions values(?,?,?,?,?,?,?)", "EV-LEGACY-4", "l", f["case_id"], f["fact_key"], f["source_sha256"], root, "{}")


def test_registering_an_alias_needs_the_same_fact_and_refuses_independent_conflicting_or_foreign_facts(migrated):
    path, root = migrated
    f = facts(path)[0]
    rec = json.loads(f["record_json"])
    moved = json.loads(json.dumps(rec)); moved["evidence_id"] = "EV-G-LEGACY"; moved["proofs"] = [{"page": 9, "quote": "別の位置にある同じ文"}]
    with closing(dbs.app_connect(path)) as c:
        ad.register_alias(c, "EV-G-LEGACY", root, "locator_corrected_copy", "same fact, locator corrected", alias_record=moved)  # same value, other locator: a moved locator
        c.commit()
        independent = json.loads(json.dumps(rec)); independent["value"] = {"different": 1}; independent["proofs"] = [{"page": 2, "quote": "全く別の文"}]
        conflict = json.loads(json.dumps(rec)); conflict["value"] = {"different": 2}
        other_cycle = json.loads(json.dumps(rec)); other_cycle["faculty"] = "別の学部"
        other_source = json.loads(json.dumps(rec)); other_source["source_sha256"] = "9" * 64; other_source.pop("source_pdf_sha256", None)
        other_key = json.loads(json.dumps(rec)); other_key["fact_key"] = "online_period"
        other_year = json.loads(json.dumps(rec)); other_year["fiscal_year"] = 2028
        for name, bad in (("independent", independent), ("conflict", conflict), ("other_cycle", other_cycle), ("other_source", other_source), ("other_key", other_key), ("other_year", other_year)):
            with pytest.raises(ad.AliasError):
                ad.register_alias(c, "EV-X-" + name, root, "legacy_compat_id", "x", alias_record=bad)
        with pytest.raises(ad.AliasError):
            ad.register_alias(c, "EV-X-unknown", "EV-NO-ROOT", "legacy_compat_id", "x", alias_record=rec)
        assert c.execute("select count(*) from evidence_aliases").fetchone()[0] == 1


def test_the_same_value_in_another_cycle_is_an_independent_fact_the_database_will_not_alias(migrated):
    path, root = migrated
    f = facts(path)[0]
    add_cycle(path, "case-two", faculty="別の学部")
    with closing(dbs.app_connect(path)) as c:
        c.execute("insert into facts(evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification) values(?,?,?,?,?,?,?)",
                  ("EV-TWO-1", "case-two", f["source_sha256"], f["fact_key"], f["value_json"], f["record_json"], f["verification"]))
        c.commit()
    with pytest.raises(sqlite3.DatabaseError):  # claiming the second cycle's id as an alias of the first cycle's root: the case differs
        alias_row(path, "EV-TWO-ALIAS", root, case="case-two")


def test_old_rows_and_articles_are_untouched_by_the_alias_work(tmp_path):
    path = build(tmp_path)
    before = dump(path)
    ad.apply(path, confirm_disposable_copy=True)
    root = facts(path)[0]["evidence_id"]
    revise(path, root)
    alias_row(path, "EV-LEGACY-5", root)
    after = dump(path)
    skip = ("evidence_revisions", "evidence_heads", "update_batches", "batch_evidence")
    assert {k: v for k, v in after.items() if k not in skip} == {k: v for k, v in before.items() if k not in skip}
    assert set(before["evidence_revisions"]) <= set(after["evidence_revisions"])  # only the test's own appended revision is new


def test_the_alias_rules_hold_on_a_connection_that_never_turned_foreign_keys_on(migrated):
    path, root = migrated
    revise(path, root)
    with closing(dbs.app_connect(path)) as c:  # SQLite's default: foreign keys OFF
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        for alias_id, r, case, key in (("EV-N1", "EV-NO-ROOT", "case", "quota"), ("EV-N2", root, "another-case", "quota"), ("EV-N3", root, "case", "another_key")):
            with pytest.raises(sqlite3.DatabaseError):
                c.execute("insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,kind,reason,created_at) values(?,?,?,?,?,?,?)", (alias_id, r, case, key, "legacy_compat_id", "x", NOW))
        assert c.execute("select count(*) from evidence_aliases").fetchone()[0] == 0
