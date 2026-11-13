"""M1.g3 formal read contract: what an article CITED, read as the exact version the article was written from.

Status: CONTRACT_PROPOSAL + SELF_VALIDATED reference reader (Claude, contract owner). It applies no schema to any database and is connected to no
product path. The storage names below (``HISTORY_DDL``) are a proposal for the 0010 / DB-17 / DB-19 migrations: the BEHAVIOUR (``read_cited_evidence``)
is the contract; the table names may change at 0010 and the tests then follow.  ``docs/G03_READ_CONTRACT_2026-11-07.md`` has the reasons.

The rules, in one place:

1. One entry: ``read_cited_evidence(db, article_id, evidence_id)``.  It runs in ONE read snapshot, writes nothing, and returns a frozen ``CitedEvidence``
   that carries the exact row, its digest, the source SHA, the case, the scope and the provenance.  Display and export use that object and
   NOTHING ELSE: they never look the evidence up again by id (``forbid_current_evidence_reads`` is the test tool that proves it).
2. The route is decided by the DATABASE, never by the caller and never by a fallback: an article registered as restored (``restored_articles``) is
   read only from its restored pin; any missing or inconsistent part is an error.  A restored article is never downgraded to an ordinary one, and the
   current row of the same evidence id is never returned in its place.
3. An ordinary (not restored) article is read exactly as before: the row of the evidence id its relation table names.  ``additive_schema.cited_version``
   refuses a restored article, so the old function cannot be used to read one by mistake.
4. Every comparison is exact: the stored row digest is recomputed from the row, and the case, the evidence id, the source SHA, the scope and the restore
   event must agree between the article, the pin and the stored version.  A scope that is missing or ``UNKNOWN`` is refused, never inferred.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

ROW_KEYS = ("evidence_id", "case_id", "fact_key", "source_sha256", "value_json", "record_json")
CYCLE_KEYS = ("university", "faculty", "department", "admission_method", "fiscal_year")
EXPECT_KEYS = frozenset({"case_id", "scope", "source_sha256", "row_digest", "record_subset"})

CODES = (
    "bad_input", "article_unknown", "cycle_unknown", "citation_missing", "citation_duplicated", "registry_ambiguous", "registry_inconsistent",
    "schema_unavailable", "restore_unavailable", "pin_missing", "pin_duplicated", "history_version_missing", "history_version_duplicated",
    "row_malformed", "digest_mismatch", "binding_mismatch", "case_mismatch", "source_mismatch", "source_unregistered", "scope_unknown",
    "scope_mismatch", "current_evidence_missing", "evidence_ambiguous", "not_restored", "restored_article_on_ordinary_route",
    "expectation_mismatch", "export_tampered",
)

# PROPOSAL for the storage of restored history (0010 / DB-17 / DB-19 decide the final form).  All five tables are append-only.
HISTORY_DDL = """
CREATE TABLE restore_events(
 restore_id TEXT NOT NULL PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('f2_recovery')),
 archive_sha256 TEXT NOT NULL CHECK(length(archive_sha256)=64), source_db_sha256 TEXT NOT NULL CHECK(length(source_db_sha256)=64),
 approved_by TEXT NOT NULL CHECK(length(trim(approved_by))>0), approved_at TEXT NOT NULL, approval_ref TEXT NOT NULL CHECK(length(trim(approval_ref))>0));
CREATE TABLE restore_revocations(
 restore_id TEXT NOT NULL PRIMARY KEY REFERENCES restore_events(restore_id), revoked_by TEXT NOT NULL, revoked_at TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE restored_articles(
 article_id TEXT NOT NULL PRIMARY KEY, restore_id TEXT NOT NULL REFERENCES restore_events(restore_id));
CREATE TABLE evidence_history_versions(
 version_id TEXT NOT NULL PRIMARY KEY, evidence_id TEXT NOT NULL, case_id TEXT NOT NULL, source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 row_json TEXT NOT NULL, row_digest TEXT NOT NULL UNIQUE CHECK(length(row_digest)=64), archive_row_sha256 TEXT NOT NULL,
 restore_id TEXT NOT NULL REFERENCES restore_events(restore_id), UNIQUE(restore_id, evidence_id));
CREATE TABLE article_history_pins(
 article_id TEXT NOT NULL, evidence_id TEXT NOT NULL, version_id TEXT NOT NULL REFERENCES evidence_history_versions(version_id),
 case_id TEXT NOT NULL, scope TEXT NOT NULL CHECK(length(trim(scope))>0), source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 row_digest TEXT NOT NULL CHECK(length(row_digest)=64), restore_id TEXT NOT NULL REFERENCES restore_events(restore_id), PRIMARY KEY(article_id, evidence_id));
"""
APPEND_ONLY_TABLES = ("restore_events", "restore_revocations", "restored_articles", "evidence_history_versions", "article_history_pins")
# Every UNIQUE key of the tables above (a PRIMARY KEY included).  tests/test_g03_replace_guard.py compares this list with what SQLite reports, so a new key cannot be forgotten.
HISTORY_UNIQUE_KEYS = {
    "restore_events": (("restore_id",),),
    "restore_revocations": (("restore_id",),),
    "restored_articles": (("article_id",),),
    "evidence_history_versions": (("version_id",), ("row_digest",), ("restore_id", "evidence_id")),
    "article_history_pins": (("article_id", "evidence_id"),),
}


def history_ddl(append_only: bool = True) -> str:
    """The proposed storage.  ``append_only=False`` omits the triggers (tests use it to simulate a tampered file the reader must still catch)."""
    if not append_only:
        return HISTORY_DDL
    triggers = "".join(
        f"CREATE TRIGGER trg_{t}_no_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;\n"
        f"CREATE TRIGGER trg_{t}_no_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;\n"
        + _no_replace_trigger(t) + _no_negative_rowid_trigger(t) for t in APPEND_ONLY_TABLES)
    return HISTORY_DDL + triggers


def _no_negative_rowid_trigger(table: str) -> str:
    """In a BEFORE INSERT trigger SQLite gives NEW.rowid the same value (-1) whether the rowid was left out or named, so the trigger above can only compare a rowid of 0 or more.  A row with a NEGATIVE
    rowid could then be replaced by naming that rowid, and comparing -1 would block every ordinary append once such a row exists.  So no row with a negative rowid may be created: an insert that ends up
    with one is aborted AFTER the insert (the abort undoes the statement, a replaced row included).  A file that already holds a row with rowid -1 keeps accepting appends (the next automatic rowid is 0)."""
    return f"CREATE TRIGGER trg_{table}_no_negative_rowid AFTER INSERT ON {table} WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, '{table} is append-only: rowid must not be negative'); END;\n"


def _no_replace_trigger(table: str) -> str:
    """``INSERT OR REPLACE`` (and ``REPLACE INTO``) deletes the row it collides with WITHOUT running the DELETE trigger unless the connection has ``PRAGMA recursive_triggers=ON``
    (SQLite's default is OFF, and the pragma is per connection, so a table cannot demand it).  A BEFORE INSERT trigger does run, whatever the conflict clause, so the insert is refused
    when the new row would collide with an existing one on ANY unique key, or on an explicitly given rowid (an insert that names the rowid replaces the row that has it, whatever its keys are)."""
    collisions = ["EXISTS (SELECT 1 FROM %s WHERE %s)" % (table, " AND ".join(f"{c} = NEW.{c}" for c in key)) for key in HISTORY_UNIQUE_KEYS[table]]
    collisions.append(f"(NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM {table} WHERE rowid = NEW.rowid))")
    return f"CREATE TRIGGER trg_{table}_no_replace BEFORE INSERT ON {table} WHEN {' OR '.join(collisions)} BEGIN SELECT RAISE(ABORT, '{table} is append-only: a row is never replaced'); END;\n"


GUARD_KINDS = ("no_update", "no_delete", "no_replace", "no_negative_rowid")
GUARD_TRIGGER_NAMES = frozenset(f"trg_{t}_{k}" for t in APPEND_ONLY_TABLES for k in GUARD_KINDS)


def history_preflight(db: sqlite3.Connection) -> list[str]:
    """READ ONLY.  The reasons why the guards of ``history_ddl`` must NOT be installed into an EXISTING file as it is; an empty list means there is none.  Nothing is changed or repaired here.

    * A table that does not exist, or lacks a key column: the guards are written for all five tables of ``HISTORY_DDL`` and a trigger on a missing table cannot be created.  A file without the history tables
      (or with only some of them) is refused with the reason; the tables have to be created first, and that is a step of its own (0010 / DB-17 / DB-19, not decided here).
    * Some, but not all, of the guard triggers already exist (a half-installed or a hand-edited file): installing again would fail on the first duplicate and leave an unclear state.  If all of them exist the
      file is already protected and there is nothing to refuse.
    * A table that holds a row with a NEGATIVE rowid: the guards never let a row with a negative rowid be created (see ``_no_negative_rowid_trigger``), and the next automatic rowid of such a table is
      negative too (the largest rowid + 1), so every ordinary append would be refused.  The contract does not support such a file: it has to be rebuilt by its owner (the rows copied into a new table, which
      gives them positive rowids), after the owner has decided how.  The five tables are created by no migration yet, so a real database cannot be in this state; a hand-made file can.
    * A NULL in a key column (a table made without the NOT NULL of ``HISTORY_DDL``): the unique keys cannot identify that row.
    """
    problems: list[str] = []
    present = _tables(db)
    for table in APPEND_ONLY_TABLES:
        if table not in present:
            problems.append(f"{table}: the table does not exist; the guards need all five history tables ({', '.join(APPEND_ONLY_TABLES)}), so nothing is installed into this file")
            continue
        columns = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        needed = {c for key in HISTORY_UNIQUE_KEYS[table] for c in key}
        if needed - columns:
            problems.append(f"{table}: the table lacks the key column(s) {', '.join(sorted(needed - columns))}; it is not the table the guards are written for")
            continue
        negative = db.execute(f'SELECT count(*) FROM "{table}" WHERE rowid < 0').fetchone()[0]
        if negative:
            problems.append(f"{table}: {negative} row(s) with a negative rowid; the guards would refuse every new row of this table (rebuild the table; nothing was changed)")
        for column in sorted(needed):
            nulls = db.execute(f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NULL').fetchone()[0]
            if nulls:
                problems.append(f"{table}: {nulls} row(s) with NULL in the key column {column}")
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")} & GUARD_TRIGGER_NAMES
    if existing and existing != GUARD_TRIGGER_NAMES:
        missing = sorted(GUARD_TRIGGER_NAMES - existing)
        problems.append(f"{len(existing)} of the {len(GUARD_TRIGGER_NAMES)} guard triggers already exist and {len(missing)} are missing ({', '.join(missing[:3])}{' ...' if len(missing) > 3 else ''}); the file is half protected")
    return problems


def history_guards_for(db: sqlite3.Connection) -> str:
    """The guard triggers (the part of ``history_ddl(True)`` after the tables) for an EXISTING file, or a refusal.  It only RETURNS SQL; it executes nothing and writes nothing, so the decision to
    apply it (on which copy, after which approval) stays with the owner.  If ``history_preflight`` reports anything it raises ``ValueError`` listing the reasons, and no SQL is returned.  If every guard
    trigger already exists the file is already protected and the answer is an empty string (a script that would fail on the first duplicate is never returned)."""
    problems = history_preflight(db)
    if problems:
        raise ValueError("the history guards are not installed into this file: " + "; ".join(problems))
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")} & GUARD_TRIGGER_NAMES
    if existing == GUARD_TRIGGER_NAMES:
        return ""
    return history_ddl(True)[len(HISTORY_DDL):]


class ReadContractError(ValueError):
    """A refusal of the read contract.  ``code`` is one of ``CODES``; nothing was written."""

    def __init__(self, code: str, message: str) -> None:
        assert code in CODES, code
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_of(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CitedEvidence:
    """The one object display and export may use.  Everything a reader needs to show or export the cited evidence is here, so that nothing is looked up again."""

    kind: str  # "current_citation" (an ordinary article) or "restored_history" (an article restored from the archive)
    article_id: str
    evidence_id: str
    version_id: str | None  # the id of the stored old version; None for an ordinary citation
    case_id: str
    scope: str | None
    source_sha256: str
    row: Mapping[str, Any]
    row_digest: str
    provenance: Mapping[str, Any] | None
    bound_digest: str

    def to_export(self) -> dict[str, Any]:
        return {"kind": self.kind, "article_id": self.article_id, "evidence_id": self.evidence_id, "version_id": self.version_id, "case_id": self.case_id,
                "scope": self.scope, "source_sha256": self.source_sha256, "row": dict(self.row), "row_digest": self.row_digest,
                "provenance": None if self.provenance is None else dict(self.provenance), "bound_digest": self.bound_digest}

    def record(self) -> dict[str, Any]:
        return json.loads(self.row["record_json"])


def _bound_digest(d: Mapping[str, Any]) -> str:
    keys = ("kind", "article_id", "evidence_id", "version_id", "case_id", "scope", "source_sha256", "row_digest", "provenance")
    return digest_of({k: d[k] for k in keys})


def verify_export(exported: Mapping[str, Any]) -> Mapping[str, Any]:
    """Check an exported citation without any database: the row still has its digest, and every identifying field is still the one that was bound at read time.
    Anything added, removed or changed after the read (a substituted version, source, scope, provenance or row) is refused."""
    try:
        keys = {"kind", "article_id", "evidence_id", "version_id", "case_id", "scope", "source_sha256", "row", "row_digest", "provenance", "bound_digest"}
        if not isinstance(exported, Mapping) or set(exported) != keys:
            raise ReadContractError("export_tampered", "the exported citation does not have exactly the bound fields")
        row = exported["row"]
        if not isinstance(row, Mapping) or tuple(sorted(row)) != tuple(sorted(ROW_KEYS)) or digest_of(dict(row)) != exported["row_digest"]:
            raise ReadContractError("export_tampered", "the exported row does not match its digest")
        if row["evidence_id"] != exported["evidence_id"] or row["case_id"] != exported["case_id"] or row["source_sha256"] != exported["source_sha256"]:
            raise ReadContractError("export_tampered", "the exported row does not match the bound identifiers")
        if exported["kind"] == "restored_history" and (not exported["version_id"] or not exported["provenance"] or not exported["scope"]):
            raise ReadContractError("export_tampered", "a restored citation must carry its version, scope and provenance")
        if exported["kind"] == "current_citation" and (exported["version_id"] is not None or exported["provenance"] is not None):
            raise ReadContractError("export_tampered", "an ordinary citation carries no restored version or provenance")
        if exported["kind"] not in ("restored_history", "current_citation") or _bound_digest(exported) != exported["bound_digest"]:
            raise ReadContractError("export_tampered", "the exported citation was changed after it was read")
    except TypeError as exc:  # unhashable / odd shapes are tampering too
        raise ReadContractError("export_tampered", f"unreadable exported citation: {exc}") from exc
    return exported


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReadContractError("bad_input", f"{name} must be a non-empty string")
    return value


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table')")}


@contextmanager
def _snapshot(db: sqlite3.Connection) -> Iterator[None]:
    """Every read of one call sees ONE state of the database.  If the caller already holds a transaction the caller's snapshot is used and left as it is."""
    own = not db.in_transaction
    if own:
        db.execute("BEGIN")
    try:
        yield
    finally:
        if own and db.in_transaction:
            db.execute("ROLLBACK")  # reads only: nothing to keep


def _one(rows: list, missing: str, many: str, what: str):
    if not rows:
        raise ReadContractError(missing, f"{what}: not found")
    if len(rows) > 1:
        raise ReadContractError(many, f"{what}: {len(rows)} rows, expected exactly one")
    return rows[0]


def _parse_row(raw: Any) -> dict[str, Any]:
    try:
        row = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ReadContractError("row_malformed", "the stored row is not JSON") from exc
    if not isinstance(row, dict) or sorted(row) != sorted(ROW_KEYS):
        raise ReadContractError("row_malformed", f"the stored row must have exactly the keys {list(ROW_KEYS)}")
    for k in ("evidence_id", "case_id", "fact_key", "source_sha256", "record_json"):
        if not isinstance(row[k], str):
            raise ReadContractError("row_malformed", f"{k} must be text")
    if row["value_json"] is not None and not isinstance(row["value_json"], str):
        raise ReadContractError("row_malformed", "value_json must be text or null")
    return row


def _record(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        record = json.loads(row["record_json"])
    except ValueError as exc:
        raise ReadContractError("row_malformed", "record_json is not JSON") from exc
    if not isinstance(record, dict):
        raise ReadContractError("row_malformed", "record_json must be an object")
    return record


def _check_expect(expect: Mapping[str, Any] | None, *, case_id: str, scope: str | None, source: str, row_digest: str, record: Mapping[str, Any]) -> None:
    if expect is None:
        return
    if not isinstance(expect, Mapping) or set(expect) - EXPECT_KEYS:
        raise ReadContractError("bad_input", f"expect may only contain {sorted(EXPECT_KEYS)}")
    have = {"case_id": case_id, "scope": scope, "source_sha256": source, "row_digest": row_digest}
    for k, v in have.items():
        if k in expect and expect[k] != v:
            raise ReadContractError("expectation_mismatch", f"the read {k} differs from the one the caller expects")
    for k, v in (expect.get("record_subset") or {}).items():
        if k not in record or canonical(record[k]) != canonical(v):
            raise ReadContractError("expectation_mismatch", f"the record field {k!r} differs from the one the caller expects")


def read_cited_evidence(db: sqlite3.Connection, article_id: str, evidence_id: str, *, expect: Mapping[str, Any] | None = None,
                        require_restored: bool | None = None) -> CitedEvidence:
    """The exact evidence version ``article_id`` cited as ``evidence_id``.  Read-only, one snapshot, no fallback.

    ``expect`` (optional) is what the CONSUMER holds for that citation (its own export record): ``case_id``, ``scope``, ``source_sha256``, ``row_digest`` and
    ``record_subset`` (fields of the record, e.g. the locator).  Any difference is a refusal.  ``require_restored`` (optional) states which route the caller
    believes it is on; a wrong belief is a refusal (True: the article must be a restored one; False: it must not be)."""
    _text(article_id, "article_id")
    _text(evidence_id, "evidence_id")
    with _snapshot(db):
        tables = _tables(db)
        row = db.execute("SELECT case_id FROM article_versions WHERE article_id=?", (article_id,)).fetchall() if "article_versions" in tables else []
        if not row and "revised_articles" in tables:
            row = db.execute("SELECT v.case_id FROM revised_articles r JOIN article_versions v ON v.article_id=r.base_article_id WHERE r.article_id=?", (article_id,)).fetchall()
        article_case = _one(row, "article_unknown", "article_unknown", f"article {article_id!r}")[0]
        cycle = db.execute("SELECT university, faculty, department, admission_method, fiscal_year FROM admission_cycles WHERE case_id=?", (article_case,)).fetchall() if "admission_cycles" in tables else []
        cycle = dict(zip(CYCLE_KEYS, _one(cycle, "cycle_unknown", "cycle_unknown", f"cycle of case {article_case!r}")))
        cited = 0
        for t in ("article_evidence", "revised_article_evidence"):
            if t in tables:
                cited += db.execute(f"SELECT count(*) FROM {t} WHERE article_id=? AND evidence_id=?", (article_id, evidence_id)).fetchone()[0]
        if cited == 0:
            raise ReadContractError("citation_missing", f"article {article_id!r} does not cite {evidence_id!r}")
        if cited > 1:
            raise ReadContractError("citation_duplicated", f"article {article_id!r} cites {evidence_id!r} {cited} times")
        registry = db.execute("SELECT restore_id FROM restored_articles WHERE article_id=?", (article_id,)).fetchall() if "restored_articles" in tables else []
        if len(registry) > 1:
            raise ReadContractError("registry_ambiguous", f"article {article_id!r} is registered as restored {len(registry)} times")
        pins_exist = "article_history_pins" in tables and db.execute("SELECT count(*) FROM article_history_pins WHERE article_id=?", (article_id,)).fetchone()[0] > 0
        if registry:
            if require_restored is False:
                raise ReadContractError("restored_article_on_ordinary_route", f"article {article_id!r} is a restored article")
            return _read_restored(db, tables, article_id, evidence_id, article_case, cycle, registry[0][0], expect)
        if pins_exist:
            raise ReadContractError("registry_inconsistent", f"article {article_id!r} has history pins but is not registered as restored: it is not read as an ordinary article")
        if require_restored is True:
            raise ReadContractError("not_restored", f"article {article_id!r} is not a restored article")
        return _read_ordinary(db, tables, article_id, evidence_id, article_case, expect)


def _finish(kind: str, article_id: str, evidence_id: str, version_id: str | None, case_id: str, scope: str | None, row: dict[str, Any],
            provenance: dict[str, Any] | None) -> CitedEvidence:
    row_digest = digest_of(row)
    fields = {"kind": kind, "article_id": article_id, "evidence_id": evidence_id, "version_id": version_id, "case_id": case_id, "scope": scope,
              "source_sha256": row["source_sha256"], "row_digest": row_digest, "provenance": provenance}
    return CitedEvidence(kind=kind, article_id=article_id, evidence_id=evidence_id, version_id=version_id, case_id=case_id, scope=scope,
                         source_sha256=row["source_sha256"], row=row, row_digest=row_digest, provenance=provenance, bound_digest=_bound_digest(fields))


def _read_ordinary(db, tables, article_id, evidence_id, article_case, expect) -> CitedEvidence:
    found = []
    for t, value in (("facts", "value_json"), ("evidence_revisions", "NULL")):
        if t in tables:
            found += db.execute(f"SELECT evidence_id, case_id, fact_key, source_sha256, {value}, record_json FROM {t} WHERE evidence_id=?", (evidence_id,)).fetchall()
    if not found:
        raise ReadContractError("current_evidence_missing", f"the evidence {evidence_id!r} cited by {article_id!r} does not exist")
    if len(found) > 1:
        raise ReadContractError("evidence_ambiguous", f"the evidence id {evidence_id!r} names {len(found)} rows")
    row = _parse_row(canonical(dict(zip(ROW_KEYS, found[0]))))
    if row["case_id"] != article_case:
        raise ReadContractError("case_mismatch", f"the cited evidence belongs to case {row['case_id']!r}, the article to {article_case!r}")
    record = _record(row)
    scope = record.get("scope") if isinstance(record.get("scope"), str) else None
    out = _finish("current_citation", article_id, evidence_id, None, article_case, scope, row, None)
    _check_expect(expect, case_id=article_case, scope=scope, source=row["source_sha256"], row_digest=out.row_digest, record=record)
    return out


def _read_restored(db, tables, article_id, evidence_id, article_case, cycle, restore_id, expect) -> CitedEvidence:
    for t in ("restore_events", "restore_revocations", "evidence_history_versions", "article_history_pins"):
        if t not in tables:
            raise ReadContractError("schema_unavailable", f"article {article_id!r} is a restored article but table {t} does not exist")
    event = db.execute("SELECT restore_id, archive_sha256, source_db_sha256, approved_by, approved_at, approval_ref FROM restore_events WHERE restore_id=?", (restore_id,)).fetchall()
    event = _one(event, "restore_unavailable", "restore_unavailable", f"restore event {restore_id!r}")
    if db.execute("SELECT 1 FROM restore_revocations WHERE restore_id=?", (restore_id,)).fetchone():
        raise ReadContractError("restore_unavailable", f"restore event {restore_id!r} was revoked")
    pin = db.execute("SELECT version_id, case_id, scope, source_sha256, row_digest, restore_id FROM article_history_pins WHERE article_id=? AND evidence_id=?", (article_id, evidence_id)).fetchall()
    version_id, pin_case, pin_scope, pin_source, pin_digest, pin_restore = _one(pin, "pin_missing", "pin_duplicated", f"history pin of ({article_id!r}, {evidence_id!r})")
    ver = db.execute("SELECT version_id, evidence_id, case_id, source_sha256, row_json, row_digest, archive_row_sha256, restore_id FROM evidence_history_versions WHERE version_id=?", (version_id,)).fetchall()
    v_id, v_evidence, v_case, v_source, v_json, v_digest, v_archive_row, v_restore = _one(ver, "history_version_missing", "history_version_duplicated", f"history version {version_id!r}")
    if db.execute("SELECT count(*) FROM evidence_history_versions WHERE restore_id=? AND evidence_id=?", (restore_id, evidence_id)).fetchone()[0] > 1:
        raise ReadContractError("history_version_duplicated", f"restore {restore_id!r} stores more than one version of {evidence_id!r}")
    row = _parse_row(v_json)
    if digest_of(row) != v_digest or v_digest != pin_digest:
        raise ReadContractError("digest_mismatch", "the stored row, its stored digest and the pinned digest are not the same")
    if v_evidence != evidence_id or row["evidence_id"] != evidence_id:
        raise ReadContractError("binding_mismatch", "the pinned version is a version of another evidence id")
    if pin_restore != restore_id or v_restore != restore_id:
        raise ReadContractError("binding_mismatch", "the pin, the version and the article's registration name different restore events")
    if not (row["case_id"] == v_case == pin_case == article_case):
        raise ReadContractError("case_mismatch", "the case of the article, the pin and the stored version are not the same")
    if not (row["source_sha256"] == v_source == pin_source):
        raise ReadContractError("source_mismatch", "the source SHA of the pin and the stored version are not the same")
    if "source_documents" not in tables or not db.execute("SELECT 1 FROM source_documents WHERE sha256=?", (row["source_sha256"],)).fetchone():
        raise ReadContractError("source_unregistered", "the source SHA of the stored version is not a registered source document")
    record = _record(row)
    scope = record.get("scope")
    if not isinstance(scope, str) or not scope.strip() or scope.strip().upper() == "UNKNOWN":
        raise ReadContractError("scope_unknown", "the stored version has no explicit scope; it is never inferred")
    if scope != pin_scope:
        raise ReadContractError("scope_mismatch", "the scope of the stored version is not the pinned scope")
    if "case_id" in record and record["case_id"] != article_case:
        raise ReadContractError("case_mismatch", "the record states another case")
    for key in ("source_pdf_sha256", "source_sha256"):
        if key in record and record[key] != row["source_sha256"]:
            raise ReadContractError("source_mismatch", f"the record's {key} differs from the stored source SHA")
    for key in CYCLE_KEYS:
        if key in record and record[key] != cycle[key]:
            raise ReadContractError("scope_mismatch", f"the record's {key} differs from the cycle of the article")
    out = _finish("restored_history", article_id, evidence_id, v_id, article_case, scope, row,
                  {"restore_id": event[0], "archive_sha256": event[1], "source_db_sha256": event[2], "approved_by": event[3], "approved_at": event[4],
                   "approval_ref": event[5], "archive_row_sha256": v_archive_row})
    _check_expect(expect, case_id=article_case, scope=scope, source=row["source_sha256"], row_digest=out.row_digest, record=record)
    return out


# ---- the test tool that proves display / export never look the evidence up again --------------------------------------------------------------
_EVIDENCE_PREFIXES = ("evidence_", "restore", "article_history", "article_evidence", "revised_article_evidence", "facts", "v_")


@contextmanager
def forbid_current_evidence_reads(db: sqlite3.Connection) -> Iterator[None]:
    """While active, ANY read of an evidence, history, relation or restore table (or view) on this connection is refused by SQLite itself.
    Run the display / export step inside it: it passes only if the step uses the ``CitedEvidence`` it was given and looks nothing up again."""
    names = set()

    def authorizer(action: int, arg1: str | None, arg2: str | None, dbname: str | None, source: str | None) -> int:
        if action == sqlite3.SQLITE_READ and arg1 and arg1.startswith(_EVIDENCE_PREFIXES):
            names.add(arg1)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.set_authorizer(authorizer)
    try:
        yield
    finally:
        db.set_authorizer(None)
