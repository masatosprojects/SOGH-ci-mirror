"""M1 gate g6 SELF_TEST end-to-end: "an old edition -> a SIMULATED new edition -> versioned source -> impacted articles only -> revision candidates".

    python scripts/g6_sim_e2e.py <copy.sqlite> [--evidence-id EV-...] [--series-id ID]

The argument MUST be a DISPOSABLE COPY of a database that already carries the migration chain up to 0014 (the real pinned v06 file is never opened
by this script; copy it first, apply `additive_schema.apply(copy, confirm_disposable_copy=True)`, then run this). The script prints one JSON document.

What it does (merged g6 product code only: src/versioning/series.py, diff.py, impact.py, snapshot.py):
  1. reads the OLD edition from the copy: one source document (source_documents / source_pages) and the evidence (facts + evidence_revisions) and the
     head articles (revised_articles through article_heads, else article_versions) that cite it;
  2. builds a SIMULATED NEW edition by a deterministic textual change (the first number of one evidence quote is raised by 1). It is fictional: the new
     edition carries an explicit label page and the series title says SIMULATED; it is never an official publication;
  3. registers both as a series (migration 0014), verifies it against the stored rows;
  4. runs diff + impact and compares the result with an INDEPENDENT oracle (which evidence quotes contain the edited span);
  5. shows that the 0014 guards refuse a skipped revision number, a wrong hash, REPLACE / UPDATE / DELETE of the old edition;
  6. compares every table that existed before, row for row, before and after (only the two series tables may change).
SELF_TEST by the author of the code (Claude). Not an independent QA, not an acceptance. No real new edition exists in this run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.verify.consistency import extract_citation_ids  # noqa: E402
from src.versioning import series as sv  # noqa: E402
from src.versioning.diff import diff_snapshots  # noqa: E402
from src.versioning.impact import REPUBLISH, assess_export  # noqa: E402
from src.versioning.snapshot import SourceSnapshot, normalize, source_hash  # noqa: E402

SERIES_TABLES = ("source_document_series_editions", "series_revision_article_impacts")
LABEL_PAGE = "【SIMULATED / 架空の版】この版は M1 g6 の自己検証 (SELF_TEST) のために機械的に作った模擬版です。大学の公式発表ではありません。"
PAGE_SEP = "\n <<PAGE-BREAK>> \n"  # PDF page text can hold any control character (FF, RS, ...), so a marker that is asserted absent


def _tables(db: sqlite3.Connection) -> list[str]:
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]


def table_digests(db: sqlite3.Connection, skip: tuple[str, ...] = ()) -> dict[str, dict]:
    """Row count and SHA-256 over the full ordered content of every table (a row-for-row fingerprint)."""
    out = {}
    for t in _tables(db):
        if t in skip:
            continue
        h, n = hashlib.sha256(), 0
        try:
            cur = db.execute(f'SELECT * FROM "{t}" ORDER BY rowid')
        except sqlite3.OperationalError:  # WITHOUT ROWID table
            cur = db.execute(f'SELECT * FROM "{t}"')
        for row in cur:
            h.update(json.dumps(row, ensure_ascii=False, default=repr).encode("utf-8") + b"\n")
            n += 1
        out[t] = {"rows": n, "sha256": h.hexdigest()}
    return out


def _load(db: sqlite3.Connection) -> dict:
    evidence: dict[str, dict] = {}
    for (rj,) in db.execute("SELECT record_json FROM evidence_revisions"):
        j = json.loads(rj)
        evidence[j["evidence_id"]] = j
    for (rj,) in db.execute("SELECT record_json FROM facts"):
        j = json.loads(rj)
        evidence.setdefault(j["evidence_id"], j)
    articles: list[dict] = []
    heads = db.execute("SELECT base_article_id, article_id FROM article_heads ORDER BY base_article_id").fetchall()
    if heads:
        for _base, aid in heads:
            row = db.execute("SELECT record_json FROM revised_articles WHERE article_id=?", (aid,)).fetchone()
            articles.append({"article_id": aid, "text": json.loads(row[0])["text"]})
    else:
        for aid, body in db.execute("SELECT article_id, body FROM article_versions ORDER BY article_id"):
            articles.append({"article_id": aid, "text": body})
    sources = {}
    for sha, url, retrieved in db.execute("SELECT sha256, url, retrieved_at FROM source_documents ORDER BY sha256"):
        rows = db.execute("SELECT page, text FROM source_pages WHERE source_sha256=? ORDER BY page", (sha,)).fetchall()
        if rows and [r[0] for r in rows] == list(range(1, len(rows) + 1)):
            sources[sha] = {"url": url, "retrieved_at": retrieved, "pages": [r[1] for r in rows]}
    return {"evidence": evidence, "articles": articles, "sources": sources}


def _pick_target(data: dict, evidence_id: str | None) -> dict:
    """Deterministic mutation target: an evidence quote with a digit that occurs exactly once in the raw text of its page."""
    cited = set().union(*(extract_citation_ids(a["text"]) for a in data["articles"])) if data["articles"] else set()
    ids = [evidence_id] if evidence_id else sorted(cited)
    for eid in ids:
        ev = data["evidence"].get(eid)
        sha = source_hash(ev) if ev else None
        if not ev or sha not in data["sources"]:
            continue
        pages = data["sources"][sha]["pages"]
        for proof in ev.get("proofs", []):
            q, pg = proof.get("quote", ""), int(proof.get("page", 0))
            m = re.search(r"[0-9]+", q)
            if m and 1 <= pg <= len(pages) and pages[pg - 1].count(q) == 1:
                new_q = q[: m.start()] + str(int(m.group()) + 1) + q[m.end():]
                return {"evidence_id": eid, "source_sha256": sha, "page": pg, "old_quote": q, "new_quote": new_q,
                        "old_number": m.group(), "new_number": str(int(m.group()) + 1),
                        "span": q[max(0, m.start() - 4): m.end() + 4]}
    raise RuntimeError("no evidence quote with a unique digit-bearing location was found: nothing to simulate on")


def _guards(db: sqlite3.Connection, sid: str, rev_ids: list[str], new_text: str) -> list[dict]:
    """Each statement MUST be refused by a 0014 trigger; the outcome (and the message) is recorded."""
    ok_sha = hashlib.sha256(b"x").hexdigest()
    last = rev_ids[-1]
    uni, title = db.execute("SELECT university, document_title FROM source_document_series_editions WHERE edition_id=?", (rev_ids[0],)).fetchone()
    ins = ("INSERT INTO source_document_series_editions(edition_id,series_id,university,document_title,rev_number,sha256_hash,content_text,supersedes_id,is_frozen) "
           "VALUES (?,?,?,?,?,?,?,?,0)")
    cases = [
        ("skipped_revision_number", ins, (f"{sid}_rev9", sid, uni, title, 9, ok_sha, "x", last)),
        ("wrong_hash", ins, (f"{sid}_rev{len(rev_ids) + 1}", sid, uni, title, len(rev_ids) + 1, "deadbeef", "x", last)),
        ("insert_or_replace_old_edition", ins.replace("INSERT INTO", "INSERT OR REPLACE INTO"), (rev_ids[0], sid, uni, title, 1, ok_sha, "x", None)),
        ("update_old_edition_content", "UPDATE source_document_series_editions SET content_text='tampered' WHERE edition_id=?", (rev_ids[0],)),
        ("update_old_edition_hash", "UPDATE source_document_series_editions SET sha256_hash=? WHERE edition_id=?", (ok_sha, rev_ids[0])),
        ("delete_old_edition", "DELETE FROM source_document_series_editions WHERE edition_id=?", (rev_ids[0],)),
        ("delete_new_edition", "DELETE FROM source_document_series_editions WHERE edition_id=?", (last,)),
    ]
    out = []
    for name, sql, args in cases:
        try:
            db.execute(sql, args)
            db.rollback()
            out.append({"case": name, "refused": False, "message": None})
        except sqlite3.DatabaseError as exc:
            db.rollback()
            out.append({"case": name, "refused": True, "message": str(exc)})
    return out


def run(copy_path: str | Path, evidence_id: str | None = None, series_id: str | None = None) -> dict:
    copy_path = Path(copy_path)
    with closing(sqlite3.connect(copy_path)) as db:
        sv.register_series_connection_guards(db)  # DDL-free: registers the connection function only; this script never creates a table
        missing = [t for t in SERIES_TABLES if t not in _tables(db)]
        if missing:
            raise SystemExit(f"{copy_path} is not migrated to 0014 (missing {missing}); apply additive_schema.apply on a disposable copy first")
        before = table_digests(db, skip=SERIES_TABLES)
        series_rows_before = {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in SERIES_TABLES}
        data = _load(db)
        target = _pick_target(data, evidence_id)
        sha, src = target["source_sha256"], data["sources"][target["source_sha256"]]

        # 1-2. old edition and the SIMULATED new edition
        old_pages = list(src["pages"])
        new_pages = list(old_pages)
        new_pages[target["page"] - 1] = old_pages[target["page"] - 1].replace(target["old_quote"], target["new_quote"], 1)
        new_pages.append(LABEL_PAGE)
        old_text, new_text = PAGE_SEP.join(old_pages), PAGE_SEP.join(new_pages)
        assert not any(PAGE_SEP in p for p in old_pages), "page separator occurs in a page"
        assert old_text.split(PAGE_SEP) == old_pages and new_text.split(PAGE_SEP) == new_pages

        # 3. series (0014)
        sid = series_id or f"SIMULATED-g6-e2e-{sha[:8]}"
        university = next((e.get("university") for e in data["evidence"].values() if source_hash(e) == sha and e.get("university")), None) or "(university not recorded)"
        title = f"[SIMULATED NEW EDITION - FICTIONAL, NOT AN OFFICIAL PUBLICATION] source {sha[:12]}"
        series = sv.create_series(sid, university, title, old_text)
        rev2 = sv.append_revision(series, new_text, metadata={"label": "SIMULATED", "official": False, "reason": "g6 SELF_TEST deterministic edit"})
        inserted = sv.persist_series(db, series)
        lineage_ok, lineage_errors = sv.verify_series_lineage(series)
        rows_ok, rows_errors = sv.verify_series_against_rows(db, series)
        rev_ids = [e.edition_id for e in series.editions]

        # 4. diff + impact
        old_snap = SourceSnapshot(f"src-{sha[:8]}", src["url"], sha, src["retrieved_at"], old_pages)
        new_snap = SourceSnapshot(f"src-{sha[:8]}", src["url"], rev2.sha256_hash, src["retrieved_at"], new_pages, supersedes=[sha],
                                  edition_note="SIMULATED / fictional edition (g6 SELF_TEST); not an official publication")
        others = [SourceSnapshot(f"src-{s[:8]}", v["url"], s, v["retrieved_at"], v["pages"]) for s, v in data["sources"].items() if s != sha]
        diff = diff_snapshots(old_snap, new_snap)
        report = assess_export({"evidence": data["evidence"], "articles": data["articles"]}, [new_snap, *others], [old_snap])
        ev_status = {k: v["status"] for k, v in report["evidence"].items()}

        def cites(a): return sorted(extract_citation_ids(a["text"]))
        per_article = {}
        for a in data["articles"]:
            c = cites(a)
            republish = [e for e in c if ev_status.get(e) in REPUBLISH]
            neighbour = [e for e in c if ev_status.get(e) in ("page_changed", "moved")]
            unassessed = [e for e in c if ev_status.get(e, "unassessed") == "unassessed"]
            per_article[a["article_id"]] = {
                "class": "revision_candidate" if republish else ("review_same_page" if neighbour else "not_flagged"),
                "changed_evidence": republish, "same_page_evidence": neighbour, "cited": len(c), "cited_unassessed": len(unassessed),
                "product_status": report["articles"][a["article_id"]]["status"]}
        # independent oracle: evidence whose quote on the edited page contains the edited span; articles citing any of them
        oracle_ev = sorted(eid for eid, ev in data["evidence"].items() if source_hash(ev) == sha and any(
            int(p.get("page", 0)) == target["page"] and target["span"] in p.get("quote", "") for p in ev.get("proofs", [])))
        oracle_articles = sorted(a["article_id"] for a in data["articles"] if set(cites(a)) & set(oracle_ev))
        flagged_ev = sorted(e for e, s in ev_status.items() if s in REPUBLISH)
        flagged_articles = sorted(k for k, v in per_article.items() if v["class"] == "revision_candidate")
        impacts = []
        for aid in flagged_articles:
            for eid in per_article[aid]["changed_evidence"]:
                iid = f"IMP-{len(impacts) + 1:03d}"
                sv.record_revision_impact(db, iid, sid, rev_ids[0], rev_ids[1], eid, aid)
                impacts.append({"impact_id": iid, "article_id": aid, "evidence_id": eid})
        impact_rows = db.execute("SELECT count(*), count(DISTINCT article_id) FROM series_revision_article_impacts").fetchone()

        # 5. guards
        guard_before = db.execute("SELECT count(*), sum(length(content_text)) FROM source_document_series_editions").fetchone()
        guards = _guards(db, sid, rev_ids, new_text)
        guard_after = db.execute("SELECT count(*), sum(length(content_text)) FROM source_document_series_editions").fetchone()
        still_ok, still_errors = sv.verify_series_against_rows(db, series)

        # 6. old rows unchanged
        after = table_digests(db, skip=SERIES_TABLES)

    n_art = len(data["articles"])
    classes = [v["class"] for v in per_article.values()]
    checks = {
        "series_lineage_ok": lineage_ok, "series_verified_against_rows": rows_ok, "two_editions_persisted": inserted == 2,
        "diff_has_exactly_one_value_change": len(diff.value_changes) == 1,
        "flagged_evidence_equals_oracle": flagged_ev == oracle_ev,
        "flagged_articles_equal_oracle": flagged_articles == oracle_articles,
        "at_least_one_article_flagged": len(flagged_articles) >= 1,
        "at_least_one_article_not_flagged": len(flagged_articles) < n_art,
        "every_unflagged_article_cites_no_changed_evidence": all(not set(cites(a)) & set(flagged_ev) for a in data["articles"] if a["article_id"] not in flagged_articles),
        "all_guards_refused": all(g["refused"] for g in guards), "guards_changed_no_row": tuple(guard_before) == tuple(guard_after),
        "series_still_verifies_after_guard_attempts": still_ok,
        "old_tables_unchanged_row_for_row": before == after,
        "only_series_tables_grew": series_rows_before == {"source_document_series_editions": 0, "series_revision_article_impacts": 0},
        "impact_rows_equal_flagged_pairs": impact_rows[0] == len(impacts) and impact_rows[1] == len(flagged_articles),
    }
    return {
        "kind": "SELF_TEST (author: Claude); SIMULATED new edition; not an acceptance; not an independent QA",
        "copy": str(copy_path), "series_id": sid, "editions": [{"edition_id": e.edition_id, "rev": e.rev_number, "sha256": e.sha256_hash, "chars": len(e.content_text)} for e in series.editions],
        "old_edition": {"source_sha256": sha, "url": src["url"], "pages": len(old_pages)}, "new_edition": {"label": "SIMULATED", "pages": len(new_pages), "sha256": rev2.sha256_hash},
        "simulated_change": {k: target[k] for k in ("evidence_id", "page", "old_number", "new_number")},
        "series_verification": {"lineage": [lineage_ok, lineage_errors], "against_rows": [rows_ok, rows_errors], "persisted_rows": inserted},
        "diff": diff.to_dict()["summary"] | {"value_change_old": [c.old_values for c in diff.value_changes], "value_change_new": [c.new_values for c in diff.value_changes]},
        "impact": {"summary": report["summary"], "evidence_flagged_republish": flagged_ev, "oracle_evidence": oracle_ev,
                   "articles_total": n_art, "articles_flagged": flagged_articles, "oracle_articles": oracle_articles,
                   "articles_review_same_page": sorted(k for k, v in per_article.items() if v["class"] == "review_same_page"),
                   "articles_not_flagged": sorted(k for k, v in per_article.items() if v["class"] == "not_flagged"),
                   "class_counts": {c: classes.count(c) for c in ("revision_candidate", "review_same_page", "not_flagged")},
                   "per_article": per_article, "recorded_impacts": impacts, "impact_table_rows": impact_rows[0]},
        "guards": guards, "guard_row_count_before_after": [list(guard_before), list(guard_after)],
        "old_tables": {"count": len(before), "unchanged": before == after, "rows_total": sum(v["rows"] for v in before.values()),
                       "changed_tables": sorted(t for t in before if before[t] != after.get(t))},
        "series_tables_rows_after": {"source_document_series_editions": inserted, "series_revision_article_impacts": impact_rows[0]},
        "checks": checks, "all_checks_pass": all(checks.values()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("copy", type=Path)
    ap.add_argument("--evidence-id", default=None)
    ap.add_argument("--series-id", default=None)
    a = ap.parse_args(argv)
    result = run(a.copy, a.evidence_id, a.series_id)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the JSON carries Japanese text; do not depend on the console code page
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
