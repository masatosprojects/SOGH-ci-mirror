"""Independent tests of Work's G2 source-registration candidate (PR #94: `research/inbox/work-source-registration-g2/source_registration.py`).

Claude-owned QA. DEFINED ONLY when Work's directory exists (absent, not skipped, until PR #94 is merged). SYNTHETIC_ONLY: an invented notice in temporary files, and a FAKE Collector with the real
Collector's contract (return value + a receipt row in `collection.sqlite`); no network is ever used. The real three documents are checked locally (docs/reviews/PR94_G2_SOURCES_REVIEW_2026-11-02.md).
Work's code is imported and called, never edited.

The evidence kinds these tests keep apart are defined in docs/SOURCE_EVIDENCE_LEVELS.md. The first review (head 3ba38d3) found that a hand-written observation file could make
`official_site_authenticity` pass (finding R-1). Work fixed it (head 659e4f1). These are now REGRESSION tests: every attack input of R-1 must be rejected or must leave the level `not_run`; none of them
asserts that a weakness exists. Limit that no test here can remove: a process that runs as the same account can rewrite the Collector, this Python process or the receipt file (D2/G-08).
"""
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import types
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_G2_DIR") or REPO / "research" / "inbox" / "work-source-registration-g2")

if (WORK / "source_registration.py").exists():
    from tests import db_support as S

    _spec = importlib.util.spec_from_file_location("pr94_registration", WORK / "source_registration.py")
    M = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(M)

    HTML = ("<html><head><title>架空のお知らせ</title></head><body><p>架空の窓口は一時的に停止しています。</p><script>隠す内容</script></body></html>").encode("utf-8")
    QUOTE = "架空の窓口は一時的に停止しています。"
    URL = "https://fiction.invalid/notice"
    ALL_NOT_RUN = {"bytes_match_recorded_sha": "pass", "stored_file_matches_record": "pass", "official_site_authenticity": "not_run", "content_meaning_checked": "not_run"}

    def make_record(raw, page_text_norm):
        start = page_text_norm.index(M.normalized(QUOTE)[0])
        return {"evidence_id": M.IDS[0], "case_id": "case", "source_sha256": hashlib.sha256(raw).hexdigest(), "source_url": URL, "source_kind": "html",
                "retrieved_at": "2026-11-01", "value": {"text": "架空"}, "proofs": [{"page": 1, "normalized_start": start, "normalized_end": start + len(M.normalized(QUOTE)[0]), "quote": QUOTE, "section": None}]}

    def canon(record):
        return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def past(seconds=5):
        return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()

    @pytest.fixture
    def world(tmp_path, monkeypatch):
        page = M.pages(HTML, "html")[0]
        record = make_record(HTML, M.normalized(page)[0])
        profile = {"published_at": None, "published_at_certainty": "unknown", "source_kind": "notice", "title": "架空のお知らせ", "applies_to_fiscal_year": None, "basis": "synthetic",
                   "proof_questions": [], "reviewed_record_sha256": canon(record)}
        profile_path = tmp_path / "profiles.json"
        profile_path.write_text(json.dumps({M.IDS[0]: profile}), encoding="utf-8")
        monkeypatch.setattr(M, "PROFILE", profile_path)
        monkeypatch.setattr(M, "IDS", (M.IDS[0],))
        saved = tmp_path / "saved"
        saved.mkdir()
        body = saved / (record["source_sha256"] + ".html")
        body.write_bytes(HTML)
        view = tmp_path / "view.json"
        view.write_text(json.dumps({"evidence": {M.IDS[0]: record}}, ensure_ascii=False), encoding="utf-8")
        audit_db, _ = S.make_native(tmp_path, "audit.sqlite")
        from admissions_pipeline.revisions import RevisionStore  # creates the revision tables the chain needs (a v0.5-lineage database)
        RevisionStore(audit_db, tmp_path / "unused-backup.sqlite")
        return record, body, saved, view, audit_db, tmp_path

    def run_main(world, monkeypatch, observations=None, out="out", live_pipeline=None):
        record, body, saved, view, audit_db, tmp = world
        argv = ["source_registration.py", "--view", str(view), "--saved-dir", str(saved), "--audit-db", str(audit_db), "--qa-root", str(REPO), "--output", str(tmp / out)]
        if observations is not None:
            path = tmp / "observations.json"
            path.write_text(json.dumps(observations), encoding="utf-8")
            argv += ["--current-observations", str(path)]
        if live_pipeline is not None:
            argv += ["--verify-official-live", "--pipeline", str(live_pipeline)]
        monkeypatch.setattr(sys, "argv", argv)
        M.main()
        with closing(sqlite3.connect(tmp / out / "disposable.sqlite")) as db:
            return dict(db.execute("SELECT level, outcome FROM source_verification_events"))

    def observation(record, path, **over):
        obs = {"url": record["source_url"], "local_path": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "robots_checked": True, "final_url": record["source_url"],
               "retrieved_at": past()}
        obs.update(over)
        return obs

    # ---- the evidence kinds that must stay apart (docs/SOURCE_EVIDENCE_LEVELS.md) -------------------------------------------------------------------------

    def test_without_an_observation_the_authenticity_and_meaning_levels_stay_not_run(world, monkeypatch):
        assert run_main(world, monkeypatch) == ALL_NOT_RUN

    def test_the_audit_copy_is_not_changed_and_the_output_is_a_new_directory(world, monkeypatch):
        record, body, saved, view, audit_db, tmp = world
        before = hashlib.sha256(audit_db.read_bytes()).hexdigest()
        run_main(world, monkeypatch)
        assert hashlib.sha256(audit_db.read_bytes()).hexdigest() == before
        with pytest.raises(SystemExit, match="output_must_be_new_disposable_directory"):
            run_main(world, monkeypatch)  # the same output again

    def test_candidates_record_which_extractor_and_normalisation_made_the_offsets(world):
        record, body, *_ = world
        c = M.inspect(record, HTML)
        assert "head-retained" in c["extractor_id"] and c["normalization_id"].startswith("per-character-NFKC")

    # ---- R-1 regression: every attack input of the first review is now rejected or leaves the level not_run ----------------------------------------------

    def test_r1_the_original_attack_a_forged_flag_file_with_a_future_date_that_points_at_the_saved_file_is_rejected(world, monkeypatch):
        record, body, *_ = world
        forged = [{"url": record["source_url"], "local_path": str(body), "sha256": record["source_sha256"], "robots_checked": True, "final_url": record["source_url"], "retrieved_at": "2099-01-01T00:00:00+09:00"}]
        with pytest.raises(ValueError, match="naive_or_future"):
            run_main(world, monkeypatch, observations=forged)

    def test_r1_the_same_forged_file_with_a_valid_past_date_is_still_rejected_because_it_is_the_saved_original(world, monkeypatch):
        record, body, *_ = world
        with pytest.raises(ValueError, match="current_observation_is_the_saved_original"):
            run_main(world, monkeypatch, observations=[observation(record, body)])

    def test_r1_a_copy_of_the_saved_bytes_with_every_flag_true_is_comparison_only_and_never_an_authenticity_pass(world, monkeypatch, tmp_path):
        record, body, *_ = world
        copy = tmp_path / "elsewhere" / "current.html"
        copy.parent.mkdir()
        copy.write_bytes(HTML)  # another file with the same bytes: a legitimate comparison input, not an official fetch
        forged = observation(record, copy, official_fetch_observation=True, provenance_kind="live_collector_in_this_process")  # extra self-declared fields are ignored
        levels = run_main(world, monkeypatch, observations=[forged])
        assert levels == ALL_NOT_RUN

    @pytest.mark.parametrize("stamp", ["2099-01-01T00:00:00+00:00", "2026-11-01T00:00:00", "2026-11-02", "not-a-date", "", None])
    def test_r1_a_future_naive_date_only_or_malformed_timestamp_is_rejected(world, monkeypatch, tmp_path, stamp):
        record, body, *_ = world
        copy = tmp_path / "current.html"
        copy.write_bytes(HTML)
        with pytest.raises(ValueError, match="timestamp"):
            run_main(world, monkeypatch, observations=[observation(record, copy, retrieved_at=stamp)])

    def test_r1_a_hardlink_to_the_saved_file_is_the_same_file_and_is_rejected(world):
        record, body, *_ = world
        with tempfile.TemporaryDirectory(prefix="sogh-hardlink-qa-") as directory:
            saved = Path(directory) / "saved.html"
            saved.write_bytes(HTML)
            alias = Path(directory) / "alias.html"
            os.link(saved, alias)
            with pytest.raises(ValueError, match="saved_original"):
                M.validate_current(observation(record, alias), saved)

    def test_a_comparison_file_whose_bytes_differ_from_its_declared_sha_is_refused(world, monkeypatch, tmp_path):
        record, body, *_ = world
        other = tmp_path / "other.html"
        other.write_bytes(HTML + b"<!-- changed -->")
        with pytest.raises(ValueError, match="current_snapshot_changed"):
            run_main(world, monkeypatch, observations=[observation(record, other, sha256="0" * 64)])

    def test_different_bytes_with_the_same_text_is_reported_as_a_byte_difference_and_never_proves_the_old_bytes(world, monkeypatch, tmp_path):
        record, body, *_ = world
        changed = HTML.replace(b"<p>", b'<p class="x">')
        path = tmp_path / "current.html"
        path.write_bytes(changed)
        raw, provenance = M.validate_current(observation(record, path), body)
        comparison = M.inspect(record, HTML, raw)["current_comparison"]
        assert comparison["same_bytes"] is False and comparison["same_normalized_text"] is True  # reported, not hidden
        assert provenance["official_fetch_observation"] is False and provenance["provenance_kind"] == "caller_json_comparison_only"
        assert run_main(world, monkeypatch, observations=[observation(record, path)])["official_site_authenticity"] == "not_run"

    def test_a_record_that_was_not_the_reviewed_version_is_refused(world, monkeypatch):
        record, body, saved, view, audit_db, tmp = world
        changed = dict(record, value={"text": "changed after review"})
        view.write_text(json.dumps({"evidence": {M.IDS[0]: changed}}, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match="unreviewed_record_version"):
            run_main(world, monkeypatch)

    # ---- the live path, with a FAKE Collector that has the real Collector's contract (no network) ------------------------------------------------------------

    def fake_collector(monkeypatch, tmp_path, *, raw=HTML, final_url=None, robots=True, shift=0, receipt="ok", url_scheme=None):
        """Install a stand-in for `admissions_pipeline.collector.Collector`: it returns what the real one returns and writes the same receipt row (table `observations`)."""
        class Collector:
            def __init__(self, root, hosts, delay=2, max_bytes=20_000_000):
                self.root = Path(root)
                self.root.mkdir(parents=True, exist_ok=True)
                self.hosts = hosts
                with sqlite3.connect(self.root / "collection.sqlite") as db:
                    db.execute("CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,url TEXT NOT NULL,sha256 TEXT NOT NULL,retrieved_at TEXT NOT NULL,metadata_json TEXT NOT NULL)")

            def fetch(self, url):
                sha = hashlib.sha256(raw).hexdigest()
                path = self.root / (sha + ".html")
                path.write_bytes(raw)
                result = {"final_url": final_url or url, "content_type": "text/html", "url": url, "sha256": sha, "bytes": len(raw), "kind": "html",
                          "retrieved_at": (datetime.now(timezone.utc) + timedelta(seconds=shift)).isoformat(), "robots_checked": robots, "local_path": str(path), "publication_allowed": False}
                stored = dict(result) if receipt == "ok" else dict(result, robots_checked=not robots) if receipt == "tampered" else None
                if stored is not None:
                    with sqlite3.connect(self.root / "collection.sqlite") as db:
                        db.execute("INSERT INTO observations(url,sha256,retrieved_at,metadata_json) VALUES(?,?,?,?)", (url, sha, result["retrieved_at"], json.dumps(stored, ensure_ascii=False)))
                return result

        package = sys.modules.get("admissions_pipeline") or types.ModuleType("admissions_pipeline")
        if not hasattr(package, "__path__"):
            package.__path__ = []
        module = types.ModuleType("admissions_pipeline.collector")
        module.Collector = Collector
        monkeypatch.setitem(sys.modules, "admissions_pipeline", package)
        monkeypatch.setitem(sys.modules, "admissions_pipeline.collector", module)
        return tmp_path / "fake-pipeline"

    def test_an_honest_live_fetch_of_the_same_bytes_is_the_only_way_to_a_pass_and_meaning_stays_not_run(world, monkeypatch, tmp_path):
        pipeline = fake_collector(monkeypatch, tmp_path)
        levels = run_main(world, monkeypatch, live_pipeline=pipeline)
        assert levels["official_site_authenticity"] == "pass" and levels["content_meaning_checked"] == "not_run"
        assert levels["bytes_match_recorded_sha"] == "pass" and levels["stored_file_matches_record"] == "pass"

    def test_a_live_fetch_that_returns_different_bytes_does_not_prove_the_old_saved_version(world, monkeypatch, tmp_path):
        pipeline = fake_collector(monkeypatch, tmp_path, raw=HTML.replace(b"<p>", b'<p class="x">'))
        assert run_main(world, monkeypatch, live_pipeline=pipeline)["official_site_authenticity"] == "not_run"  # same text is not the same bytes

    def test_a_tampered_or_missing_collector_receipt_is_refused(world, monkeypatch, tmp_path):
        for n, receipt in enumerate(("tampered", "missing")):
            pipeline = fake_collector(monkeypatch, tmp_path / f"r{n}", receipt=receipt)
            with pytest.raises(ValueError, match="live_collector_receipt_mismatch"):
                run_main(world, monkeypatch, live_pipeline=pipeline, out=f"out{n}")

    @pytest.mark.parametrize("kwargs,match", [({"final_url": "https://elsewhere.invalid/x"}, "live_collector_observation_invalid"), ({"robots": False}, "live_collector_observation_invalid"),
                                              ({"shift": -3600}, "fetch_window")])
    def test_a_live_observation_with_another_final_url_without_the_robots_check_or_outside_the_fetch_window_is_refused(world, monkeypatch, tmp_path, kwargs, match):
        pipeline = fake_collector(monkeypatch, tmp_path, **kwargs)
        with pytest.raises(ValueError, match=match):
            run_main(world, monkeypatch, live_pipeline=pipeline)

    def test_the_live_check_cannot_be_combined_with_caller_json_or_run_without_a_pipeline(world, monkeypatch, tmp_path):
        record, body, saved, view, audit_db, tmp = world
        base = ["source_registration.py", "--view", str(view), "--saved-dir", str(saved), "--audit-db", str(audit_db), "--qa-root", str(REPO), "--output", str(tmp / "o")]
        obs = tmp / "o.json"
        obs.write_text("[]", encoding="utf-8")
        for extra in (["--verify-official-live", "--pipeline", str(tmp), "--current-observations", str(obs)], ["--verify-official-live"]):
            monkeypatch.setattr(sys, "argv", base + extra)
            with pytest.raises(SystemExit) as e:
                M.main()
            assert e.value.code == 2
        assert not (tmp / "o").exists()  # refused before any output
