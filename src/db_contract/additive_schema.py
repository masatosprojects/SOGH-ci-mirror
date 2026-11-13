"""Additive schema proposals G-02, G-04, G-05 and G-09 for the admissions database (migrations 0002, 0003 and 0004 are FROZEN SQL FILES under src/db_contract/migrations/). A DRAFT written by Claude while Work is unavailable
(labels: SELF_VALIDATED, WORK_CONTRACT_REVIEW_PENDING; see docs/G04_G05_CONTRACT.md and docs/TEMPORARY_WORK_LEDGER.md).

What it does: a migration runner (G-02: `schema_migrations(version, from_version, applied_at, checksum)` and `PRAGMA user_version`, as docs/DB_MIGRATION_REQUIREMENTS.md asks) and three migrations that only ADD objects:
  0002  G-04  a unique identity for a cycle and for an offering that treats a missing department / entry month as one "unspecified" value
  0003  G-05  a root / alias model for evidence ids (no id is renamed, no row is updated or deleted)
  0004  G-09  frozen SQL: capability gate, append-only tables, update_batches transitions, heads only for approved batches (they guard future writes; they never repair the past, F-2 stays open)

Safety rules (all tested): nothing is applied unless every pending preflight passes; the whole run is one transaction (a failure leaves the file byte-for-byte as it was
apart from nothing at all); running it again changes nothing; no existing row is touched. `apply` refuses a file that has a journal or WAL sidecar and requires the
caller to say that the file is a disposable copy. NEVER run it on an original database: the DDL is not approved for any original (Work and the user decide that).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.db_contract import identity

# the layout asked for by docs/DB_MIGRATION_REQUIREMENTS.md: schema_migrations(version, from_version, applied_at, checksum), plus additive columns (description, seq, applied statements)
SCHEMA_MIGRATIONS = """CREATE TABLE IF NOT EXISTS schema_migrations(
 version TEXT PRIMARY KEY, from_version TEXT, applied_at TEXT NOT NULL, checksum TEXT NOT NULL CHECK(length(checksum)=64),
 description TEXT NOT NULL, seq INTEGER NOT NULL UNIQUE, statements_applied_sha256 TEXT NOT NULL CHECK(length(statements_applied_sha256)=64),
 applied_statement_ids TEXT NOT NULL)"""

def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class MigrationError(ValueError):
    """The migration history and the code disagree (a checksum, an unknown or out-of-order migration, a user_version drift): nothing is applied."""


# ---- frozen SQL files (G-04 and G-05) ---------------------------------------------------------------------------------------------------------
MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"
_SEPARATOR = re.compile(r"^-- @@(.*)$", re.M)


def parse_frozen(text: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """A frozen migration file -> ((statement, required tables), ...). Statements are separated by `-- @@` lines (which may say `requires: table NAME[, table NAME]`);
    the part before the first separator is the file header. A statement holds no comment line, so the text that is executed is exactly the text that is checked later."""
    pieces = _SEPARATOR.split(text)
    out = []
    for header, body in zip(pieces[1::2], pieces[2::2]):
        statement = body.strip().rstrip(";").strip()
        if not statement or any(line.lstrip().startswith("--") for line in statement.splitlines()):
            raise MigrationError("a frozen migration statement is empty or holds a comment")
        tables = tuple(t.strip() for t in re.findall(r"table\s+(\w+)", header))
        out.append((statement, tables))
    return tuple(out)


def _frozen(filename: str) -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    text = (MIGRATION_DIR / filename).read_bytes().decode("utf-8")
    return text, parse_frozen(text)


def frozen_statement_ids(parsed: tuple[tuple[str, tuple[str, ...]], ...], db: sqlite3.Connection) -> list[int]:
    t = _tables(db)
    return [i for i, (_, needs) in enumerate(parsed) if all(n in t for n in needs)]


def preflight_g04(db: sqlite3.Connection) -> list[str]:
    problems = []
    t = _tables(db)
    if "admission_cycles" not in t:
        return ["not_applicable: no admission_cycles table (another schema lineage)"]
    for row in db.execute("SELECT university, faculty, COALESCE(department,''), admission_method, fiscal_year, count(*) FROM admission_cycles GROUP BY 1,2,3,4,5 HAVING count(*) > 1"):
        problems.append(f"cycle identity collision ({row[5]} rows): the same university, faculty, department-or-unspecified, method and entry year")
    if "admission_offerings" in t:  # the source is NOT part of an offering's identity: one offering described by two documents is one offering (offering_sources links both)
        for row in db.execute("SELECT case_id, round_name, COALESCE(entry_month,-1), count(*) FROM admission_offerings GROUP BY case_id, round_name, COALESCE(entry_month,-1), scope_json HAVING count(*) > 1"):
            problems.append(f"offering identity collision ({row[3]} rows) in case {row[0]!r}")
    return problems


def preflight_g05(db: sqlite3.Connection) -> list[str]:
    t = _tables(db)
    problems = []
    if not {"facts", "evidence_revisions"} <= t:
        problems.append("not_applicable: needs facts and evidence_revisions (schema v0.5 lineage)")
    if "evidence_aliases" in t:
        problems.append("evidence_aliases already exists under another definition: stop")
    return problems


# ---- G-09 -----------------------------------------------------------------------------------------------------------------------------------
# Every table of the v0.5+ lineage, classified from the contract (DB-09) and from the statements Work's code really runs
# (research/inbox/work-faq-v3/pipeline: UPDATE / DELETE / INSERT OR REPLACE / ON CONFLICT, read on 2026-11-01).
TABLE_CLASS = {
    "A": ("facts", "source_documents", "source_pages", "evidence_revisions", "article_versions", "revised_articles", "article_evidence", "batch_evidence", "update_events",
          "cycle_editions", "qa_runs", "schema_versions", "schema_migrations"),  # append-only: no UPDATE, no DELETE (evidence_aliases has its own triggers from 0003)
    "B": ("evidence_heads", "article_heads", "update_batches"),  # legitimate writers: heads move (upsert, delete and re-insert on rollback); a batch changes state
    "C": ("legacy_fact_links",),  # Work's importer uses INSERT OR REPLACE on purpose: left unprotected until Work decides
    "D": ("legacy_imports", "legacy_records", "admission_cycles", "admission_offerings", "cycle_dimensions"),  # contract not fixed; only the identity columns and DELETE are guarded
}
def preflight_g09(db: sqlite3.Connection) -> list[str]:
    """The triggers guard future writes; they never repair the past. Stop when an existing head would already break the head rules (the data is reported, not changed)."""
    t = _tables(db)
    problems = []
    if not {"evidence_revisions", "update_batches", "batch_evidence"} <= t:
        return ["not_applicable: needs the v0.5 revision tables"]
    for logical, eid in db.execute("SELECT logical_id, evidence_id FROM evidence_heads"):
        ok = db.execute("SELECT 1 FROM evidence_revisions r JOIN batch_evidence e ON e.evidence_id = r.evidence_id JOIN update_batches b ON b.batch_id = e.batch_id "
                        "WHERE r.evidence_id = ? AND r.logical_id = ? AND b.state = 'approved'", (eid, logical)).fetchone()
        if not ok:
            problems.append(f"an existing evidence head ({logical!r}) is not a revision of its logical id in an APPROVED update batch")
    for base, aid in db.execute("SELECT base_article_id, article_id FROM article_heads"):
        ok = db.execute("SELECT 1 FROM revised_articles r JOIN update_batches b ON b.batch_id = r.batch_id WHERE r.article_id = ? AND r.base_article_id = ? AND b.state = 'approved'", (aid, base)).fetchone()
        if not ok:
            problems.append(f"an existing article head ({base[:40]!r}) is not a revision of its base article in an APPROVED update batch")
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    clash = sorted(n for n in (re.findall(r"CREATE TRIGGER (\w+)", st)[0] for st, _needs in _PARSED_0004) if n in existing)
    if clash:
        problems.append("trigger names already exist: " + ", ".join(clash))
    return problems


def preflight_g07(db: sqlite3.Connection) -> list[str]:
    t = _tables(db)
    if not {"revised_articles", "article_versions", "article_evidence", "facts", "evidence_revisions", "evidence_aliases"} <= t:
        return ["not_applicable: needs the v0.5 revision tables and the alias table of migration 0003"]
    if "revised_article_evidence" in t:
        return ["revised_article_evidence already exists under another definition: stop"]
    try:
        db.execute("SELECT json_extract('{\"a\":[1]}', '$.a[0]'), count(*) FROM json_each('[1]')").fetchone()
    except sqlite3.DatabaseError:
        return ["SQLite JSON1 is not available: stop"]
    return []


def preflight_g11(db: sqlite3.Connection) -> list[str]:
    t = _tables(db)
    if "update_batches" not in t:
        return ["not_applicable: needs update_batches"]
    clash = sorted({"revision_reasons", "revision_reason_corrections", "revision_reason_contract"} & t)
    return [f"{', '.join(clash)} already exist under another definition: stop"] if clash else []


def preflight_g06(db: sqlite3.Connection) -> list[str]:
    t = _tables(db)
    if "source_documents" not in t:
        return ["not_applicable: needs source_documents"]
    clash = sorted({"source_document_metadata", "source_verification_events"} & t)
    return [f"{', '.join(clash)} already exist under another definition: stop"] if clash else []


def preflight_g03(db: sqlite3.Connection) -> list[str]:
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    clash = sorted(n for n in (re.findall(r"CREATE INDEX (\w+)", st)[0] for st, _needs in _PARSED_0008) if n in names)
    return [f"index names already exist: {', '.join(clash)}"] if clash else []


def preflight_m14(db: sqlite3.Connection) -> list[str]:
    t = _tables(db)
    if not {"update_events", "update_batches"} <= t:
        return ["not_applicable: needs update_events and update_batches"]
    if "v_head_events" in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='view'")}:
        return ["v_head_events already exists under another definition: stop"]
    return []


RESTORE_HISTORY_TABLES = ("restore_events", "restore_revocations", "restored_articles", "evidence_history_versions", "article_history_pins")


def preflight_g03_history(db: sqlite3.Connection) -> list[str]:
    """0010 creates five NEW tables and their guards. A table or a trigger of those names that exists already has a definition nobody has checked: stop (nothing is adopted, nothing is repaired)."""
    tables = _tables(db)
    clash = sorted(t for t in RESTORE_HISTORY_TABLES if t in tables)
    triggers = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    own = sorted(n for n in triggers if any(n.startswith(f"trg_{t}_") for t in RESTORE_HISTORY_TABLES))
    problems = []
    if clash:
        problems.append(f"tables already exist under another definition: {', '.join(clash)}")
    if own:
        problems.append(f"triggers already exist: {', '.join(own)}")
    return problems


ALIAS_PROVENANCE_TABLES = ("alias_provenance_bundles", "source_representations")
FAQ_UNCONFIRMED_TABLES = ("faq_unconfirmed_evidence",)
QUARANTINE_TABLES = ("quarantine_staging_candidates", "_quarantine_approval_seals", "canonical_facts_staging_target")
QUARANTINE_TRIGGER_PREFIXES = ("trg_quarantine_", "trg_canonical_")
SERIES_TABLES = ("source_document_series_editions", "series_revision_article_impacts")
SERIES_TRIGGER_PREFIXES = ("trg_series_",)


def preflight_g05_provenance(db: sqlite3.Connection) -> list[str]:
    """0011 creates two NEW tables and their guards and needs the tables they refer to. A table or trigger of those names that exists already has a definition nobody has checked: stop."""
    t = _tables(db)
    if not {"evidence_aliases", "source_documents"} <= t:
        return ["not_applicable: needs evidence_aliases (0003) and source_documents"]
    problems = []
    clash = sorted(x for x in ALIAS_PROVENANCE_TABLES if x in t)
    if clash:
        problems.append(f"tables already exist under another definition: {', '.join(clash)}")
    own = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'") if any(r[0].startswith(f"trg_{x}_") for x in ALIAS_PROVENANCE_TABLES))
    if own:
        problems.append(f"triggers already exist: {', '.join(own)}")
    return problems


def preflight_g02_faq_unconfirmed(db: sqlite3.Connection) -> list[str]:
    """0012 creates ONE new table and its guards and needs admission_cycles, source_documents and facts. A table or trigger of that name that exists already has a definition nobody has checked: stop."""
    t = _tables(db)
    if not {"admission_cycles", "source_documents", "facts"} <= t:
        return ["not_applicable: needs admission_cycles, source_documents and facts"]
    problems = []
    clash = sorted(x for x in FAQ_UNCONFIRMED_TABLES if x in t)
    if clash:
        problems.append(f"tables already exist under another definition: {', '.join(clash)}")
    own = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'") if any(r[0].startswith(f"trg_{x}_") for x in FAQ_UNCONFIRMED_TABLES))
    if own:
        problems.append(f"triggers already exist: {', '.join(own)}")
    return problems


def _preflight_new_tables(db: sqlite3.Connection, tables: tuple[str, ...], trigger_prefixes: tuple[str, ...]) -> list[str]:
    """A migration that creates only NEW tables and their guards: a table or trigger of those names that exists already has a definition nobody has checked: stop."""
    t = _tables(db)
    problems = []
    clash = sorted(x for x in tables if x in t)
    if clash:
        problems.append(f"tables already exist under another definition: {', '.join(clash)}")
    own = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'") if any(r[0].startswith(pf) for pf in trigger_prefixes))
    if own:
        problems.append(f"triggers already exist: {', '.join(own)}")
    return problems


def preflight_g07_quarantine(db: sqlite3.Connection) -> list[str]:
    return _preflight_new_tables(db, QUARANTINE_TABLES, QUARANTINE_TRIGGER_PREFIXES)


def preflight_g06_series(db: sqlite3.Connection) -> list[str]:
    return _preflight_new_tables(db, SERIES_TABLES, SERIES_TRIGGER_PREFIXES)


def _frozen_statements(parsed):
    def statements(db: sqlite3.Connection) -> tuple[str, ...]:
        return tuple(parsed[i][0] for i in frozen_statement_ids(parsed, db))
    statements.frozen = parsed  # type: ignore[attr-defined]
    return statements


_TEXT_0002, _PARSED_0002 = _frozen("0002_g04_cycle_and_offering_identity.sql")
_TEXT_0003, _PARSED_0003 = _frozen("0003_g05_evidence_root_alias.sql")
_TEXT_0004, _PARSED_0004 = _frozen("0004_g09_append_only_and_head_integrity.sql")
_TEXT_0005, _PARSED_0005 = _frozen("0005_g07_revised_article_evidence.sql")
_TEXT_0006, _PARSED_0006 = _frozen("0006_g11_revision_reasons.sql")
_TEXT_0007, _PARSED_0007 = _frozen("0007_g06_source_metadata_and_verification.sql")
_TEXT_0008, _PARSED_0008 = _frozen("0008_g03_lookup_indexes.sql")
_TEXT_0009, _PARSED_0009 = _frozen("0009_m14_head_history.sql")
_TEXT_0010, _PARSED_0010 = _frozen("0010_g03_restore_history.sql")
_TEXT_0011, _PARSED_0011 = _frozen("0011_g05_alias_provenance.sql")
_TEXT_0012, _PARSED_0012 = _frozen("0012_g02_faq_unconfirmed_evidence.sql")
_TEXT_0013, _PARSED_0013 = _frozen("0013_g07_quarantine_staging.sql")
_TEXT_0014, _PARSED_0014 = _frozen("0014_g06_source_series.sql")
statements_g04 = _frozen_statements(_PARSED_0002)
statements_g05 = _frozen_statements(_PARSED_0003)
statements_g09 = _frozen_statements(_PARSED_0004)
statements_g07 = _frozen_statements(_PARSED_0005)
statements_g11 = _frozen_statements(_PARSED_0006)
statements_g06 = _frozen_statements(_PARSED_0007)
statements_g03 = _frozen_statements(_PARSED_0008)
statements_m14 = _frozen_statements(_PARSED_0009)
statements_g03_history = _frozen_statements(_PARSED_0010)
statements_g05_provenance = _frozen_statements(_PARSED_0011)
statements_g02_faq = _frozen_statements(_PARSED_0012)
statements_g07_quarantine = _frozen_statements(_PARSED_0013)
statements_g06_series = _frozen_statements(_PARSED_0014)


# (id, description, statements for this database, preflight, the DEFINITION used for the checksum: it does not depend on which lineage the file has)
MIGRATIONS: tuple[tuple[str, str, Callable[[sqlite3.Connection], tuple[str, ...]], Callable[[sqlite3.Connection], list[str]], str], ...] = (
    ("0002-g04-cycle-and-offering-identity", "G-04: unique identity of a cycle and of an offering, missing = unspecified", statements_g04, preflight_g04, _TEXT_0002),
    ("0003-g05-evidence-root-alias", "G-05: evidence aliases that resolve to a root, never rename or overwrite an id", statements_g05, preflight_g05, _TEXT_0003),
    ("0004-g09-append-only-and-head-integrity", "G-09: capability gate, append-only tables, update_batches transitions, heads only for approved batches", statements_g09, preflight_g09, _TEXT_0004),
    ("0005-g07-revised-article-evidence", "G-07: the concrete evidence versions a revised article cites, as rows, with roots, a citation view and a mismatch view", statements_g07, preflight_g07, _TEXT_0005),
    ("0006-g11-revision-reasons", "G-11: one reason per batch that can change something, numbered corrections, the unknown past stays unknown", statements_g11, preflight_g11, _TEXT_0006),
    ("0007-g06-source-metadata-and-verification", "G-06: versioned source metadata and per-level verification events (append-only; an unknown publication date stays unknown)", statements_g06, preflight_g06, _TEXT_0007),
    ("0008-g03-lookup-indexes", "G-03: the six lookup indexes (plus the revised-article relation) that the root view, the impact analysis and the audit repeat", statements_g03, preflight_g03, _TEXT_0008),
    ("0009-m14-head-history", "M-14: the ordered approval and rollback events, from which the heads of any past time are replayed", statements_m14, preflight_m14, _TEXT_0009),
    ("0010-g03-restore-history", "M1.g3: the append-only storage of restored history (five tables, empty; restore events, revocations, restored articles, exact old versions, citation pins)", statements_g03_history, preflight_g03_history, _TEXT_0010),
    ("0011-g05-alias-provenance", "M1.g1/G-05: the append-only provenance bundle of an alias (its extractor pattern, versioned) and the versioned medium (pdf / html / unknown) of a stored source", statements_g05_provenance, preflight_g05_provenance, _TEXT_0011),
    ("0012-g02-faq-unconfirmed-evidence", "M1.g2/STR-100: the append-only storage of the evidence of an official FAQ whose applicability (year, faculty, method) is UNKNOWN; not a fact, no applicability column, no promotion path", statements_g02_faq, preflight_g02_faq_unconfirmed, _TEXT_0012),
    ("0013-g07-quarantine-staging", "M1.g7: the append-only quarantine staging of extracted candidates (stager recorded, approval by an authorized human who is not the stager, promotion only from APPROVED), three tables, empty", statements_g07_quarantine, preflight_g07_quarantine, _TEXT_0013),
    ("0014-g06-source-series", "M1.g6: the append-only lineage of a source document's editions (hash = content, consecutive revisions, supersedes the previous) and the revision impacts, two tables, empty", statements_g06_series, preflight_g06_series, _TEXT_0014),
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seq(migration_id: str) -> int:
    return int(migration_id.split("-", 1)[0])


def _last_schema_version(db: sqlite3.Connection) -> str | None:
    """What `schema_versions` says before the first migration: recorded as a fact in from_version, never invented."""
    if "schema_versions" not in _tables(db):
        return None
    row = db.execute("SELECT version FROM schema_versions ORDER BY rowid DESC LIMIT 1").fetchone()
    return row[0] if row else None


def history(db: sqlite3.Connection) -> list[tuple[str, str, int]]:
    if "schema_migrations" not in _tables(db):
        return []
    cols = [r[1] for r in db.execute("PRAGMA table_info(schema_migrations)")]
    if cols[:4] != ["version", "from_version", "applied_at", "checksum"]:
        raise MigrationError("schema_migrations has another layout (the draft of PR #70?): use a fresh disposable copy")
    return [(r[0], r[1], r[2]) for r in db.execute("SELECT version, checksum, seq FROM schema_migrations ORDER BY seq")]


def verify_history(db: sqlite3.Connection) -> list[str]:
    """Drift between the recorded history and this code: an applied checksum that differs, an applied migration the code does not know, a gap or an order that is not a prefix of the
    chain, a user_version that is not the sequence of the last applied migration. Returns the list of problems (empty = consistent)."""
    problems = []
    rows = history(db)
    uv = db.execute("PRAGMA user_version").fetchone()[0]
    chain = [m[0] for m in MIGRATIONS]
    known = {m[0]: m for m in MIGRATIONS}
    for version, checksum, seq in rows:
        if version not in known:
            problems.append(f"applied migration {version!r} is unknown to this code (the database is newer, or the id was renamed)")
        elif checksum != _sha(known[version][4]):
            problems.append(f"checksum mismatch for {version!r}: the SQL applied earlier differs from the SQL in this code (a migration is never edited after it was applied)")
        elif seq != _seq(version):
            problems.append(f"{version!r} was recorded with sequence {seq}")
    applied = [r[0] for r in rows]
    if applied != chain[:len(applied)]:
        problems.append("the applied migrations are not a prefix of the chain in order (a gap, a skip or another order): " + ", ".join(applied))
    expected_uv = _seq(applied[-1]) if applied else 0
    if (rows or uv) and uv != expected_uv:
        problems.append(f"PRAGMA user_version is {uv} but the history says {expected_uv}")
    return problems


HISTORY_COLUMNS = ("version", "from_version", "applied_at", "checksum", "description", "seq", "statements_applied_sha256", "applied_statement_ids")


def _history_layout_ok(db: sqlite3.Connection) -> bool:
    if "schema_migrations" not in _tables(db):
        return False
    cols = [r[1] for r in db.execute("PRAGMA table_info(schema_migrations)")]
    return tuple(cols[:len(HISTORY_COLUMNS)]) == HISTORY_COLUMNS or cols[:4] == ["version", "from_version", "applied_at", "checksum"] and set(HISTORY_COLUMNS) <= set(cols)


def verify_history_provenance(db: sqlite3.Connection) -> list[str]:
    """READ ONLY, DETECTION ONLY (nothing is prevented, repaired or written).  The provenance columns of ``schema_migrations`` that ``verify_history`` does not look at: a plain connection can replace a
    row (``INSERT OR REPLACE`` does not run the DELETE trigger while ``recursive_triggers`` is OFF), and a replaced ``from_version``, ``applied_at`` or ``description`` was not detected.  Reported here:

    * a NULL or non-positive rowid, a NULL version (the TEXT primary key of a rowid table does not imply NOT NULL);
    * the physical order (rowid) that is not the sequence order: a row written again lands after the later ones;
    * a ``from_version`` that is not the migration applied just before it (the first row's value is a fact about the database before the first migration and cannot be checked);
    * a ``description`` that is not the one the code holds for that migration;
    * an ``applied_at`` that is not an ISO-8601 time with a zone, or that goes back in time along the sequence.

    What it cannot see: a row replaced with an explicit rowid, a plausible time and the right chain.  Only a witness taken BEFORE (``history_witness`` / ``verify_history_step``) detects that.
    A database that was built by this runner has none of these problems; an empty list means "the rows that are there are consistent", NOT "untouched" and NOT "complete": a history that stops at 0004
    is consistent.  **Never use this function alone as an acceptance gate** (an empty list does not say that 0002-0009 are all recorded): use ``verify_history_for_acceptance``."""
    problems: list[str] = []
    if "schema_migrations" not in _tables(db):
        return ["schema_migrations does not exist: there is no migration history, so nothing about it can be called consistent"]
    if not _history_layout_ok(db):
        return ["schema_migrations has another layout (the draft of PR #70?): its history cannot be read, so nothing about it is claimed"]
    known = {m[0]: m for m in MIGRATIONS}
    rows = db.execute("SELECT rowid, version, from_version, applied_at, description, seq FROM schema_migrations ORDER BY seq").fetchall()
    if not rows:
        return ["schema_migrations holds no migration: an empty history is not a consistent one (a wiped or never migrated database)"]
    previous_version = previous_time = None
    previous_rowid = 0
    out_of_order: list[str] = []
    for index, (rowid, version, from_version, applied_at, description, seq) in enumerate(rows):
        label = repr(version)
        if version is None:
            problems.append(f"a row with sequence {seq} has no version")
        if rowid is None or rowid <= 0:
            problems.append(f"{label} has the rowid {rowid}: the history is append-only and its rowids are positive")
        elif rowid <= previous_rowid:
            out_of_order.append(label)
        if isinstance(rowid, int) and rowid > previous_rowid:
            previous_rowid = rowid
        if index > 0 and from_version != previous_version:
            problems.append(f"{label} says it follows {from_version!r} but the migration applied before it is {previous_version!r}")
        if version in known and description != known[version][1]:
            problems.append(f"{label} carries a description that is not the one this code holds for it")
        try:
            moment = datetime.fromisoformat(applied_at)
        except (TypeError, ValueError):
            problems.append(f"{label} has an applied_at that is not an ISO-8601 time: {applied_at!r}")
            moment = None
        if moment is not None:
            if moment.tzinfo is None:
                problems.append(f"{label} has an applied_at without a time zone: {applied_at!r}")
            elif previous_time is not None and moment < previous_time:
                problems.append(f"{label} was applied at {applied_at}, before the migration applied just before it")
            if moment.tzinfo is not None:
                previous_time = moment
        previous_version = version
    if out_of_order:
        problems.append(f"{len(out_of_order)} row(s) ({', '.join(out_of_order[:3])}) are stored before an earlier migration: a row was written again after the later ones (the physical order is not the sequence order)")
    return problems


def history_witness(db: sqlite3.Connection) -> tuple[tuple[Any, ...], ...]:
    """READ ONLY.  Every row of ``schema_migrations`` with every column, in sequence order: the evidence an operator keeps OUTSIDE the database before a migration step (a file, a ticket, a signed note).
    It is not authentication: whoever holds it can be wrong or forged; it only lets a later reader see that an old row changed.  **An empty witness (no table, or no row) proves nothing about old rows**:
    a gate must not treat "no problems against an empty witness" as acceptance (``verify_history_for_acceptance`` refuses it)."""
    if "schema_migrations" not in _tables(db):
        return ()
    if not _history_layout_ok(db):
        raise MigrationError("schema_migrations has another layout: no witness can be taken of a history that cannot be read")
    return tuple(tuple(r) for r in db.execute(f"SELECT {', '.join(HISTORY_COLUMNS)} FROM schema_migrations ORDER BY seq"))


def verify_history_step(before: tuple[tuple[Any, ...], ...], db: sqlite3.Connection, *, expected_new: tuple[str, ...] | None = None) -> list[str]:
    """READ ONLY, DETECTION ONLY.  Compare a witness taken before a migration step with the database now: every old row must be there, unchanged in EVERY column, and what was added must be the
    next migrations of the chain, in order, with consecutive sequence numbers and the right ``from_version``; ``PRAGMA user_version`` must be the last sequence.  ``expected_new`` names the versions
    the step was supposed to add (``None``: any number of next migrations, including none).  Returns the problems (empty = the step only appended)."""
    problems: list[str] = []
    if "schema_migrations" not in _tables(db):
        return ["schema_migrations does not exist: there is no history to compare with the witness"]
    try:
        now = history_witness(db)
    except MigrationError as e:
        return [str(e)]
    versions = {r[0]: r for r in now}
    for old in before:
        current = versions.get(old[0])
        if current is None:
            problems.append(f"the recorded migration {old[0]!r} is gone")
            continue
        for name, was, is_ in zip(HISTORY_COLUMNS, old, current):
            if was != is_:
                problems.append(f"the recorded migration {old[0]!r} changed its {name}")
    old_versions = [r[0] for r in before]
    appended = [r for r in now if r[0] not in set(old_versions)]
    chain = [m[0] for m in MIGRATIONS]
    last_old = old_versions[-1] if old_versions else None
    expected_after = chain[chain.index(last_old) + 1:] if last_old in chain else (chain if last_old is None else [])
    if [r[0] for r in now][:len(old_versions)] != old_versions:
        problems.append("the old rows are no longer the first rows of the history, in their order")
    for position, row in enumerate(appended):
        version, from_version, _at, _sum, _desc, seq = row[:6]
        wanted = expected_after[position] if position < len(expected_after) else None
        if version != wanted:
            problems.append(f"the appended migration {version!r} is not the next one of the chain ({wanted!r})")
            continue
        if seq != _seq(version):
            problems.append(f"the appended migration {version!r} has the sequence {seq}")
        follows = old_versions[-1] if position == 0 and old_versions else (appended[position - 1][0] if position > 0 else None)
        if (position > 0 or old_versions) and from_version != follows:
            problems.append(f"the appended migration {version!r} says it follows {from_version!r}, not {follows!r}")
    if expected_new is not None and tuple(r[0] for r in appended) != tuple(expected_new):
        problems.append(f"the step was to add {tuple(expected_new)} but added {tuple(r[0] for r in appended)}")
    last_seq = now[-1][5] if now else 0
    uv = db.execute("PRAGMA user_version").fetchone()[0]
    if (now or uv) and uv != last_seq:
        problems.append(f"PRAGMA user_version is {uv} but the history ends at sequence {last_seq}")
    return problems


def provenance_problems_if_history(db: sqlite3.Connection) -> list[str]:
    """``verify_history_provenance`` for a database that ALREADY HAS a recorded history; nothing for one that has none yet (a fresh database has no row to check, and the runner is what creates the table).
    This is what ``plan()``, ``apply()`` and the DB-17 audit call: a replaced ``from_version``, ``description`` or ``applied_at``, a row written again or out of order is DRIFT there. Completeness of the
    chain is not asked here (``verify_history_for_acceptance`` is the gate for that); only that the rows that are there are consistent."""
    if "schema_migrations" not in _tables(db) or not _history_layout_ok(db):
        return []  # a missing table is a fresh database; another layout is reported by history() as before
    if db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0:
        return []
    return verify_history_provenance(db)


def verify_history_for_acceptance(db: sqlite3.Connection, *, before: tuple[tuple[Any, ...], ...] | None, expected_new: tuple[str, ...] | None = None, through: str | None = None) -> list[str]:
    """READ ONLY, DETECTION ONLY.  The one question an ACCEPTANCE gate may ask about the migration history: "is the history COMPLETE and has it only grown since the witness?".  The answer is an empty
    list only when ALL of these hold, and every reason is given otherwise:

    * ``schema_migrations`` exists, can be read, and its versions are EXACTLY the chain 0002-0009 in order (``through`` names the last migration that is expected, default: the whole chain).
      A missing, empty, wiped or partial history is a reason, never a pass;
    * the existing contract holds (``verify_history`` and ``verify_schema_state``: checksums, order, ``user_version``, the objects the migrations created);
    * the provenance columns are consistent (``verify_history_provenance``);
    * the history agrees with a witness taken BEFORE the step (``verify_history_step``).  ``before`` is required: ``None`` means no witness was given, which is itself a reason; an EMPTY witness
      (a database that had no history) proves nothing about old rows, so it is accepted only together with ``expected_new`` (the migrations the step was to add).

    ``verify_history`` is not changed by this function and still answers an empty list for a database without a history (``apply()`` relies on that to migrate one); that answer must not be used as an
    acceptance."""
    if "schema_migrations" not in _tables(db):
        return ["schema_migrations does not exist: the history is not complete (no migration is recorded)"]
    if not _history_layout_ok(db):
        return ["schema_migrations has another layout (the draft of PR #70?): its history cannot be read, so it cannot be accepted"]
    chain = [m[0] for m in MIGRATIONS]
    if through is not None:
        if through not in chain:
            return [f"'through' names {through!r}, which is not a migration of this code"]
        chain = chain[:chain.index(through) + 1]
    problems: list[str] = []
    recorded = [r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY seq")]
    if recorded != chain:
        missing = [v for v in chain if v not in recorded]
        extra = [v for v in recorded if v not in chain]
        problems.append(f"the recorded history is not the complete chain: {len(recorded)} of {len(chain)} recorded"
                        + (f", missing {', '.join(missing)}" if missing else "") + (f", not part of the chain {', '.join(map(repr, extra))}" if extra else "")
                        + ("" if missing or extra else ", in another order"))
    problems += verify_history(db) + verify_schema_state(db) + verify_history_provenance(db)
    if before is None:
        problems.append("no witness was given: nothing shows that the old rows are unchanged")
    elif not before and expected_new is None:
        problems.append("an empty witness proves nothing about old rows: say which migrations the step was to add (expected_new)")
    else:
        problems += verify_history_step(before, db, expected_new=expected_new)
    return problems


_OBJECT = re.compile(r"CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|TRIGGER|VIEW)\s+(?:IF NOT EXISTS\s+)?(\w+)", re.I)
_OWNED_PREFIXES = ("trg_", "ux_", "ix_", "v_")  # the namespace of objects that migrations create (Work's own objects use none of these)

# DB-17 (design: docs/DB17_MIGRATION_DESIGN_DRAFT_20261111.md, decision D1 approved 2026-11-11): the tables of Work's v06 base schema. ``verify_schema_state`` reports every other table that is not
# created by an applied migration, so a table created OUTSIDE the migration chain (the quarantine / series tables of PR #306 were five of them, invisible to the name-prefix rule above) is DRIFT.
# Source: the 21 tables of Work's pinned read-only v06 (outputs/resume-m1/work-solo-light-20261106/pinned-v06-readonly.sqlite, SHA-256 a8e48b5b16239368e9b5c05aad1dbeb692a657f28dab909bf3c99fff41539578),
# which contains the 16 tables of the synthetic native schema (tests.db_support.make_native + RevisionStore) plus the 5 that Work's v06 already had: admission_offerings, cycle_dimensions,
# cycle_editions, legacy_fact_links, legacy_records. ``schema_migrations`` is the history table itself.
BASE_TABLES = frozenset({
    "admission_cycles", "admission_offerings", "article_evidence", "article_heads", "article_versions", "batch_evidence", "cycle_dimensions", "cycle_editions", "evidence_heads",
    "evidence_revisions", "facts", "legacy_fact_links", "legacy_imports", "legacy_records", "qa_runs", "revised_articles", "schema_versions", "source_documents", "source_pages",
    "update_batches", "update_events",
})


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").strip()


def applied_statements(db: sqlite3.Connection, version: str) -> tuple[str, ...]:
    """The statements a migration applied: for a frozen file, the recorded statement ids of the file; for a generated one, what the code generates for this database."""
    entry = next(m for m in MIGRATIONS if m[0] == version)
    parsed = getattr(entry[2], "frozen", None)
    if parsed is None:
        return entry[2](db)
    ids = json.loads(db.execute("SELECT applied_statement_ids FROM schema_migrations WHERE version=?", (version,)).fetchone()[0])
    return tuple(parsed[i][0] for i in ids if i < len(parsed))


def expected_objects(db: sqlite3.Connection) -> dict[str, str]:
    out: dict[str, str] = {}
    for version, _checksum, _seq in history(db):
        if version not in {m[0] for m in MIGRATIONS}:
            continue
        for st in applied_statements(db, version):
            m = _OBJECT.match(st)
            if m:
                out[m.group(2)] = _norm(st)
    return out


def verify_schema_state(db: sqlite3.Connection) -> list[str]:
    """What is REALLY in the database against what the applied migrations created: the SQL each applied migration recorded (statements_applied_sha256) against the frozen file / generator, and every
    table, index, view and trigger they create, by name and whitespace-normalised SQL, against sqlite_master. A dropped, edited or unexpected object is reported (a detection, not a prevention)."""
    problems: list[str] = []
    rows = history(db)
    if not rows:
        return problems
    known = {m[0] for m in MIGRATIONS}
    for version, _checksum, _seq in rows:
        if version not in known:
            continue  # reported by verify_history
        recorded = db.execute("SELECT statements_applied_sha256 FROM schema_migrations WHERE version=?", (version,)).fetchone()[0]
        try:
            statements = applied_statements(db, version)
        except (ValueError, TypeError, KeyError) as e:
            problems.append(f"{version!r}: the recorded applied statements cannot be read ({e})")
            continue
        if _sha("\n".join(statements)) != recorded:
            problems.append(f"{version!r}: the SQL this code holds for the recorded statements differs from the SQL that was applied (statements_applied_sha256)")
    expected = expected_objects(db)
    actual = {r[0]: _norm(r[1]) for r in db.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
    for name, sql in sorted(expected.items()):
        if name not in actual:
            problems.append(f"schema object {name!r} was created by an applied migration and is missing now")
        elif actual[name] != sql:
            problems.append(f"schema object {name!r} differs from the SQL its migration applied")
    for name in sorted(actual):
        if name not in expected and name.startswith(_OWNED_PREFIXES):
            problems.append(f"schema object {name!r} is not created by any applied migration")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    for name in sorted(tables - BASE_TABLES - {"schema_migrations"} - set(expected)):
        problems.append(f"table {name!r} is not in the base schema and is not created by any applied migration (created outside the migration chain?)")
    return problems


def plan(path: Path) -> dict[str, Any]:
    """Read only: drift of the history, and what a run WOULD do. The pending migrations are tried in order on an in-memory COPY (a migration may depend on the objects of an earlier pending one, so a
    preflight on the untouched file alone would be wrong); the file itself is opened read-only and never written."""
    with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as db:
        try:
            drift = verify_history(db) + verify_schema_state(db) + provenance_problems_if_history(db)
            applied = {r[0] for r in history(db)}
        except MigrationError as e:
            return {"migrations": [], "can_apply": False, "drift": [str(e)]}
        with closing(sqlite3.connect(":memory:")) as mem:
            db.backup(mem)
            mem.create_function("sogh_write_ok", 0, lambda: 1)
            mem.execute("PRAGMA foreign_keys=ON")
            out, stopped = [], False
            for mid, desc, stmts, pre, _definition in MIGRATIONS:
                if mid in applied:
                    out.append({"migration": mid, "applied": True, "not_applicable": False, "blocking_problems": [], "would_apply": False})
                    continue
                if stopped:
                    out.append({"migration": mid, "applied": False, "not_applicable": False, "blocking_problems": [], "would_apply": False, "after_a_blocked_migration": True})
                    continue
                problems = pre(mem)
                blocked = [p for p in problems if not p.startswith("not_applicable")]
                na = any(p.startswith("not_applicable") for p in problems)
                out.append({"migration": mid, "applied": False, "not_applicable": na, "blocking_problems": blocked, "would_apply": not problems})
                if problems:
                    stopped = True
                    continue
                try:
                    for st in stmts(mem):
                        mem.execute(st)
                except sqlite3.DatabaseError as e:
                    out[-1].update(would_apply=False, blocking_problems=[f"the statements do not run on a copy of this database: {e}"])
                    stopped = True
    return {"migrations": out, "drift": drift, "can_apply": not drift and all(m["applied"] or m["not_applicable"] or (not m["blocking_problems"]) for m in out)}


def apply(path: Path, *, confirm_disposable_copy: bool = False, only: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Apply every pending migration in ONE transaction, in chain order, or none. A blocked preflight returns a report with the file unchanged; a drift of the recorded
    history (checksum, unknown or out-of-order migration, user_version) raises MigrationError and the file is unchanged."""
    path = Path(path)
    if not confirm_disposable_copy:
        raise PermissionError("say that the file is a disposable copy (confirm_disposable_copy=True); never run this on an original database")
    if any(Path(str(path) + s).exists() for s in ("-wal", "-shm", "-journal")):
        raise ValueError("a journal or WAL sidecar exists: make a new consistent copy first")
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.create_function("sogh_write_ok", 0, lambda: 1)  # the runner is SOGH's own writer: its transaction may write what the guards protect (a backfill of a new migration, the history row)
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(SCHEMA_MIGRATIONS)
            drift = verify_history(db) + verify_schema_state(db) + provenance_problems_if_history(db)
            if drift:
                raise MigrationError("; ".join(drift))
            applied = [r[0] for r in history(db)]
            pending = [m for m in MIGRATIONS if m[0] not in applied]
            if only is not None and tuple(m[0] for m in pending[:len(only)]) != tuple(only):
                raise MigrationError("`only` must name the next pending migrations in chain order")
            if only is not None:
                pending = pending[:len(only)]
            done, blocked, previous = [], {}, (applied[-1] if applied else _last_schema_version(db))
            for mid, desc, stmts, pre, definition in pending:
                problems = pre(db)
                na = [p for p in problems if p.startswith("not_applicable")]
                real = [p for p in problems if not p.startswith("not_applicable")]
                if real:
                    blocked[mid] = real
                    break  # the chain is ordered: a blocked migration stops everything after it
                if na:
                    db.execute("ROLLBACK")
                    return {"applied": [], "blocked": {}, "not_applicable": {mid: na}, "rolled_back": True}
                statements = stmts(db)
                parsed = getattr(stmts, "frozen", None)
                ids = frozen_statement_ids(parsed, db) if parsed is not None else []
                for st in statements:
                    db.execute(st)
                db.execute("INSERT INTO schema_migrations(version, from_version, applied_at, checksum, description, seq, statements_applied_sha256, applied_statement_ids) VALUES(?,?,?,?,?,?,?,?)",
                           (mid, previous, datetime.now(timezone.utc).isoformat(), _sha(definition), desc, _seq(mid), _sha("\n".join(statements)), json.dumps(ids)))
                previous = mid
                done.append(mid)
            if blocked:  # nothing is half applied
                db.execute("ROLLBACK")
                return {"applied": [], "blocked": blocked, "not_applicable": {}, "rolled_back": True}
            if done:
                db.execute(f"PRAGMA user_version = {_seq(done[-1])}")
            db.execute("COMMIT")
            return {"applied": done, "blocked": {}, "not_applicable": {}, "skipped": applied, "rolled_back": False}
        except BaseException:
            db.execute("ROLLBACK")
            raise


# ---- G-05 resolution and registration (the code layer: the database cannot compare values) ---------------------------------------------------
class AliasError(ValueError):
    pass


def root_of(db: sqlite3.Connection, evidence_id: str) -> str:
    """The root of the series an evidence id or an alias belongs to (the native fact, or the first revision whose parent is unknown). NOT a version to read or to cite.
    A revision that has no root (a cyclic series) is an error, never silently the id itself."""
    if db.execute("SELECT 1 FROM facts WHERE evidence_id=?", (evidence_id,)).fetchone():
        return evidence_id
    if db.execute("SELECT 1 FROM evidence_revisions WHERE evidence_id=?", (evidence_id,)).fetchone():
        row = db.execute("SELECT root_evidence_id FROM v_evidence_root WHERE evidence_id=?", (evidence_id,)).fetchone()
        if row is None:
            raise AliasError(f"revision {evidence_id!r} has no root (a cyclic or broken revision series)")
        return row[0]
    row = db.execute("SELECT root_evidence_id FROM evidence_aliases WHERE alias_id=?", (evidence_id,)).fetchone()
    if row is None:
        raise AliasError(f"unknown evidence id or alias: {evidence_id!r}")
    return row[0]


def current_head_of(db: sqlite3.Connection, root: str) -> str:
    """The current head of the revision series of a root, or the root itself when the series has no head."""
    rows = db.execute("SELECT h.evidence_id FROM evidence_heads h JOIN v_evidence_root r ON r.evidence_id = h.evidence_id WHERE r.root_evidence_id = ? ORDER BY h.logical_id", (root,)).fetchall()
    if len(rows) > 1:  # owner review 2026-11-07: never pick one of several heads silently by the order of their logical ids
        raise AliasError(f"root {root!r} has {len(rows)} heads ({[r[0] for r in rows]}): an alias cannot follow an ambiguous head")
    return rows[0][0] if rows else root


def read_version(db: sqlite3.Connection, evidence_id: str) -> dict[str, Any]:
    """The version to READ for an evidence id or an alias. An evidence id names its own version. An alias names its pinned version, or the current head of its root.
    (The version an article CITED is not decided here and never follows a head: it is the row of the article's relation table.)"""
    root = root_of(db, evidence_id)
    if db.execute("SELECT 1 FROM facts WHERE evidence_id=? UNION SELECT 1 FROM evidence_revisions WHERE evidence_id=?", (evidence_id, evidence_id)).fetchone():
        return {"input": evidence_id, "kind": "evidence", "root": root, "resolved_evidence_id": evidence_id, "cited_version_fixed": True}
    pinned = db.execute("SELECT pinned_evidence_id FROM evidence_aliases WHERE alias_id=?", (evidence_id,)).fetchone()[0]
    target = pinned or current_head_of(db, root)
    return {"input": evidence_id, "kind": "alias", "root": root, "resolved_evidence_id": target, "cited_version_fixed": bool(pinned), "resolution": "pinned_version" if pinned else "current_head_of_root"}


def resolve(db: sqlite3.Connection, evidence_id: str) -> dict[str, Any]:
    """Kept for callers of the first draft: the root is now the real root (it used to be the id itself for a revision); see root_of and read_version."""
    return read_version(db, evidence_id)


def cited_version(db: sqlite3.Connection, article_id: str, evidence_id: str) -> dict[str, Any]:
    """The version an article CITED: the row of its relation table, exactly as written. It never looks at a head: an old article keeps the evidence it was written from, even after the evidence was
    corrected. An alias cannot be cited; an evidence id the article does not cite is an error (never the current value).
    A RESTORED article (g3 read contract, `historical_read`) is refused here: it is never read as an ordinary article, and its old version is not what this function names."""
    if "restored_articles" in _tables(db) and db.execute("SELECT 1 FROM restored_articles WHERE article_id=?", (article_id,)).fetchone():
        raise AliasError(f"article {article_id!r} is a restored article: read it with historical_read.read_cited_evidence, never as an ordinary article")
    for table, kind in (("article_evidence", "base"), ("revised_article_evidence", "revised")):
        if table not in _tables(db):
            continue
        if db.execute(f"SELECT 1 FROM {table} WHERE article_id=? AND evidence_id=?", (article_id, evidence_id)).fetchone():
            return {"article_id": article_id, "article_kind": kind, "cited_evidence_id": evidence_id, "root": root_of(db, evidence_id), "follows_head": False}
    raise AliasError(f"article {article_id!r} does not cite {evidence_id!r}")


def impacted_articles(db: sqlite3.Connection, evidence_or_root: str) -> list[tuple[str, str, str]]:
    """Every article (first version or revision) that cites ANY version under the root of the given evidence id or alias: (article_id, kind, the cited evidence id). The cited versions stay as they were."""
    root = root_of(db, evidence_or_root)
    return [tuple(r) for r in db.execute("SELECT article_id, article_kind, evidence_id FROM v_article_citations WHERE root_evidence_id=? ORDER BY article_id, evidence_id", (root,))]


REASON_CLASSES = ("source_changed", "new_fact", "correction", "locator_correction", "withdrawal", "wording", "article_refresh", "other")


def record_reason(db: sqlite3.Connection, batch_id: str, *, reason_class: str, reason_text: str, source_changed: str, actor: str,
                  source_sha256_before: str | None = None, source_sha256_after: str | None = None) -> None:
    """The one reason of a batch. The database refuses an empty reason, a contradiction (a locator correction that claims a source change), a second reason, and a batch that cannot change anything.
    A past batch is never given a reason by this function: nothing here guesses."""
    if reason_class not in REASON_CLASSES:
        raise ValueError(f"unknown reason class {reason_class!r}")
    db.create_function("sogh_write_ok", 0, lambda: 1)
    db.execute("INSERT INTO revision_reasons(batch_id, reason_class, reason_text, source_changed, source_sha256_before, source_sha256_after, actor, recorded_at) VALUES(?,?,?,?,?,?,?,?)",
               (batch_id, reason_class, reason_text, source_changed, source_sha256_before, source_sha256_after, actor, datetime.now(timezone.utc).isoformat()))


def correct_reason(db: sqlite3.Connection, batch_id: str, *, reason_class: str, reason_text: str, source_changed: str, correction_note: str, actor: str,
                   source_sha256_before: str | None = None, source_sha256_after: str | None = None) -> int:
    """A mistake in a recorded reason is corrected by a NEW numbered row; the first reason stays as it was written. Returns the number of the correction."""
    if reason_class not in REASON_CLASSES:
        raise ValueError(f"unknown reason class {reason_class!r}")
    db.create_function("sogh_write_ok", 0, lambda: 1)
    n = db.execute("SELECT COALESCE(MAX(correction_no), 0) + 1 FROM revision_reason_corrections WHERE batch_id=?", (batch_id,)).fetchone()[0]
    db.execute("INSERT INTO revision_reason_corrections(batch_id, correction_no, reason_class, reason_text, source_changed, source_sha256_before, source_sha256_after, correction_note, actor, recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (batch_id, n, reason_class, reason_text, source_changed, source_sha256_before, source_sha256_after, correction_note, actor, datetime.now(timezone.utc).isoformat()))
    return n


SOURCE_KINDS = ("admission_guide", "faq", "notice", "briefing", "other")
VERIFICATION_LEVELS = ("bytes_match_recorded_sha", "stored_file_matches_record", "official_site_authenticity", "content_meaning_checked")


def record_source_metadata(db: sqlite3.Connection, source_sha256: str, *, source_kind: str, title: str, basis: str, recorded_by: str, published_at: str | None = None,
                           published_at_certainty: str = "unknown", applies_to_fiscal_year: int | None = None) -> int:
    """A new VERSION of what is known about a stored source document (the earlier versions stay). A publication date that is not known stays None / 'unknown': it is never guessed, and the retrieval date is
    a different column of source_documents. Returns the version number."""
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind {source_kind!r}")
    db.create_function("sogh_write_ok", 0, lambda: 1)
    n = db.execute("SELECT COALESCE(MAX(meta_version), 0) + 1 FROM source_document_metadata WHERE source_sha256=?", (source_sha256,)).fetchone()[0]
    db.execute("INSERT INTO source_document_metadata(source_sha256, meta_version, published_at, published_at_certainty, source_kind, title, applies_to_fiscal_year, basis, recorded_by, recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (source_sha256, n, published_at, published_at_certainty, source_kind, title, applies_to_fiscal_year, basis, recorded_by, datetime.now(timezone.utc).isoformat()))
    return n


def record_verification(db: sqlite3.Connection, source_sha256: str, *, level: str, outcome: str, evidence: str, performed_by: str) -> int:
    """One check that was really done, at one level (bytes equal the recorded SHA / the stored file matches the record / authenticity at the official site / meaning checked). Returns the event number."""
    if level not in VERIFICATION_LEVELS:
        raise ValueError(f"unknown verification level {level!r}")
    db.create_function("sogh_write_ok", 0, lambda: 1)
    n = db.execute("SELECT COALESCE(MAX(event_no), 0) + 1 FROM source_verification_events WHERE source_sha256=?", (source_sha256,)).fetchone()[0]
    db.execute("INSERT INTO source_verification_events(source_sha256, event_no, level, outcome, evidence, performed_by, performed_at) VALUES(?,?,?,?,?,?,?)",
               (source_sha256, n, level, outcome, evidence, performed_by, datetime.now(timezone.utc).isoformat()))
    return n


def heads_as_of(db: sqlite3.Connection, as_of: str) -> dict[str, dict[str, str]]:
    """The heads (evidence and articles) as they were at `as_of` (an ISO time like the ones in update_events): the state stored by the last approval or rollback event up to that time, or nothing
    when there was none. A candidate, an interrupted or a rejected batch never was a head, so it does not appear. This is a replay of what the database recorded, not a stored copy."""
    row = db.execute("SELECT heads_json FROM v_head_events WHERE created_at <= ? ORDER BY event_id DESC LIMIT 1", (as_of,)).fetchone()
    if row is None:
        return {"evidence": {}, "articles": {}}
    state = json.loads(row[0])
    return {"evidence": dict(state.get("evidence", {})), "articles": dict(state.get("articles", {}))}


def read_as_of(db: sqlite3.Connection, logical_id: str, as_of: str) -> str | None:
    """The evidence version that was the head of `logical_id` at `as_of`, or None when it had no head then. (An article that CITED a version never uses this: it keeps the version it cited.)"""
    return heads_as_of(db, as_of)["evidence"].get(logical_id)


def _locator_problem(record: dict[str, Any]) -> str | None:
    """Why a record does not state a usable locator, or None.  Owner review 2026-11-07 (after Work's technical review of PR #191): `proofs` must be a non-empty list of objects that each
    state a `page` (an integer, 1 or more) and a non-empty `quote`; `field_proofs`, when present, must be a non-empty object whose values are objects (they point into `proofs` by `proof_indices`)."""
    proofs = record.get("proofs")
    if not isinstance(proofs, (list, tuple)) or not proofs:
        return "`proofs` must be a non-empty list"
    for p in proofs:
        if not isinstance(p, dict) or type(p.get("page")) is not int or p["page"] < 1 or not isinstance(p.get("quote"), str) or not p["quote"].strip():
            return "every proof needs an integer `page` (1 or more) and a non-empty `quote`"
    if "field_proofs" in record:
        fp = record["field_proofs"]
        if not isinstance(fp, dict) or not fp or not all(isinstance(v, dict) for v in fp.values()):
            return "`field_proofs`, when present, must be a non-empty object of objects"
        for v in fp.values():
            idx = v.get("proof_indices")
            if idx is not None and (not isinstance(idx, (list, tuple)) or not all(type(i) is int and 0 <= i < len(proofs) for i in idx)):
                return "`proof_indices` must point into `proofs`"
    return None


def _position_digest(record: dict[str, Any]) -> str:
    """The EXACT position of a record: every proof object as written (offsets and all) and every field proof.  The ordinary identity (`identity.locator`) compares only page and normalised quote;
    an approved (pinned) registration binds to the exact position, so a changed offset is a different position."""
    return hashlib.sha256(json.dumps({"proofs": sorted(json.dumps(p, ensure_ascii=False, sort_keys=True) for p in record.get("proofs") or []),
                                      "field_proofs": record.get("field_proofs")}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def position_differences(alias_record: dict[str, Any], head_record: dict[str, Any]) -> list[dict[str, Any]]:
    """Read-only diagnostic for an approved registration that was refused for a different position: for every proof, WHICH keys differ (key names and page only, never the quote or any value).
    Proofs are paired by (page, quote).  An empty list means the positions are identical.  It decides nothing: whether a differing key is an offset (a different position: refused) or only extractor
    metadata (a candidate for an explicit allow-list) is a contract decision that needs evidence per key."""
    def keyed(record):
        out: dict[tuple, dict[str, Any]] = {}
        for i, p in enumerate(record.get("proofs") or []):
            if isinstance(p, dict):
                out.setdefault((p.get("page"), p.get("quote")), p)
        return out
    a, h = keyed(alias_record), keyed(head_record)
    diffs: list[dict[str, Any]] = []
    for key in sorted(set(a) | set(h), key=lambda k: (str(k[0]), str(k[1]))):
        if key not in a or key not in h:
            diffs.append({"page": key[0], "unpaired": "alias" if key in a else "head"})
            continue
        pa, ph = a[key], h[key]
        only_a, only_h = sorted(set(pa) - set(ph)), sorted(set(ph) - set(pa))
        differ = sorted(k for k in set(pa) & set(ph) if json.dumps(pa[k], sort_keys=True, ensure_ascii=False) != json.dumps(ph[k], sort_keys=True, ensure_ascii=False))
        if only_a or only_h or differ:
            diffs.append({"page": key[0], "only_in_alias": only_a, "only_in_head": only_h, "value_differs": differ})
    if json.dumps(alias_record.get("field_proofs"), sort_keys=True, ensure_ascii=False) != json.dumps(head_record.get("field_proofs"), sort_keys=True, ensure_ascii=False):
        diffs.append({"field_proofs": "differ"})
    return diffs


def _scope_label_problem(alias_record: dict[str, Any], root_record: dict[str, Any]) -> str | None:
    """The record's `scope` LABEL (e.g. "department_and_method") is not the five cycle dimensions.  If the record states one it must be a real label (not null, empty or UNKNOWN) and the root's own;
    if it states none, the root must state none either (a missing label is never read as "the same")."""
    root_label = root_record.get("scope")
    if "scope" in alias_record:
        label = alias_record["scope"]
        if not isinstance(label, str) or not label.strip() or label.strip().upper() == "UNKNOWN":
            return "the record's scope label is null, empty or UNKNOWN: it is never inferred"
        if label != root_label:
            return f"the record's scope label {label!r} is not the root's ({root_label!r})"
    elif isinstance(root_label, str) and root_label.strip():
        return "the record states no scope label but the root states one: a missing label is not read as the same"
    return None


def register_alias(db: sqlite3.Connection, alias_id: str, root_evidence_id: str, kind: str, reason: str, *, alias_record: dict[str, Any], pinned_evidence_id: str | None = None,
                   approved_head_id: str | None = None, provenance_bundle: dict[str, Any] | None = None, recorded_by: str | None = None) -> None:
    """Register a legacy id as an alias of a root. The alias record is the legacy delivery's record; it must be the SAME fact (same cycle, fact_key and source, same value),
    possibly with a corrected locator. Independent or conflicting facts are refused here; the database enforces the structure (root exists, same case and fact_key,
    no id reuse, no alias of an alias, append-only).

    Ordinary registration (`approved_head_id` is None): the alias follows the head of its root and is never pinned (`pinned_evidence_id` must be None). Owner review 2026-11-07 (docs/G05_OWNER_REVIEW_2026-11-07.md):
    an explicit `case_id` in the record must be the root's case, the record must state a usable locator (`proofs` with page and quote), its scope label must be the root's, and a root with several heads is refused.

    Approved registration (`approved_head_id` given: the 01 case, where the legacy record carries a CORRECTED locator that only the current head has): the alias is bound to ONE approved version.
    The head must still be that version, `pinned_evidence_id` must be that version and no other, and the record must equal that version in value and locator. The head is checked in the SAME SQL statement
    as the insert (no caller transaction is required), so a head that moves between the check and the write cannot be missed: the statement inserts nothing and this function raises."""
    db.create_function("sogh_write_ok", 0, lambda: 1)  # the sanctioned writer of aliases (it has just classified the alias in code): a bare connection is refused by the gate
    root = db.execute("SELECT case_id, fact_key, source_sha256, record_json, value_json FROM facts WHERE evidence_id=?", (root_evidence_id,)).fetchone()
    if not root:
        raise AliasError(f"unknown root: {root_evidence_id!r}")
    case_id, fact_key, source, record_json, value_json = root
    cycle = db.execute("SELECT university, faculty, department, admission_method, fiscal_year FROM admission_cycles WHERE case_id=?", (case_id,)).fetchone()
    scope = ("university", "faculty", "department", "admission_method", "fiscal_year")
    # the root's cycle comes from the database (the stored native record does not repeat it); its value comes from the value column
    root_record = {**json.loads(record_json), "value": json.loads(value_json), "fact_key": fact_key, **dict(zip(scope, cycle))}
    if "case_id" in alias_record and alias_record["case_id"] != case_id:
        raise AliasError(f"the record names case {alias_record['case_id']!r}, the root belongs to {case_id!r}: not the same fact")
    if alias_record.get("fact_key") != fact_key or any(alias_record.get(k) != root_record.get(k) for k in scope):
        raise AliasError("different fact_key, cycle or year: the same value elsewhere is an independent fact, not an alias")
    if (alias_record.get("source_sha256") or alias_record.get("source_pdf_sha256")) != source:
        raise AliasError("different source: not the same fact")
    problem = _locator_problem(alias_record)
    if problem:
        raise AliasError(f"the record states no usable locator: {problem}")
    problem = _scope_label_problem(alias_record, root_record)
    if problem:
        raise AliasError(problem)
    verdict = identity.classify(alias_record, root_record)
    if verdict not in ("duplicate", "same_value_moved"):
        raise AliasError(f"classified as {verdict!r}: only a duplicate or a moved locator may become an alias")
    created_at = datetime.now(timezone.utc).isoformat()
    columns = "alias_id, root_evidence_id, case_id, fact_key, pinned_evidence_id, kind, reason, created_at"
    if approved_head_id is None:
        if pinned_evidence_id is not None:
            raise AliasError("a pinned version is registered only by an approved registration (`approved_head_id`): an ordinary alias follows the head")
        if provenance_bundle is not None:
            raise AliasError("a provenance bundle belongs to an approved registration (the one that compares positions): an ordinary registration stores none")
        current_head_of(db, root_evidence_id)  # an early, readable refusal when the root already has more than one head ...
        # ... and the SAME check inside the write: a second head that is committed by another connection between the check and the insert (Work's review of PR #191, re-check 2026-11-07)
        # makes the statement insert nothing, so an ambiguous alias is never stored.
        cursor = db.execute(f"INSERT INTO evidence_aliases({columns}) SELECT ?,?,?,?,?,?,?,? WHERE (SELECT count(*) FROM evidence_heads h JOIN v_evidence_root r ON r.evidence_id = h.evidence_id WHERE r.root_evidence_id = ?) <= 1",
                            (alias_id, root_evidence_id, case_id, fact_key, pinned_evidence_id, kind, reason, created_at, root_evidence_id))
        if cursor.rowcount != 1:
            raise AliasError("the root has more than one head at the moment of the write (a head appeared between the check and the write): nothing was registered")
        return
    head = current_head_of(db, root_evidence_id)  # raises when the root has more than one head
    if head == root_evidence_id:
        raise AliasError("the root has no revision: there is no version to bind an approval to (use the ordinary registration)")
    if approved_head_id != head:
        raise AliasError(f"the head changed since the approval ({approved_head_id!r} is now {head!r}): a new review is required, the old approval is not reused")
    if pinned_evidence_id != approved_head_id:
        raise AliasError("an approved registration pins exactly the approved version")
    head_row = db.execute("SELECT record_json FROM evidence_revisions WHERE evidence_id=?", (head,)).fetchone()
    head_record = {**json.loads(head_row[0]), "fact_key": fact_key, **dict(zip(scope, cycle))}
    if "value" not in head_record:
        raise AliasError("the approved version's record carries no value to compare")
    if identity.classify(alias_record, head_record) != "duplicate":
        raise AliasError("the approved version does not carry exactly this record (same value and same locator)")
    differs = _position_digest(alias_record) != _position_digest(head_record)
    diffs = position_differences(alias_record, head_record) if differs else []
    if differs and provenance_bundle is None:
        raise AliasError("the approved version does not carry exactly this position (every proof object, offsets included, and every field proof must be identical); "
                         f"differing keys: {diffs}")
    if provenance_bundle is not None and not recorded_by:
        raise AliasError("a provenance bundle needs `recorded_by`")
    heads = "FROM evidence_heads h JOIN v_evidence_root r ON r.evidence_id = h.evidence_id WHERE r.root_evidence_id = ?"
    db.execute("SAVEPOINT alias_registration")  # the alias and its bundle are one unit: both are kept or neither
    try:
        cursor = db.execute(f"INSERT INTO evidence_aliases({columns}) SELECT ?,?,?,?,?,?,?,? WHERE (SELECT count(*) {heads}) = 1 AND (SELECT h.evidence_id {heads}) = ?",
                            (alias_id, root_evidence_id, case_id, fact_key, pinned_evidence_id, kind, reason, created_at, root_evidence_id, root_evidence_id, approved_head_id))
        if cursor.rowcount != 1:  # the head moved (or a second head appeared) after the checks above and before the write: nothing was written
            raise AliasError("the head changed between the check and the write: nothing was registered, a new review is required")
        if provenance_bundle is not None:
            from . import alias_provenance as prov
            prov.record_alias_provenance(db, alias_id, provenance_bundle, recorded_by)
            reasons = prov.explain_position_differences(db, diffs, alias_id, alias_record, head_record, source)
            if reasons:
                raise AliasError("the position differs and the differences are not explained by the stored provenance: " + "; ".join(reasons))
    except BaseException:
        db.execute("ROLLBACK TO alias_registration")
        db.execute("RELEASE alias_registration")
        raise
    db.execute("RELEASE alias_registration")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("database")
    p.add_argument("--apply", action="store_true", help="apply to a DISPOSABLE COPY (requires --confirm-disposable-copy)")
    p.add_argument("--confirm-disposable-copy", action="store_true")
    a = p.parse_args(argv)
    if a.apply:
        print(json.dumps(apply(Path(a.database), confirm_disposable_copy=a.confirm_disposable_copy), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(plan(Path(a.database)), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
