"""Read the STRUCTURE of the SQLite schemas that exist in the repository, and compare their generations.

    python -m src.db_contract.introspect [--out reports/db-audit]

Sources (each is labelled with how we know it — nothing is inferred about a database that is not here):
  schema_file       a `database-schema.sql` delivered by Work (loaded into an in-memory SQLite and introspected)
  repository_sample the gzip'd sample database delivered with the v0.2 handoff (decompressed to a temp copy, opened read-only)
The local production database of Work is NOT in the repository: it is never assumed to equal either of these.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
INBOX = REPO / "research" / "inbox"

SOURCES = [
    {"id": "v0_2_sample_db", "kind": "repository_sample", "path": "work-db-v02-20261101/data/admission_media_v0_2.sqlite.gz",
     "evidence": "a real SQLite file delivered in the repository (rows counted; schema read)"},
    {"id": "v0_3_national_v1", "kind": "schema_file", "path": "work-national-v1/database-schema.sql",
     "evidence": "a schema dump delivered by Work (no rows)"},
    {"id": "v0_5_updates_v2", "kind": "schema_file", "path": "work-updates-v2/database-schema.sql",
     "evidence": "a schema dump delivered by Work (no rows)"},
]


def introspect(db: sqlite3.Connection, with_counts: bool) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        cols = db.execute(f"PRAGMA table_info('{name}')").fetchall()
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0] or ""
        uniques = []
        for idx in db.execute(f"PRAGMA index_list('{name}')").fetchall():
            if idx[2]:  # unique
                uniques.append([r[2] for r in db.execute(f"PRAGMA index_info('{idx[1]}')")])
        tables[name] = {
            "columns": [{"name": c[1], "type": c[2], "not_null": bool(c[3]), "pk": c[5]} for c in cols],
            "primary_key": [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]],
            "foreign_keys": [{"from": f[3], "table": f[2], "to": f[4], "on_delete": f[6]} for f in db.execute(f"PRAGMA foreign_key_list('{name}')")],
            "unique": sorted(uniques),
            "indexes": [i[1] for i in db.execute(f"PRAGMA index_list('{name}')") if not i[1].startswith("sqlite_autoindex")],
            "checks": sql.upper().count("CHECK"),
        }
        if with_counts:
            tables[name]["rows"] = db.execute(f"SELECT count(*) FROM '{name}'").fetchone()[0]
    return tables


def load_source(src: dict[str, str]) -> dict[str, Any]:
    path = INBOX / src["path"]
    if not path.is_file():
        return {"id": src["id"], "kind": src["kind"], "status": "not_found", "evidence": src["evidence"]}
    if src["kind"] == "schema_file":
        with closing(sqlite3.connect(":memory:")) as db:
            db.executescript(path.read_text(encoding="utf-8"))
            tables = introspect(db, with_counts=False)
        extra: dict[str, Any] = {}
    else:
        tmp = Path(tempfile.mkdtemp()) / "sample.sqlite"
        tmp.write_bytes(gzip.decompress(path.read_bytes()))
        with closing(sqlite3.connect(f"{tmp.as_uri()}?mode=ro", uri=True)) as db:
            tables = introspect(db, with_counts=True)
            extra = {"integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0],
                     "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
                     "has_schema_migrations_table": any(r[0] == "schema_migrations" for r in db.execute("SELECT name FROM sqlite_master"))}
    return {"id": src["id"], "kind": src["kind"], "status": "read", "evidence": src["evidence"], "table_count": len(tables),
            "foreign_key_count": sum(len(t["foreign_keys"]) for t in tables.values()), "index_count": sum(len(t["indexes"]) for t in tables.values()),
            "tables": tables, **extra}


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ta, tb = a.get("tables", {}), b.get("tables", {})
    common = sorted(set(ta) & set(tb))
    return {"from": a["id"], "to": b["id"], "tables_removed": sorted(set(ta) - set(tb)), "tables_added": sorted(set(tb) - set(ta)),
            "tables_in_both": common,
            "columns_changed": {n: {"removed": sorted({c["name"] for c in ta[n]["columns"]} - {c["name"] for c in tb[n]["columns"]}),
                                    "added": sorted({c["name"] for c in tb[n]["columns"]} - {c["name"] for c in ta[n]["columns"]})}
                                for n in common if {c["name"] for c in ta[n]["columns"]} != {c["name"] for c in tb[n]["columns"]}}}


def build_report() -> dict[str, Any]:
    sources = [load_source(s) for s in SOURCES]
    read = [s for s in sources if s["status"] == "read"]
    return {"note": "Structure read from files in the repository. Work's local production database is not here and is not assumed to equal any of these.",
            "sources": sources,
            "evolution": [compare(read[i], read[i + 1]) for i in range(len(read) - 1)]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=REPO / "reports" / "db-audit")
    args = parser.parse_args(argv)
    report = build_report()
    args.out.mkdir(parents=True, exist_ok=True)
    for s in report["sources"]:
        (args.out / f"schema_{s['id']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (args.out / "schema_evolution.json").write_text(json.dumps(report["evolution"], ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    for s in report["sources"]:
        print(s["id"], s["status"], s.get("table_count"), "tables", s.get("foreign_key_count"), "FKs", s.get("index_count"), "indexes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
