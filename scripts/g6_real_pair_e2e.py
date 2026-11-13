"""M1 gate g6 SELF_TEST on the first REAL pair of editions: previous edition (PDF) -> stored current edition -> versioned source -> impacted articles.

    python scripts/g6_real_pair_e2e.py <migrated-disposable-copy.sqlite> <old-edition.pdf> [--new-sha-prefix 49cb4d7d] [--series-id ID]
    python scripts/g6_real_pair_e2e.py <copy.sqlite> --old-pages-json pages.json   (a JSON list of page texts instead of a PDF; used by the tests)

The first argument MUST be a DISPOSABLE COPY already migrated to 0014 (never the real pinned file). The PDF is only read.
The stored source whose sha256 starts with --new-sha-prefix is the NEW edition (rev 2): its source_pages and its evidence (facts) were taken from it.
The OLD edition (rev 1) is the PDF: PyMuPDF raw page text (stored raw, compared after NFKC + whitespace removal, as scripts/g2_full_source_check.py does).

Direction: the stored evidence comes from the NEW edition, so the impact analysis asks "which cited statements are NOT in the previous edition as they stand"
(the old edition is handed to src/versioning/impact.py as the edition to check against; the stored new edition is the "old snapshot" of that call). The
INDEPENDENT oracle does a plain string search of every proof quote in the old pages; a quote absent from every old page = the cited text CHANGED between editions.
Output: one JSON document (UTF-8). Original document text is never written to git: the JSON carries counts, hashes and short excerpts (<= 30 characters) only.
SELF_TEST by the author (Claude). Not an independent QA, not an acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.g6_sim_e2e import PAGE_SEP, SERIES_TABLES, _guards, _load, _tables, table_digests  # noqa: E402
from src.verify.consistency import extract_citation_ids  # noqa: E402
from src.versioning import series as sv  # noqa: E402
from src.versioning.diff import diff_snapshots  # noqa: E402
from src.versioning.impact import REPUBLISH, assess_export  # noqa: E402
from src.versioning.snapshot import SourceSnapshot, source_hash  # noqa: E402

EXCERPT = 30  # characters; an excerpt of original text is never longer


def norm(t: str) -> str:
    """Oracle's own normalisation (same rule as g2_full_source_check.py): NFKC, all whitespace removed."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", t or ""))


def excerpt(t: str, around: int | None = None) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    start = 0 if around is None else max(0, min(around, len(t)) - EXCERPT // 2)
    return t[start:start + EXCERPT]


def old_vs_new(quote: str, old_page_norm: str) -> dict:
    """Locate the window of the old page closest to the (normalised) new quote and return both short excerpts around the first difference."""
    import difflib
    q, n = norm(quote), len(norm(quote))
    if not q or not old_page_norm:
        return {"old": None, "new": excerpt(q)}
    best, best_i = -1.0, 0
    for i in range(max(1, len(old_page_norm) - n + 1)):
        r = difflib.SequenceMatcher(None, old_page_norm[i:i + n], q, autojunk=False).ratio()
        if r > best:
            best, best_i = r, i
    win = old_page_norm[best_i:best_i + n]
    ops = [o for o in difflib.SequenceMatcher(None, win, q, autojunk=False).get_opcodes() if o[0] != "equal"]
    i1, j1 = (ops[0][1], ops[0][3]) if ops else (0, 0)
    return {"old": win[max(0, i1 - 8):][:EXCERPT], "new": q[max(0, j1 - 8):][:EXCERPT], "window_similarity": round(best, 3)}


def extract_pdf_pages(pdf: Path) -> list[str]:
    import fitz  # PyMuPDF, imported lazily: the tests and the oracle do not need it
    with fitz.open(pdf) as doc:
        return [p.get_text() for p in doc]


def oracle_proofs(evidence: dict[str, dict], new_sha: str, old_pages: list[str]) -> dict[str, list[dict]]:
    """Plain string search of every proof quote of the new edition's evidence in the old edition."""
    old_n = [norm(p) for p in old_pages]
    out: dict[str, list[dict]] = {}
    for eid, ev in sorted(evidence.items()):
        if source_hash(ev) != new_sha:
            continue
        rows = []
        for proof in ev.get("proofs", []):
            q, pg = norm(proof.get("quote", "")), int(proof.get("page", 0))
            same = 1 <= pg <= len(old_n) and bool(q) and q in old_n[pg - 1]
            elsewhere = [i + 1 for i, p in enumerate(old_n) if q and q in p and i + 1 != pg]
            state = "unchanged" if same else ("moved" if elsewhere else "changed")
            rows.append({"page": pg, "state": state, "old_pages": elsewhere, "quote": proof.get("quote", "")})
        out[eid] = rows
    return out


def run(copy_path: str | Path, old_pages: list[str], new_sha_prefix: str, old_sha: str | None = None, old_url: str = "(old edition file)",
        series_id: str | None = None) -> dict:
    copy_path = Path(copy_path)
    with closing(sqlite3.connect(copy_path)) as db:
        sv.register_series_connection_guards(db)
        missing = [t for t in SERIES_TABLES if t not in _tables(db)]
        if missing:
            raise SystemExit(f"{copy_path} is not migrated to 0014 (missing {missing}); apply additive_schema.apply on a disposable copy first")
        before = table_digests(db, skip=SERIES_TABLES)
        series_before = {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in SERIES_TABLES}
        data = _load(db)
        cands = [s for s in data["sources"] if s.startswith(new_sha_prefix)]
        if len(cands) != 1:
            raise SystemExit(f"--new-sha-prefix {new_sha_prefix!r} matches {len(cands)} stored sources with pages (need exactly 1)")
        new_sha = cands[0]
        src = data["sources"][new_sha]
        new_pages = list(src["pages"])
        old_pages = list(old_pages)
        if not old_pages:
            raise SystemExit("the old edition has no pages")
        old_sha = old_sha or hashlib.sha256("\n".join(old_pages).encode("utf-8")).hexdigest()
        if old_sha == new_sha:
            raise SystemExit("the old and the new edition have the same sha256: not a pair")
        old_text, new_text = PAGE_SEP.join(old_pages), PAGE_SEP.join(new_pages)
        if old_text == new_text:
            raise SystemExit("the old and the new edition have identical text: no revision to register")
        assert not any(PAGE_SEP in p for p in old_pages + new_pages), "page separator occurs in a page"

        # 1-2. series (0014): rev 1 = old (PDF), rev 2 = stored new edition
        sid = series_id or f"REAL-g6-pair-{new_sha[:8]}"
        university = next((e.get("university") for e in data["evidence"].values() if source_hash(e) == new_sha and e.get("university")), None) or "(university not recorded)"
        series = sv.create_series(sid, university, f"[REAL EDITIONS] previous edition {old_sha[:12]} -> stored edition {new_sha[:12]}", old_text)
        rev2 = sv.append_revision(series, new_text, metadata={"label": "REAL", "official": True, "reason": "previous edition -> stored current edition"})
        inserted = sv.persist_series(db, series)
        lineage_ok, lineage_errors = sv.verify_series_lineage(series)
        rows_ok, rows_errors = sv.verify_series_against_rows(db, series)
        rev_ids = [e.edition_id for e in series.editions]
        contents_ok = series.editions[0].content_text.split(PAGE_SEP) == old_pages and series.editions[1].content_text.split(PAGE_SEP) == new_pages

        # 3. diff + impact (product code)
        new_snap = SourceSnapshot(f"src-{new_sha[:8]}", src["url"], new_sha, src["retrieved_at"], new_pages)
        old_snap = SourceSnapshot(f"src-{new_sha[:8]}", old_url, old_sha, src["retrieved_at"], old_pages, supersedes=[new_sha],
                                  edition_note="previous edition (back-check target)")
        others = [SourceSnapshot(f"src-{s[:8]}", v["url"], s, v["retrieved_at"], v["pages"]) for s, v in data["sources"].items() if s != new_sha]
        diff = diff_snapshots(old_snap, new_snap)  # chronological: old -> new
        export = {"evidence": data["evidence"], "articles": data["articles"]}
        report = assess_export(export, [old_snap, *others], [new_snap])
        self_report = assess_export(export, [new_snap, *others])  # sanity: the stored evidence against its own edition
        ev_status = {k: v["status"] for k, v in report["evidence"].items()}
        new_ev_ids = sorted(e for e, ev in data["evidence"].items() if source_hash(ev) == new_sha)
        self_not_intact = sorted(e for e in new_ev_ids if self_report["evidence"][e]["status"] not in ("intact",))

        def cites(a): return sorted(extract_citation_ids(a["text"]))
        per_article = {}
        for a in data["articles"]:
            c = cites(a)
            rep = [e for e in c if ev_status.get(e) in REPUBLISH]
            nb = [e for e in c if ev_status.get(e) in ("page_changed", "moved")]
            per_article[a["article_id"]] = {
                "class": "revision_candidate" if rep else ("review_same_page" if nb else "not_flagged"), "changed_evidence": rep,
                "same_page_or_moved_evidence": nb, "cited": len(c), "cited_unassessed": len([e for e in c if ev_status.get(e, "unassessed") == "unassessed"]),
                "product_status": report["articles"][a["article_id"]]["status"]}
        flagged_ev = sorted(e for e, s in ev_status.items() if s in REPUBLISH)
        flagged_articles = sorted(k for k, v in per_article.items() if v["class"] == "revision_candidate")

        # 4. independent oracle
        proofs = oracle_proofs(data["evidence"], new_sha, old_pages)
        oracle_ev = sorted(e for e, rows in proofs.items() if any(r["state"] == "changed" for r in rows))
        oracle_moved = sorted(e for e, rows in proofs.items() if e not in oracle_ev and any(r["state"] == "moved" for r in rows))
        n_proofs = sum(len(r) for r in proofs.values())
        n_changed = sum(r["state"] == "changed" for rows in proofs.values() for r in rows)
        proof_mismatch = []
        for e, rows in proofs.items():
            pp = report["evidence"][e].get("proofs", [])
            if len(pp) != len(rows):
                proof_mismatch.append({"evidence_id": e, "why": "proof count differs"})
                continue
            for r, p in zip(rows, pp):
                if (r["state"] == "changed") != (p["status"] in REPUBLISH):
                    proof_mismatch.append({"evidence_id": e, "page": r["page"], "oracle": r["state"], "product": p["status"]})
        # article relation: (a) text citations of the head (what the product reads), (b) the article_evidence table of the clone (independent)
        rel: dict[str, set[str]] = {}
        heads = {aid: base for base, aid in db.execute("SELECT base_article_id, article_id FROM article_heads")}
        for a in data["articles"]:
            ids = {r[0] for r in db.execute("SELECT evidence_id FROM article_evidence WHERE article_id=?", (heads.get(a["article_id"], a["article_id"]),))}
            rel[a["article_id"]] = ids or {r[0] for r in db.execute("SELECT evidence_id FROM article_evidence WHERE article_id=?", (a["article_id"],))}
        oracle_articles_text = sorted(a["article_id"] for a in data["articles"] if set(cites(a)) & set(oracle_ev))
        oracle_articles_rel = sorted(k for k, v in rel.items() if v & set(oracle_ev))
        relation_vs_text = {a["article_id"]: {"only_in_text": sorted(set(cites(a)) - rel[a["article_id"]]), "only_in_table": sorted(rel[a["article_id"]] - set(cites(a)))}
                            for a in data["articles"] if set(cites(a)) != rel[a["article_id"]]}

        impacts = []
        for aid in flagged_articles:
            for eid in per_article[aid]["changed_evidence"]:
                iid = f"IMP-{len(impacts) + 1:03d}"
                sv.record_revision_impact(db, iid, sid, rev_ids[0], rev_ids[1], eid, aid)
                impacts.append({"impact_id": iid, "article_id": aid, "evidence_id": eid})
        impact_rows = db.execute("SELECT count(*), count(DISTINCT article_id) FROM series_revision_article_impacts").fetchone()

        # 5. real changes (short excerpts only)
        real_changes = []
        for e in oracle_ev:
            ev = data["evidence"][e]
            for r, p in zip(proofs[e], report["evidence"][e].get("proofs", [])):
                if r["state"] != "changed":
                    continue
                real_changes.append({"evidence_id": e, "fact_key": ev.get("fact_key"), "new_page": r["page"],
                                     "product_status": p["status"], "old_page_of_match": p.get("page"),
                                     **{f"{k}_excerpt": v for k, v in old_vs_new(r["quote"], norm(old_pages[(p.get("page") or r["page"]) - 1])).items() if k in ("old", "new")}})
        diff_lines = [{"old_page": c.old_page, "new_page": c.new_page, "kind": c.kind, "value_change": c.value_change,
                       "old_excerpt": excerpt(c.old), "new_excerpt": excerpt(c.new), "old_values": c.old_values[:10], "new_values": c.new_values[:10]}
                      for c in diff.changes]

        # 6. guards
        guard_before = db.execute("SELECT count(*), sum(length(content_text)) FROM source_document_series_editions").fetchone()
        guards = _guards(db, sid, rev_ids, new_text)
        guard_after = db.execute("SELECT count(*), sum(length(content_text)) FROM source_document_series_editions").fetchone()
        still_ok, _ = sv.verify_series_against_rows(db, series)
        # 7. old rows
        after = table_digests(db, skip=SERIES_TABLES)

    n_art = len(data["articles"])
    classes = [v["class"] for v in per_article.values()]
    checks = {
        "series_lineage_ok": lineage_ok, "series_verified_against_rows": rows_ok, "two_editions_persisted": inserted == 2, "series_contents_split_back_to_the_pages": contents_ok,
        "stored_evidence_intact_against_its_own_edition": not self_not_intact,
        "flagged_evidence_equals_oracle": flagged_ev == oracle_ev, "proof_level_equals_oracle": not proof_mismatch,
        "flagged_articles_equal_oracle_by_text_citations": flagged_articles == oracle_articles_text,
        "flagged_articles_equal_oracle_by_article_evidence_table": flagged_articles == oracle_articles_rel,
        "every_unflagged_article_cites_no_changed_evidence": all(not set(cites(a)) & set(oracle_ev) for a in data["articles"] if a["article_id"] not in flagged_articles),
        "all_guards_refused": all(g["refused"] for g in guards), "guards_changed_no_row": tuple(guard_before) == tuple(guard_after),
        "series_still_verifies_after_guard_attempts": still_ok,
        "old_tables_unchanged_row_for_row": before == after,
        "only_series_tables_grew": series_before == {"source_document_series_editions": 0, "series_revision_article_impacts": 0},
        "impact_rows_equal_flagged_pairs": impact_rows[0] == len(impacts) and impact_rows[1] == len(flagged_articles),
    }
    return {
        "kind": "SELF_TEST (author: Claude); 2 real editions of one document; not an acceptance; not an independent QA; oracle is string-based",
        "copy": str(copy_path), "series_id": sid,
        "editions": [{"edition_id": e.edition_id, "rev": e.rev_number, "sha256": e.sha256_hash, "chars": len(e.content_text)} for e in series.editions],
        "old_edition": {"file_sha256": old_sha, "pages": len(old_pages), "url": old_url},
        "new_edition": {"source_sha256": new_sha, "pages": len(new_pages), "url": src["url"], "series_hash": rev2.sha256_hash},
        "diff": diff.to_dict()["summary"] | {"pages_moved_list": diff.to_dict()["pages_moved"]},
        "diff_changes": diff_lines,
        "oracle": {"new_edition_evidence": len(proofs), "proofs": n_proofs, "proofs_unchanged": sum(r["state"] == "unchanged" for v in proofs.values() for r in v),
                   "proofs_moved": sum(r["state"] == "moved" for v in proofs.values() for r in v), "proofs_changed": n_changed,
                   "evidence_changed": oracle_ev, "evidence_moved_only": oracle_moved, "articles_by_text": oracle_articles_text, "articles_by_table": oracle_articles_rel},
        "real_changes": real_changes,
        "impact": {"summary": report["summary"], "evidence_flagged_republish": flagged_ev, "proof_mismatches": proof_mismatch,
                   "articles_total": n_art, "articles_flagged": flagged_articles,
                   "articles_review_same_page": sorted(k for k, v in per_article.items() if v["class"] == "review_same_page"),
                   "articles_not_flagged": sorted(k for k, v in per_article.items() if v["class"] == "not_flagged"),
                   "class_counts": {c: classes.count(c) for c in ("revision_candidate", "review_same_page", "not_flagged")},
                   "per_article": per_article, "relation_text_vs_table_differences": relation_vs_text, "self_check_not_intact": self_not_intact,
                   "recorded_impacts": impacts, "impact_table_rows": impact_rows[0]},
        "guards": guards, "guard_row_count_before_after": [list(guard_before), list(guard_after)],
        "old_tables": {"count": len(before), "unchanged": before == after, "rows_total": sum(v["rows"] for v in before.values()),
                       "changed_tables": sorted(t for t in before if before[t] != after.get(t))},
        "series_tables_rows_after": {"source_document_series_editions": inserted, "series_revision_article_impacts": impact_rows[0]},
        "checks": checks, "all_checks_pass": all(checks.values()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("copy", type=Path)
    ap.add_argument("old_pdf", type=Path, nargs="?", default=None)
    ap.add_argument("--old-pages-json", type=Path, default=None)
    ap.add_argument("--new-sha-prefix", default="49cb4d7d")
    ap.add_argument("--series-id", default=None)
    ap.add_argument("--old-url", default=None)
    a = ap.parse_args(argv)
    if (a.old_pdf is None) == (a.old_pages_json is None):
        ap.error("give exactly one of: the old edition PDF, or --old-pages-json")
    if not a.copy.is_file():
        ap.error(f"{a.copy} does not exist")
    if a.old_pdf is not None:
        if not a.old_pdf.is_file():
            ap.error(f"{a.old_pdf} does not exist")
        pages, sha = extract_pdf_pages(a.old_pdf), hashlib.sha256(a.old_pdf.read_bytes()).hexdigest()
    else:
        pages, sha = json.loads(a.old_pages_json.read_text(encoding="utf-8")), None
    result = run(a.copy, pages, a.new_sha_prefix, sha, a.old_url or (a.old_pdf.name if a.old_pdf else a.old_pages_json.name), a.series_id)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
