"""Preserve v0.2 verbatim and link each old claim to freshly checked PDF facts.

Old `verified` flags and summary-file hashes are never evidence of PDF checking.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .store import canonical

CYCLE_MAP = {"cy_tsu_klis_2027": "tsukuba-klis-ac-2027",
             "cy_keio_env_2027apr": "keio-environment-ao-2026s-2027"}
FIELD_MAP = {"intake_count": "quota", "web_application_open": "online_period",
    "web_application_close": "online_period", "mail_window": "postal_period",
    "selection_first": "first_stage", "selection_second": "interview", "interview_day": "second_stage_date"}
SECRET_PATTERNS = {
    "github_token": r"\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})\b",
    "api_key": r"\b(?:AIza[A-Za-z0-9_-]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,})\b",
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "credential_assignment": r"(?i)(?:api[_ -]?key|cookie|password|access[_ -]?token)\s*[=:]\s*['\"]?[A-Za-z0-9_+/=-]{16,}",
}


def inspect_legacy(path):
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        required = {"fact_claims", "fact_evidence", "source_snapshots", "admission_cycles", "universities"}
        if not required <= set(tables):
            raise ValueError("not the expected admissions v0.2 database")
        counts, records, schema = {}, {}, {}
        for table in tables:
            q = '"' + table.replace('"', '""') + '"'
            records[table] = [dict(r) for r in db.execute("SELECT * FROM " + q)]
            counts[table] = len(records[table])
            schema[table] = [dict(r) for r in db.execute("PRAGMA table_info(" + q + ")")]
        integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
        foreign_keys = [list(r) for r in db.execute("PRAGMA foreign_key_check")]
        freelist_pages = db.execute("PRAGMA freelist_count").fetchone()[0]
    findings = []
    for table, rows in records.items():
        if table in ("experience_reports", "experience_observations", "publications") and rows:
            findings.append({"table": table, "reason": "personal_or_external_account_records_require_manual_redaction"})
        for n, row in enumerate(rows):
            for field, value in row.items():
                if isinstance(value, str):
                    for kind, pattern in SECRET_PATTERNS.items():
                        if re.search(pattern, value):
                            findings.append({"table": table, "row": n, "field": field, "reason": kind})
    if freelist_pages:
        findings.append({"reason": "freelist_pages_require_scrubbed_export_before_sharing", "pages": freelist_pages})
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "counts": counts,
            "schema": schema, "records": records, "integrity": integrity, "foreign_keys": foreign_keys,
            "privacy_findings": findings, "summaries_are_not_pdf_originals": True}


def compare(old, fact):
    a, b, key = json.loads(old["value_json"]), fact["value"], old["field_key"]
    def eq(left, right):
        return canonical(left) == canonical(right)
    checks, enrichment = [], False
    if key == "intake_count":
        checks.append(eq(a.get("value"), b["count"]))
        if fact["scope"] == "faculty_annual_AO_aggregate":
            scope = a.get("scope", "")
            checks.append(all(t in scope for t in ("2026", "AO", "合計", "4", "9")))
            checks.append("のみの人数ではない" in old["display_statement"])
        else:
            checks.append("当学類" in a.get("scope", "") and "AC" in a.get("scope", ""))
    elif key in ("web_application_open", "web_application_close"):
        checks.append(eq(a.get("datetime"), b["start" if key.endswith("open") else "end"]))
    elif key == "mail_window":
        checks.extend([eq(a.get("start"), b["start"]), eq(a.get("end"), b["end"])])
        checks.append(("必着" in a.get("deadline_rule", "")) if fact["case_id"].startswith("tsukuba") else ("国内" in a.get("deadline_rule", "") and "消印有効" in a.get("deadline_rule", "")))
        enrichment = True
    elif key == "selection_first":
        checks.append(a.get("method") == "書類審査")
    elif key == "selection_second":
        if "minutes_approx" in a:
            checks.extend([eq(a["minutes_approx"], b["minutes"]), a.get("extension_possible") is True,
                           b["type"] == "individual_interview_and_oral_exam"])
        else:
            checks.extend([eq(a.get("time_slot_minutes_approx"), b["minutes"]),
                           b["type"] == "allocated_time_window_not_net_question_time",
                           "時間枠" in old["display_statement"]])
    elif key == "interview_day":
        checks.append(eq(a.get("dates", [a.get("date")]), b["dates"]))
        if len(b["dates"]) > 1:
            checks.append(b["selection"] == "one_of_not_both" and "いずれか" in old["display_statement"])
    elif key in ("first_stage_result", "final_result"):
        if "datetime" in a:
            checks.append(eq(a["datetime"], b["date"] + "T" + b["time"] + ":00+09:00"))
        else:
            checks.append(eq(a.get("date"), b["date"]))
            enrichment = True
    elif key == "statement_length":
        checks.append(eq(a.get("max_characters"), b["max_characters"]))
    elif key == "recommendation_format":
        checks.extend([a.get("format") == b["body_format"], a.get("length_limit") == "指定なし",
                       a.get("supporting_materials") is True, b["supporting_materials"] is True])
        enrichment = True
    elif key == "common_test":
        checks.append(eq(a.get("required"), b["required"]))
    elif key == "interview_scope":
        checks.append(eq(a.get("topic_types"), b["topic_types"]))
    elif key == "personal_statement":
        checks.extend(eq(a.get(k), b[k]) for k in ("essay_max_ja_chars", "free_format_a4_pages_max"))
        enrichment = True
    elif key in ("optional_materials", "referees"):
        field = "max_items" if key == "optional_materials" else "evaluators_required"
        checks.append(eq(a.get(field), b[field]))
        enrichment = key == "referees"
    elif key == "generative_ai_policy":
        checks.append(eq(a, b))
    elif key == "interview_language":
        checks.extend([eq(a.get("languages"), b["languages"]), a.get("choice_required") is True])
        enrichment = True
    if not checks:
        return "needs_review", "unsupported_legacy_field"
    if not all(checks):
        return "conflict", "legacy_value_or_scope_does_not_match_original"
    return ("matched_with_added_context" if enrichment else "matched_saved_original"), "original_pdf_profile_checked"


def integrate_legacy(store, snapshot, packs, *, original_path=None):
    data = inspect_legacy(snapshot)
    if data["integrity"] != ["ok"] or data["foreign_keys"] or data["privacy_findings"]:
        raise ValueError("legacy integrity/privacy gate requires review")
    native = {p["cycle"]["case_id"]: {f["key"]: f for f in p["facts"]} for p in packs}
    links = []
    for row in data["records"]["fact_claims"]:
        case_id = CYCLE_MAP.get(row["cycle_id"])
        fact = native.get(case_id, {}).get(FIELD_MAP.get(row["field_key"], row["field_key"]))
        if fact is None:
            status, reason = "needs_review", "target_original_profile_not_available"
        else:
            status, reason = compare(row, fact)
        links.append({"legacy_fact_id": row["id"], "legacy_cycle_id": row["cycle_id"],
            "case_id": case_id, "legacy_field": row["field_key"], "status": status, "reason": reason,
            "evidence_id": fact["evidence_id"] if fact else None,
            "new_pdf_sha256": fact["source_pdf_sha256"] if fact else None,
            "pages": sorted({p["page"] for p in fact["proofs"]}) if fact else [],
            "legacy_review_status_not_trusted": row["review_status"],
            "legacy_entry_scope": "2027-04"})
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS legacy_records(
          legacy_sha256 TEXT NOT NULL REFERENCES legacy_imports(file_sha256),table_name TEXT NOT NULL,
          record_key TEXT NOT NULL,record_json TEXT NOT NULL,PRIMARY KEY(legacy_sha256,table_name,record_key))""")
        db.execute("""CREATE TABLE IF NOT EXISTS legacy_fact_links(
          legacy_sha256 TEXT NOT NULL REFERENCES legacy_imports(file_sha256),legacy_fact_id TEXT NOT NULL,
          case_id TEXT REFERENCES admission_cycles(case_id),evidence_id TEXT REFERENCES facts(evidence_id),
          status TEXT NOT NULL,report_json TEXT NOT NULL,PRIMARY KEY(legacy_sha256,legacy_fact_id))""")
        audit = {k: data[k] for k in ("counts", "schema", "integrity", "foreign_keys", "privacy_findings")}
        db.execute("INSERT OR IGNORE INTO legacy_imports VALUES (?,?,?,?,0)",
                   (data["sha256"], str(original_path or snapshot), str(snapshot), canonical(audit)))
        for table, rows in data["records"].items():
            primary = sorted((c for c in data["schema"][table] if c["pk"]), key=lambda c: c["pk"])
            for index, row in enumerate(rows):
                key = canonical([row[c["name"]] for c in primary]) if primary else str(index)
                db.execute("INSERT OR IGNORE INTO legacy_records VALUES (?,?,?,?)", (data["sha256"], table, key, canonical(row)))
        for link in links:
            db.execute("INSERT OR REPLACE INTO legacy_fact_links VALUES (?,?,?,?,?,?)",
                       (data["sha256"], link["legacy_fact_id"], link["case_id"] if link["case_id"] in native else None,
                        link["evidence_id"], link["status"], canonical(link)))
    counts = {status: sum(l["status"] == status for l in links) for status in ("matched_saved_original", "matched_with_added_context", "needs_review", "conflict")}
    return {"integrated": True, "mode": "immutable_legacy_records_and_original_fact_links",
        "legacy_snapshot": str(snapshot), "legacy_sha256": data["sha256"], "legacy_table_counts": data["counts"],
        "records_preserved": sum(data["counts"].values()), "reconciliation_counts": counts, "fact_links": links,
        "privacy_findings": data["privacy_findings"], "old_verified_flags_promoted": False,
        "summary_hashes_used_as_pdf_hashes": False, "publication_allowed": False}
