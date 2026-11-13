"""M1.g6 Product Implementation Candidate: Document Series Contract & Revision Lineage.

Enforces append-only document lineage, cryptographic hash verification across all
editions including Rev 1, external head/edition anchoring against middle-edition
forgery or tail rollback, append-only SQLite persistence, and revision impact linkage.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import secrets
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "SCHEMA_SQL",
    "SourceEdition",
    "SourceSeries",
    "create_series",
    "append_revision",
    "verify_series_lineage",
    "verify_series_against_rows",
    "to_rows",
    "init_series_schema",
    "persist_series",
    "record_revision_impact",
]

# Append-only external authority log anchoring created/appended editions and head state per series instance and series_id
_SERIES_ANCHOR_LOG: Dict[int, List[Dict[str, Any]]] = {}
_SERIES_ID_ANCHOR_LOG: Dict[str, List[Dict[str, Any]]] = {}
_EDITION_SEAL_SECRET = secrets.token_bytes(32)


def _compute_edition_seal(
    edition_id: str,
    series_id: str,
    rev_number: int,
    sha256_hash: str,
    content_text: str,
    supersedes_id: Optional[str],
    prev_seal: str,
) -> str:
    msg = f"{edition_id}|{series_id}|{rev_number}|{sha256_hash}|{content_text}|{supersedes_id or ''}|{prev_seal}".encode("utf-8")
    return hmac.new(_EDITION_SEAL_SECRET, msg, hashlib.sha256).hexdigest()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_document_series_editions (
    edition_id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL,
    university TEXT NOT NULL,
    document_title TEXT NOT NULL,
    rev_number INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    content_text TEXT NOT NULL,
    supersedes_id TEXT,
    is_frozen INTEGER NOT NULL DEFAULT 0 CHECK(is_frozen IN (0, 1)),
    UNIQUE(series_id, rev_number)
);

CREATE TABLE IF NOT EXISTS series_revision_article_impacts (
    impact_id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL,
    old_edition_id TEXT NOT NULL,
    new_edition_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    impact_status TEXT NOT NULL DEFAULT 'REVISION_REQUIRED',
    FOREIGN KEY(old_edition_id) REFERENCES source_document_series_editions(edition_id),
    FOREIGN KEY(new_edition_id) REFERENCES source_document_series_editions(edition_id)
);

CREATE TRIGGER IF NOT EXISTS trg_series_editions_prevent_replace
BEFORE INSERT ON source_document_series_editions
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM source_document_series_editions
    WHERE edition_id = NEW.edition_id
       OR (series_id = NEW.series_id AND rev_number = NEW.rev_number)
)
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Cannot overwrite existing series edition via INSERT OR REPLACE');
END;

CREATE TRIGGER IF NOT EXISTS trg_series_editions_validate_insert
BEFORE INSERT ON source_document_series_editions
FOR EACH ROW
WHEN NEW.sha256_hash != _g6_sha256_hex(NEW.content_text)
  OR trim(NEW.university) = ''
  OR trim(NEW.document_title) = ''
  OR NEW.rev_number < 1
  OR (NEW.rev_number = 1 AND NEW.supersedes_id IS NOT NULL)
  OR (
      NEW.rev_number > 1
      AND NOT EXISTS (
          SELECT 1 FROM source_document_series_editions p
          WHERE p.series_id = NEW.series_id
            AND p.rev_number = NEW.rev_number - 1
            AND p.edition_id = NEW.supersedes_id
      )
  )
  OR EXISTS (
      SELECT 1 FROM source_document_series_editions s
      WHERE s.series_id = NEW.series_id
        AND (s.university != NEW.university OR s.document_title != NEW.document_title)
  )
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Edition content hash mismatch, broken rev_number/supersedes chain, or inconsistent series metadata on INSERT');
END;

CREATE TRIGGER IF NOT EXISTS trg_series_editions_prevent_delete
BEFORE DELETE ON source_document_series_editions
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Document series editions are append-only; DELETE prohibited');
END;

CREATE TRIGGER IF NOT EXISTS trg_series_editions_immutable_payload
BEFORE UPDATE ON source_document_series_editions
FOR EACH ROW
WHEN NEW.edition_id != OLD.edition_id
  OR NEW.series_id != OLD.series_id
  OR NEW.university != OLD.university
  OR NEW.document_title != OLD.document_title
  OR NEW.rev_number != OLD.rev_number
  OR NEW.sha256_hash != OLD.sha256_hash
  OR NEW.content_text != OLD.content_text
  OR COALESCE(NEW.supersedes_id, '') != COALESCE(OLD.supersedes_id, '')
  OR (OLD.is_frozen = 1 AND NEW.is_frozen != 1)
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Edition identity, labels, hash, and content are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_series_impacts_validate_insert
BEFORE INSERT ON series_revision_article_impacts
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM series_revision_article_impacts
    WHERE impact_id = NEW.impact_id
)
  OR NEW.old_edition_id = NEW.new_edition_id
  OR NOT EXISTS (
      SELECT 1 FROM source_document_series_editions e1
      WHERE e1.edition_id = NEW.old_edition_id
        AND e1.series_id = NEW.series_id
  )
  OR NOT EXISTS (
      SELECT 1 FROM source_document_series_editions e2
      WHERE e2.edition_id = NEW.new_edition_id
        AND e2.series_id = NEW.series_id
  )
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Impact record must reference existing distinct editions in the same series and cannot be overwritten');
END;

CREATE TRIGGER IF NOT EXISTS trg_series_impacts_prevent_update
BEFORE UPDATE ON series_revision_article_impacts
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Revision impact records are append-only; UPDATE prohibited');
END;

CREATE TRIGGER IF NOT EXISTS trg_series_impacts_prevent_delete
BEFORE DELETE ON series_revision_article_impacts
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Revision impact records are append-only; DELETE prohibited');
END;
"""


@dataclasses.dataclass(frozen=True)
class SourceEdition:
    edition_id: str
    series_id: str
    rev_number: int
    sha256_hash: str
    content_text: str
    supersedes_id: Optional[str] = None
    is_frozen: bool = False
    metadata: Optional[Dict[str, Any]] = None

    def freeze(self) -> SourceEdition:
        """Return a frozen copy of this edition."""
        return dataclasses.replace(self, is_frozen=True)


@dataclasses.dataclass
class SourceSeries:
    series_id: str
    university: str
    document_title: str
    editions: List[SourceEdition] = dataclasses.field(default_factory=list)

    @property
    def latest_edition(self) -> Optional[SourceEdition]:
        return self.editions[-1] if self.editions else None


def _snapshot_edition(ed: SourceEdition) -> Dict[str, Any]:
    return {
        "edition_id": ed.edition_id,
        "series_id": ed.series_id,
        "rev_number": ed.rev_number,
        "sha256_hash": ed.sha256_hash,
        "supersedes_id": ed.supersedes_id,
    }


def create_series(series_id: str, university: str, document_title: str, initial_content: str) -> SourceSeries:
    """Create a new document series with Rev 1 and anchor its genesis hash."""
    sha = hashlib.sha256(initial_content.encode("utf-8")).hexdigest()
    rev1_id = f"{series_id}_rev1"
    seal1 = _compute_edition_seal(rev1_id, series_id, 1, sha, initial_content, None, "GENESIS")
    rev1 = SourceEdition(
        edition_id=rev1_id,
        series_id=series_id,
        rev_number=1,
        sha256_hash=sha,
        content_text=initial_content,
        supersedes_id=None,
        is_frozen=False,
        metadata={"_chain_seal": seal1},
    )
    series = SourceSeries(
        series_id=series_id,
        university=university,
        document_title=document_title,
        editions=[rev1],
    )
    snap = [_snapshot_edition(rev1)]
    _SERIES_ANCHOR_LOG[id(series)] = snap
    _SERIES_ID_ANCHOR_LOG[series_id] = list(snap)
    return series


def append_revision(
    series: SourceSeries,
    new_content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceEdition:
    """Append a new revision to the series and update external head anchor."""
    if not series.editions:
        raise ValueError("Cannot append to empty series")

    prev = series.editions[-1]
    new_sha = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

    if new_sha == prev.sha256_hash:
        raise ValueError(f"Redundant revision: content SHA-256 identical to Rev {prev.rev_number}")

    # Freeze previous edition
    series.editions[-1] = prev.freeze()

    new_rev_number = prev.rev_number + 1
    new_id = f"{series.series_id}_rev{new_rev_number}"
    prev_seal = (prev.metadata or {}).get("_chain_seal", "")
    new_seal = _compute_edition_seal(
        new_id, series.series_id, new_rev_number, new_sha, new_content, prev.edition_id, prev_seal
    )
    meta = dict(metadata or {})
    meta["_chain_seal"] = new_seal

    new_edition = SourceEdition(
        edition_id=new_id,
        series_id=series.series_id,
        rev_number=new_rev_number,
        sha256_hash=new_sha,
        content_text=new_content,
        supersedes_id=prev.edition_id,
        is_frozen=False,
        metadata=meta,
    )
    series.editions.append(new_edition)

    snap = [_snapshot_edition(e) for e in series.editions]
    _SERIES_ANCHOR_LOG[id(series)] = snap
    _SERIES_ID_ANCHOR_LOG[series.series_id] = list(snap)

    return new_edition


def _check_anchor_list(
    series: SourceSeries, anchored: List[Dict[str, Any]], label: str
) -> List[str]:
    errs: List[str] = []
    if len(series.editions) != len(anchored):
        errs.append(
            f"History length mismatch against {label}: expected {len(anchored)} editions, got {len(series.editions)}"
        )
    else:
        for idx, (ed, exp) in enumerate(zip(series.editions, anchored)):
            if (
                ed.edition_id != exp["edition_id"]
                or ed.series_id != exp["series_id"]
                or ed.rev_number != exp["rev_number"]
                or ed.sha256_hash != exp["sha256_hash"]
                or ed.supersedes_id != exp["supersedes_id"]
            ):
                errs.append(
                    f"Edition at index {idx} (Rev {ed.rev_number}) diverges from {label} seal"
                )
    return errs


def verify_series_lineage(series: SourceSeries) -> Tuple[bool, List[str]]:
    """Verify cryptographic and structural lineage of all editions (including Rev 1 and external anchor)."""
    errors: List[str] = []

    if not series.editions:
        if (
            id(series) in _SERIES_ANCHOR_LOG and len(_SERIES_ANCHOR_LOG[id(series)]) > 0
        ) or (
            series.series_id in _SERIES_ID_ANCHOR_LOG
            and len(_SERIES_ID_ANCHOR_LOG[series.series_id]) > 0
        ):
            errors.append("History truncated: all editions were dropped from series")
            return False, errors
        return True, []

    # 1. Verify Rev 1 (oldest edition) structural & cryptographic integrity
    rev1 = series.editions[0]
    if rev1.series_id != series.series_id:
        errors.append(f"Rev 1 series_id '{rev1.series_id}' does not match series '{series.series_id}'")
    if rev1.rev_number != 1:
        errors.append(f"Rev 1 has invalid rev_number: {rev1.rev_number}")
    if rev1.supersedes_id is not None:
        errors.append(f"Rev 1 cannot have supersedes_id, got: {rev1.supersedes_id}")
    rev1_calc_sha = hashlib.sha256(rev1.content_text.encode("utf-8")).hexdigest()
    if rev1.sha256_hash != rev1_calc_sha:
        errors.append("Hash mismatch on Rev 1 (oldest edition content tampered)")

    # 2. Verify subsequent editions
    for i in range(1, len(series.editions)):
        curr = series.editions[i]
        prev = series.editions[i - 1]

        if curr.series_id != series.series_id:
            errors.append(
                f"Rev {curr.rev_number} series_id '{curr.series_id}' does not match series '{series.series_id}'"
            )

        if not prev.is_frozen:
            errors.append(f"Prior edition Rev {prev.rev_number} is not marked frozen")

        if curr.rev_number != prev.rev_number + 1:
            errors.append(
                f"Non-sequential revision: Rev {prev.rev_number} followed by Rev {curr.rev_number}"
            )

        if curr.supersedes_id != prev.edition_id:
            errors.append(
                f"Broken lineage: Rev {curr.rev_number} supersedes_id '{curr.supersedes_id}' does not match '{prev.edition_id}'"
            )

        calc_sha = hashlib.sha256(curr.content_text.encode("utf-8")).hexdigest()
        if curr.sha256_hash != calc_sha:
            errors.append(f"Hash mismatch on Rev {curr.rev_number}")

    # 3. Verify cumulative edition cryptographic chain seals (detects middle-edition forgery even when in-memory anchors are cleared)
    if any(isinstance(e.metadata, dict) and "_chain_seal" in e.metadata for e in series.editions):
        prev_seal = "GENESIS"
        for ed in series.editions:
            actual_seal = (ed.metadata or {}).get("_chain_seal", "")
            expected_seal = _compute_edition_seal(
                ed.edition_id,
                ed.series_id,
                ed.rev_number,
                ed.sha256_hash,
                ed.content_text,
                ed.supersedes_id,
                prev_seal,
            )
            if not actual_seal or not hmac.compare_digest(actual_seal, expected_seal):
                errors.append(
                    f"Chain seal mismatch on Rev {ed.rev_number} (edition forged or previous edition altered)"
                )
            prev_seal = expected_seal

    # 4. Verify against external anchor logs (both instance and series_id)
    anchored_inst = _SERIES_ANCHOR_LOG.get(id(series))
    if anchored_inst is not None:
        errors.extend(_check_anchor_list(series, anchored_inst, "external instance anchor"))

    anchored_sid = _SERIES_ID_ANCHOR_LOG.get(series.series_id)
    if anchored_sid is not None:
        errors.extend(_check_anchor_list(series, anchored_sid, "external series_id anchor"))

    return len(errors) == 0, errors


def verify_series_against_rows(
    conn: sqlite3.Connection, series: SourceSeries
) -> Tuple[bool, List[str]]:
    """Verify a SourceSeries against persisted database rows in `source_document_series_editions` (STR-106 g6-1).

    Detects tail deletion, middle-edition forgery, or hash divergence against stored rows
    independently of any in-memory process state.
    """
    ok, errors = verify_series_lineage(series)
    stored_rows = conn.execute(
        """
        SELECT edition_id, series_id, rev_number, sha256_hash, content_text, supersedes_id, is_frozen
        FROM source_document_series_editions
        WHERE series_id = ?
        ORDER BY rev_number ASC
        """,
        (series.series_id,),
    ).fetchall()

    if not stored_rows:
        errors.append(f"No persisted rows found in database for series '{series.series_id}'")
        return False, errors

    if len(series.editions) != len(stored_rows):
        errors.append(
            f"Persisted row count mismatch for series '{series.series_id}': stored={len(stored_rows)}, candidate={len(series.editions)}"
        )
        return False, errors

    for idx, (ed, row) in enumerate(zip(series.editions, stored_rows)):
        r_eid, r_sid, r_rev, r_sha, r_txt, r_sup, _r_frz = row
        calc_sha = hashlib.sha256(str(r_txt).encode("utf-8")).hexdigest()
        if (
            ed.edition_id != r_eid
            or ed.series_id != r_sid
            or ed.rev_number != r_rev
            or ed.sha256_hash != r_sha
            or ed.sha256_hash != calc_sha
            or ed.content_text != r_txt
            or ed.supersedes_id != r_sup
        ):
            errors.append(
                f"Edition at index {idx} (Rev {ed.rev_number}) diverges from persisted database row"
            )

    return len(errors) == 0, errors


def to_rows(series: SourceSeries) -> List[Dict[str, Any]]:
    """Serialize series editions into append-only database row dicts."""
    ok, errors = verify_series_lineage(series)
    if not ok:
        raise ValueError(f"Cannot serialize invalid series lineage: {errors}")
    return [
        {
            "edition_id": ed.edition_id,
            "series_id": series.series_id,
            "university": series.university,
            "document_title": series.document_title,
            "rev_number": ed.rev_number,
            "sha256_hash": ed.sha256_hash,
            "content_text": ed.content_text,
            "supersedes_id": ed.supersedes_id,
            "is_frozen": 1 if ed.is_frozen else 0,
        }
        for ed in series.editions
    ]


def _g6_sha256_hex_sql(text: Optional[str]) -> str:
    if not isinstance(text, str):
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def register_series_connection_guards(conn: sqlite3.Connection) -> None:
    """DDL-free connection guard registration (DB-17 R1)."""
    conn.execute("PRAGMA recursive_triggers = ON")
    conn.create_function("_g6_sha256_hex", 1, _g6_sha256_hex_sql)


def _is_migration_managed_db(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return False
    return conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] > 0


def init_series_schema(conn: sqlite3.Connection) -> None:
    """Initialize series connection guards and (for unmigrated `:memory:` tests only) DDL.

    Per DB-17 (`docs/DB17_MIGRATION_DESIGN_DRAFT_20261111.md` §4 R1), when called
    on a migration-managed database (`schema_migrations` present), this function
    never executes `CREATE TABLE` or `CREATE TRIGGER` outside the migration chain.
    """
    register_series_connection_guards(conn)
    if _is_migration_managed_db(conn):
        return
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def persist_series(conn: sqlite3.Connection, series: SourceSeries) -> int:
    """Persist verified series editions into append-only SQLite storage."""
    rows = to_rows(series)
    cur = conn.cursor()
    inserted = 0
    for r in rows:
        existing = cur.execute(
            "SELECT is_frozen, sha256_hash FROM source_document_series_editions WHERE edition_id = ?",
            (r["edition_id"],),
        ).fetchone()
        if existing is None:
            cur.execute(
                """
                INSERT INTO source_document_series_editions (
                    edition_id, series_id, university, document_title,
                    rev_number, sha256_hash, content_text, supersedes_id, is_frozen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["edition_id"],
                    r["series_id"],
                    r["university"],
                    r["document_title"],
                    r["rev_number"],
                    r["sha256_hash"],
                    r["content_text"],
                    r["supersedes_id"],
                    r["is_frozen"],
                ),
            )
            inserted += 1
        elif existing[0] == 0 and r["is_frozen"] == 1:
            cur.execute(
                "UPDATE source_document_series_editions SET is_frozen = 1 WHERE edition_id = ?",
                (r["edition_id"],),
            )
    conn.commit()
    return inserted


def record_revision_impact(
    conn: sqlite3.Connection,
    impact_id: str,
    series_id: str,
    old_edition_id: str,
    new_edition_id: str,
    evidence_id: str,
    article_id: str,
) -> None:
    """Link a document edition revision to an impacted evidence ID and article ID."""
    conn.execute(
        """
        INSERT INTO series_revision_article_impacts (
            impact_id, series_id, old_edition_id, new_edition_id, evidence_id, article_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (impact_id, series_id, old_edition_id, new_edition_id, evidence_id, article_id),
    )
    conn.commit()
