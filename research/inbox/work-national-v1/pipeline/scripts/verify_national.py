"""Independent Claude source audit plus read-only preservation checks."""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--pdf-dir", type=Path, required=True)
    p.add_argument("--collab", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    args = p.parse_args()
    code = '''
import json,sys
from pathlib import Path
from src.integration.audit_handoff import check_source_pdfs,check_values_in_quotes,check_export
export=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
r={"source_pdfs":check_source_pdfs(export,Path(sys.argv[2])),"values_in_quotes":check_values_in_quotes(export),"export":check_export(export)}
Path(sys.argv[3]).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({k:v["status"] for k,v in r.items()}))
raise SystemExit(0 if all(x["status"]=="pass" for x in r.values()) else 1)
'''
    report_path = args.run.resolve() / "independent-source-audit.json"
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", code,
                             str((args.run / "claude-compatible-export.json").resolve()),
                             str(args.pdf_dir.resolve()), str(report_path)], cwd=args.collab,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=180)
    baseline_hash = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    differences = []
    with closing(sqlite3.connect(f"{args.baseline.resolve().as_uri()}?mode=ro", uri=True)) as old, closing(sqlite3.connect(f"{(args.run / 'admissions-snapshot.sqlite').resolve().as_uri()}?mode=ro", uri=True)) as new:
        tables = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            cols = [r[1] for r in old.execute("PRAGMA table_info(" + quoted + ")")]
            selected = ",".join('"' + c.replace('"', '""') + '"' for c in cols)
            old_rows = old.execute("SELECT " + selected + " FROM " + quoted).fetchall()
            new_rows = set(new.execute("SELECT " + selected + " FROM " + quoted).fetchall())
            if not set(old_rows) <= new_rows:
                differences.append(table)
        integrity = new.execute("PRAGMA integrity_check").fetchall()
        fks = new.execute("PRAGMA foreign_key_check").fetchall()
    report = {"baseline_sha256": baseline_hash, "tables_checked": len(tables),
              "old_rows_missing_or_modified": differences, "integrity_check": integrity, "foreign_keys": fks,
              "success": result.returncode == 0 and not differences and integrity == [("ok",)] and not fks}
    (args.run / "preservation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()
