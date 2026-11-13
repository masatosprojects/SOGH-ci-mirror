"""DB acceptance A — normal paths. Target kind: synthetic (driven through Work's store code, judged by the independent audit)."""
import shutil
from pathlib import Path

import pytest

from tests import db_support as S  # first: it puts Work's package on the path (read-only import)
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.store import EvidenceStore  # noqa: E402


def new_store(tmp_path: Path):
    path, p = S.make_native(tmp_path)
    return path, p, RevisionStore(path, tmp_path / "backup-before-update.sqlite")


def test_the_target_kind_is_recorded_and_synthetic_is_never_called_real(tmp_path):
    path, *_ = new_store(tmp_path)
    r = S.audit(path)
    assert r["target_kind"] == "synthetic" and r["lineage"] == "flat" and r["original_source_comparison"] == "not_run"


def test_a_registered_cycle_fact_and_article_pass_every_invariant(tmp_path):
    path, *_ = new_store(tmp_path)
    r = S.audit(path)
    assert r["ok"] and r["summary"]["fail"] == []
    assert r["invariants"]["DB-04"]["status"] == "pass" and r["invariants"]["DB-12"]["status"] == "pass"


def test_a_new_university_is_added_without_touching_the_existing_cycle(tmp_path):
    path, p, store = new_store(tmp_path)
    before = S.counts(path)
    S.ingest_cycle(EvidenceStore(path), "case-b", S.profile(university="別の大学", sha="c" * 64), tmp_path, count=40)
    after = S.counts(path)
    assert after["admission_cycles"] == before["admission_cycles"] + 1 and after["facts"] == before["facts"] + 1
    assert S.audit(path)["ok"] and not S.failing(path)


def test_the_same_method_name_at_two_universities_is_two_independent_cycles(tmp_path):
    path, p, store = new_store(tmp_path)
    S.ingest_cycle(EvidenceStore(path), "case-b", S.profile(university="別の大学", method=p["admission_method"], sha="c" * 64), tmp_path, count=40)
    with store.connect() as db:
        rows = db.execute("SELECT case_id,university FROM admission_cycles WHERE admission_method=? ORDER BY case_id", (p["admission_method"],)).fetchall()
        quotas = dict(db.execute("SELECT case_id,value_json FROM facts"))
    assert [r["university"] for r in rows] == ["試験大学", "別の大学"] and "16" in quotas["case"] and "40" in quotas["case-b"]
    assert S.audit(path)["ok"]


def test_a_new_year_of_the_same_university_and_method_is_a_separate_cycle(tmp_path):
    path, p, store = new_store(tmp_path)
    S.ingest_cycle(EvidenceStore(path), "case-2028", S.profile(fiscal_year=2028, sha="d" * 64), tmp_path, count=18)
    with store.connect() as db:
        years = [r[0] for r in db.execute("SELECT fiscal_year FROM admission_cycles ORDER BY fiscal_year")]
    assert years == [2027, 2028] and S.audit(path)["ok"]


def test_registering_a_correct_revision_activates_it_and_keeps_the_old_facts(tmp_path):
    path, p, store = new_store(tmp_path)
    before = S.counts(path)
    batch, revised, qa, ok = S.approve(store, S.notice(p), S.base_article(store))
    assert ok and S.heads(path)["evidence"] == {"notice": "EV-U-1"}
    assert S.counts(path)["facts"] == before["facts"] and S.counts(path)["evidence_revisions"] == 1
    r = S.audit(path)
    assert r["ok"] and r["invariants"]["DB-05"]["status"] == "pass" and r["invariants"]["DB-06"]["status"] == "pass"


def test_the_article_can_be_traced_to_its_evidence_and_back(tmp_path):
    path, p, store = new_store(tmp_path)
    batch, revised, qa, ok = S.approve(store, S.notice(p), S.base_article(store))
    assert ok and "EV-U-1" in revised["evidence_ids"] and "EV-case-1" in revised["evidence_ids"]
    with store.connect() as db:
        base_links = {r[0] for r in db.execute("SELECT evidence_id FROM article_evidence WHERE article_id='art-case'")}
        row = db.execute("SELECT record_json FROM revised_articles").fetchone()
    assert base_links == {"EV-case-1"} and "EV-U-1" in row[0]


def test_a_second_revision_of_the_same_fact_replaces_the_head_and_keeps_the_first(tmp_path):
    path, p, store = new_store(tmp_path)
    _, first, _, ok1 = S.approve(store, S.notice(p), S.base_article(store))
    corrected = S.notice(p, eid="EV-U-2", parent_evidence_id="EV-U-1", value={"allowed": "訂正後の説明"}, sentences=["生成AIの使用を訂正後の方法で明示します。"])
    _, second, _, ok2 = S.approve(store, corrected, S.base_article(store), previous_id=first["article_id"])
    assert ok1 and ok2 and S.heads(path)["evidence"] == {"notice": "EV-U-2"}
    assert S.counts(path)["evidence_revisions"] == 2 and S.counts(path)["revised_articles"] == 2
    assert S.audit(path)["ok"]


def test_the_candidate_is_only_active_after_the_independent_qa_approves_it(tmp_path):
    path, p, store = new_store(tmp_path)
    batch = store.stage([S.notice(p)], S.REGISTRY)
    assert batch["state"] == "candidate" and S.heads(path) == {"evidence": {}, "articles": {}}  # staged, not active
    assert S.audit(path)["invariants"]["DB-07"]["status"] == "warn"  # a candidate that nobody approved is reported, not passed


def test_running_the_same_data_again_changes_nothing(tmp_path):
    path, p, store = new_store(tmp_path)
    S.approve(store, S.notice(p), S.base_article(store))
    snapshot = S.counts(path)
    again = store.stage([S.notice(p)], S.REGISTRY)
    assert again["state"] == "no_change"
    EvidenceStore(path)  # re-opening / re-ingesting the base is idempotent
    S.ingest_cycle(EvidenceStore(path), "case", S.profile(), tmp_path)
    after = S.counts(path)
    assert {k: v for k, v in after.items() if k != "update_batches" and k != "batch_evidence"} == {k: v for k, v in snapshot.items() if k != "update_batches" and k != "batch_evidence"}
    assert S.audit(path)["ok"]


def test_restoring_the_backup_taken_before_the_update_gives_back_exactly_the_old_state(tmp_path):
    path, p, store = new_store(tmp_path)
    backup = tmp_path / "backup-before-update.sqlite"
    assert backup.exists()  # RevisionStore takes it BEFORE it changes the schema
    S.approve(store, S.notice(p), S.base_article(store))
    r = S.audit(path, backup)  # nothing of the old state was lost by the update
    assert r["ok"] and r["invariants"]["DB-09"]["status"] == "pass"
    restored = tmp_path / "restored.sqlite"
    shutil.copy(backup, restored)
    r2 = S.audit(restored, backup)
    assert r2["ok"] and r2["invariants"]["DB-09"]["status"] == "pass" and S.counts(restored)["facts"] == 1


def test_an_added_unregistered_fact_key_proposal_is_pending_not_active(tmp_path):
    path, p, store = new_store(tmp_path)
    batch = store.stage([S.notice(p, fact_key="multilingual_evaluation", value={"languages": ["ドイツ語"], "application_required": True, "text": "x"})], S.REGISTRY)
    assert batch["state"] == "pending_contract" and S.heads(path) == {"evidence": {}, "articles": {}}
