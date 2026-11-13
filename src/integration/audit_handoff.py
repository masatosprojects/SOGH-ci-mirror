"""Independent audit of a Work handoff directory (e.g. research/inbox/work-db-v02-*).

Nothing here trusts the handoff's own report: every claim is recomputed from the
files. Read-only — databases are opened with mode=ro / immutable=1.

    python -m src.integration.audit_handoff <handoff_dir> \
        [--pdf-dir <dir of <sha256>.pdf>] [--original-db <path>] [--json-out out.json]

Checks (each reports its own pass/fail and is skipped, not passed, when its
input is missing):
  manifest        every listed file exists and matches its sha256 and size
  database        sqlite integrity/foreign keys, table & row counts, and — if the
                  original is given — logical equality with it
  reconciliation  each legacy fact is compared leaf-by-leaf with the new fact it
                  was linked to (a legacy value absent from the new fact = conflict)
  source_pdfs     PDF sha256 vs the evidence records, and every proof quote found
                  on its cited page; weekday and date cross-checks
  values_in_quotes  every integer in a record's structured value appears in that
                  record's own quoted text (no PDF needed)
  export          every claude-compatible-export.json in the handoff through the Phase E gate and the
                  article QA (strict validation included)
  whole view      (Issue #48) a handoff with no differential export but a manifest + `active-state.json` / `full-view.json`:
                  shape, the gate and article QA, which evidence ids repeat an earlier delivery legitimately and which
                  collide, article revision history. Reported under `export`; original PDFs/HTML stay `skipped` / `not_run`.
  privacy         secret / personal-data patterns in every file and DB text cell
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any

_WEEKDAYS = "月火水木金土日"


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", s) if not c.isspace())


# ---------------------------------------------------------------- manifest

def check_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return {"status": "skipped", "reason": "no manifest.json"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    checked = 0
    listed: set[str] = {"manifest.json"}
    for entry in manifest.get("files", []):
        rel = entry["path"]
        listed.add(rel.replace("\\", "/"))
        path = root / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
            continue
        data = path.read_bytes()
        checked += 1
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            problems.append(f"sha256 differs: {rel}")
        if "bytes" in entry and len(data) != entry["bytes"]:
            problems.append(f"size differs: {rel}")
    on_disk = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    unlisted = sorted(on_disk - listed)
    if unlisted:
        problems.append(f"files not in manifest: {unlisted}")
    return {"status": "pass" if not problems else "fail", "files_checked": checked, "problems": problems,
            "note": "hash a checkout made with core.autocrlf=false; CRLF conversion changes text-file hashes"}


# ---------------------------------------------------------------- database

def _rows(db: sqlite3.Connection, table: str) -> list[tuple]:
    return sorted(db.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)


def check_database(db_path: Path, original: Path | None = None) -> dict[str, Any]:
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as db:
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
        counts = {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        result: dict[str, Any] = {
            "integrity_check": [r[0] for r in db.execute("PRAGMA integrity_check")],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "tables": len(tables), "rows": sum(counts.values()), "row_counts": counts,
            "sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        }
        if original is not None:
            with closing(sqlite3.connect(f"{original.as_uri()}?immutable=1", uri=True)) as other:
                other_tables = [r[0] for r in other.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
                differing = [t for t in tables if t not in other_tables or _rows(db, t) != _rows(other, t)]
                result["original_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
                result["same_tables_as_original"] = tables == other_tables
                result["tables_with_different_rows"] = differing
    ok = (result["integrity_check"] == ["ok"] and result["foreign_key_violations"] == 0
          and (original is None or (result["same_tables_as_original"] and not result["tables_with_different_rows"])))
    result["status"] = "pass" if ok else "fail"
    return result


# ---------------------------------------------------------- reconciliation

def _leaves(value: Any, out: set[str] | None = None) -> set[str]:
    """Scalar leaves as comparable strings; datetimes also contribute date and HH:MM."""
    out = set() if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("qualifier", "unit", "timezone", "scope", "period"):
                continue  # descriptive, not facts to compare
            _leaves(v, out)
    elif isinstance(value, list):
        for v in value:
            _leaves(v, out)
    elif isinstance(value, bool) or value is None:
        if value is not None:
            out.add(str(value))
    elif isinstance(value, (int, float)):
        out.add(str(int(value)) if float(value).is_integer() else str(value))
    elif isinstance(value, str):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}):\d{2}.*)?", value)
        if m:
            out.add(m.group(1))
            if m.group(2):
                out.add(m.group(2))
        else:
            out.add(value)
    return out


def check_reconciliation(db_path: Path, reconciliation: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as db:
        legacy = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id, value_json FROM fact_claims")}
    conflicts, manual_review, added, missing_evidence, page_issues = [], [], [], [], []
    for link in reconciliation["fact_links"]:
        ev = evidence.get(link["evidence_id"])
        if ev is None:
            missing_evidence.append(link["legacy_fact_id"])
            continue
        old, new = _leaves(legacy[link["legacy_fact_id"]]), _leaves(ev["value"])
        # Numbers and dates must survive exactly. A legacy true/false flag may legitimately
        # have become a free-text qualifier, so a missing flag needs a human look, not a verdict.
        absent = sorted(x for x in old if re.search(r"\d", x) and x not in new)
        if absent:
            conflicts.append({"legacy_fact_id": link["legacy_fact_id"], "legacy_values_not_in_new_fact": absent})
        flags = sorted(x for x in old if x in ("True", "False") and x not in new)
        if flags:
            manual_review.append({"legacy_fact_id": link["legacy_fact_id"], "legacy_flags_not_in_new_fact": flags,
                                  "new_value": ev["value"]})
        if new - old:
            added.append(link["legacy_fact_id"])
        proof_pages = {p["page"] for p in ev.get("proofs", [])}
        if proof_pages and not set(link.get("pages", [])) <= proof_pages:
            page_issues.append(link["legacy_fact_id"])
    counts = reconciliation.get("reconciliation_counts", {})
    status = "fail" if (conflicts or missing_evidence or page_issues) else ("review" if manual_review else "pass")
    return {
        "status": status,
        "links": len(reconciliation["fact_links"]), "independent_conflicts": conflicts,
        "needs_manual_review": manual_review,
        "links_to_missing_evidence": missing_evidence, "link_page_not_in_evidence_proofs": page_issues,
        "new_fact_adds_values_beyond_legacy": added,
        "work_reported_counts": counts,
        "work_reported_total": sum(counts.values()),
        "note": "'added values' is a leaf-level measure and need not equal Work's 'matched_with_added_context' set",
    }


# -------------------------------------------------------------- source PDFs

def _pdf_pages(path: Path, errors: dict[str, str]) -> dict[str, list[str]]:
    """Page texts from each available extraction library; a library that is
    missing or cannot read this file is recorded in `errors`, not fatal."""
    pages: dict[str, list[str]] = {}
    try:
        import pymupdf  # type: ignore

        with pymupdf.open(path) as doc:
            pages["pymupdf"] = [_norm(p.get_text()) for p in doc]
    except ImportError:
        errors["pymupdf"] = "not installed"
    except Exception as exc:  # noqa: BLE001 - report, don't crash the audit
        errors["pymupdf"] = f"{type(exc).__name__}: {exc}"
    try:
        import pypdf  # type: ignore

        pages["pypdf"] = [_norm(p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages]
    except ImportError:
        errors["pypdf"] = "not installed"
    except Exception as exc:  # noqa: BLE001
        errors["pypdf"] = f"{type(exc).__name__}: {exc}"
    return pages


_NON_QUOTED_KEYS = re.compile(r"page|period|timezone|^logic$", re.I)  # where-to-look / label fields, not quoted facts


def _int_leaves(value: Any, key: str = "") -> list[tuple[str, int]]:
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in _int_leaves(v, str(k))]
    if isinstance(value, list):
        return [x for v in value for x in _int_leaves(v, key)]
    if isinstance(value, int) and not isinstance(value, bool) and not _NON_QUOTED_KEYS.search(key):
        return [(key, value)]
    return []


def check_values_in_quotes(export: dict[str, Any]) -> dict[str, Any]:
    """Every integer in a record's structured value must appear in that record's
    own quoted text (so a number cannot have been entered without a source line).
    Dates are covered by the weekday/date cross-check, so ISO strings are skipped here."""
    unmatched = []
    checked = 0
    for eid, ev in export["evidence"].items():
        quotes = _norm(" ".join(p["quote"] for p in ev.get("proofs", []))).replace(",", "")
        for key, n in _int_leaves(ev.get("value")):
            checked += 1
            if not re.search(rf"(?<!\d){n}(?!\d)", quotes):
                unmatched.append({"evidence_id": eid, "key": key, "value": n})
    return {"status": "pass" if not unmatched else "fail", "integers_checked": checked, "not_in_own_quotes": unmatched}


def check_source_pdfs(export: dict[str, Any], pdf_dir: Path | None) -> dict[str, Any]:
    # Evidence taken from an HTML page (no PDF, source_pdf_sha256 null) cannot be checked against a
    # PDF and is never presented as if it had been: it is listed and caps the status at "review".
    non_pdf = sorted(eid for eid, e in export["evidence"].items() if not e.get("source_pdf_sha256"))
    pdf_evidence = {eid: e for eid, e in export["evidence"].items() if e.get("source_pdf_sha256")}
    if not pdf_evidence:
        return {"status": "skipped", "reason": "no PDF-backed evidence in this export (HTML sources are not checked against a PDF)",
                "non_pdf_evidence": non_pdf}
    if pdf_dir is None:
        return {"status": "skipped", "reason": "no --pdf-dir: original PDFs not verified", "non_pdf_evidence": non_pdf}
    by_sha: dict[str, dict[str, Any]] = {}
    library_errors: dict[str, dict[str, str]] = {}
    for sha in sorted({e["source_pdf_sha256"] for e in pdf_evidence.values()}):
        path = pdf_dir / f"{sha}.pdf"
        if not path.is_file():
            by_sha[sha] = {"found": False}
            continue
        errors: dict[str, str] = {}
        by_sha[sha] = {"found": True, "hash_matches": hashlib.sha256(path.read_bytes()).hexdigest() == sha,
                       "pages": _pdf_pages(path, errors)}
        if errors:
            library_errors[sha[:12]] = errors
    missing_pdfs = [s for s, d in by_sha.items() if not d["found"]]
    bad_hash = [s for s, d in by_sha.items() if d["found"] and not d["hash_matches"]]
    if missing_pdfs and len(missing_pdfs) == len(by_sha):
        return {"status": "skipped", "reason": f"none of the {len(by_sha)} source PDFs is in {pdf_dir.name}: their quotes are NOT verified",
                "pdfs_missing": [s[:12] for s in missing_pdfs]}
    libs = sorted({lib for d in by_sha.values() if d.get("found") for lib in d["pages"]})
    total = {lib: 0 for lib in libs}
    found = {lib: 0 for lib in libs}
    unresolved: list[str] = []
    weekday_checked = weekday_bad = 0
    for eid, ev in pdf_evidence.items():
        d = by_sha.get(ev["source_pdf_sha256"])
        if not d or not d.get("found"):
            continue
        for proof in ev.get("proofs", []):
            q = _norm(proof["quote"])
            hit_any = False
            for lib in libs:
                total[lib] += 1
                pages = d["pages"][lib]
                ok = proof["page"] - 1 < len(pages) and q in pages[proof["page"] - 1]
                found[lib] += ok
                hit_any = hit_any or ok
            if libs and not hit_any:
                unresolved.append(f"{eid} p.{proof['page']}")
            for m in re.finditer(r"(?:令和(\d+)|(\d{4}))年(\d+)月(\d+)日[（(]([月火水木金土日])[）)]", q):
                year = int(m.group(1)) + 2018 if m.group(1) else int(m.group(2))
                weekday_checked += 1
                weekday_bad += _WEEKDAYS[datetime.date(year, int(m.group(3)), int(m.group(4))).weekday()] != m.group(5)
    if bad_hash or unresolved or weekday_bad or not libs:
        status = "fail"
    elif missing_pdfs or non_pdf:
        status = "review"  # what could be checked passed; the rest is NOT verified
    else:
        status = "pass"
    return {"status": status, "non_pdf_evidence": non_pdf, "pdfs_missing": [s[:12] for s in missing_pdfs], "pdfs_hash_mismatch": bad_hash,
            "extraction_libraries": libs, "library_errors": library_errors,
            "proofs_checked": total, "proofs_found": found,
            "proofs_not_found_by_any_library": unresolved,
            "weekday_checks": weekday_checked, "weekday_mismatches": weekday_bad}


# ------------------------------------------------------------ export + QA

def check_export(export: dict[str, Any]) -> dict[str, Any]:
    from src.article_qa.evaluate import evaluate_article
    from src.integration.validate_export import validate_records

    gate = validate_records(export["evidence"])
    articles = []
    for a in export["articles"]:
        report = evaluate_article(a["article_id"], a["text"], a["claim"], export["evidence"])
        articles.append({"article_id": a["article_id"], "ok": report.ok, "findings": report.findings})
    gate_ok = gate["invalid_count"] == 0
    return {"status": "pass" if gate_ok and all(a["ok"] for a in articles) else "fail",
            "evidence_records": len(export["evidence"]),
            "gate": {k: gate[k] for k in ("total", "ok_count", "invalid_count")}, "articles": articles}


# ------------------------------------------------------------------ privacy

_PRIVACY_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone_jp": re.compile(r"(?<!\d)0\d{1,4}-\d{1,4}-\d{3,4}(?!\d)"),
    "api_key": re.compile(r"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|AKIA[0-9A-Z]{16})"),
    "private_key": re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"),
    "secret_assignment": re.compile(r"(?i)\b(?:api[_-]?key|secret|password|token)\s*[=:]\s*['\"]?\w{8,}"),
    "windows_user_path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+"),
}


def _scan_text(name: str, text: str, findings: list[dict[str, str]]) -> None:
    for kind, pattern in _PRIVACY_PATTERNS.items():
        for m in pattern.finditer(text):
            findings.append({"where": name, "kind": kind, "sample": m.group(0)[:40]})


def check_privacy(root: Path, database: Path | None) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    scanned = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        if path.suffix == ".gz":
            data = gzip.decompress(data)
            if data[:15] == b"SQLite format 3":
                continue  # database cells are scanned below
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        _scan_text(rel, text, findings)
    cells = 0
    if database is not None:
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as db:
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                for row in db.execute(f'SELECT * FROM "{table}"'):
                    for cell in row:
                        if isinstance(cell, str):
                            cells += 1
                            _scan_text(f"db:{table}", cell, findings)
    return {"status": "pass" if not findings else "fail", "files_scanned": scanned, "db_text_cells_scanned": cells,
            "findings": findings}


# ------------------------------------------------------------- whole views

def _find_views(root: Path) -> dict[str, Any]:
    """Whole-view deliveries (`*active-state*.json` / `*full-view*.json`, Issue #48): the current state of all
    universities, repeating evidence ids of earlier deliveries on purpose. An unreadable file is kept, as a problem."""
    from src.regression.fullview import CANONICAL_VIEW_NAMES, VIEW_GLOBS, looks_like_view
    found: dict[str, Any] = {}
    for pattern in VIEW_GLOBS:
        for p in sorted(root.rglob(pattern)):
            if p.name == "claude-compatible-export.json":
                continue
            try:
                data: Any = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                data = {"_unreadable": type(exc).__name__}
            # Work's own REPORTS (qa/full-view-final.json, ...) match the glob but are not views; a canonical
            # name (active-state.json / full-view.json) is always a view, so a broken one fails instead of vanishing
            if p.name in CANONICAL_VIEW_NAMES or looks_like_view(data):
                found[p.relative_to(root).as_posix()] = data
    return found


def check_whole_view(root: Path, name: str, view: Any) -> dict[str, Any]:
    """A whole view is audited as an export (gate + article QA) AND as a view: its shape, which evidence ids repeat an
    earlier delivery legitimately and which collide, and the revision history of its articles. The earlier
    deliveries are the other handoffs next to this one (research/inbox/*). Nothing here reads an original PDF/HTML."""
    from src.regression.fullview import article_history, evidence_reuse, find_base_states, view_shape_problems
    from src.regression.handoffs import find_exports

    shape = view_shape_problems(view)
    if shape:
        return {"status": "fail", "mode": "whole_view", "view": name, "shape_problems": shape, "evidence_records": 0,
                "gate": {"total": 0, "ok_count": 0, "invalid_count": 0}, "articles": [], "failures": shape,
                "original_source_comparison": "not_run"}
    inbox = root.parent
    priors = {r.key: r.load() for r in find_exports(inbox) if r.handoff != root.name}
    bases = find_base_states(inbox)  # earlier states of any handoff: used only to find the text a revision changed
    reuse = evidence_reuse(view, priors)
    history = article_history(view, priors, bases)
    base = check_export(view)
    failures = [f"evidence id {c['evidence_id']} also in {c['against']} but differs in {c['differs']}" for c in reuse["collisions"]]
    failures += history["failures"]
    status = "fail" if failures or base["status"] == "fail" else ("review" if history["notices"] else "pass")
    return {**base, "status": status, "mode": "whole_view", "view": name, "shape_problems": [],
            "evidence_reuse": {k: reuse[k] for k in ("reused", "new", "collisions", "retrieved_at_differs")},
            "article_history": {k: history[k] for k in ("same_text", "new", "revisions", "failures", "notices")},
            "failures": failures, "original_source_comparison": "not_run"}


# --------------------------------------------------------------------- main

def _find_exports(root: Path) -> dict[str, dict[str, Any]]:
    """Every claude-compatible-export.json under the handoff (v0.2 keeps one in samples/,
    national-v1 one per case under samples/<case>/)."""
    return {p.relative_to(root).as_posix(): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(root.rglob("claude-compatible-export.json"))}


def _worst(statuses: list[str]) -> str:
    for s in ("fail", "review", "pass", "skipped"):
        if s in statuses:
            return s
    return "skipped"


def audit(root: Path, pdf_dir: Path | None = None, original_db: Path | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"handoff": root.name}  # name only: reports must not embed local absolute paths
    report["manifest"] = check_manifest(root)
    gz = root / "data" / "admission_media_v0_2.sqlite.gz"
    exports = _find_exports(root)
    views = _find_views(root)
    export = next(iter(exports.values())) if len(exports) == 1 else None  # the DB reconciliation is v0.2-specific
    with tempfile.TemporaryDirectory() as tmp:
        db_path = None
        if gz.is_file():
            db_path = Path(tmp) / "handoff-copy.sqlite"
            db_path.write_bytes(gzip.decompress(gz.read_bytes()))
            report["database"] = check_database(db_path, original_db)
            wanted = None
            if (root / "manifest.json").is_file():
                wanted = json.loads((root / "manifest.json").read_text(encoding="utf-8")).get("gzip_uncompressed_database_sha256")
            if wanted:
                report["database"]["matches_manifest_gzip_uncompressed_sha256"] = report["database"]["sha256"] == wanted
        else:
            report["database"] = {"status": "skipped", "reason": "no data/admission_media_v0_2.sqlite.gz in this handoff"}
        recon_path = root / "qa" / "reconciliation-27.json"
        if db_path and export and recon_path.is_file():
            report["reconciliation"] = check_reconciliation(db_path, json.loads(recon_path.read_text(encoding="utf-8")), export["evidence"])
        else:
            report["reconciliation"] = {"status": "skipped", "reason": "no legacy DB / reconciliation in this handoff"}
        report["privacy"] = check_privacy(root, db_path)
    if not exports and not views:
        for key in ("source_pdfs", "values_in_quotes", "export"):
            report[key] = {"status": "skipped", "reason": "no claude-compatible-export.json and no whole view (*active-state*.json / *full-view*.json) in this handoff"}
    else:
        per = {name: {"source_pdfs": check_source_pdfs(e, pdf_dir), "values_in_quotes": check_values_in_quotes(e), "export": check_export(e)}
               for name, e in exports.items()}
        for name, v in views.items():
            shaped = isinstance(v, dict) and isinstance(v.get("evidence"), dict) and all(isinstance(e, dict) for e in v["evidence"].values()) \
                and isinstance(v.get("articles"), list)
            bad = {"status": "fail", "integers_checked": 0, "not_in_own_quotes": []}
            per[name] = {"source_pdfs": check_source_pdfs(v, pdf_dir) if shaped else {"status": "fail", "reason": "not a whole view"},
                         "values_in_quotes": check_values_in_quotes(v) if shaped else bad,
                         "export": check_whole_view(root, name, v)}
        for key in ("source_pdfs", "values_in_quotes", "export"):
            parts = {name: r[key] for name, r in per.items()}
            merged: dict[str, Any] = {"status": _worst([r["status"] for r in parts.values()])}
            if key == "values_in_quotes":
                merged["integers_checked"] = sum(r["integers_checked"] for r in parts.values())
                merged["not_in_own_quotes"] = [x for r in parts.values() for x in r["not_in_own_quotes"]]
            elif key == "export":
                merged["evidence_records"] = sum(r["evidence_records"] for r in parts.values())
                merged["gate"] = {k: sum(r["gate"][k] for r in parts.values()) for k in ("total", "ok_count", "invalid_count")}
                merged["articles"] = [a for r in parts.values() for a in r["articles"]]
                merged["whole_views"] = {n: {k: r[k] for k in ("status", "shape_problems", "evidence_reuse", "article_history", "failures",
                                                              "original_source_comparison") if k in r}
                                         for n, r in parts.items() if r.get("mode") == "whole_view"}
            else:
                merged["exports"] = {n: r["status"] for n, r in parts.items()}
                if len(parts) == 1:
                    merged.update(next(iter(parts.values())))
                else:
                    merged["details"] = {n: {k: v for k, v in r.items() if k != "status"} for n, r in parts.items() if r["status"] != "pass"}
            if len(parts) > 1:
                merged["per_export"] = {n: r["status"] for n, r in parts.items()}
            report[key] = merged
    statuses = {k: v["status"] for k, v in report.items() if isinstance(v, dict) and "status" in v}
    report["summary"] = {"statuses": statuses, "exports_checked": sorted(exports), "views_checked": sorted(views), "failed": [k for k, s in statuses.items() if s == "fail"],
                         "needs_review": [k for k, s in statuses.items() if s == "review"],
                         "skipped": [k for k, s in statuses.items() if s == "skipped"]}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("handoff_dir", type=Path)
    parser.add_argument("--pdf-dir", type=Path, default=None)
    parser.add_argument("--original-db", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = audit(args.handoff_dir, args.pdf_dir, args.original_db)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
