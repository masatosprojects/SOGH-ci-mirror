"""M1.g7 Product Implementation Candidate: Diverse Formats & Quarantine Staging.

Provides isolated quarantine staging, SQLite trigger guards against premature
or self-approved promotion, append-only immutability on staging and canonical
tables, cryptographic HMAC approval tokens, atomic transactional rollback,
and the 12-row table-cell refusal matrix in accordance with G-07 quarantine
isolation and STR-076 UNKNOWN policy.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "SCHEMA_SQL",
    "RefusalCode",
    "RefusalResult",
    "init_quarantine_schema",
    "stage_candidate",
    "review_candidate",
    "promote_candidate",
    "reject_candidate",
    "evaluate_table_cell_format",
    "evaluate_html_structure_format",
    "register_authorized_reviewers",
    "clear_authorized_reviewers",
]

# Process-local cryptographic authority secret for HMAC approval tokens (never derived from public values alone)
_APPROVAL_HMAC_SECRET = secrets.token_bytes(32)
_AUTHORIZED_SEAL_GRANTS: Dict[str, str] = {}
# External reviewer registry: loaded from external configuration (env SOGH_AUTHORIZED_REVIEWERS) or registered via register_authorized_reviewers; never hard-coded generic names
_AUTHORIZED_HUMAN_REVIEWERS: frozenset[str] = frozenset()


def _load_configured_reviewers() -> frozenset[str]:
    env_val = os.environ.get("SOGH_AUTHORIZED_REVIEWERS", "")
    from_env = {
        unicodedata.normalize("NFKC", x).strip()
        for x in env_val.split(",")
        if x.strip()
    }
    return _AUTHORIZED_HUMAN_REVIEWERS | from_env


def register_authorized_reviewers(reviewers: Iterable[str]) -> None:
    """Register authorized human reviewer identifiers in-process."""
    global _AUTHORIZED_HUMAN_REVIEWERS
    _AUTHORIZED_HUMAN_REVIEWERS = _AUTHORIZED_HUMAN_REVIEWERS | frozenset(
        unicodedata.normalize("NFKC", r).strip()
        for r in reviewers
        if r and str(r).strip()
    )


def clear_authorized_reviewers() -> None:
    """Clear all in-process registered reviewers."""
    global _AUTHORIZED_HUMAN_REVIEWERS
    _AUTHORIZED_HUMAN_REVIEWERS = frozenset()


def _is_authorized_human_reviewer(reviewer: str) -> bool:
    norm = unicodedata.normalize("NFKC", reviewer or "").strip()
    if not norm:
        return False
    configured = _load_configured_reviewers()
    if not configured:
        return False  # Closed by default: empty registry means no approver is authorized
    return norm in configured


def _extract_stager_identity(isolation_reason: Optional[str]) -> Optional[str]:
    if not isolation_reason:
        return None
    norm = unicodedata.normalize("NFKC", str(isolation_reason)).strip()
    m = re.search(r"(?:staged[\s_:-]*by|stager|submitted[\s_:-]*by)\s*[:=]?\s*([A-Za-z0-9_\-]+)", norm, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


SCHEMA_SQL = """
-- Quarantine candidate staging table (append-only payload; isolated from canonical facts)
CREATE TABLE IF NOT EXISTS quarantine_staging_candidates (
    staging_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    format_type TEXT NOT NULL,
    extracted_key TEXT NOT NULL,
    extracted_value TEXT NOT NULL,
    quarantine_status TEXT NOT NULL CHECK(quarantine_status IN ('QUARANTINED', 'PROMOTED', 'REJECTED')),
    review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(review_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    approved_by TEXT,
    approval_token TEXT,
    isolation_reason TEXT,
    staged_by TEXT,
    sha256_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    promoted_at TEXT
);

-- Internal authority seal table recording verified review approvals
CREATE TABLE IF NOT EXISTS _quarantine_approval_seals (
    staging_id TEXT PRIMARY KEY,
    reviewer TEXT NOT NULL,
    approval_token TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    sealed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Canonical mirror table for promotion verification (append-only)
CREATE TABLE IF NOT EXISTS canonical_facts_staging_target (
    fact_id TEXT PRIMARY KEY,
    staging_id TEXT NOT NULL UNIQUE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    promoted_at TEXT NOT NULL,
    FOREIGN KEY(staging_id) REFERENCES quarantine_staging_candidates(staging_id)
);

-- Guard 0: Enforce strict initial state on INSERT into quarantine_staging_candidates and block INSERT OR REPLACE
CREATE TRIGGER IF NOT EXISTS trg_quarantine_enforce_initial_insert
BEFORE INSERT ON quarantine_staging_candidates
FOR EACH ROW
WHEN NEW.quarantine_status != 'QUARANTINED'
  OR NEW.review_status != 'PENDING'
  OR NEW.approved_by IS NOT NULL
  OR NEW.approval_token IS NOT NULL
  OR NEW.promoted_at IS NOT NULL
  OR NEW.sha256_hash IS NULL
  OR length(trim(NEW.sha256_hash)) = 0
  OR EXISTS (
      SELECT 1 FROM quarantine_staging_candidates
      WHERE staging_id = NEW.staging_id
  )
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Initial staging insert must be QUARANTINED with PENDING review_status, no pre-approval, and cannot overwrite an existing staging_id');
END;

-- Guard 1: Prevent ANY mutation of REJECTED or PROMOTED records (terminal state immutability)
CREATE TRIGGER IF NOT EXISTS trg_quarantine_prevent_terminal_mutation
BEFORE UPDATE ON quarantine_staging_candidates
FOR EACH ROW
WHEN OLD.quarantine_status = 'REJECTED'
  OR OLD.review_status = 'REJECTED'
  OR OLD.quarantine_status = 'PROMOTED'
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Cannot mutate status of REJECTED candidate or terminal PROMOTED record');
END;

-- Guard 2: Enforce append-only immutability of staged payload, staged_by, hash fields, and promoted_at on UPDATE
CREATE TRIGGER IF NOT EXISTS trg_quarantine_immutable_payload
BEFORE UPDATE ON quarantine_staging_candidates
FOR EACH ROW
WHEN NEW.staging_id != OLD.staging_id
  OR NEW.source_id != OLD.source_id
  OR NEW.format_type != OLD.format_type
  OR NEW.extracted_key != OLD.extracted_key
  OR NEW.extracted_value != OLD.extracted_value
  OR COALESCE(NEW.staged_by, '') != COALESCE(OLD.staged_by, '')
  OR NEW.sha256_hash != OLD.sha256_hash
  OR NEW.created_at != OLD.created_at
  OR (NEW.promoted_at IS NOT NULL AND NEW.quarantine_status != 'PROMOTED')
  OR (OLD.promoted_at IS NOT NULL AND NEW.promoted_at != OLD.promoted_at)
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Staged candidate payload, staged_by, sha256_hash, and promoted_at are immutable');
END;

-- Guard 3: Prevent DELETE on quarantine_staging_candidates (append-only audit trail)
CREATE TRIGGER IF NOT EXISTS trg_quarantine_prevent_delete
BEFORE DELETE ON quarantine_staging_candidates
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Quarantine staging table is append-only; DELETE is prohibited');
END;

-- Guard 4: Require named approver, cryptographic token, and verified HMAC authority seal when transitioning to APPROVED
CREATE TRIGGER IF NOT EXISTS trg_quarantine_enforce_approval_credentials
BEFORE UPDATE ON quarantine_staging_candidates
FOR EACH ROW
WHEN NEW.review_status = 'APPROVED'
  AND (
      NEW.approved_by IS NULL
      OR length(trim(NEW.approved_by)) = 0
      OR NEW.approval_token IS NULL
      OR length(trim(NEW.approval_token)) < 16
      OR COALESCE((
          SELECT approval_token FROM _quarantine_approval_seals
          WHERE staging_id = NEW.staging_id
            AND reviewer = NEW.approved_by
            AND payload_sha256 = OLD.sha256_hash
      ), '') != NEW.approval_token
      OR (
          OLD.staged_by IS NOT NULL
          AND lower(trim(OLD.staged_by)) = lower(trim(NEW.approved_by))
      )
      OR _g7_verify_hmac_seal(
          NEW.staging_id,
          NEW.approved_by,
          NEW.approval_token,
          OLD.sha256_hash
      ) != 1
  )
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: APPROVED status requires verified approver, token, and cryptographic authority seal');
END;

-- Guard 5: Once APPROVED, review_status, approved_by, and approval_token cannot be altered
CREATE TRIGGER IF NOT EXISTS trg_quarantine_lock_approved_review
BEFORE UPDATE ON quarantine_staging_candidates
FOR EACH ROW
WHEN OLD.review_status = 'APPROVED'
  AND (
      NEW.review_status != 'APPROVED'
      OR COALESCE(NEW.approved_by, '') != COALESCE(OLD.approved_by, '')
      OR COALESCE(NEW.approval_token, '') != COALESCE(OLD.approval_token, '')
  )
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Cannot alter review fields after APPROVED');
END;

-- Guard 6: Prevent promotion unless candidate was ALREADY in QUARANTINED + APPROVED state prior to promotion UPDATE
CREATE TRIGGER IF NOT EXISTS trg_quarantine_enforce_promotion_flow
BEFORE UPDATE OF quarantine_status ON quarantine_staging_candidates
FOR EACH ROW
WHEN NEW.quarantine_status = 'PROMOTED'
  AND (
      OLD.quarantine_status != 'QUARANTINED'
      OR OLD.review_status != 'APPROVED'
      OR NEW.review_status != 'APPROVED'
      OR OLD.approved_by IS NULL
      OR OLD.approval_token IS NULL
  )
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Promotion requires prior verified review_status APPROVED from QUARANTINED state');
END;

-- Guard 7: Prevent direct insert into canonical target unless staging is PROMOTED, APPROVED, and key/value match exactly
CREATE TRIGGER IF NOT EXISTS trg_canonical_block_unquarantined
BEFORE INSERT ON canonical_facts_staging_target
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN COALESCE((
            SELECT quarantine_status FROM quarantine_staging_candidates
            WHERE staging_id = NEW.staging_id
              AND review_status = 'APPROVED'
              AND approved_by IS NOT NULL
              AND approval_token IS NOT NULL
              AND extracted_key = NEW.key
              AND extracted_value = NEW.value
        ), '') != 'PROMOTED'
        THEN RAISE(ABORT, 'G-07 VIOLATION: Canonical insert requires PROMOTED+APPROVED staging with exact key/value match')
    END;
END;

-- Guard 8: Enforce append-only immutability on canonical_facts_staging_target
CREATE TRIGGER IF NOT EXISTS trg_canonical_prevent_update
BEFORE UPDATE ON canonical_facts_staging_target
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Canonical target table is append-only; UPDATE prohibited');
END;

CREATE TRIGGER IF NOT EXISTS trg_canonical_prevent_delete
BEFORE DELETE ON canonical_facts_staging_target
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Canonical target table is append-only; DELETE prohibited');
END;
"""


class RefusalCode:
    ACCEPTED = "ACCEPTED"
    AMBIGUOUS_MULTI_YEAR = "REFUSED_AMBIGUOUS_MULTI_YEAR"
    UNKNOWN_SCHEMA_KEY = "REFUSED_UNKNOWN_SCHEMA_KEY"
    LAYOUT_COLLAPSE = "REFUSED_LAYOUT_COLLAPSE"
    MISSING_EVIDENCE_CONTEXT = "REFUSED_MISSING_EVIDENCE_CONTEXT"
    VALUE_NOT_IN_TABLE = "REFUSED_VALUE_NOT_IN_TABLE"
    ROW_LABEL_MISMATCH = "REFUSED_ROW_LABEL_MISMATCH"
    COLUMN_POOL_MISMATCH = "REFUSED_COLUMN_POOL_MISMATCH"
    PAGE_MISMATCH = "REFUSED_PAGE_MISMATCH"
    TABLE_TITLE_MISMATCH = "REFUSED_TABLE_TITLE_MISMATCH"
    CROSS_SOURCE_MISMATCH = "REFUSED_CROSS_SOURCE_MISMATCH"
    POOL_TAMPERED = "REFUSED_POOL_TAMPERED"
    BUNDLE_HASH_MISMATCH = "REFUSED_BUNDLE_HASH_MISMATCH"
    INVALID_UNIT_OR_TYPE = "REFUSED_INVALID_UNIT_OR_TYPE"
    UNKNOWN_GRANULARITY = "REFUSED_UNKNOWN_GRANULARITY"


@dataclasses.dataclass(frozen=True)
class RefusalResult:
    decision: str  # "ACCEPT" or "REFUSE"
    code: str
    reason: str
    normalized_value: Optional[str] = None
    quarantine_payload: Optional[Dict[str, Any]] = None


def _compute_payload_sha256(source_id: str, format_type: str, extracted_key: str, extracted_value: str) -> str:
    canonical = json.dumps(
        [source_id, format_type, extracted_key, extracted_value],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _issue_approval_token(staging_id: str, reviewer: str, payload_sha256: str) -> str:
    msg = f"{staging_id}:{reviewer}:{payload_sha256}".encode("utf-8")
    return hmac.new(_APPROVAL_HMAC_SECRET, msg, hashlib.sha256).hexdigest()[:32]


def _verify_hmac_seal_sql(
    staging_id: Optional[str],
    reviewer: Optional[str],
    approval_token: Optional[str],
    payload_sha256: Optional[str],
) -> int:
    if not (
        isinstance(staging_id, str)
        and isinstance(reviewer, str)
        and isinstance(approval_token, str)
        and isinstance(payload_sha256, str)
    ):
        return 0
    clean_reviewer = reviewer.strip()
    if not _is_authorized_human_reviewer(clean_reviewer):
        return 0
    expected = _issue_approval_token(staging_id, clean_reviewer, payload_sha256)
    if not hmac.compare_digest(expected, approval_token):
        return 0
    granted = _AUTHORIZED_SEAL_GRANTS.get(staging_id)
    if granted is None or not hmac.compare_digest(granted, approval_token):
        return 0
    return 1


def register_quarantine_connection_guards(conn: sqlite3.Connection) -> None:
    """DDL-free connection guard registration (DB-17 R1)."""
    conn.execute("PRAGMA recursive_triggers = ON")
    conn.create_function("_g7_verify_hmac_seal", 4, _verify_hmac_seal_sql)


def _is_migration_managed_db(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return False
    return conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] > 0


def init_quarantine_schema(conn: sqlite3.Connection) -> None:
    """Initialize quarantine connection guards and (for unmigrated `:memory:` tests only) DDL.

    Per DB-17 (`docs/DB17_MIGRATION_DESIGN_DRAFT_20261111.md` §4 R1), when called
    on a migration-managed database (`schema_migrations` present), this function
    never executes `CREATE TABLE` or `CREATE TRIGGER` outside the migration chain.
    """
    register_quarantine_connection_guards(conn)
    if _is_migration_managed_db(conn):
        return
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def stage_candidate(
    conn: sqlite3.Connection,
    staging_id: str,
    source_id: str,
    format_type: str,
    extracted_key: str,
    extracted_value: str,
    isolation_reason: Optional[str] = None,
    staged_by: Optional[str] = None,
) -> str:
    """Stage a candidate in quarantine isolation with PENDING review status.

    Idempotent if re-submitted with identical staging_id and identical payload hash.
    """
    register_quarantine_connection_guards(conn)
    sha = _compute_payload_sha256(source_id, format_type, extracted_key, extracted_value)
    stager = (staged_by.strip() if isinstance(staged_by, str) and staged_by.strip() else _extract_stager_identity(isolation_reason))

    existing = conn.execute(
        "SELECT sha256_hash FROM quarantine_staging_candidates WHERE staging_id = ?",
        (staging_id,),
    ).fetchone()
    if existing is not None:
        if existing[0] == sha:
            return staging_id
        raise sqlite3.IntegrityError(
            f"G-07 VIOLATION: Conflicting re-submission for staging_id '{staging_id}'"
        )

    conn.execute(
        """
        INSERT INTO quarantine_staging_candidates (
            staging_id, source_id, format_type, extracted_key, extracted_value,
            quarantine_status, review_status, isolation_reason, staged_by, sha256_hash
        ) VALUES (?, ?, ?, ?, ?, 'QUARANTINED', 'PENDING', ?, ?, ?)
        """,
        (staging_id, source_id, format_type, extracted_key, extracted_value, isolation_reason, stager, sha),
    )
    conn.commit()
    return staging_id


def review_candidate(
    conn: sqlite3.Connection,
    staging_id: str,
    decision: str,  # "APPROVED" or "REJECTED"
    reviewer: str,
    approval_token: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> bool:
    """Record formal review decision on a quarantined candidate."""
    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError(f"Invalid review decision: {decision}")
    if not reviewer or not str(reviewer).strip():
        raise ValueError("Reviewer identity is required")
    clean_reviewer = str(reviewer).strip()

    register_quarantine_connection_guards(conn)
    row = conn.execute(
        "SELECT quarantine_status, review_status, sha256_hash, staged_by, isolation_reason FROM quarantine_staging_candidates WHERE staging_id = ?",
        (staging_id,),
    ).fetchone()
    if not row:
        return False

    q_status, r_status, payload_sha, staged_by_col, iso_reason = row[0], row[1], row[2], row[3], row[4]
    if q_status != "QUARANTINED" or r_status != "PENDING":
        raise sqlite3.IntegrityError(
            f"G-07 VIOLATION: Cannot review candidate in state ({q_status}, {r_status})"
        )

    cur = conn.cursor()
    if decision == "APPROVED":
        if not _is_authorized_human_reviewer(clean_reviewer):
            raise PermissionError(
                f"G-07 VIOLATION: Reviewer '{clean_reviewer}' is not an authorized human reviewer (AI/automated/unregistered identities forbidden)"
            )
        stager_actor = staged_by_col or _extract_stager_identity(iso_reason)
        if not stager_actor or not str(stager_actor).strip():
            raise PermissionError(
                "G-07 VIOLATION: Candidate was staged without a recorded stager identity (staged_by required to verify separation of duties)"
            )
        if unicodedata.normalize("NFKC", stager_actor).strip().lower() == unicodedata.normalize("NFKC", clean_reviewer).strip().lower():
            raise PermissionError(
                f"G-07 VIOLATION: Separation of duties violation — stager '{stager_actor}' cannot approve their own staged candidate"
            )
        if approval_token is not None:
            raise PermissionError(
                "G-07 VIOLATION: Caller-supplied approval_token is not accepted as authority"
            )
        token = _issue_approval_token(staging_id, clean_reviewer, payload_sha)
        _AUTHORIZED_SEAL_GRANTS[staging_id] = token

        cur.execute(
            """
            INSERT OR REPLACE INTO _quarantine_approval_seals (
                staging_id, reviewer, approval_token, payload_sha256
            ) VALUES (?, ?, ?, ?)
            """,
            (staging_id, clean_reviewer, token, payload_sha),
        )
        cur.execute(
            """
            UPDATE quarantine_staging_candidates
            SET review_status = 'APPROVED',
                approved_by = ?,
                approval_token = ?
            WHERE staging_id = ? AND quarantine_status = 'QUARANTINED' AND review_status = 'PENDING'
            """,
            (clean_reviewer, token, staging_id),
        )
    else:
        cur.execute(
            """
            UPDATE quarantine_staging_candidates
            SET quarantine_status = 'REJECTED',
                review_status = 'REJECTED',
                isolation_reason = COALESCE(?, isolation_reason)
            WHERE staging_id = ? AND quarantine_status = 'QUARANTINED'
            """,
            (rejection_reason, staging_id),
        )
    conn.commit()
    return cur.rowcount > 0


def promote_candidate(
    conn: sqlite3.Connection,
    staging_id: str,
    fact_id: str,
) -> bool:
    """Promote an approved quarantined candidate to canonical target with strict transactional atomicity."""
    row = conn.execute(
        """
        SELECT extracted_key, extracted_value, quarantine_status, review_status, approved_by, approval_token
        FROM quarantine_staging_candidates
        WHERE staging_id = ?
        """,
        (staging_id,),
    ).fetchone()

    if not row:
        return False

    q_status, r_status, approved_by, approval_token = row[2], row[3], row[4], row[5]
    if q_status != "QUARANTINED":
        raise sqlite3.IntegrityError(f"G-07 VIOLATION: Candidate status is {q_status}, must be QUARANTINED")

    if r_status != "APPROVED" or not approved_by or not approval_token:
        raise sqlite3.IntegrityError("G-07 VIOLATION: Promotion requires verified review_status APPROVED")

    cur = conn.cursor()
    try:
        cur.execute("SAVEPOINT promote_savepoint")
        cur.execute(
            """
            UPDATE quarantine_staging_candidates
            SET quarantine_status = 'PROMOTED',
                promoted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE staging_id = ?
            """,
            (staging_id,),
        )

        cur.execute(
            """
            INSERT INTO canonical_facts_staging_target (fact_id, staging_id, key, value, promoted_at)
            VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (fact_id, staging_id, row[0], row[1]),
        )
        cur.execute("RELEASE SAVEPOINT promote_savepoint")
        conn.commit()
        return True
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT promote_savepoint")
        cur.execute("RELEASE SAVEPOINT promote_savepoint")
        conn.commit()
        raise


def reject_candidate(
    conn: sqlite3.Connection,
    staging_id: str,
    reason: str,
) -> bool:
    """Mark candidate as REJECTED in quarantine (terminal immutable state)."""
    return review_candidate(
        conn,
        staging_id=staging_id,
        decision="REJECTED",
        reviewer="system",
        rejection_reason=reason,
    )


_KANJI_DIGIT_MAP = str.maketrans("〇零一二三四五六七八九", "00123456789")


def _normalize_kanji_numbers(text: str) -> str:
    """Convert Kanji positional digits and 十-compounds (e.g., 二〇二七 -> 2027, 九 -> 9, 十 -> 10, 十一 -> 11)."""
    def _single_kanji_int(k: str) -> str:
        if k == "元":
            return "1"
        if k == "十":
            return "10"
        if k.startswith("十") and len(k) == 2:
            return f"1{k[1].translate(_KANJI_DIGIT_MAP)}"
        if k.endswith("十") and len(k) == 2:
            return f"{k[0].translate(_KANJI_DIGIT_MAP)}0"
        if "十" in k and len(k) == 3:
            return f"{k[0].translate(_KANJI_DIGIT_MAP)}{k[2].translate(_KANJI_DIGIT_MAP)}"
        return k.translate(_KANJI_DIGIT_MAP)

    # First normalize era compounds with separators like 令和九・十年度 -> 令和9・10年度
    def _era_pair_num(m: re.Match[str]) -> str:
        prefix, k1, sep, k2 = m.group(1), m.group(2), m.group(3), m.group(4)
        return f"{prefix}{_single_kanji_int(k1)}{sep}{_single_kanji_int(k2)}"

    out = re.sub(
        r"(令和|平成|昭和)\s*([元〇零一二三四五六七八九十]+)\s*([・/／\-〜～~と、,])\s*([元〇零一二三四五六七八九十]+)",
        _era_pair_num,
        text,
    )
    out = re.sub(
        r"(令和|平成|昭和)\s*([元〇零一二三四五六七八九十]+)",
        lambda m: f"{m.group(1)}{_single_kanji_int(m.group(2))}",
        out,
    )
    out = re.sub(
        r"[〇零一二三四五六七八九]{2,4}",
        lambda m: m.group(0).translate(_KANJI_DIGIT_MAP),
        out,
    )
    return out


def _has_multi_year_ambiguity(text: str) -> bool:
    norm = _normalize_kanji_numbers(unicodedata.normalize("NFKC", text or ""))
    # 1. 4-digit Western year followed by another 4-digit or 2-digit year (e.g., 2027〜2028, 2027/28年度, 2027年度から2028年度まで)
    if re.search(
        r"(?:19\d\d|20\d\d)\s*(?:年度|年)?\s*(?:[-〜～~・/／と、,]|から|より|および|及び|または|又は)\s*(?:19\d\d|20\d\d|\d{2}\s*(?:年度|年))",
        norm,
    ):
        return True
    if re.search(r"(?:19\d\d|20\d\d)\s*/\s*\d{2}\s*(?:年度|年)", norm):
        return True
    # 2. 2-digit year ranges ONLY when at least one side has an explicit year suffix 年度 or 年 (never match 10〜12名 or 11〜12月)
    if re.search(
        r"(?<!\d)[2-9]\d\s*(?:年度|年)\s*(?:[-〜～~・/／と、,]|から|より|および|及び|または|又は)\s*[2-9]\d\s*(?:年度|年)",
        norm,
    ):
        return True
    if re.search(
        r"(?<!\d)[2-9]\d\s*[・/／\-〜～~と、,]\s*[2-9]\d\s*(?:年度|年)",
        norm,
    ):
        return True
    # 3. Japanese era ranges/lists (e.g., 令和9・10年度, R9年度〜R10年度, 令和9年度及び令和10年度)
    if re.search(
        r"(?:令和|平成|昭和|[RHRh])\s*(?:\d+|元)\s*(?:年度|年)?\s*(?:[-〜～~・/／と、,]|から|より|および|及び|または|又は)\s*(?:令和|平成|昭和|[RHRh])?\s*(?:\d+|元)\s*(?:年度|年)",
        norm,
    ):
        return True
    if re.search(r"(?:翌年度|次年度|前年度|昨年度|複数年度|または翌|および翌|及び翌)", norm):
        return True
    return False


def _extract_normalized_years(text: str) -> set[int]:
    """Extract all Western (4-digit & suffixed 2-digit), Kanji, and Japanese era fiscal/academic years from text."""
    norm = _normalize_kanji_numbers(unicodedata.normalize("NFKC", text or ""))
    years: set[int] = set()
    for ym in re.finditer(
        r"(?:(19\d\d|20\d\d)\s*(?:年度|年|/|-|〜|～|~)|FY\s*(19\d\d|20\d\d)|(?:令和|R|r)\s*(\d+)\s*(?:年度|年|入試)|(?:平成|H|h)\s*(\d+)\s*(?:年度|年|入試)|(?<!\d)([2-9]\d)\s*年度)",
        norm,
    ):
        if ym.group(1):
            years.add(int(ym.group(1)))
        elif ym.group(2):
            years.add(int(ym.group(2)))
        elif ym.group(3):
            years.add(2018 + int(ym.group(3)))
        elif ym.group(4):
            years.add(1988 + int(ym.group(4)))
        elif ym.group(5):
            years.add(2000 + int(ym.group(5)))
    for pair in re.finditer(
        r"(19\d\d|20\d\d)\s*[/\-〜～~]\s*(19\d\d|20\d\d)", norm
    ):
        years.add(int(pair.group(1)))
        years.add(int(pair.group(2)))
    for slash_pair in re.finditer(
        r"(19\d\d|20\d\d)\s*/\s*(\d{2})\s*(?:年度|年)", norm
    ):
        y1 = int(slash_pair.group(1))
        years.add(y1)
        years.add((y1 // 100) * 100 + int(slash_pair.group(2)))
    for era_pair in re.finditer(
        r"(令和|平成|[RHRh])\s*(\d+)\s*(?:年度|年)?\s*[・/／\-〜～~と、,]\s*(?:令和|平成|[RHRh])?\s*(\d+)\s*(?:年度|年)",
        norm,
    ):
        era = era_pair.group(1).upper()
        base = 2018 if era in ("令和", "R") else 1988
        years.add(base + int(era_pair.group(2)))
        years.add(base + int(era_pair.group(3)))
    return years


def evaluate_table_cell_format(table_data: Dict[str, Any]) -> RefusalResult:
    """Evaluate table-cell / geometry candidate against the 12-row G-07 refusal matrix.

    Enforces:
    - Layout integrity (non-empty headers/rows, consistent column count)
    - Multi-year ambiguity refusal (Western, full-width, Reiwa, Heisei, FY, slash notations)
    - Known schema key & registry type/unit rules (admission_quota requires positive integer)
    - Cell existence & coordinate binding (row_label, column/pool, page, table_title, cross-source, bundle_sha256)
    - UNKNOWN granularity refusal
    """
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])
    context_text = table_data.get("context_text", "")

    if not headers or not rows:
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.LAYOUT_COLLAPSE,
            reason="Empty table headers or rows detected",
        )

    # Check consistent column count across rows
    expected_cols = len(headers)
    for r_idx, row in enumerate(rows):
        if len(row) != expected_cols:
            return RefusalResult(
                decision="REFUSE",
                code=RefusalCode.LAYOUT_COLLAPSE,
                reason=f"Row {r_idx} column count mismatch: expected {expected_cols}, got {len(row)}",
            )

    # Row 5: Multi-year ambiguity detection across context_text and headers, or explicit column_year mismatch
    combined_year_text = f"{context_text} {' '.join(str(h) for h in headers)}"
    year_numbers = _extract_normalized_years(combined_year_text)
    if len(year_numbers) > 1 or _has_multi_year_ambiguity(combined_year_text):
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.AMBIGUOUS_MULTI_YEAR,
            reason=f"Ambiguous multiple fiscal years present in table context: {sorted(year_numbers)}",
        )

    if "column_year" in table_data and "expected_year" in table_data:
        if table_data["column_year"] != table_data["expected_year"]:
            return RefusalResult(
                decision="REFUSE",
                code=RefusalCode.AMBIGUOUS_MULTI_YEAR,
                reason=f"Column year {table_data['column_year']} does not match expected year {table_data['expected_year']}",
            )

    # Row 10: Granularity UNKNOWN check
    granularity = table_data.get("scope_granularity")
    if isinstance(granularity, dict):
        for dim, val in granularity.items():
            if val is None or str(val).strip() == "" or str(val).strip().upper() == "UNKNOWN":
                return RefusalResult(
                    decision="REFUSE",
                    code=RefusalCode.UNKNOWN_GRANULARITY,
                    reason=f"Required scope granularity dimension '{dim}' is UNKNOWN",
                )

    # Row 3, 4, 6, 7: Page, Table Title, Cross-source, and Pool tampering checks
    if "page" in table_data and "expected_page" in table_data:
        if table_data["page"] != table_data["expected_page"]:
            return RefusalResult(
                decision="REFUSE",
                code=RefusalCode.PAGE_MISMATCH,
                reason=f"Page {table_data['page']} does not match expected page {table_data['expected_page']}",
            )

    if "primary_page" in table_data and "secondary_page" in table_data:
        if table_data["primary_page"] != table_data["secondary_page"]:
            return RefusalResult(
                decision="REFUSE",
                code=RefusalCode.CROSS_SOURCE_MISMATCH,
                reason="Primary and secondary source pages do not match",
            )

    if "table_title" in table_data and "expected_table_title" in table_data:
        if table_data["table_title"] != table_data["expected_table_title"]:
            return RefusalResult(
                decision="REFUSE",
                code=RefusalCode.TABLE_TITLE_MISMATCH,
                reason="Table title does not match expected title",
            )

    if "structured_pool" in table_data and "source_pool" in table_data:
        if table_data["structured_pool"] != table_data["source_pool"]:
            return RefusalResult(
                decision="REFUSE",
                code=RefusalCode.POOL_TAMPERED,
                reason="Admission pool was altered after structuring",
            )

    # Known schema key check
    target_key = table_data.get("target_key")
    recognized_keys = {
        "admission_quota",
        "admission_unit_quota",  # the fact_key adopted by the user on 2026-11-13 (STR-138 decision 3); see docs/G7_TITLE_SCOPE_AND_FACT_KEY_CONTRACT.md section 6
        "admission_category_quota",  # Work's earlier working name for the same meaning; still accepted for existing bundles
        "application_deadline",
        "selection_date",
        "announcement_date",
        "faculty_name",
        "department_name",
    }
    if target_key and target_key not in recognized_keys:
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.UNKNOWN_SCHEMA_KEY,
            reason=f"Target key '{target_key}' not in recognized fact key catalog",
        )

    raw_val = str(table_data.get("raw_cell_value", "")).strip()
    if not raw_val:
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.MISSING_EVIDENCE_CONTEXT,
            reason="Target cell value is empty",
        )

    # Row 9: Registry unit and type validation for quota keys (must be positive integer, optional unit 名)
    if target_key in ("admission_quota", "admission_unit_quota", "admission_category_quota"):
        if not re.fullmatch(r"[1-9][0-9]*(?:名)?", raw_val):
            return RefusalResult(
                decision="REFUSE",
                code=RefusalCode.INVALID_UNIT_OR_TYPE,
                reason=f"Quota value '{raw_val}' violates positive integer / unit '名' registry contract",
            )

    # Row 1 & Row 2: Verify cell exists in table rows and matches requested row_label and column
    requested_row_label = table_data.get("row_label")
    requested_column = table_data.get("column")

    if requested_column is not None and requested_column not in headers:
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.COLUMN_POOL_MISMATCH,
            reason=f"Requested column '{requested_column}' not found in headers {headers}",
        )

    matched_coords: List[Tuple[str, str]] = []
    found_at_requested_row = False

    for row in rows:
        r_label = str(row[0]).strip() if row else ""
        if requested_row_label is not None and r_label == str(requested_row_label).strip():
            found_at_requested_row = True
            for c_idx, cell in enumerate(row):
                if c_idx == 0 and len(headers) > 1 and requested_column is None:
                    # Skip row label column when matching data values unless explicitly requested
                    pass
                if str(cell).strip() == raw_val:
                    col_name = str(headers[c_idx])
                    if requested_column is None or col_name == str(requested_column):
                        matched_coords.append((r_label, col_name))
        elif requested_row_label is None:
            for c_idx, cell in enumerate(row):
                if str(cell).strip() == raw_val:
                    col_name = str(headers[c_idx])
                    if requested_column is None or col_name == str(requested_column):
                        matched_coords.append((r_label, col_name))

    if requested_row_label is not None and not found_at_requested_row:
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.ROW_LABEL_MISMATCH,
            reason=f"Row label '{requested_row_label}' not found in table",
        )

    if len(matched_coords) == 0:
        code = (
            RefusalCode.ROW_LABEL_MISMATCH
            if requested_row_label is not None
            else (
                RefusalCode.COLUMN_POOL_MISMATCH
                if requested_column is not None
                else RefusalCode.VALUE_NOT_IN_TABLE
            )
        )
        return RefusalResult(
            decision="REFUSE",
            code=code,
            reason=f"Cell value '{raw_val}' does not exist at the specified table coordinates",
        )

    if len(matched_coords) > 1:
        code = (
            RefusalCode.ROW_LABEL_MISMATCH
            if requested_row_label is None
            else RefusalCode.COLUMN_POOL_MISMATCH
        )
        return RefusalResult(
            decision="REFUSE",
            code=code,
            reason=f"Ambiguous cell value '{raw_val}' matches {len(matched_coords)} cells {matched_coords}; specify disambiguating row_label and column",
        )

    matched_row_label, matched_column = matched_coords[0]

    page_val = table_data.get("page", 1)
    title_val = table_data.get("table_title", context_text[:80] if context_text else "untitled_table")
    bundle_canonical = json.dumps(
        {
            "target_key": target_key,
            "value": raw_val,
            "row_label": matched_row_label,
            "column": matched_column,
            "page": page_val,
            "table_title": title_val,
            "headers": headers,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    bundle_sha256 = hashlib.sha256(bundle_canonical.encode("utf-8")).hexdigest()

    # Row 8: External bundle SHA verification
    expected_bundle_sha = table_data.get("expected_bundle_sha256")
    if expected_bundle_sha is not None and expected_bundle_sha != bundle_sha256:
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.BUNDLE_HASH_MISMATCH,
            reason=f"Bundle SHA-256 '{bundle_sha256}' does not match expected '{expected_bundle_sha}'",
        )

    return RefusalResult(
        decision="ACCEPT",
        code=RefusalCode.ACCEPTED,
        reason="Table-cell geometry, coordinates, and schema constraints verified (quarantine staging only)",
        normalized_value=raw_val,
        quarantine_payload={
            "target_key": target_key,
            "value": raw_val,
            "row_label": matched_row_label,
            "column": matched_column,
            "page": page_val,
            "table_title": title_val,
            "bundle_sha256": bundle_sha256,
            "headers": headers,
            "context_year": list(year_numbers)[0] if year_numbers else None,
        },
    )


def evaluate_html_structure_format(html_data: Dict[str, Any]) -> RefusalResult:
    """Evaluate HTML layout candidate (attributes, section hierarchy)."""
    tag = html_data.get("tag", "")
    text = html_data.get("text", "").strip()
    attrs = html_data.get("attributes", {})

    if not tag or not text:
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.LAYOUT_COLLAPSE,
            reason="Missing HTML tag or empty inner text",
        )

    classes = attrs.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()

    if any("deprecated" in c.lower() or "draft" in c.lower() for c in classes):
        return RefusalResult(
            decision="REFUSE",
            code=RefusalCode.MISSING_EVIDENCE_CONTEXT,
            reason="HTML element marked with draft or deprecated class attribute",
        )

    return RefusalResult(
        decision="ACCEPT",
        code=RefusalCode.ACCEPTED,
        reason="HTML element structure cleanly verified",
        normalized_value=text,
        quarantine_payload={"tag": tag, "text": text, "attributes": attrs},
    )
