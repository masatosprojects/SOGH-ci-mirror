"""Additive v0.4 dimensions on a backed-up v0.3 database; no legacy rewrites."""
import hashlib
import json
from pathlib import Path
from .store import canonical

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycle_dimensions(
 case_id TEXT PRIMARY KEY REFERENCES admission_cycles(case_id),
 selection_category TEXT NOT NULL CHECK(selection_category IN
 ('comprehensive','school_recommendation','general','common_test','special')),
 entry_year INTEGER NOT NULL CHECK(entry_year BETWEEN 2000 AND 2100),
 exam_year INTEGER NOT NULL CHECK(exam_year BETWEEN 2000 AND 2100),
 entry_months_json TEXT NOT NULL,round_name TEXT NOT NULL,scope_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cycle_editions(
 case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
 source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),
 profile_sha256 TEXT NOT NULL,profile_version TEXT NOT NULL,observed_at TEXT NOT NULL,profile_json TEXT,
 PRIMARY KEY(case_id,source_sha256,profile_sha256));
CREATE TABLE IF NOT EXISTS admission_offerings(
 offering_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
 round_name TEXT NOT NULL,entry_month INTEGER CHECK(entry_month BETWEEN 1 AND 12),
 scope_json TEXT NOT NULL,source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256));
INSERT OR IGNORE INTO schema_versions VALUES ('admissions-v0.4-additive-dimensions');
"""


def migrate(store, backup_path):
    # A caller must supply a fresh backup target; refusing overwrite protects history.
    backup = store.snapshot(backup_path)
    sha = hashlib.sha256(backup.read_bytes()).hexdigest()
    with store.connect() as db:
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
        if "profile_json" not in {r[1] for r in db.execute("PRAGMA table_info(cycle_editions)")}:
            db.execute("ALTER TABLE cycle_editions ADD COLUMN profile_json TEXT")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("migration integrity check failed")
    return {"backup": str(backup), "sha256": sha, "rollback": "Stop writers; restore backup to a separate database and verify before switching configuration"}


def save_dimensions(store, profile, observed_at):
    d = profile["dimensions"]
    months = d["entry_months"]
    if (not months and d.get("entry_month_status") != "unconfirmed") or any(type(m) is not int or not 1 <= m <= 12 for m in months) or len(set(months)) != len(months):
        raise ValueError("invalid entry months")
    row = (profile["case_id"], d["selection_category"], profile["fiscal_year"], profile["exam_year"],
           canonical(months), d["round_name"], canonical(d["scope"]))
    with store.connect() as db:
        previous = db.execute("SELECT * FROM cycle_dimensions WHERE case_id=?", (row[0],)).fetchone()
        if previous and tuple(previous) != row:
            raise ValueError("cycle identity changed; create distinct cycle instead")
        db.execute("INSERT OR IGNORE INTO cycle_dimensions VALUES(?,?,?,?,?,?,?)", row)
        db.execute("INSERT OR IGNORE INTO cycle_editions(case_id,source_sha256,profile_sha256,profile_version,observed_at,profile_json) VALUES(?,?,?,?,?,?)", (
            profile["case_id"], profile["sha256"], hashlib.sha256(canonical(profile).encode()).hexdigest(),
            profile["profile_version"], observed_at, canonical(profile)))
        for offering in d.get("offerings", [{"round_name": d["round_name"], "scope": d["scope"], "entry_month": m} for m in (months or [None])]):
            month = offering["entry_month"]
            if month is not None and (type(month) is not int or not 1 <= month <= 12):
                raise ValueError("invalid offering month")
            identity = canonical([row[0], offering["round_name"], month, offering["scope"], profile["sha256"]])
            db.execute("INSERT OR IGNORE INTO admission_offerings VALUES(?,?,?,?,?,?)", (
                hashlib.sha256(identity.encode()).hexdigest(), row[0], offering["round_name"], month,
                canonical(offering["scope"]), profile["sha256"]))
