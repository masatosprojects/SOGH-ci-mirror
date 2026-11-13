"""Which saved facts, and which articles, are affected by a newer edition?

Every evidence record carries the exact quotes (proofs) it rests on and the page
they were on. Given the current edition of each source, each quote is looked up:

  intact        the quote is still on its page, word for word
  moved         it is intact but on a different page (page numbers shifted)
  page_changed  intact, yet a number/date/amount elsewhere on its page changed
                (needs the OLD edition too; the change is not necessarily the fact)
  reworded      the quote is gone but a close match exists: the wording changed
  value_change  the quote is the same *except for its numbers/dates*: the fact changed
  missing       nothing close is left: the clause was removed or rewritten

An evidence record takes its worst proof's status; an article takes its worst
cited evidence's:  republish_required > unassessed > review > ok.
Evidence with no current edition to check against is reported as *unassessed* —
it is never assumed to still hold.

    python -m src.versioning.impact --export export.json --new current.snapshot.json [--new ...] \
        [--old earlier.snapshot.json ...] [--json-out out.json] [--require-all-assessed]

Exit status: 1 when anything other than intact was found (a quote that only
moved still matters: articles print page numbers such as "p.6"); 2 when only
unassessed evidence remains and --require-all-assessed was given; else 0.
This tool never publishes or edits anything: it only says what to re-check.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any

from src.verify.consistency import extract_citation_ids
from src.versioning.diff import diff_snapshots
from src.versioning.snapshot import SourceSnapshot, load_snapshot, normalize, source_hash

SEVERITY = ["intact", "moved", "page_changed", "reworded", "value_change", "missing"]
REPUBLISH = {"reworded", "value_change", "missing"}
REWORD_RATIO = 0.6


def _rank(status: str) -> int:
    return SEVERITY.index(status)


def _skeleton(quote: str) -> re.Pattern[str] | None:
    parts = re.split(r"(\d+)", quote)
    if len(parts) < 3:
        return None  # no digits: exact match is the only possibility
    return re.compile("".join(r"(\d+)" if i % 2 else re.escape(p) for i, p in enumerate(parts)))


def _best_ratio(page: str, quote: str) -> float:
    if not page or not quote:
        return 0.0
    blocks = difflib.SequenceMatcher(None, page, quote, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(quote)


def assess_quote(quote: str, cited_page: int, pages: list[str]) -> dict[str, Any]:
    """Status of one quote against the normalized pages of the current edition."""
    q = normalize(quote)
    order = [cited_page - 1] + [i for i in range(len(pages)) if i != cited_page - 1]
    order = [i for i in order if 0 <= i < len(pages)]
    if 0 <= cited_page - 1 < len(pages) and q in pages[cited_page - 1]:
        return {"status": "intact"}
    elsewhere = [i + 1 for i in order if q in pages[i]]
    if elsewhere:
        return {"status": "moved", "new_pages": elsewhere}
    skeleton = _skeleton(q)
    if skeleton:
        old_numbers = re.findall(r"\d+", q)
        for i in order:
            m = skeleton.search(pages[i])
            if m:
                changes = [{"from": a, "to": b} for a, b in zip(old_numbers, m.groups()) if a != b]
                return {"status": "value_change", "page": i + 1, "changes": changes}
    best_page, best = None, 0.0
    for i in order:
        ratio = _best_ratio(pages[i], q)
        if ratio > best:
            best_page, best = i + 1, ratio
    if best >= REWORD_RATIO:
        return {"status": "reworded", "page": best_page, "similarity": round(best, 3)}
    return {"status": "missing", "closest_similarity": round(best, 3)}


def _matching_snapshot(evidence: dict[str, Any], snapshots: list[SourceSnapshot]) -> SourceSnapshot | None:
    sha, url = source_hash(evidence), evidence.get("source_url")
    for s in snapshots:
        if sha and (sha == s.sha256 or sha in s.supersedes):
            return s
    for s in snapshots:
        if url and url == s.url:
            return s
    return None


def assess_evidence(
    evidence_by_id: dict[str, dict[str, Any]],
    new_snapshots: list[SourceSnapshot],
    old_snapshots: list[SourceSnapshot] | None = None,
) -> dict[str, Any]:
    old_snapshots = old_snapshots or []
    pages_cache = {s.sha256: s.normalized_pages() for s in new_snapshots}
    diffs: dict[tuple[str, str], Any] = {}
    results: dict[str, Any] = {}
    for eid, ev in evidence_by_id.items():
        snap = _matching_snapshot(ev, new_snapshots)
        if snap is None:
            results[eid] = {"status": "unassessed", "reason": "no current edition of this source was provided",
                            "source_url": ev.get("source_url"), "fact_key": ev.get("fact_key")}
            continue
        if not ev.get("proofs"):
            results[eid] = {"status": "unassessed", "reason": "the evidence record carries no quote to check",
                            "snapshot": snap.source_id, "fact_key": ev.get("fact_key")}
            continue
        same_edition = source_hash(ev) == snap.sha256
        proofs, worst = [], "intact"
        old_snap = next((o for o in old_snapshots if o.sha256 == source_hash(ev)), None)
        for proof in ev.get("proofs", []):
            outcome = assess_quote(proof["quote"], int(proof["page"]), pages_cache[snap.sha256])
            if same_edition and outcome["status"] != "intact":
                outcome["note"] = "same sha256 as the saved edition, yet the quote is not on the page: evidence and source disagree"
            if outcome["status"] == "intact" and old_snap and not same_edition:
                key = (old_snap.sha256, snap.sha256)
                diffs.setdefault(key, diff_snapshots(old_snap, snap))
                page_changes = [c for c in diffs[key].value_changes if c.old_page == int(proof["page"])]
                if page_changes:
                    outcome = {"status": "page_changed",
                               "values_changed_on_page": sorted({v for c in page_changes for v in (*c.old_values, *c.new_values)})}
            proofs.append({"page": proof["page"], **outcome})
            if _rank(outcome["status"]) > _rank(worst):
                worst = outcome["status"]
        entry: dict[str, Any] = {"status": worst, "snapshot": snap.source_id, "same_edition": same_edition,
                                 "fact_key": ev.get("fact_key"), "proofs": proofs}
        if ev.get("source_url") and snap.url and ev["source_url"] != snap.url:
            entry["source_url_changed"] = {"from": ev["source_url"], "to": snap.url}
        results[eid] = entry
    return results


def assess_articles(articles: list[dict[str, Any]], evidence_status: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for article in articles:
        cited = sorted(extract_citation_ids(article["text"]))
        reasons = []
        for eid in cited:
            st = evidence_status.get(eid, {"status": "unassessed", "reason": "unknown evidence id"})["status"]
            if st != "intact":
                reasons.append({"evidence_id": eid, "status": st})
        statuses = {r["status"] for r in reasons}
        if statuses & REPUBLISH:
            status = "republish_required"
        elif "unassessed" in statuses:
            status = "unassessed"
        elif statuses:
            status = "review"  # moved / page_changed only
        else:
            status = "ok"
        out[article["article_id"]] = {"status": status, "cited": cited, "reasons": reasons}
    return out


def assess_export(export: dict[str, Any], new_snapshots: list[SourceSnapshot],
                  old_snapshots: list[SourceSnapshot] | None = None) -> dict[str, Any]:
    evidence = assess_evidence(export["evidence"], new_snapshots, old_snapshots)
    articles = assess_articles(export.get("articles", []), evidence)
    count = lambda d, s: sorted(k for k, v in d.items() if v["status"] == s)  # noqa: E731
    return {
        "current_editions": [{"source_id": s.source_id, "sha256": s.sha256, "retrieved_at": s.retrieved_at} for s in new_snapshots],
        "evidence": evidence,
        "articles": articles,
        "republish_required": count(articles, "republish_required"),
        "articles_to_review": count(articles, "review"),
        "articles_unassessed": count(articles, "unassessed"),
        "unassessed_evidence": count(evidence, "unassessed"),
        "summary": {
            "evidence": len(evidence),
            **{f"evidence_{s}": len(count(evidence, s)) for s in (*SEVERITY, "unassessed")},
            "articles": len(articles),
            **{f"articles_{s}": len(count(articles, s)) for s in ("republish_required", "unassessed", "review", "ok")},
        },
    }


def exit_code(report: dict[str, Any], require_all_assessed: bool = False) -> int:
    changed = any(v["status"] not in ("intact", "moved", "unassessed") for v in report["evidence"].values())
    reviewing = bool(report["republish_required"] or report["articles_to_review"])
    if changed or reviewing:
        return 1
    if require_all_assessed and (report["unassessed_evidence"] or report["articles_unassessed"]):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", type=Path, required=True, help="JSON with 'evidence' and 'articles'")
    parser.add_argument("--new", type=Path, action="append", required=True, help="current edition snapshot (repeatable)")
    parser.add_argument("--old", type=Path, action="append", default=[], help="earlier edition snapshot (repeatable)")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--require-all-assessed", action="store_true")
    args = parser.parse_args(argv)
    export = json.loads(args.export.read_text(encoding="utf-8"))
    report = assess_export(export, [load_snapshot(p) for p in args.new], [load_snapshot(p) for p in args.old])
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("summary", "republish_required", "articles_to_review", "unassessed_evidence")},
                     ensure_ascii=False, indent=2))
    return exit_code(report, args.require_all_assessed)


if __name__ == "__main__":
    raise SystemExit(main())
