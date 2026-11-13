"""DB acceptance E — backward compatibility. Target kinds are stated per test:
repository_sample = built from / read from files that are in the repository (Work's real delivered samples), NOT Work's database;
synthetic = invented data. Nothing here is a result on Work's local production database (not available: `not_run`)."""
import gzip
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import introspect, load_export
from src.integration import db_audit as da
from src.regression.fullview import find_views
from src.regression.handoffs import INBOX, find_exports

V02_GZ = INBOX / "work-db-v02-20261101" / "data" / "admission_media_v0_2.sqlite.gz"


def load_all(tmp_path: Path, include_exports=False):
    """The authoritative current state = the whole view + the base state it was derived from. `include_exports` adds every
    differential export too, which exposes the duplicate evidence-id space (see test_the_same_general_selection_facts...)."""
    exports = [e.load() for e in find_exports()] if include_exports else []
    bases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(INBOX.rglob("*base-state*.json"))]
    views = [json.loads(p.read_text(encoding="utf-8")) for p in find_views()]
    db = tmp_path / "from-samples.sqlite"
    info = load_export.load(db, [*bases, *exports, *views])
    return db, info


def test_the_v0_2_sample_database_in_the_repository_passes_its_invariants(tmp_path):
    db = tmp_path / "v02.sqlite"
    db.write_bytes(gzip.decompress(V02_GZ.read_bytes()))
    r = da.audit(db, None, "repository_sample")
    assert r["lineage"] == "normalized_v0_2" and r["ok"] and r["target_kind"] == "repository_sample"
    assert {"DB-01", "V02-02", "V02-03", "V02-04"} <= set(r["summary"]["pass"])
    assert "V02-05" in r["summary"]["not_run"]  # the sample has no publications: nothing was examined, so it is not a pass


def test_the_existing_50_evidence_13_articles_are_referentially_consistent_in_the_delivered_schema(tmp_path):
    """Everything Work delivered (all exports + the whole view + the base state) loaded into the delivered v0.5 schema holds the contract.
    Target kind: repository_sample (built from repository files; the original pages are not here, pages are rebuilt from the quotes)."""
    db, info = load_all(tmp_path)
    assert info["skipped"] == [] and info["evidence"] >= 50
    r = da.audit(db, None, "repository_sample")
    assert r["ok"], r["summary"]
    for iid in ("DB-01", "DB-02", "DB-03", "DB-04", "DB-05", "DB-06", "DB-07", "DB-08", "DB-11", "DB-12"):
        assert r["invariants"][iid]["status"] == "pass", (iid, r["invariants"][iid]["problems"][:2])
    assert r["invariants"]["DB-09"]["status"] == "not_run" and r["original_source_comparison"] == "not_run"
    assert r["table_row_counts"]["revised_articles"] >= 6 and r["table_row_counts"]["article_versions"] >= 13


def test_the_same_general_selection_facts_exist_under_two_evidence_ids_in_the_repository(tmp_path):
    """FINDING (see docs/DB_SCHEMA_GAP_ANALYSIS.md): `samples/general/claude-compatible-export.json` carries EV-G27C-01..06 and the whole view
    carries EV-G27-01..06 for the SAME facts (same cycle, source and fact_key; the content is identical). The delivered schema's
    UNIQUE(case_id, source_sha256, fact_key) refuses the second copy. The id-reuse check cannot see it (the ids differ). If Work removes the
    duplicate id space this test must change — that is the point."""
    _, info = load_all(tmp_path, include_exports=True)
    assert sorted(s.split(":")[0] for s in info["skipped"]) == [f"EV-G27C-0{i}-e1137e" for i in range(1, 7)]


def test_the_loader_states_what_it_had_to_assume(tmp_path):
    _, info = load_all(tmp_path)
    assert info["assumptions"] and all("exam_year" in a for a in info["assumptions"])  # an export carries no exam year: it is not hidden


def test_an_old_format_export_and_the_new_whole_view_both_load_and_pass(tmp_path):
    old = [e.load() for e in find_exports() if e.handoff.startswith("work-db-v02")]
    assert old
    db = tmp_path / "old.sqlite"
    info = load_export.load(db, old)
    assert info["skipped"] == [] and da.audit(db, None, "repository_sample")["ok"]
    views = [json.loads(p.read_text(encoding="utf-8")) for p in find_views()]
    assert views and da.audit(load_all(tmp_path)[0], None, "repository_sample")["ok"]


def test_a_new_fact_key_is_rejected_until_it_is_registered_and_a_stage_is_accepted_when_valid(tmp_path):
    db, _ = load_all(tmp_path)
    with closing(sqlite3.connect(db)) as con:
        eid, rec_json, case, sha = con.execute("SELECT evidence_id,record_json,case_id,source_sha256 FROM facts LIMIT 1").fetchone()
        rec = json.loads(rec_json)
        rec.update(evidence_id="EV-new", fact_key="brand_new_key", key="brand_new_key", value={"x": 1})
        con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?)", ("EV-new", case, sha, "brand_new_key", '{"x": 1}', json.dumps(rec), "source_checked_for_saved_version"))
        con.commit()
    assert "DB-11" in {k for k, v in da.audit(db, None, "repository_sample")["invariants"].items() if v["status"] == "fail"}
    with closing(sqlite3.connect(db)) as con:
        con.execute("DELETE FROM facts WHERE evidence_id='EV-new'")
        rec.update(evidence_id="EV-stage", fact_key="interview", key="interview", value={"minutes": 30, "type": "t"}, stage=[1])
        con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?)", ("EV-stage", case, sha, "interview-stage", json.dumps(rec["value"]), json.dumps(rec), "source_checked_for_saved_version"))
        con.commit()
    assert "DB-11" not in {k for k, v in da.audit(db, None, "repository_sample")["invariants"].items() if v["status"] == "fail"}


def test_moving_from_the_v0_3_schema_to_v0_5_only_adds_and_loses_no_row(tmp_path):
    """The delivered v0.3 -> v0.5 step is additive: opening an older database with the update store adds tables and keeps every row.
    Target kind: synthetic (the step is driven through Work's RevisionStore on an invented database)."""
    path, p = S.make_native(tmp_path)
    old = tmp_path / "v03.sqlite"
    shutil.copy(path, old)
    RevisionStore(path, tmp_path / "backup.sqlite")
    r = da.audit(path, old, "synthetic")
    assert r["ok"] and r["invariants"]["DB-09"]["status"] == "pass"
    assert S.counts(path)["facts"] == S.counts(old)["facts"]


def test_the_delivered_schemas_have_not_lost_anything_since_the_previous_generation():
    """A guard for the NEXT schema Work delivers: v0.3 -> v0.5 removed no table and no column. (v0.2 -> v0.3 did: see the gap analysis.)"""
    report = introspect.build_report()
    step = next(e for e in report["evolution"] if e["from"] == "v0_3_national_v1")
    assert step["tables_removed"] == [] and step["columns_changed"] == {}


def test_the_generation_break_between_v0_2_and_v0_3_is_recorded_as_a_fact():
    report = introspect.build_report()
    step = next(e for e in report["evolution"] if e["from"] == "v0_2_sample_db")
    assert {"publications", "article_plans", "fact_claims", "audit_events"} <= set(step["tables_removed"])
    assert step["tables_in_both"] == ["admission_cycles", "article_versions", "source_documents"]
    assert all(c["removed"] for c in step["columns_changed"].values())  # in all three shared tables the key columns changed: not an upgrade path


def test_the_local_production_database_is_not_here_and_is_reported_as_not_run():
    assert not list(Path(INBOX).rglob("*.sqlite"))  # only the gzip'd v0.2 sample exists in the repository
    assert da.TARGET_KINDS == ("synthetic", "repository_sample", "copied_real_db", "production_read_only")
    with pytest.raises(ValueError):
        da.audit(Path("x"), None, "production")  # the kind is validated before anything is opened
