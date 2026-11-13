"""Reference mapping: a Work export / whole view -> a database of the delivered flat schema (v0.5), for audit.

It exists to answer ONE question without Work's real database: "if the data we have were stored in the delivered schema, would the
acceptance contract hold?" The result is a database built FROM repository samples (target kind `repository_sample`), not Work's database.

What the exports do not contain is not invented silently: `exam_year` is not in an export, so it is set to the entry year minus one
(the usual case) and the cycle is listed in `assumptions`; pages are rebuilt from the proof quotes only (the original text is not here).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

SCHEMA_SQL = Path(__file__).resolve().parents[2] / "research" / "inbox" / "work-updates-v2" / "database-schema.sql"
_CITE = re.compile(r"\[(EV-[A-Za-z0-9_\-]+)\]")


def _j(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def case_id_of(rec: dict[str, Any]) -> str:
    key = _j([rec.get("university"), rec.get("faculty"), rec.get("department"), rec.get("admission_method"), rec.get("fiscal_year")])
    return "case-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def load(db_path: Path, exports: list[dict[str, Any]]) -> dict[str, Any]:
    """Write every evidence record and article of `exports` into a new database. Returns what was assumed or skipped."""
    assumptions: list[str] = []
    skipped: list[str] = []
    with closing(sqlite3.connect(db_path)) as db:
        db.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
        db.execute("INSERT INTO schema_versions VALUES ('reference-load-from-export')")
        cycles: dict[str, dict[str, Any]] = {}
        evidence: dict[str, dict[str, Any]] = {}
        for export in exports:
            for eid, rec in export["evidence"].items():
                if eid in evidence:
                    if evidence[eid] != rec:
                        skipped.append(f"{eid}: same id with different content in another export")
                    continue
                evidence[eid] = rec
        pages: dict[tuple[str, int], list[str]] = {}
        revisions: dict[str, dict[str, Any]] = {}
        for eid, rec in evidence.items():
            cid = case_id_of(rec)
            if cid not in cycles:
                cycles[cid] = rec
                db.execute("INSERT INTO admission_cycles VALUES (?,?,?,?,?,?,?)", (cid, rec["university"], rec["faculty"], rec.get("department"),
                                                                                    rec["admission_method"], rec["fiscal_year"], rec["fiscal_year"] - 1))
                assumptions.append(f"{cid}: exam_year not in the export, set to entry year - 1")
            sha = rec.get("source_sha256") or rec.get("source_pdf_sha256")
            if not sha:
                skipped.append(f"{eid}: no source hash")
                continue
            db.execute("INSERT OR IGNORE INTO source_documents VALUES (?,?,?,?,?)", (sha, rec.get("source_url", ""), "", rec.get("retrieved_at", ""), "not_cleared_for_publication"))
            for p in rec.get("proofs", []):
                if isinstance(p, dict) and isinstance(p.get("page"), int) and p.get("quote"):
                    quotes = pages.setdefault((sha, p["page"]), [])
                    if p["quote"] not in quotes:
                        quotes.append(p["quote"])
            if rec.get("logical_id"):  # a notice / correction: stored as a revision of a logical fact, not as an initial fact
                revisions[eid] = {**rec, "_case": cid, "_sha": sha}
                continue
            try:
                db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?)", (eid, cid, sha, rec["fact_key"], _j(rec.get("value")), _j({**rec, "key": rec["fact_key"]}),
                                                                      "source_checked_for_saved_version"))
            except sqlite3.IntegrityError as exc:
                skipped.append(f"{eid}: {exc}")  # e.g. two facts of one key from one source (UNIQUE(case_id, source_sha256, fact_key))
        for (sha, page), quotes in pages.items():
            text = "\n".join(quotes) + "\n"
            db.execute("INSERT OR IGNORE INTO source_pages VALUES (?,?,?,?)", (sha, page, text, hashlib.sha256(text.encode()).hexdigest()))
        parents = {r.get("parent_evidence_id") for r in revisions.values()}
        for eid, r in revisions.items():
            rec = {k: v for k, v in r.items() if not k.startswith("_")}
            db.execute("INSERT INTO evidence_revisions VALUES (?,?,?,?,?,?,?)", (eid, r["logical_id"], r["_case"], r["fact_key"], r["_sha"], r.get("parent_evidence_id"), _j(rec)))
        heads: dict[str, list[str]] = {}
        for eid, r in revisions.items():
            if eid not in parents:
                heads.setdefault(r["logical_id"], []).append(eid)
        for logical, ids in heads.items():
            if len(ids) == 1:
                db.execute("INSERT INTO evidence_heads VALUES (?,?)", (logical, ids[0]))
            else:
                skipped.append(f"{logical}: {len(ids)} candidate heads, none chosen")
        base_ids = set()
        for export in exports:
            for a in export["articles"]:
                if ":revision:" not in a["article_id"]:
                    base_ids.add(a["article_id"])
        seen: set[str] = set()
        for export in exports:
            for a in export["articles"]:
                aid = a["article_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                cited = sorted(set(_CITE.findall(a["text"])))
                known = [c for c in cited if c in evidence]
                cases = {case_id_of(evidence[c]) for c in known}
                if ":revision:" in aid:
                    base = aid.split(":revision:")[0]
                    if base in base_ids and len(cases) == 1:
                        db.execute("INSERT INTO update_batches VALUES (?,?,?,?,?,?,?,?)", (f"batch-{aid[-16:]}", "reference-load", "approved", "2026-11-01", "{}", "{}", "-", _j({"success": True, "batch_input_sha": "reference-load"})))
                        db.execute("INSERT INTO update_events(batch_id,event,created_at,detail_json) VALUES (?,?,?,?)", (f"batch-{aid[-16:]}", "approved", "2026-11-01", "{}"))
                        db.execute("INSERT INTO revised_articles VALUES (?,?,?,?)", (aid, base, f"batch-{aid[-16:]}", _j({**a, "publish_allowed": False})))
                        db.execute("INSERT OR REPLACE INTO article_heads VALUES (?,?)", (base, aid))
                    else:
                        skipped.append(f"{aid[-40:]}: revision whose base is not in the loaded data")
                    continue
                case = next(iter(cases)) if len(cases) == 1 else None
                if case is None:
                    skipped.append(f"{aid[-40:]}: its citations do not resolve to exactly one cycle")
                    continue
                db.execute("INSERT INTO article_versions VALUES (?,?,?,?,?,?,?,0)", (aid, case, a.get("input_hash", "-"), a.get("series", "-"), a.get("title", ""), a["text"], ""))
                for c in known:
                    db.execute("INSERT OR IGNORE INTO article_evidence VALUES (?,?)", (aid, c))
        last = db.execute("SELECT b.batch_id FROM update_events e JOIN update_batches b ON b.batch_id = e.batch_id WHERE e.event = 'approved' ORDER BY e.id DESC LIMIT 1").fetchone()
        if last:  # a reference load records ONE state: the last approval says what the heads are (the replay of the events must equal the heads, db_audit DB-18)
            state = {"evidence": dict(db.execute("SELECT logical_id, evidence_id FROM evidence_heads").fetchall()), "articles": dict(db.execute("SELECT base_article_id, article_id FROM article_heads").fetchall())}
            db.execute("UPDATE update_batches SET after_json = ? WHERE batch_id = ?", (_j(state), last[0]))
        db.commit()
    return {"assumptions": assumptions, "skipped": skipped, "cycles": len(cycles), "evidence": len(evidence)}
