"""Phase E preparation: validate an incoming export (from Work, or anywhere
else) against the evidence-record contract this repo's Phase C/D tooling
relies on, *before* it's imported anywhere.

This is deliberately the only piece of Phase E implemented ahead of time:
we don't know Work's real export format yet (docs/INTEGRATION_PLAN.md is
still "保留中"), but whatever it turns out to be, it will need to produce
records shaped like src.verify.schema.EVIDENCE_SCHEMA before src/verify and
src/article_qa can check anything against them. Having this gate ready
means Phase E's first real step is "point this at the export," not "design
a validator from scratch."

CLI:
    python -m src.integration.validate_export <path-to-export.json> [--json-out reports/x.json]

Input file shape: a JSON array of evidence-like records, OR a JSON object
with an "evidence" key mapping id -> record (same shape run_qa_suite.py's
--articles-json uses, so an export can double as that CLI's input once it
also carries claim/article data).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.verify.fact_registry import get_registry
from src.verify.schema import validate_evidence


def validate_records(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Schema check plus the fact_key registry check. A record whose fact_key is
    not registered (or whose value has the wrong type / lacks a required field)
    is invalid: it must not pass the gate as if it were verified."""
    registry = get_registry()
    results = {}
    for record_id, record in records.items():
        errors = validate_evidence(record)
        issues = registry.check_record(record, record_id)
        errors += [f"[registry:{i.category}] {i.detail}" for i in issues if i.severity == "error"]
        results[record_id] = {"ok": not errors, "errors": errors,
                              "registry_notes": [i.to_dict() for i in issues if i.severity != "error"]}
    ok_count = sum(1 for r in results.values() if r["ok"])
    summary = registry.check_evidence(records)
    return {
        "total": len(results),
        "ok_count": ok_count,
        "invalid_count": len(results) - ok_count,
        "registry_version": registry.version,
        "unregistered_fact_keys": summary["unregistered_fact_keys"],
        "proposed_fact_keys": summary["proposed_fact_keys"],
        "records": results,
    }


def _load_records(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "evidence" in data:
        data = data["evidence"]
    if isinstance(data, list):
        # fall back to positional ids if the export doesn't key its own records
        return {str(r.get("evidence_id", i)): r for i, r in enumerate(data)}
    if isinstance(data, dict):
        return data
    raise ValueError("export file must be a JSON array of records, or an object keyed by id (or with an 'evidence' key)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_path", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    records = _load_records(args.export_path)
    report = validate_records(records)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 1 if report["invalid_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
