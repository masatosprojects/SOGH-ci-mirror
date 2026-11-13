"""Read-only SQLite QA checks.

Generic, schema-agnostic integrity checks for a SQLite database file.
Designed to run against an independent COPY of a production database —
never opens its target with write intent, and never the original file path
directly from a caller that might be a live, in-use database.

CLI:
    python -m src.db_qa.sqlite_integrity <path-to-sqlite-file> [--year-columns 年度,year,fiscal_year]
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any


@dataclasses.dataclass
class Issue:
    severity: str  # "error" | "warning"
    category: str
    table: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def check_integrity(conn: sqlite3.Connection) -> list[Issue]:
    issues: list[Issue] = []
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    results = [r[0] for r in rows]
    if results != ["ok"]:
        for r in results:
            issues.append(Issue("error", "integrity_check", None, str(r)))
    return issues


def check_foreign_keys(conn: sqlite3.Connection) -> list[Issue]:
    issues: list[Issue] = []
    conn.execute("PRAGMA foreign_keys = ON")
    for table in list_tables(conn):
        rows = conn.execute(f'PRAGMA foreign_key_check("{table}")').fetchall()
        for row in rows:
            # (table, rowid, referenced_table, fk_id)
            issues.append(
                Issue(
                    "error",
                    "foreign_key_violation",
                    table,
                    f"rowid={row[0]} references missing row in {row[2]} (fk id {row[3]})",
                )
            )
    return issues


def check_duplicate_rows(conn: sqlite3.Connection, max_rows_per_table: int = 200_000) -> list[Issue]:
    """Flags rows that are identical on every non-primary-key column.

    Primary key / rowid columns are excluded from the comparison: two rows
    with the same synthetic id are the same row, not a duplicate, but two
    rows with different ids and otherwise identical content are exactly the
    "重複レコード" (duplicate record) class this check targets.

    A composite primary key is different: its columns *are* the row's
    identity (an association table such as fact_evidence(fact_id, snapshot_id,
    relation, locator)), and the database already forbids duplicates of it.
    Comparing only the leftover payload columns there reports false
    duplicates, so such tables are skipped.

    Skipped for tables above max_rows_per_table to keep this a QA tool,
    not a full-table-scan liability on large production copies.
    """
    issues: list[Issue] = []
    for table in list_tables(conn):
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if count == 0 or count > max_rows_per_table:
            continue
        table_info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        pk_cols = {r[1] for r in table_info if r[5]}  # column index 5 = pk flag
        if len(pk_cols) > 1:
            continue
        cols = [r[1] for r in table_info if r[1] not in pk_cols]
        if not cols:
            continue
        col_list = ", ".join(f'"{c}"' for c in cols)
        dupes = conn.execute(
            f'SELECT COUNT(*) FROM (SELECT {col_list}, COUNT(*) c FROM "{table}" '
            f'GROUP BY {col_list} HAVING c > 1)'
        ).fetchone()[0]
        if dupes:
            issues.append(
                Issue("warning", "duplicate_rows", table, f"{dupes} distinct row-value(s) repeated")
            )
    return issues


_YEAR_RE = re.compile(r"(年度|year|nendo|fiscal)", re.IGNORECASE)


def check_year_columns(
    conn: sqlite3.Connection,
    plausible_min: int = 2000,
    plausible_max: int = 2100,
    extra_column_names: list[str] | None = None,
) -> list[Issue]:
    """Flags values in columns that look like a 'year' column but fall outside
    a plausible range, or mix clearly inconsistent magnitudes (e.g. 2024 vs 24 vs 20240401)
    within the same column — a common source of "年度混在" bugs.
    """
    issues: list[Issue] = []
    extra = set(extra_column_names or [])
    for table in list_tables(conn):
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        year_cols = [c for c in cols if _YEAR_RE.search(c) or c in extra]
        for col in year_cols:
            values = [
                row[0]
                for row in conn.execute(f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL')
                if row[0] is not None
            ]
            if not values:
                continue
            numeric_values = []
            for v in values:
                try:
                    numeric_values.append(int(v))
                except (TypeError, ValueError):
                    issues.append(
                        Issue("warning", "year_column_non_numeric", table, f'{col}="{v}" is not numeric')
                    )
            out_of_range = [v for v in numeric_values if not (plausible_min <= v <= plausible_max)]
            if out_of_range:
                issues.append(
                    Issue(
                        "error",
                        "year_out_of_range",
                        table,
                        f"{col} has implausible year value(s): {sorted(set(out_of_range))}",
                    )
                )
            # magnitude mixing, e.g. {2024, 24} or {2024, 20240401}
            magnitudes = {len(str(abs(v))) for v in numeric_values}
            if len(magnitudes) > 1:
                issues.append(
                    Issue(
                        "warning",
                        "year_column_mixed_magnitude",
                        table,
                        f"{col} mixes differently-formatted year-like values: {sorted(set(numeric_values))}",
                    )
                )
    return issues


_ENTITY_NAME_RE = re.compile(r"(大学|学部|学科|学群|学類|方式|university|faculty|department|method|name)", re.IGNORECASE)


def check_near_duplicate_entity_names(
    conn: sqlite3.Connection,
    *,
    similarity_threshold: float = 0.92,
    max_distinct_values: int = 500,
    extra_column_names: list[str] | None = None,
) -> list[Issue]:
    """Flags pairs of distinct values in entity-name-like columns (university,
    faculty, department, admission method) that are near-identical but not
    exactly equal — the "大学・学部・方式の混同" / 表記揺れ failure mode, e.g. a
    trailing space, a different full-width character, or a typo that would
    otherwise silently create two "different" universities in the data.

    Exact duplicates are not flagged here (that's normal — many rows legitimately
    share the same university name); only *near* matches that are NOT identical.
    """
    issues: list[Issue] = []
    extra = set(extra_column_names or [])
    for table in list_tables(conn):
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        name_cols = [c for c in cols if _ENTITY_NAME_RE.search(c) or c in extra]
        for col in name_cols:
            values = [
                row[0]
                for row in conn.execute(f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL')
                if isinstance(row[0], str) and row[0].strip()
            ]
            if len(values) < 2 or len(values) > max_distinct_values:
                continue
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    a, b = values[i], values[j]
                    if a == b:
                        continue
                    norm_a, norm_b = _normalize_entity_name(a), _normalize_entity_name(b)
                    if norm_a == norm_b:
                        issues.append(
                            Issue(
                                "warning",
                                "near_duplicate_entity_name",
                                table,
                                f"{col}: {a!r} and {b!r} differ only in whitespace/width — same after normalization (表記揺れ)",
                            )
                        )
                        continue
                    ratio = difflib.SequenceMatcher(a=a, b=b).ratio()
                    if ratio >= similarity_threshold:
                        issues.append(
                            Issue(
                                "warning",
                                "near_duplicate_entity_name",
                                table,
                                f"{col}: {a!r} and {b!r} are {ratio:.0%} similar but not identical (表記揺れの可能性)",
                            )
                        )
    return issues


def _normalize_entity_name(value: str) -> str:
    """Collapses the differences that are almost always noise, not a real
    distinction between two entity names: surrounding whitespace and
    full-width/half-width character width (NFKC).
    """
    return unicodedata.normalize("NFKC", value).strip()


def backup_and_verify(db_path: Path, backup_path: Path) -> list[Issue]:
    """Performs a SQLite backup and verifies per-table row counts match the source."""
    issues: list[Issue] = []
    src = _connect_readonly(db_path)
    try:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path.exists():
            backup_path.unlink()
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()

        verify = sqlite3.connect(str(backup_path))
        try:
            for table in list_tables(src):
                src_count = src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                dst_count = verify.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if src_count != dst_count:
                    issues.append(
                        Issue(
                            "error",
                            "backup_restore_mismatch",
                            table,
                            f"source has {src_count} rows, backup has {dst_count}",
                        )
                    )
        finally:
            verify.close()
    finally:
        src.close()
    return issues


def run_all_checks(
    db_path: Path,
    year_columns: list[str] | None = None,
    entity_name_columns: list[str] | None = None,
) -> dict[str, Any]:
    conn = _connect_readonly(db_path)
    try:
        issues: list[Issue] = []
        issues += check_integrity(conn)
        issues += check_foreign_keys(conn)
        issues += check_duplicate_rows(conn)
        issues += check_year_columns(conn, extra_column_names=year_columns)
        issues += check_near_duplicate_entity_names(conn, extra_column_names=entity_name_columns)
        tables = list_tables(conn)
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "tables": tables,
        "issue_count": len(issues),
        "issues": [i.to_dict() for i in issues],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", type=Path)
    parser.add_argument("--year-columns", default="", help="comma-separated extra column names to treat as year columns")
    parser.add_argument("--entity-name-columns", default="", help="comma-separated extra column names to check for near-duplicate (表記揺れ) values")
    parser.add_argument("--backup-to", type=Path, default=None, help="also perform a backup+restore verification")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    year_cols = [c.strip() for c in args.year_columns.split(",") if c.strip()]
    entity_cols = [c.strip() for c in args.entity_name_columns.split(",") if c.strip()]
    result = run_all_checks(args.db_path, year_columns=year_cols, entity_name_columns=entity_cols)

    if args.backup_to:
        backup_issues = backup_and_verify(args.db_path, args.backup_to)
        result["issues"].extend(i.to_dict() for i in backup_issues)
        result["issue_count"] = len(result["issues"])

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 1 if any(i["severity"] == "error" for i in result["issues"]) else 0


if __name__ == "__main__":
    sys.exit(main())
