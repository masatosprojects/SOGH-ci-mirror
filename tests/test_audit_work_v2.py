"""Independent audit of Work's v0.5 pipeline (PR #33, Issue #26): the database and the monitor.

Written from the stated guarantees, with its own fixtures — not by reusing Work's tests. Everything is local and
synthetic: a throw-away SQLite database in tmp_path and a fake collector (no network, no university site is contacted,
no production worker, scheduler or database is touched). A failure here is a defect in Work's code, to be reported
in Issue #26, not something to be 'fixed' by loosening the test.
"""
from __future__ import annotations

import copy
import hashlib
import sqlite3
import sys
import urllib.error
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

# Importing Work's package must not leave anything inside Work's delivery directory (its manifest lists every file):
# no bytecode, no caches. test_regression_handoffs audits that manifest in the same run.
sys.dont_write_bytecode = True

PIPELINE = Path(__file__).resolve().parents[1] / "research" / "inbox" / "work-updates-v2" / "pipeline"
sys.path.insert(0, str(PIPELINE))

from admissions_pipeline.collector import Collector  # noqa: E402
from admissions_pipeline.extract import Extracted  # noqa: E402
from admissions_pipeline.monitor import Monitor  # noqa: E402
from admissions_pipeline.notice_articles import revise_article  # noqa: E402
from admissions_pipeline.process_lock import ProcessLock  # noqa: E402
from admissions_pipeline.revisions import RevisionStore, clone_database  # noqa: E402
from admissions_pipeline.store import EvidenceStore, canonical  # noqa: E402

PROFILE = {"university": "〇〇大学", "faculty": "環境学部", "department": None, "admission_method": "夏秋AO入試",
           "fiscal_year": 2027, "exam_year": 2026, "sha256": "a" * 64, "url": "https://example.ac.jp/guide"}
SCOPE = {k: PROFILE[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")}
REGISTRY = {"fact_keys": {"generative_ai_policy": {"status": "active"}, "fee_refund": {"status": "active"},
                          "multilingual_evaluation": {"status": "proposed"}}}
TABLES = ("admission_cycles", "source_documents", "source_pages", "facts", "article_versions", "article_evidence")


def dump(path: Path) -> dict[str, list]:
    with closing(sqlite3.connect(path)) as db:
        return {t: sorted(map(tuple, db.execute(f"SELECT * FROM {t}").fetchall())) for t in TABLES}


@pytest.fixture
def world(tmp_path):
    path = tmp_path / "native.sqlite"
    base = EvidenceStore(path)
    fact = {"evidence_id": "EV-OLD-1", "key": "quota", "value": {"count": 16, "unit": "名"}, "fiscal_year": 2027,
            "verification": "source_checked_for_saved_version"}
    base.ingest(Extracted("case", PROFILE, tmp_path / "source.pdf", ["募集人員は16名です。"], [fact]), "2026-11-01")
    article = {"article_id": "base", "case_id": "case", "input_hash": "a" * 64, "series": "overview", "title": "試験記事",
               "text": "# 試験記事\n\n募集人員は16名[EV-OLD-1]です。\n\n## 根拠資料\n- [EV-OLD-1] 募集要項 PDF p.1\n", "evidence_ids": ["EV-OLD-1"],
               "claim": dict(SCOPE)}
    base.save_article(article, tmp_path / "base.md")
    record = {"evidence_id": "EV-U-1", "logical_id": "notice", "case_id": "case", **SCOPE, "fact_key": "generative_ai_policy",
              "source_sha256": "b" * 64, "source_kind": "html", "source_url": "https://example.ac.jp/faq", "proofs": [{"page": 1}],
              "value": {"allowed": "FAQの説明"}, "sentences": ["生成AIの使用を明示します。"], "temporal_status": "current_faq",
              "retrieved_at": "2026-11-01"}
    return path, base, article, record


def open_store(path: Path, tmp_path: Path, name="backup.sqlite") -> RevisionStore:
    return RevisionStore(path, tmp_path / name)


def approve(store, record, article, previous_id=None, as_of=date(2026, 11, 1)):
    batch = store.stage([record], REGISTRY)
    revised = revise_article(article, store.effective_records(batch), as_of, previous_id)
    qa = {"success": True, "batch_input_sha": batch["input_sha"],
          "articles_sha256": hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    return batch, revised, qa, store.finalize(batch, [revised], qa, REGISTRY)


# ============================================================ database

def test_cloning_never_changes_the_source_and_refuses_an_existing_destination(world, tmp_path):
    path, *_ = world
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    copy_path = clone_database(path, tmp_path / "copy.sqlite")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before and dump(copy_path) == dump(path)
    with pytest.raises(ValueError):
        clone_database(path, copy_path)
    with pytest.raises(ValueError):
        clone_database(path, path)


def test_a_backup_exists_before_the_schema_changes_and_restores_the_old_state(world, tmp_path):
    path, *_ = world
    old = dump(path)
    store = open_store(path, tmp_path)
    with closing(sqlite3.connect(tmp_path / "backup.sqlite")) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "evidence_heads" not in tables and "facts" in tables  # the backup is the state BEFORE the update schema
    assert dump(tmp_path / "backup.sqlite") == old
    with pytest.raises(FileExistsError):
        store.snapshot(tmp_path / "backup.sqlite")


def test_approval_preserves_every_old_row_and_leaves_the_database_consistent(world, tmp_path):
    path, _, article, record = world
    old = dump(path)
    store = open_store(path, tmp_path)
    *_, ok = approve(store, record, article)
    assert ok and dump(path) == old  # nothing in the original tables changed: facts, pages, articles, links
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_qa_leaves_no_trace_in_the_heads_or_the_revised_articles(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    batch = store.stage([record], REGISTRY)
    assert store.finalize(batch, [], {"success": False}, REGISTRY) is False
    assert store.heads() == {"evidence": {}, "articles": {}}
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM revised_articles").fetchone()[0] == 0
        assert db.execute("SELECT state FROM update_batches").fetchone()[0] == "rejected"


def test_a_proposed_fact_key_is_never_activated_even_with_passing_qa(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    proposed = dict(record, fact_key="multilingual_evaluation")
    batch = store.stage([proposed], REGISTRY)
    assert batch["state"] == "pending_contract"
    with pytest.raises(ValueError):
        store.finalize(batch, [], {"success": True}, REGISTRY)
    assert store.heads() == {"evidence": {}, "articles": {}}


def test_rerunning_the_same_input_changes_nothing_and_cannot_be_approved_twice(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    batch, revised, qa, ok = approve(store, record, article)
    assert ok
    heads = store.heads()
    with store.connect() as db:
        counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("evidence_revisions", "revised_articles", "evidence_heads")}
    again = store.stage([record], REGISTRY)
    assert again["state"] == "no_change"
    with pytest.raises(ValueError):
        store.finalize(batch, [revised], qa, REGISTRY)  # the same approved batch again
    with pytest.raises(ValueError):
        store.finalize(again, [revised], qa, REGISTRY)  # a no_change batch is not eligible
    assert store.heads() == heads
    with store.connect() as db:
        assert counts == {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in counts}


def test_an_evidence_id_cannot_be_reused_for_different_content(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    approve(store, record, article)
    changed = copy.deepcopy(record)
    changed["value"] = {"allowed": "別の説明"}
    with pytest.raises(ValueError):
        store.stage([changed], REGISTRY)


@pytest.mark.parametrize("field,value", [("fiscal_year", 2026), ("admission_method", "一般選抜"), ("faculty", "文学部"), ("university", "△△大学")])
def test_an_update_for_another_year_method_faculty_or_university_is_rejected(world, tmp_path, field, value):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    wrong = dict(record, **{field: value})
    with pytest.raises(ValueError, match="cross-cycle"):
        store.stage([wrong], REGISTRY)
    assert store.heads() == {"evidence": {}, "articles": {}}


def test_a_correction_whose_parent_belongs_to_another_fact_or_cycle_is_rejected(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    approve(store, record, article)
    other_fact = dict(record, evidence_id="EV-U-2", fact_key="fee_refund", parent_evidence_id="EV-U-1", logical_id="n2")
    with pytest.raises(ValueError):
        store.stage([other_fact], REGISTRY)
    with pytest.raises(ValueError):
        store.stage([dict(record, evidence_id="EV-U-3", logical_id="n3", parent_evidence_id="EV-NOWHERE")], REGISTRY)


def test_a_revised_article_that_is_not_what_was_qad_or_is_publishable_or_miscites_is_rejected(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    batch = store.stage([record], REGISTRY)
    revised = revise_article(article, store.effective_records(batch), date(2026, 11, 1))
    good_qa = {"success": True, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    tampered = dict(revised, text=revised["text"].replace("生成AI", "生成ＡＩ"))
    with pytest.raises(ValueError, match="not bound"):
        store.finalize(batch, [tampered], good_qa, REGISTRY)
    publishable = dict(revised, publish_allowed=True)
    qa_pub = dict(good_qa, articles_sha256=hashlib.sha256(canonical([publishable]).encode()).hexdigest())
    with pytest.raises(ValueError, match="unapproved"):
        store.finalize(batch, [publishable], qa_pub, REGISTRY)
    wrong_year = dict(revised, claim=dict(revised["claim"], fiscal_year=2026))
    qa_year = dict(good_qa, articles_sha256=hashlib.sha256(canonical([wrong_year]).encode()).hexdigest())
    with pytest.raises(ValueError, match="scope or year"):
        store.finalize(batch, [wrong_year], qa_year, REGISTRY)
    assert store.heads() == {"evidence": {}, "articles": {}}  # none of the three attempts activated anything


def test_the_same_day_correction_gets_a_new_article_id_and_keeps_the_old_one(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    _, first, _, ok1 = approve(store, record, article)
    correction = dict(copy.deepcopy(record), evidence_id="EV-U-1B", parent_evidence_id="EV-U-1", value={"allowed": "訂正後の説明"},
                      sentences=["生成AIの使用を訂正後の方法で明示します。"])
    _, second, _, ok2 = approve(store, correction, article, previous_id=first["article_id"])
    assert ok1 and ok2 and first["article_id"] != second["article_id"]
    assert store.heads()["articles"]["base"] == second["article_id"] and store.heads()["evidence"]["notice"] == "EV-U-1B"
    with store.connect() as db:  # nothing was overwritten: both revisions and both evidence rows are kept
        assert {r[0] for r in db.execute("SELECT article_id FROM revised_articles")} == {first["article_id"], second["article_id"]}
        assert db.execute("SELECT count(*) FROM evidence_revisions").fetchone()[0] == 2


def test_a_crash_between_stage_and_approval_is_recovered_without_activating(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    batch = store.stage([record], REGISTRY)
    assert store.recover_candidates() == [batch["batch_id"]]
    assert store.heads() == {"evidence": {}, "articles": {}}
    with pytest.raises(ValueError):
        store.finalize(batch, [], {"success": True}, REGISTRY)


def test_an_expired_refund_cannot_be_written_as_a_current_notice(world, tmp_path):
    path, _, article, record = world
    store = open_store(path, tmp_path)
    expired = dict(record, evidence_id="EV-U-R", logical_id="refund", fact_key="fee_refund", temporal_status="deadline_elapsed",
                   value={"amount": 13000, "currency": "JPY", "deadline": "2026-11-05"}, sentences=["検定料13,000円を返還します。"])
    batch = store.stage([expired], REGISTRY)
    with pytest.raises(ValueError, match="future deadline"):
        revise_article(article, store.effective_records(batch), date(2026, 11, 1))  # 11/5 is still ahead of 11/1


# ============================================================ monitor

class FakeCollector:
    write_snapshot = Collector.write_snapshot

    def __init__(self, root: Path, plan):
        self.root, self.plan, self.calls = root, {u: list(v) for u, v in plan.items()}, []
        root.mkdir(parents=True)

    def fetch(self, url):
        self.calls.append(url)
        item = self.plan[url].pop(0)
        if isinstance(item, Exception):
            raise item
        sha = hashlib.sha256(item).hexdigest()
        path = self.root / (sha + ".html")
        path.write_bytes(item)
        return {"url": url, "sha256": sha, "kind": "html", "local_path": str(path), "retrieved_at": "2026-11-01T00:00:00Z"}


A, B = "https://example.ac.jp/a", "https://example.ac.jp/b"


def config(**over):
    return {"allowed_hosts": ["example.ac.jp"], "interval_seconds": 60, "max_attempts": 2, "failure_backoff_seconds": 300,
            "targets": [{"url": A, "case": "c", "role": "faq"}, {"url": B, "case": "c", "role": "notice"}], **over}


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    monkeypatch.setattr("admissions_pipeline.monitor.time.sleep", lambda s: None)
    clock = [1000.0]

    def make(plan, **over):
        collector = FakeCollector(tmp_path / f"bodies{len(list(tmp_path.glob('bodies*')))}", plan)
        return Monitor(tmp_path / "state", config(**over), clock=lambda: clock[0], collector=collector), collector, clock
    return make


def status_of(report):
    return {r["url"]: r["status"] for r in report["results"]}


def test_a_404_is_not_retried_and_does_not_stop_the_other_url(monitor):
    m, collector, _ = monitor({A: [urllib.error.HTTPError(A, 404, "x", {}, None)], B: [b"<p>ok</p>"]})
    report = m.run_once()
    assert status_of(report) == {A: "failed", B: "first_fetch"} and report["success"] is False
    assert collector.calls == [A, B]  # one attempt for the 404
    with m.connect() as db:
        row = db.execute("SELECT failures,last_error,last_success FROM targets WHERE url=?", (A,)).fetchone()
    assert row["failures"] == 1 and row["last_error"] == "HTTPError:404" and row["last_success"] is None


def test_a_503_is_retried_and_a_second_failure_backs_off_longer(monitor):
    err = lambda: urllib.error.HTTPError(A, 503, "x", {}, None)  # noqa: E731
    m, collector, clock = monitor({A: [err(), b"<p>ok</p>", err(), err(), err(), err()], B: [b"b1", b"b2", b"b3"]})
    first = m.run_once()
    assert status_of(first)[A] == "first_fetch" and [r for r in first["results"] if r["url"] == A][0]["attempts"] == 2
    clock[0] += 61
    m.run_once()  # A: 503 + 503 -> failed (attempts 2)
    with m.connect() as db:
        due1 = db.execute("SELECT next_due FROM targets WHERE url=?", (A,)).fetchone()[0]
    clock[0] = due1 + 1
    m.run_once()  # fails again
    with m.connect() as db:
        due2 = db.execute("SELECT next_due FROM targets WHERE url=?", (A,)).fetchone()[0]
    assert due2 - clock[0] > due1 - (due1 - 300) - 1 and due2 - clock[0] >= 600  # exponential backoff, not a fixed retry


def test_a_failure_never_replaces_the_last_good_version(monitor):
    m, _, clock = monitor({A: [b"<p>good</p>", TimeoutError(), TimeoutError()], B: [b"b", b"b", b"b"]})
    m.run_once()
    with m.connect() as db:
        good = db.execute("SELECT last_sha,last_snapshot FROM targets WHERE url=?", (A,)).fetchone()
    clock[0] += 61
    assert status_of(m.run_once())[A] == "failed"
    with m.connect() as db:
        after = db.execute("SELECT last_sha,last_snapshot,failures FROM targets WHERE url=?", (A,)).fetchone()
    assert (after["last_sha"], after["last_snapshot"]) == (good["last_sha"], good["last_snapshot"]) and after["failures"] == 1
    assert Path(good["last_snapshot"]).exists()


@pytest.mark.parametrize("body", [b"\xff\xfe\x00bad", "<p>壊れ�文字</p>".encode()])
def test_undecodable_or_replacement_character_pages_are_not_accepted_as_a_new_edition(monitor, body):
    m, _, clock = monitor({A: [b"<p>good</p>", body, body], B: [b"b", b"b", b"b"]})
    m.run_once()
    clock[0] += 61
    report = m.run_once()
    assert status_of(report)[A] == "failed"
    with m.connect() as db:
        assert db.execute("SELECT last_sha FROM targets WHERE url=?", (A,)).fetchone()[0] == hashlib.sha256(b"<p>good</p>").hexdigest()


def test_same_bytes_are_unchanged_and_different_bytes_are_changed_with_both_snapshots(monitor):
    m, _, clock = monitor({A: [b"<p>one</p>", b"<p>one</p>", b"<p>two</p>"], B: [b"b", b"b", b"b"]})
    assert status_of(m.run_once())[A] == "first_fetch"
    clock[0] += 61
    assert status_of(m.run_once())[A] == "unchanged"
    clock[0] += 61
    changed = [r for r in m.run_once()["results"] if r["url"] == A][0]
    assert changed["status"] == "changed" and changed["previous_sha256"] != changed["sha256"]
    assert Path(changed["old_snapshot"]).exists() and Path(changed["new_snapshot"]).exists()


def test_a_url_outside_the_allowed_hosts_is_refused_before_any_request(tmp_path):
    collector = FakeCollector(tmp_path / "bodies", {})
    bad = config(targets=[{"url": "https://evil.example.com/x", "case": "c", "role": "faq"}])
    m = Monitor(tmp_path / "state", bad, collector=collector)
    with pytest.raises(Exception):
        m.run_once()
    assert collector.calls == []


def test_a_moved_url_cannot_silently_take_over_an_existing_source_identity(monitor):
    m, _, _ = monitor({A: [b"x"], B: [b"y"]})
    m.run_once()
    m.config["targets"][0]["source_id"] = "a-different-source"
    with pytest.raises(ValueError, match="source identity"):
        m.configure()


def test_the_stop_flag_prevents_every_request_and_the_run_reports_stopped(monitor):
    m, collector, _ = monitor({A: [b"x"], B: [b"y"]})
    (m.root / "STOP").write_text("stop")
    report = m.run_once()
    assert collector.calls == [] and report["stopped"] is True and report["publication_allowed"] is False


def test_state_survives_a_restart_and_a_second_start_is_refused(tmp_path, monitor):
    m, collector, clock = monitor({A: [b"x", b"x"], B: [b"y", b"y"]})
    m.run_once()
    clock[0] += 61
    restarted = Monitor(m.root, config(), clock=lambda: clock[0], collector=collector)
    assert status_of(restarted.run_once()) == {A: "unchanged", B: "unchanged"}  # the previous hashes were remembered
    with ProcessLock(m.root / "monitor.lock"):
        with pytest.raises(RuntimeError, match="another collection process"):
            restarted.run_once()
    restarted.run_once(force=True)  # the lock was released


def test_one_url_listed_for_two_universities_is_requested_once_per_cycle(monitor):
    m, collector, _ = monitor({A: [b"x"]}, targets=[{"url": A, "case": "c1", "role": "faq"}, {"url": A, "case": "c1", "role": "faq"}])
    m.run_once()
    assert collector.calls == [A]
