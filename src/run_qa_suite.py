"""Aggregate QA entrypoint: runs db_qa + verify + article_qa checks a human
(or Work) can invoke in one shot and get a single JSON report back.

This intentionally takes plain inputs (a sqlite path, a dict of
evidence-id -> record, a dict of article-id -> text) rather than reaching
into any specific database schema — see docs/ARCHITECTURE.md for why.

CLI:
    python -m src.run_qa_suite --sqlite <path> [--json-out reports/x.json]
    python -m src.run_qa_suite --articles-json <path>

    --articles-json points at a JSON file shaped as:
        {
          "evidence": {"EV-1": {"university": ..., "faculty": ..., "admission_method": ...,
                                  "fiscal_year": 2026, "department": null, "quota": 30}},
          "articles": [{"article_id": "a1", "text": "...", "claim": {"university": ..., ...}}]
        }
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Any

from src.article_qa.checks import find_near_duplicates, find_overused_phrases
from src.article_qa.evaluate import evaluate_article
from src.db_qa import sqlite_integrity
from src.verify.fact_registry import get_registry


def run(sqlite_path: Path | None) -> dict[str, Any]:
    report: dict[str, Any] = {"db_qa": None}
    if sqlite_path is not None:
        report["db_qa"] = sqlite_integrity.run_all_checks(sqlite_path)
    return report


def run_articles(data: dict[str, Any], reference_date: datetime.date | str | None = None,
                 require_as_of: bool = False) -> dict[str, Any]:
    """Runs per-article evaluation (fact/quality checks against evidence)
    plus batch-level checks that only make sense across multiple articles
    at once: near-duplicate detection and overused template phrases.
    """
    evidence_by_id = data.get("evidence", {})
    per_article = []
    texts: dict[str, str] = {}
    for article in data.get("articles", []):
        texts[article["article_id"]] = article["text"]
        result = evaluate_article(article["article_id"], article["text"], article["claim"], evidence_by_id,
                                  reference_date=reference_date, require_as_of=require_as_of)
        per_article.append({"article_id": result.article_id, "ok": result.ok, "findings": result.findings,
                            "notices": result.notices, "semantic_coverage": result.coverage})

    batch_findings = [
        {"category": f.category, "detail": f.detail}
        for f in [*find_near_duplicates(texts), *find_overused_phrases(texts)]
    ]
    registry = get_registry().check_evidence(evidence_by_id)
    return {"per_article": per_article, "batch_findings": batch_findings,
            "registry": {k: registry[k] for k in ("registry_version", "ok", "by_severity", "fact_keys_used", "unregistered_fact_keys",
                                                  "proposed_fact_keys", "records_without_fact_key")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=None, help="path to a sqlite file (ideally an independent copy)")
    parser.add_argument("--articles-json", type=Path, default=None, help="path to an article+evidence batch (see module docstring)")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--reference-date", default=None, metavar="YYYY-MM-DD|today",
                        help="what \"now\" is for the as-of date checks (not read from the clock unless you say `today`)")
    parser.add_argument("--require-as-of", action="store_true", help="flag an article that cites evidence but has no 作業基準日")
    args = parser.parse_args(argv)

    report = run(args.sqlite)
    if args.articles_json is not None:
        data = json.loads(args.articles_json.read_text(encoding="utf-8"))
        reference = datetime.date.today() if args.reference_date == "today" else args.reference_date
        report["article_qa"] = run_articles(data, reference_date=reference, require_as_of=args.require_as_of)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)

    db_report = report.get("db_qa")
    db_failed = bool(db_report and any(i["severity"] == "error" for i in db_report["issues"]))
    article_qa = report.get("article_qa") or {}
    articles_failed = any(not a["ok"] for a in article_qa.get("per_article", []))
    batch_failed = bool(article_qa.get("batch_findings"))
    return 1 if (db_failed or articles_failed or batch_failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
