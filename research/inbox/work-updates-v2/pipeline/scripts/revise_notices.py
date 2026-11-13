"""Source-bound candidate extraction -> registry gate -> revised drafts -> QA -> CAS activation."""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from admissions_pipeline.claude_adapter import run_qa,run_quote_gate
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.revisions import RevisionStore, clone_database
from admissions_pipeline.store import canonical
from admissions_pipeline.supplements import extract_notice, contract_state
from admissions_pipeline.process_lock import ProcessLock


def run(*args):
    with ProcessLock(Path(args[4]).with_suffix(".updates.lock")):
        return _run(*args)


def _run(specs_path, monitor_root, base_export, base_db, work_db, qa_root, output, as_of, refresh_articles=False):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    if not Path(work_db).exists(): clone_database(base_db, work_db)
    store = RevisionStore(work_db, output / "before-update.sqlite")
    recovered = store.recover_candidates()
    registry = json.loads((Path(qa_root) / "src/verify/data/fact_keys.json").read_text(encoding="utf-8"))
    with sqlite3.connect(Path(monitor_root) / "monitor.sqlite") as db:
        db.row_factory = sqlite3.Row; targets = {r["url"]: dict(r) for r in db.execute("SELECT * FROM targets")}
    with store.connect() as db: cycles = {r["case_id"]: dict(r) for r in db.execute("SELECT * FROM admission_cycles")}
    records, source_review_pending = [], []
    for spec in json.loads(Path(specs_path).read_text(encoding="utf-8")):
        row = targets.get(spec["url"])
        if not row or not row["last_success"] or row["last_error"]:
            raise ValueError("notice was not successfully checked in collection state")
        if datetime.now(timezone.utc).timestamp() - row["last_success"] > 86400:
            raise ValueError("source observation is stale; collect again before proposing an update")
        sha = row["last_sha"]; kind = "pdf" if (Path(monitor_root) / "bodies" / (sha + ".pdf")).exists() else "html"
        record = {"url": spec["url"], "sha256": sha, "kind": kind,
                  "local_path": str(Path(monitor_root) / "bodies" / (sha + "." + kind)),
                  "retrieved_at": datetime.fromtimestamp(row["last_success"], timezone.utc).isoformat()}
        try:
            records.append(extract_notice(spec, record, cycles[spec["case_id"]]))
        except ValueError as exc:
            source_review_pending.append({"logical_id": spec["logical_id"], "source_url": spec["url"], "reason": str(exc), "sha256": sha})
    pending = [r for r in records if contract_state(r, registry) != "candidate"]
    eligible = [r for r in records if contract_state(r, registry) == "candidate"]
    current_heads=store.heads()["evidence"]
    newly_registered=sum(current_heads.get(r["logical_id"]) != r["evidence_id"] for r in eligible)
    if not refresh_articles:eligible=[r for r in eligible if current_heads.get(r["logical_id"]) != r["evidence_id"]]
    (output / "notice-candidates.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    waiting_batch = store.stage(pending, registry) if pending else None
    report = {"pending_contract": [r["fact_key"] for r in pending], "candidate_count": len(records),
              "interrupted_batches_recovered": recovered,
              "source_review_pending": source_review_pending,
              "waiting_batch": waiting_batch["batch_id"] if waiting_batch else None, "approved": False, "revised_articles": 0}
    if eligible:
        batch = store.stage(eligible, registry, refresh_articles=refresh_articles)
        if batch["state"] == "no_change":
            report.update(batch_id=batch["batch_id"], approved=True, no_change=True, registered_evidence=0,
                          heads=store.heads(), native_counts=store.counts(), publication_allowed=False)
            (output / "update-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report
        effective = store.effective_records(batch)
        old = json.loads(Path(base_export).read_text(encoding="utf-8"))
        with store.connect() as db:
            for eid, evidence in old["evidence"].items():
                row = db.execute("SELECT record_json FROM facts WHERE evidence_id=?", (eid,)).fetchone()
                if not row: raise ValueError("base evidence missing from native DB")
                fact = json.loads(row[0])
                if evidence["fact_key"] != fact["key"] or canonical(evidence["value"]) != canonical(fact["value"]) or evidence["source_pdf_sha256"] != fact["source_pdf_sha256"]:
                    raise ValueError("base evidence differs from native DB")
            for article in old["articles"]:
                native = db.execute("SELECT * FROM article_versions WHERE article_id=?", (article["article_id"],)).fetchone()
                if not native or native["body"] != article["text"]: raise ValueError("base article differs from native DB")
                import re
                article.update(case_id=native["case_id"], series=native["series"],
                               evidence_ids=sorted(set(re.findall(r"\[(EV-[A-Za-z0-9_-]+)\]", article["text"]))))
        affected = {r["case_id"] for r in eligible}
        originals = [a for a in old["articles"] if a["case_id"] in affected and any(
            r["case_id"]==a["case_id"] and (not r.get("replaces_evidence_ids") or any("["+eid+"]" in a["text"] for eid in r["replaces_evidence_ids"])) for r in effective)]
        articles = [revise_article(a, effective, as_of, batch["before"]["articles"].get(a["article_id"])) for a in originals]
        export = {"evidence": dict(old["evidence"]), "articles": articles}
        for record in effective:
            for ancestor in record.get("replaces_evidence_ids",[]): export["evidence"].pop(ancestor,None)
        export["evidence"].update({r["evidence_id"]: r for r in effective})
        export_path = output / "claude-compatible-export.json"
        export_path.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
        for i, article in enumerate(articles):
            (output / (f"article-{i+1}-" + article["series"] + ".md")).write_text(article["text"], encoding="utf-8")
        qa_input = store.snapshot(output / "qa-input.sqlite")
        checked_export_sha = hashlib.sha256(export_path.read_bytes()).hexdigest()
        qa = run_qa(qa_root, export_path, qa_input, output, reference_date=as_of)
        # Article-vs-data agreement alone does not show that the extracted value is in its quote.
        value_report=output/'claude-values-in-quotes.json'
        qa['source_values_gate']=run_quote_gate(qa_root,export_path,value_report)
        qa['success']=qa['success'] and qa['source_values_gate']['success']
        # Bind the activation to the exact artifact that was checked, not just a Boolean.
        if hashlib.sha256(export_path.read_bytes()).hexdigest() != checked_export_sha:
            raise ValueError("export changed while QA was running")
        qa.update(batch_input_sha=batch["input_sha"], articles_sha256=hashlib.sha256(canonical(articles).encode()).hexdigest(),
                  export_sha256=hashlib.sha256(export_path.read_bytes()).hexdigest())
        approved = store.finalize(batch, articles, qa, registry)
        report.update(batch_id=batch["batch_id"], approved=approved, qa=qa, registered_evidence=newly_registered if approved else 0,
                      revised_articles=len(articles) if approved else 0)
    if not eligible and current_heads: report.update(approved=True,no_change=True,registered_evidence=0)
    report.update(heads=store.heads(), native_counts=store.counts(), publication_allowed=False)
    store.snapshot(output / "after-update.sqlite")
    (output / "update-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser()
    for name in ("specs", "monitor-root", "base-export", "base-db", "work-db", "qa-root", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    p.add_argument("--refresh-articles",action="store_true",help="explicit template revision without changing facts")
    args = p.parse_args()
    r = run(args.specs, args.monitor_root, args.base_export, args.base_db, args.work_db, args.qa_root, args.output, args.as_of,args.refresh_articles)
    print(json.dumps({k:r[k] for k in ("approved", "pending_contract", "revised_articles")}, ensure_ascii=False))
    raise SystemExit(0 if r["approved"] else 1)


if __name__ == "__main__": main()
