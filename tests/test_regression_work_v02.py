"""Regression tests on Work's real v0.2 handoff (research/inbox/work-db-v02-20261101,
merged in PR #6): 30 evidence records from two official PDFs, 4 drafts, the DB copy.

These run in CI with no skips: the data is in the repository. The official PDFs
themselves are not (rights, size), so anything that needs them is covered by
`python -m src.integration.audit_handoff --pdf-dir ...` and recorded in reports/.
"""
import gzip
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.article_qa.mutation_sweep import sweep
from src.integration import audit_handoff as ah
from src.integration.validate_export import validate_records
from src.versioning import impact
from src.versioning.snapshot import snapshot_from_evidence

HANDOFF = Path(__file__).parent.parent / "research" / "inbox" / "work-db-v02-20261101"
EXPORT_PATH = HANDOFF / "samples" / "claude-compatible-export.json"

# Real data must be present: a missing handoff makes collection fail loudly, it is never skipped.
_EXPORT = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
WITH_DIGITS = [eid for eid, e in _EXPORT["evidence"].items() if re.search(r"\d", e["proofs"][0]["quote"])]


@pytest.fixture(scope="module")
def export():
    return json.loads(EXPORT_PATH.read_text(encoding="utf-8"))


def test_handoff_shape(export):
    assert len(export["evidence"]) == 30 and len(export["articles"]) == 4
    assert len({e["source_pdf_sha256"] for e in export["evidence"].values()}) == 2


def test_every_evidence_record_passes_the_phase_e_gate(export):
    result = validate_records(export["evidence"])
    assert result["total"] == 30 and result["invalid_count"] == 0, result


def test_the_four_real_drafts_pass_the_strict_article_qa(export):
    for article in export["articles"]:
        report = evaluate_article(article["article_id"], article["text"], article["claim"], export["evidence"])
        assert report.ok, (article["article_id"], report.findings)


def test_mutation_detection_rate_does_not_regress(export):
    """Edit every number in the real drafts by +1: QA must keep catching them.
    (Measured: body numbers 139/141 = 98.6%, all numbers incl. citation ids and
    the as-of date 301/317 = 95.0%. The as-of date has no evidence: 0/12, see Issue #11.)"""
    result = sweep(export)
    body = result["by_class"]["body"]
    assert body["detected"] / body["mutations"] >= 0.98, body
    assert result["detection_rate"] >= 0.94, result["detection_rate"]
    assert all(a["baseline_ok"] for a in result["per_article"])
    cid = result["by_class"]["citation_id"]
    assert cid["detected"] / cid["mutations"] >= 0.98, cid


def test_database_copy_matches_what_work_reported(tmp_path: Path):
    raw = gzip.decompress((HANDOFF / "data" / "admission_media_v0_2.sqlite.gz").read_bytes())
    manifest = json.loads((HANDOFF / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == manifest["gzip_uncompressed_database_sha256"]
    path = tmp_path / "v02.sqlite"
    path.write_bytes(raw)
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        rows = sum(db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables)
        assert (len(tables), rows) == (17, 121)
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM fact_claims").fetchone()[0] == 27


def test_independent_audit_has_no_failures_without_the_pdfs():
    """manifest hashes, DB integrity, reconciliation, privacy scan, values in quotes,
    export gate + QA. Source PDFs are skipped here (not in the repo) — reported as such."""
    report = ah.audit(HANDOFF)
    assert report["summary"]["failed"] == [], report["summary"]
    assert report["source_pdfs"]["status"] == "skipped"
    assert report["manifest"]["files_checked"] == 43
    assert report["privacy"]["findings"] == []
    assert report["reconciliation"]["independent_conflicts"] == []
    assert report["values_in_quotes"]["integers_checked"] == 12


# ------------------------------------------------- versioning on real data

def _current_editions(export, mutate=None):
    """The 'new edition' of each source: pages rebuilt from the quotes. `mutate`
    may rewrite page text to simulate an official change."""
    snaps = []
    for sha in sorted({e["source_pdf_sha256"] for e in export["evidence"].values()}):
        s = snapshot_from_evidence(export["evidence"], sha, sha[:8], "2026-11-01")
        if mutate:
            s.pages = mutate(s, sha)
        snaps.append(s)
    return snaps


def test_unchanged_official_documents_affect_nothing(export):
    report = impact.assess_export(export, _current_editions(export))
    assert report["summary"]["evidence_intact"] == 30
    assert report["republish_required"] == [] and report["articles_to_review"] == []
    assert all(a["status"] == "ok" for a in report["articles"].values())
    assert impact.exit_code(report, require_all_assessed=True) == 0


def test_with_no_current_edition_nothing_is_assumed_current(export):
    report = impact.assess_export(export, [])
    assert len(report["unassessed_evidence"]) == 30
    assert all(a["status"] == "unassessed" for a in report["articles"].values())


def _citing(export, eid):
    return {a["article_id"] for a in export["articles"] if f"[{eid}]" in a["text"]}


@pytest.mark.parametrize("eid", WITH_DIGITS)
def test_changing_a_number_in_any_fact_flags_that_fact_and_exactly_its_articles(export, eid):
    ev = export["evidence"][eid]
    proof = ev["proofs"][0]
    bumped = re.sub(r"\d+", lambda m: str(int(m.group()) + 1), proof["quote"], count=1)

    def mutate(snapshot, sha):
        pages = list(snapshot.pages)
        if sha == ev["source_pdf_sha256"]:
            pages[proof["page"] - 1] = pages[proof["page"] - 1].replace(proof["quote"], bumped)
        return pages

    report = impact.assess_export(export, _current_editions(export, mutate))
    assert report["evidence"][eid]["status"] == "value_change", report["evidence"][eid]
    changed = {k for k, v in report["evidence"].items() if v["status"] != "intact"}
    for article in export["articles"]:
        cited_changed = any(f"[{k}]" in article["text"] for k in changed)
        expected = "republish_required" if cited_changed else "ok"
        assert report["articles"][article["article_id"]]["status"] == expected, (eid, article["article_id"])
    assert _citing(export, eid) <= set(report["republish_required"])


def test_digit_free_quotes_are_checked_by_deletion(export):
    """Quotes with no digits cannot show a 'value change'; if the clause disappears
    the fact must be flagged and its articles must need republishing."""
    digit_free = [eid for eid, e in export["evidence"].items() if not re.search(r"\d", e["proofs"][0]["quote"])]
    assert digit_free, "expected some digit-free quotes in the real data"
    for eid in digit_free:
        ev = export["evidence"][eid]
        proof = ev["proofs"][0]

        def mutate(snapshot, sha, ev=ev, proof=proof):
            pages = list(snapshot.pages)
            if sha == ev["source_pdf_sha256"]:
                pages[proof["page"] - 1] = pages[proof["page"] - 1].replace(proof["quote"], "（この部分は改訂により削除されました）")
            return pages

        report = impact.assess_export(export, _current_editions(export, mutate))
        assert report["evidence"][eid]["status"] in {"missing", "reworded"}, (eid, report["evidence"][eid])
        assert _citing(export, eid) <= set(report["republish_required"])


def test_a_page_inserted_into_the_official_pdf_makes_every_page_reference_need_review(export):
    report = impact.assess_export(export, _current_editions(export, lambda s, sha: ["お知らせ（追加ページ）"] + list(s.pages)))
    assert report["summary"]["evidence_moved"] == 30
    assert report["republish_required"] == [] and len(report["articles_to_review"]) == 4
