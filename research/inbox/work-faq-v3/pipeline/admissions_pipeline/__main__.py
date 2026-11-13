import argparse
import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .articles import build_article, claude_export, validate_article, verify_pack
from .claude_adapter import run_qa
from .extract import PROFILES, PROFILE_VERSION, extract_pdf
from .store import EvidenceStore, canonical

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run_pipeline(source_root, state_dir, output_root, collab_root, *, cases=None, as_of=None, legacy_db=None):
    cases = list(cases or PROFILES)
    as_of = as_of or datetime.now(JST).date()
    output = Path(output_root).resolve() / (datetime.now(JST).strftime("run-%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6])
    output.mkdir(parents=True)
    store = EvidenceStore(Path(state_dir) / "admission_media_v0_3.sqlite")
    before = store.counts()
    packs, articles, case_reports = [], [], []
    for case_id in cases:
        profile = PROFILES[case_id]
        try:
            pdf = Path(source_root) / (profile["sha256"] + ".pdf")
            extracted = extract_pdf(case_id, pdf)
            retrieved_at = datetime.fromtimestamp(pdf.stat().st_mtime, JST).date().isoformat()
            # Persist actual extracted pages and facts, then reconstruct the
            # information pack from SQLite rather than reusing in-memory data.
            store.ingest(extracted, retrieved_at)
            pack = store.pack(case_id, profile["sha256"])
            errors = verify_pack(pack)
            if errors:
                raise ValueError(";".join(errors))
            case_dir = output / case_id
            case_dir.mkdir()
            save_json(case_dir / "extracted-pages.json", {"source_hash": profile["sha256"], "pages": extracted.pages})
            save_json(case_dir / "source-facts.json", extracted.facts)
            save_json(case_dir / "article-input.json", pack)
            generated = []
            for series in ("overview", "interview"):
                article = build_article(pack, series, as_of)
                findings = validate_article(article, pack)
                if findings:
                    raise ValueError(";".join(findings))
                draft_path = case_dir / (series + ".md")
                draft_path.write_text(article["text"], encoding="utf-8")
                store.save_article(article, draft_path)
                save_json(case_dir / (series + "-claim-map.json"), article)
                articles.append(article)
                generated.append(str(draft_path))
            packs.append(pack)
            case_reports.append({"case_id": case_id, "status": "source_to_drafts_completed", "facts": len(extracted.facts),
                                 "source_pages": len(extracted.pages), "drafts": generated,
                                 "source_check": "original_hash_and_quotes_and_scoped_profile", "publish_allowed": False})
        except Exception as exc:
            case_reports.append({"case_id": case_id, "status": "failed", "reason": str(exc), "error_type": type(exc).__name__})
    export = claude_export(packs, articles)
    export_path = output / "claude-articles-export.json"
    save_json(export_path, export)
    legacy_status = {"integrated": False, "reason": "v0.2_not_found_in_available_searches"}
    if legacy_db:
        # Preserve all legacy tables as an independent snapshot. No old verified
        # flags are promoted into the newly checked facts without a mapping.
        from database_manager import DatabaseManager
        manager = DatabaseManager(Path(state_dir) / "legacy-audit-state.sqlite")
        copy_path = output / "legacy-v0_2-original-copy.sqlite"
        manager.snapshot_external(legacy_db, copy_path)
        from .legacy import integrate_legacy
        legacy_status = integrate_legacy(store, copy_path, packs, original_path=str(Path(legacy_db).resolve()))
        save_json(output / "legacy-reconciliation.json", legacy_status)
    qa_snapshot = store.snapshot(output / "database-for-claude-qa.sqlite")
    qa = run_qa(collab_root, export_path, qa_snapshot, output) if articles else {"success": False, "reason": "no_articles_to_check"}
    save_json(output / "claude-adapter-result.json", qa)
    success = bool(case_reports) and all(r["status"] == "source_to_drafts_completed" for r in case_reports) and qa["success"]
    if legacy_status.get("reconciliation_counts", {}).get("conflict", 0):
        success = False
    with store.connect() as db:
        db.execute("INSERT INTO qa_runs VALUES (?,?,?,?)", (output.name, qa.get("claude_commit", "unavailable"), str(output / "claude-adapter-result.json"), int(success)))
    snapshot = store.snapshot(output / "admission_media_v0_3.sqlite")
    with sqlite3.connect(snapshot) as check:
        final_integrity = [r[0] for r in check.execute("PRAGMA integrity_check")]
        final_foreign_keys = list(check.execute("PRAGMA foreign_key_check"))
    if final_integrity != ["ok"] or final_foreign_keys:
        success = False
    report = {"run_id": output.name, "generated_at_jst": datetime.now(JST).isoformat(),
        "success": success, "case_results": case_reports, "counts": store.counts(),
        "new_checked_facts": sum(r.get("facts", 0) for r in case_reports), "new_drafts": len(articles),
        "new_registered_facts": store.counts()["facts"] - before["facts"],
        "new_article_versions": store.counts()["article_versions"] - before["article_versions"],
        "final_snapshot_integrity": final_integrity, "final_snapshot_foreign_keys": final_foreign_keys,
        "claude_quality_success": qa["success"], "claude_commit": qa.get("claude_commit"),
        "legacy_v0_2": legacy_status, "live_ai_calls": 0, "paid_api_calls": 0, "note_posts": 0,
        "publish_allowed": False, "profile_version": PROFILE_VERSION, "output": str(output),
        "runtime_database": str(store.path), "database_snapshot": str(snapshot),
        "verification_limit": "Facts were checked against a pinned original PDF edition; latest corrections and publication clearance remain separate."}
    save_json(output / "pipeline-report.json", report)
    save_json(Path(output_root).resolve() / "latest.json", report)
    (output / "schema.sql").write_text(__import__("admissions_pipeline.store", fromlist=["SCHEMA"]).SCHEMA, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Run real-source admissions E2E without AI billing or publishing")
    parser.add_argument("--source-root", type=Path, default=ROOT / "night_output")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / "SOGHRuntime/Admissions")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/admissions")
    parser.add_argument("--collab-root", type=Path, default=ROOT.parent / "SOGH-collab")
    parser.add_argument("--case", choices=list(PROFILES), action="append")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--legacy-db", type=Path)
    args = parser.parse_args()
    report = run_pipeline(args.source_root, args.state_dir, args.output_root, args.collab_root,
                          cases=args.case, as_of=args.as_of, legacy_db=args.legacy_db)
    print(json.dumps({k: report[k] for k in ("success", "new_checked_facts", "new_drafts", "claude_quality_success", "output")}, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
