import copy
import gzip
import hashlib
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from admissions_pipeline.collector import Collector, Page, Redirect, official_url
from admissions_pipeline.dimensions import migrate, save_dimensions
from admissions_pipeline.extract import ExtractionError
from admissions_pipeline.generic import draft
from admissions_pipeline.profiles import extract_profile, load_profile, substitute
from admissions_pipeline.store import EvidenceStore


@pytest.fixture
def sample(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"controlled fixture, not an official PDF")
    p = {"case_id": "fixture", "code": "X27", "profile_version": "test", "university": "試験大学",
         "faculty": "試験学部", "department": None, "admission_method": "試験方式", "fiscal_year": 2027,
         "exam_year": 2026, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "url": "https://example.ac.jp/guide.pdf",
         "cover_anchor": "2027募集要項", "dimensions": {"selection_category": "general", "entry_months": [4, 9],
         "round_name": "前期", "scope": {"faculty": "試験学部"}},
         "rules": [{"key": "quota", "scope": "department_and_method", "anchors": [{"page": 1, "pattern": r"募集(?P<count>\d+)人。注記"}],
                    "value": {"count": "$int:count"}, "sentence": "募集人員は{count}人です。"}]}
    pages = ["2027募集要項\n募集50人。注記"]
    class Document:
        is_encrypted = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self): return iter([SimpleNamespace(get_text=lambda: x) for x in pages])
    monkeypatch.setitem(sys.modules, "pymupdf", SimpleNamespace(open=lambda _: Document()))
    return p, pdf, pages


def test_hash_change_stops_extraction(sample):
    p, pdf, _ = sample
    pdf.write_bytes(b"replaced")
    with pytest.raises(ExtractionError): extract_profile(p, pdf)


@pytest.mark.parametrize("text", ["2027募集要項 募集50人。", "2027募集要項 募集50人。注記 募集99人。注記", "scanned PDF"])
def test_missing_ambiguous_or_scan_stops(sample, text):
    p, pdf, pages = sample
    pages[0] = text
    with pytest.raises(ExtractionError): extract_profile(p, pdf)


def test_raw_position_and_capture_not_guess(sample):
    p, pdf, pages = sample
    pages[0] = "2027募集要項\n募 集５０人。注記"
    fact = extract_profile(p, pdf).facts[0]
    assert fact["value"]["count"] == 50
    assert fact["proofs"][0]["quote"] == "募 集５０人。注記"


def test_exception_anchor_required(sample):
    p, pdf, _ = sample
    p["rules"][0]["anchors"].append({"page": 1, "pattern": "郵送期限の例外"})
    with pytest.raises(ExtractionError): extract_profile(p, pdf)


@pytest.mark.parametrize("mutate", ["unknown_key", "missing_hash", "duplicate_rule"])
def test_profile_contract_rejects(sample, tmp_path, mutate):
    p, _, _ = sample
    if mutate == "unknown_key": p["rules"][0]["key"] = "unagreed_new_fact"
    if mutate == "missing_hash": p["sha256"] = ""
    if mutate == "duplicate_rule": p["rules"].append(p["rules"][0])
    path = tmp_path / "profile.json"; path.write_text(json.dumps(p), encoding="utf-8")
    with pytest.raises(ExtractionError): load_profile(path)


def test_date_capture_checks_calendar():
    assert substitute("$date:ry,m,d", {"ry": "8", "m": "11", "d": "2"}) == "2026-11-02"
    with pytest.raises(ValueError): substitute("$date:ry,m,d", {"ry": "8", "m": "2", "d": "30"})


def test_additive_migration_backup_and_multiple_rounds(sample, tmp_path):
    p, pdf, _ = sample
    store = EvidenceStore(tmp_path / "db.sqlite")
    store.ingest(extract_profile(p, pdf), "2026-11-01")
    before = store.counts()
    backup = tmp_path / "backup.sqlite"
    migrate(store, backup)
    assert store.counts() == before
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT count(*) FROM facts").fetchone()[0] == 1
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='cycle_dimensions'").fetchall()
    p["dimensions"]["offerings"] = [{"round_name": r, "entry_month": m, "scope": {"faculty": "試験学部"}} for r in ("前期", "後期") for m in (4, 9)]
    save_dimensions(store, p, "2026-11-01")
    save_dimensions(store, p, "2026-11-01")
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM admission_offerings").fetchone()[0] == 4
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(FileExistsError): migrate(store, backup)


def test_unknown_month_preserved_without_guess(sample, tmp_path):
    p, pdf, _ = sample
    store = EvidenceStore(tmp_path / "db.sqlite"); store.ingest(extract_profile(p, pdf), "2026-11-01")
    migrate(store, tmp_path / "backup.sqlite")
    p["dimensions"]["entry_months"] = []
    with pytest.raises(ValueError): save_dimensions(store, p, "2026-11-01")
    p["dimensions"]["entry_month_status"] = "unconfirmed"
    save_dimensions(store, p, "2026-11-01")
    with store.connect() as db: assert db.execute("SELECT entry_month FROM admission_offerings").fetchone()[0] is None


@pytest.mark.parametrize("field", ["count", "url", "university"])
def test_draft_rejects_forged_pack(sample, tmp_path, field):
    p, pdf, _ = sample
    store = EvidenceStore(tmp_path / "db.sqlite"); store.ingest(extract_profile(p, pdf), "2026-11-01")
    pack = store.pack(p["case_id"], p["sha256"])
    if field == "count": pack["facts"][0]["value"]["count"] = 999
    if field == "url": pack["source"]["url"] = "https://other.example/"
    if field == "university": pack["cycle"]["university"] = "別大学"
    with pytest.raises(ValueError): draft(pack, p, "overview", date(2026, 11, 1))


@pytest.mark.parametrize("url", ["http://example.ac.jp/a", "https://else.ac.jp/a", "https://fixture-user:" + "@" + "127.0.0.1/a", "https://example.ac.jp:444/a"])
def test_collector_official_boundary(url):
    with pytest.raises(ValueError): official_url(url, {"example.ac.jp"})


def test_html_candidates_are_not_facts():
    page = Page('<script>private</script><a href="/fix">募集要項の訂正</a>', "https://example.ac.jp/")
    assert "private" not in page.text
    assert page.links == [{"url": "https://example.ac.jp/fix", "label": "募集要項の訂正"}]


def test_gzip_is_decoded_and_bounded(tmp_path):
    collector = Collector(tmp_path, {"example.ac.jp"}, delay=0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = gzip.compress(b"<html>official</html>")
    response.headers = {"Content-Encoding": "gzip", "Content-Type": "text/html"}; response.url = "https://example.ac.jp/"
    opener = MagicMock(); opener.open.return_value = response
    raw, _ = collector._read(opener, response.url, 1000)
    assert raw == b"<html>official</html>"
    response.read.return_value = gzip.compress(b"x" * 10000)
    with pytest.raises(ValueError): collector._read(opener, response.url, 100)


def test_collection_keeps_versions_and_repeat_is_unchanged(tmp_path, monkeypatch):
    collector = Collector(tmp_path, {"example.ac.jp"}, delay=0)
    bodies = iter([b"User-agent: *\nAllow: /", b"<html>old</html>", b"<html>old</html>", b"<html>new</html>"])
    monkeypatch.setattr(collector, "_read", lambda *args: (next(bodies), {"content_type": "text/html"}))
    first, repeat, changed = [collector.fetch("https://example.ac.jp/guide") for _ in range(3)]
    assert [x["observation"] for x in (first, repeat, changed)] == ["baseline", "unchanged", "changed_requires_review"]
    assert changed["previous_sha256"] == first["sha256"]
    assert Path(first["local_path"]).read_bytes() == b"<html>old</html>"
    with sqlite3.connect(tmp_path / "collection.sqlite") as db: assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 3


def test_robots_denial_does_not_download_source(tmp_path, monkeypatch):
    collector = Collector(tmp_path, {"example.ac.jp"}, delay=0)
    calls = []
    def read(opener, url, limit):
        calls.append(url)
        return b"User-agent: *\nDisallow: /", {"content_type": "text/plain"}
    monkeypatch.setattr(collector, "_read", read)
    with pytest.raises(ValueError): collector.fetch("https://example.ac.jp/guide")
    assert calls == ["https://example.ac.jp/robots.txt"]


def test_snapshot_contract_and_tampered_body(tmp_path):
    collector = Collector(tmp_path / "bodies", {"example.ac.jp"})
    body = tmp_path / "body.html"; body.write_bytes(b"<h1>official</h1>")
    record = {"url": "https://example.ac.jp/", "local_path": str(body), "sha256": hashlib.sha256(body.read_bytes()).hexdigest(), "kind": "html", "retrieved_at": "2026-11-01T00:00:00Z"}
    path = collector.write_snapshot(record, "test-source", tmp_path / "snapshots")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == 1 and snapshot["pages"] == ["official"]
    assert snapshot["retrieved_at"] == "2026-11-01" and snapshot["supersedes"] == []
    assert collector.write_snapshot(record, "test-source", tmp_path / "snapshots") == path
    body.write_bytes(b"changed")
    with pytest.raises(ValueError): collector.write_snapshot(record, "test-source", tmp_path / "snapshots")


@pytest.mark.parametrize('keys,shared',[(['eligibility'],[]),(['quota'],['postal_period'])])
def test_article_policy_cannot_invent_unextracted_facts(sample,tmp_path,keys,shared):
    p,pdf,_=sample;store=EvidenceStore(tmp_path/'policy.sqlite');store.ingest(extract_profile(p,pdf),'2026-11-01')
    p['article_policy']={'documents':{'fact_keys':keys,'shared_fact_keys':shared}}
    with pytest.raises(ValueError,match='unproven'):draft(store.pack(p['case_id'],p['sha256']),p,'documents',date(2026,11,1))


def test_article_policy_preserves_proofs_and_labels_official_vs_advice(sample,tmp_path):
    p,pdf,_=sample;store=EvidenceStore(tmp_path/'policy.sqlite');store.ingest(extract_profile(p,pdf),'2026-11-01')
    p['article_policy']={'documents':{'fact_keys':['quota'],'shared_fact_keys':[]}}
    article=draft(store.pack(p['case_id'],p['sha256']),p,'documents',date(2026,11,1))
    assert 'この方式固有の公式事実' in article['text'] and '編集上の助言' in article['text']
    assert article['evidence_ids']==[extract_profile(p,pdf).facts[0]['evidence_id']]
