"""Regenerate the machine-readable DB audit reports under reports/db-audit/.

    python -m src.db_contract.reports

  schema_*.json, schema_evolution.json   structure of the schemas in the repository (introspect)
  audit_v0_2_sample.json                 the v0.2 sample database, `repository_sample`
  audit_current_view_loaded.json         the whole view + base state loaded into the delivered v0.5 schema, `repository_sample` (derived)
  audit_all_deliveries_loaded.json       ALL deliveries loaded together: shows the duplicate evidence-id space (`repository_sample`, derived)

Work's local database is not in the repository: there is NO report for it (`not_run`).
"""
from __future__ import annotations

import gzip
import json
import tempfile
from pathlib import Path

from src.db_contract import introspect, load_export
from src.integration import db_audit
from src.regression.fullview import find_views
from src.regression.handoffs import INBOX, find_exports

OUT = introspect.REPO / "reports" / "db-audit"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    introspect.main(["--out", str(OUT)])
    tmp = Path(tempfile.mkdtemp())
    sample = tmp / "v02.sqlite"
    sample.write_bytes(gzip.decompress((INBOX / "work-db-v02-20261101" / "data" / "admission_media_v0_2.sqlite.gz").read_bytes()))
    reports = {"audit_v0_2_sample.json": {"database": "work-db-v02-20261101/data/admission_media_v0_2.sqlite.gz", **db_audit.audit(sample, None, "repository_sample")}}
    bases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(INBOX.rglob("*base-state*.json"))]
    views = [json.loads(p.read_text(encoding="utf-8")) for p in find_views()]
    exports = [e.load() for e in find_exports()]
    for name, parts in (("audit_current_view_loaded.json", [*bases, *views]), ("audit_all_deliveries_loaded.json", [*bases, *exports, *views])):
        db = tmp / name.replace(".json", ".sqlite")
        info = load_export.load(db, parts)
        reports[name] = {"built_from": "repository files (exports / view / base state) via src/db_contract/load_export.py — NOT Work's database",
                         "loader_assumptions": info["assumptions"], "loader_skipped": info["skipped"], **db_audit.audit(db, None, "repository_sample")}
    for name, report in reports.items():
        (OUT / name).write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(name, "ok" if report["ok"] else "FAIL", report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
