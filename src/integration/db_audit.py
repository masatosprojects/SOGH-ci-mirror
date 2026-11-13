"""Read-only audit of an admissions database against the DB v1 acceptance contract (docs/DB_ACCEPTANCE_CONTRACT.md).

    python -m src.integration.db_audit <db.sqlite> --target-kind {synthetic,repository_sample,copied_real_db,production_read_only}
                                       [--baseline <older copy>] [--json-out report.json]

Two schema lineages exist in the repository and are told apart by their tables: `flat` (v0.3 and later: admission_cycles with the
names inline, facts, evidence_revisions ...) and `normalized_v0_2` (the first sample DB: universities, admission_routes,
fact_claims, publications ...). Each has its own invariants; a database of neither shape gets only DB-01.

`--target-kind` is REQUIRED and recorded in the report: a pass on a synthetic database is not a pass on a real one.

Nothing is written: the database is opened with mode=ro. Run it on a COPY of a real database (never on a production file).
Every invariant is reported as `pass`, `fail`, `warn` or `not_run`; `not_run` (a table the database does not have, no baseline
given) is never counted as a pass. The exit code is 1 when any invariant fails.

What it cannot check, and says so: the original PDFs / HTML (`source_documents.local_path` is not opened), whether a quoted
sentence is on its page of the ORIGINAL, and anything about rows that are not in the database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

APPROVED_STATES = {"approved"}
KNOWN_BATCH_STATES = {"candidate", "pending_contract", "no_change", "approved", "rejected", "interrupted", "rolled_back"}
# tables whose rows must never change or disappear once written (append-only history)
APPEND_ONLY = ("admission_cycles", "source_documents", "source_pages", "facts", "article_versions", "article_evidence",
               "evidence_revisions", "revised_articles", "update_batches", "update_events", "legacy_imports", "legacy_records")
_CITE = re.compile(r"\[(EV-[A-Za-z0-9_\-]+)\]")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _json(text: Any) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _problem(**kw: Any) -> dict[str, Any]:
    return kw


def _cycles(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {r["case_id"]: dict(r) for r in db.execute("SELECT * FROM admission_cycles")}


# ---------------------------------------------------------------------------------------------------- invariants

def db01_integrity(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        out.append(_problem(what="integrity_check is not ok"))
    for row in db.execute("PRAGMA foreign_key_check"):
        out.append(_problem(what="foreign key violation", table=row[0], rowid=row[1], references=row[2]))
    return out


def db02_cycles(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    seen: dict[tuple, str] = {}
    for c in _cycles(db).values():
        key = (c["university"], c["faculty"], c["department"] or "", c["admission_method"], c["fiscal_year"])
        if key in seen:  # UNIQUE does not see NULL departments as equal
            out.append(_problem(what="the same university/faculty/department/method/year twice", case_ids=[seen[key], c["case_id"]]))
        seen[key] = c["case_id"]
        if not (c["fiscal_year"] - 1 <= c["exam_year"] <= c["fiscal_year"]):
            out.append(_problem(what="exam year is not the entry year or the year before it", case_id=c["case_id"],
                                fiscal_year=c["fiscal_year"], exam_year=c["exam_year"], severity="warn"))
    return out


def db03_sources(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    for r in db.execute("SELECT sha256 FROM source_documents"):
        if not _HEX64.fullmatch(r["sha256"]):
            out.append(_problem(what="source sha256 is not 64 lowercase hex", sha256=r["sha256"]))
    if "source_pages" in t:
        for r in db.execute("SELECT source_sha256,page,text,text_sha256 FROM source_pages"):
            if hashlib.sha256(r["text"].encode()).hexdigest() != r["text_sha256"]:
                out.append(_problem(what="page text does not match its text_sha256", source=r["source_sha256"][:12], page=r["page"]))
    return out


def _record_problems(kind: str, eid: str, record: Any, cycle: dict[str, Any] | None, case_id: str) -> list[dict]:
    if not isinstance(record, dict):
        return [_problem(what=f"{kind} record_json is not an object", evidence_id=eid)]
    out = []
    if record.get("evidence_id") != eid:
        out.append(_problem(what=f"{kind}: record evidence_id differs from its key", evidence_id=eid, record_id=record.get("evidence_id")))
    if cycle is None:
        return out
    for field, value in (("fiscal_year", cycle["fiscal_year"]), ("admission_method", cycle["admission_method"]),
                         ("university", cycle["university"]), ("faculty", cycle["faculty"])):
        if field in record and record[field] != value:
            out.append(_problem(what=f"{kind}: record {field} differs from its admission cycle (a year / method / school mix-up)",
                                evidence_id=eid, case_id=case_id, record=record[field], cycle=value))
    return out


def db04_facts(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    cycles = _cycles(db)
    for r in db.execute("SELECT evidence_id,case_id,source_sha256,fact_key,value_json,record_json FROM facts"):
        record = _json(r["record_json"])
        out += _record_problems("fact", r["evidence_id"], record, cycles.get(r["case_id"]), r["case_id"])
        if isinstance(record, dict):
            if record.get("key", record.get("fact_key")) != r["fact_key"]:
                out.append(_problem(what="fact: the row's fact_key differs from its record", evidence_id=r["evidence_id"]))
            if "value" in record and _json(r["value_json"]) != record["value"]:
                out.append(_problem(what="fact: value_json differs from the record's value", evidence_id=r["evidence_id"]))
            recorded = record.get("source_sha256") or record.get("source_pdf_sha256")
            if recorded and recorded != r["source_sha256"]:
                out.append(_problem(what="fact: the record's source hash differs from the row's source_sha256", evidence_id=r["evidence_id"]))
    return out


def db05_revisions(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    cycles = _cycles(db)
    facts = {r["evidence_id"]: (r["case_id"], r["fact_key"]) for r in db.execute("SELECT evidence_id,case_id,fact_key FROM facts")}
    revs = {r["evidence_id"]: r for r in db.execute("SELECT * FROM evidence_revisions")}
    parents = {e: r["parent_evidence_id"] for e, r in revs.items()}
    for eid, r in revs.items():
        out += _record_problems("revision", eid, _json(r["record_json"]), cycles.get(r["case_id"]), r["case_id"])
        p = r["parent_evidence_id"]
        if p:
            ref = facts.get(p) or ((revs[p]["case_id"], revs[p]["fact_key"]) if p in revs else None)
            if ref is None:
                out.append(_problem(what="revision parent does not exist", evidence_id=eid, parent=p))
            elif ref != (r["case_id"], r["fact_key"]):
                out.append(_problem(what="revision parent belongs to another cycle or fact_key", evidence_id=eid, parent=p))
        cur, seen = r["parent_evidence_id"], {eid}
        while cur:
            if cur in seen:
                out.append(_problem(what="revision ancestry cycle", evidence_id=eid))
                break
            seen.add(cur)
            cur = parents.get(cur)
    for h in db.execute("SELECT logical_id,evidence_id FROM evidence_heads"):
        r = revs.get(h["evidence_id"])
        if r is None:
            out.append(_problem(what="evidence head points to no revision", logical_id=h["logical_id"], evidence_id=h["evidence_id"]))
        elif r["logical_id"] != h["logical_id"]:
            out.append(_problem(what="evidence head's logical_id differs from its revision", logical_id=h["logical_id"], evidence_id=h["evidence_id"]))
    return out


def _known_ids(db: sqlite3.Connection, t: set[str]) -> dict[str, str]:
    known = {r["evidence_id"]: r["case_id"] for r in db.execute("SELECT evidence_id,case_id FROM facts")}
    if "evidence_revisions" in t:
        known.update({r["evidence_id"]: r["case_id"] for r in db.execute("SELECT evidence_id,case_id FROM evidence_revisions")})
    return known


def db06_articles(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    known = _known_ids(db, t)
    cases = {r["article_id"]: r["case_id"] for r in db.execute("SELECT article_id,case_id FROM article_versions")}
    for a in db.execute("SELECT article_id,case_id,body,publish_allowed FROM article_versions"):
        if a["publish_allowed"] != 0:
            out.append(_problem(what="an article is marked publishable by the database", article_id=a["article_id"]))
        for eid in sorted(set(_CITE.findall(a["body"]))):
            if eid not in known:
                out.append(_problem(what="article cites evidence the database does not have", article_id=a["article_id"], evidence_id=eid))
            elif known[eid] != a["case_id"]:
                out.append(_problem(what="article cites evidence of another cycle", article_id=a["article_id"], evidence_id=eid))
    if "article_evidence" in t:
        for r in db.execute("SELECT article_id,evidence_id FROM article_evidence"):
            if known.get(r["evidence_id"]) not in (None, cases.get(r["article_id"])):
                out.append(_problem(what="article_evidence links evidence of another cycle", article_id=r["article_id"], evidence_id=r["evidence_id"]))
    if "revised_articles" in t:
        revised = {}
        for r in db.execute("SELECT article_id,base_article_id,record_json FROM revised_articles"):
            revised[r["article_id"]] = r["base_article_id"]
            rec = _json(r["record_json"])
            if r["base_article_id"] not in cases:
                out.append(_problem(what="revised article's base does not exist", article_id=r["article_id"]))
                continue
            if not isinstance(rec, dict):
                out.append(_problem(what="revised article record_json is not an object", article_id=r["article_id"]))
                continue
            if rec.get("publish_allowed") is not False:
                out.append(_problem(what="a revised article is not explicitly unpublishable", article_id=r["article_id"]))
            if ":revision:" in r["article_id"]:
                suffix = r["article_id"].rsplit(":revision:", 1)[1]
                if not str(rec.get("revision_hash", "")).startswith(suffix):
                    out.append(_problem(what="a revised article's id does not carry its revision_hash (tampered or recomputed?)", article_id=r["article_id"]))
                if rec.get("base_article_id") not in (None, r["base_article_id"]):
                    out.append(_problem(what="a revised article's record names another base than its row", article_id=r["article_id"]))
            for eid in sorted(set(_CITE.findall(rec.get("text", "")))):
                if eid not in known:
                    out.append(_problem(what="revised article cites evidence the database does not have", article_id=r["article_id"], evidence_id=eid))
                elif known[eid] != cases[r["base_article_id"]]:
                    out.append(_problem(what="revised article cites evidence of another cycle", article_id=r["article_id"], evidence_id=eid))
        if "article_heads" in t:
            for h in db.execute("SELECT base_article_id,article_id FROM article_heads"):
                if revised.get(h["article_id"]) != h["base_article_id"]:
                    out.append(_problem(what="article head is not a revision of its base", base=h["base_article_id"], article_id=h["article_id"]))
    return out


def db07_batches(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    events = {}
    if "update_events" in t:
        for r in db.execute("SELECT batch_id,event FROM update_events"):
            events.setdefault(r["batch_id"], set()).add(r["event"])
    for b in db.execute("SELECT batch_id,input_sha,state,qa_json FROM update_batches"):
        if b["state"] not in KNOWN_BATCH_STATES:
            out.append(_problem(what="unknown batch state", batch_id=b["batch_id"], state=b["state"], severity="warn"))
        if b["state"] == "candidate":
            out.append(_problem(what="a candidate batch was never approved or rejected: recover it before the next update",
                                batch_id=b["batch_id"], severity="warn"))
        if b["state"] in APPROVED_STATES:
            qa = _json(b["qa_json"])
            if not isinstance(qa, dict) or qa.get("success") is not True:
                out.append(_problem(what="an approved batch has no successful QA result", batch_id=b["batch_id"]))
            elif qa.get("batch_input_sha") != b["input_sha"]:
                out.append(_problem(what="an approved batch's QA is not bound to its input", batch_id=b["batch_id"]))
            if "approved" not in events.get(b["batch_id"], set()):
                out.append(_problem(what="an approved batch has no 'approved' event", batch_id=b["batch_id"]))
    if "evidence_heads" in t:
        approved = [b for b in db.execute("SELECT batch_id,after_json FROM update_batches WHERE state='approved' ORDER BY created_at DESC, rowid DESC LIMIT 1")]
        if approved:
            after = _json(approved[0]["after_json"])
            heads = {r["logical_id"]: r["evidence_id"] for r in db.execute("SELECT logical_id,evidence_id FROM evidence_heads")}
            if isinstance(after, dict) and after.get("evidence") and any(heads.get(k) != v for k, v in after["evidence"].items()):
                out.append(_problem(what="the latest approved batch's evidence heads are not the current heads (a partial or rolled-back update?)",
                                    batch_id=approved[0]["batch_id"], severity="warn"))
    return out


def db08_duplicates(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    seen: dict[str, str] = {}
    out = []
    for r in db.execute("SELECT evidence_id,logical_id,record_json FROM evidence_revisions"):
        rec = _json(r["record_json"])
        if not isinstance(rec, dict):
            continue
        body = {k: v for k, v in rec.items() if k not in ("evidence_id", "retrieved_at", "parent_evidence_id", "replaces_evidence_ids", "revision_ancestors")}
        key = hashlib.sha256(json.dumps([r["logical_id"], body], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if key in seen:
            out.append(_problem(what="two revisions of one logical fact have identical content", evidence_ids=[seen[key], r["evidence_id"]], severity="warn"))
        seen[key] = r["evidence_id"]
    return out


def _squash(text: str) -> str:
    import unicodedata
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def db12_quotes_on_pages(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """Each proof quote of a fact must appear (NFKC, whitespace removed) on the STORED page it cites. This is the stored copy, not the
    original PDF/HTML: it does not replace the check against the original (always not_run here)."""
    out = []
    pages = {(r["source_sha256"], r["page"]): _squash(r["text"]) for r in db.execute("SELECT source_sha256,page,text FROM source_pages")}
    for r in db.execute("SELECT evidence_id,source_sha256,record_json FROM facts"):
        rec = _json(r["record_json"])
        for proof in (rec.get("proofs") or []) if isinstance(rec, dict) else []:
            if not isinstance(proof, dict) or not proof.get("quote") or not isinstance(proof.get("page"), int):
                continue
            page = pages.get((r["source_sha256"], proof["page"]))
            if page is None:
                continue  # page not stored: nothing to compare with (not a pass, just not examined)
            if _squash(proof["quote"]) not in page:
                out.append(_problem(what="a quoted sentence is not on the stored page it cites", evidence_id=r["evidence_id"], page=proof["page"]))
    return out


def db10_dimensions(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """cycle_dimensions repeats the entry / exam year of admission_cycles: the two must agree (a year can live in only one place)."""
    out = []
    cycles = _cycles(db)
    for d in db.execute("SELECT case_id,entry_year,exam_year FROM cycle_dimensions"):
        c = cycles.get(d["case_id"])
        if c and (d["entry_year"] != c["fiscal_year"] or d["exam_year"] != c["exam_year"]):
            out.append(_problem(what="cycle_dimensions disagrees with admission_cycles about the entry / exam year", case_id=d["case_id"]))
    return out


_REGISTRY_ERRORS = {"unregistered_fact_key", "value_not_object", "value_type_mismatch", "stage_invalid", "stage_conflict"}


def db11_registry(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """Every fact / revision uses a registered fact_key and a value of the registered shape (the QA contract, registry.check_record)."""
    from src.verify.fact_registry import get_registry
    registry = get_registry()
    out = []
    for table in [n for n in ("facts", "evidence_revisions") if n in t]:
        for r in db.execute(f"SELECT evidence_id,record_json FROM {table}"):
            rec = _json(r["record_json"])
            if not isinstance(rec, dict):
                continue
            rec.setdefault("fact_key", rec.get("key"))
            for issue in registry.check_record(rec, r["evidence_id"]):
                if issue.category in _REGISTRY_ERRORS:
                    out.append(_problem(what=f"{table}: {issue.category}", evidence_id=r["evidence_id"], detail=issue.detail[:120]))
    return out


def _schema_objects(db: sqlite3.Connection) -> dict[str, Any]:
    triggers = [(r["name"], r["tbl_name"], r["sql"] or "") for r in db.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='trigger'")]
    indexes = [(r["name"], r["tbl_name"]) for r in db.execute("SELECT name,tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%'")]
    return {"triggers": triggers, "indexes": indexes}


def db14_append_only_triggers(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """History is only append-only if the DATABASE refuses an UPDATE / DELETE of an old row. Today it is enforced by code only (gap G-09):
    every append-only table without a refusing trigger is listed. A warning, not a failure: the contract does not yet require triggers."""
    objs = _schema_objects(db)
    out = []
    for table in [n for n in APPEND_ONLY if n in t]:
        guarded = {kind for _, tbl, sql in objs["triggers"] if tbl == table for kind in ("UPDATE", "DELETE") if kind in sql.upper() and "RAISE" in sql.upper()}
        if guarded != {"UPDATE", "DELETE"}:
            out.append(_problem(what="an append-only table has no trigger refusing UPDATE/DELETE of old rows", table=table,
                                missing=sorted({"UPDATE", "DELETE"} - guarded), severity="warn"))
    return out


_LOOKUPS = {"facts": "case_id", "evidence_revisions": "case_id", "article_versions": "case_id", "revised_articles": "base_article_id",
            "batch_evidence": "evidence_id", "update_events": "batch_id"}


def db15_lookup_indexes(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """The columns the audit and the impact analysis look rows up by must be indexed (gap G-03: the delivered schema has no index at all)."""
    out = []
    for table, column in _LOOKUPS.items():
        if table not in t:
            continue
        covered = False
        for idx in db.execute(f"PRAGMA index_list('{table}')"):
            cols = [r[2] for r in db.execute(f"PRAGMA index_info('{idx[1]}')")]
            covered |= bool(cols) and cols[0] == column
        if not covered:
            out.append(_problem(what="a lookup column has no index that starts with it", table=table, column=column, severity="warn"))
    return out


def db16_roots(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """Every revision belongs to a series that has a root (a native fact, or a first revision whose parent is unknown). A cyclic or broken series has none: impact analysis would silently drop it.
    Computed here by its own recursive query (not through the migration's view), so that a missing or edited view cannot hide an orphan."""
    rows = db.execute("WITH RECURSIVE reach(id) AS (SELECT evidence_id FROM facts "
                      "UNION SELECT evidence_id FROM evidence_revisions WHERE parent_evidence_id IS NULL OR parent_evidence_id NOT IN (SELECT evidence_id FROM facts UNION SELECT evidence_id FROM evidence_revisions) "
                      "UNION SELECT r.evidence_id FROM evidence_revisions r JOIN reach c ON r.parent_evidence_id = c.id) "
                      "SELECT evidence_id FROM evidence_revisions WHERE evidence_id NOT IN (SELECT id FROM reach) ORDER BY evidence_id").fetchall()
    return [_problem(what="a revision has no root (a cyclic or broken revision series)", evidence_id=r[0]) for r in rows]


def db17_schema_state(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """The schema that is really there against the migrations that the history says were applied: definition checksums, applied-SQL hashes, order, user_version, and every object the
    applied migrations created (a dropped, edited or unexpected protection is a failure). A detection, not a prevention."""
    from src.db_contract import additive_schema as ad
    try:
        problems = ad.verify_history(db) + ad.verify_schema_state(db) + ad.provenance_problems_if_history(db)
    except ad.MigrationError as e:
        problems = [str(e)]
    return [_problem(what=m) for m in problems]


def db18_head_replay(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    """The current heads must equal the replay of the recorded approval and rollback events (the state after the last one). A head that no approved batch explains, or a recorded approval that the
    heads do not show, is the failure. Computed here from update_events and update_batches directly (not through the migration's view)."""
    out = []
    row = db.execute("SELECT b.after_json, b.before_json, e.event FROM update_events e JOIN update_batches b ON b.batch_id = e.batch_id WHERE e.event IN ('approved', 'rolled_back') ORDER BY e.id DESC LIMIT 1").fetchone()
    expected = {"evidence": {}, "articles": {}}
    if row is not None:
        state = _json(row["after_json"] if row["event"] == "approved" else row["before_json"]) or {}
        expected = {"evidence": state.get("evidence", {}), "articles": state.get("articles", {})}
    actual = {"evidence": dict(db.execute("SELECT logical_id, evidence_id FROM evidence_heads").fetchall()), "articles": dict(db.execute("SELECT base_article_id, article_id FROM article_heads").fetchall())}
    for kind in ("evidence", "articles"):
        for k in sorted(set(expected[kind]) | set(actual[kind])):
            if expected[kind].get(k) != actual[kind].get(k):
                out.append(_problem(what="the current head differs from the replay of the approval and rollback events", kind=kind, key=k, replay=expected[kind].get(k), current=actual[kind].get(k)))
    return out


INVARIANTS: list[tuple[str, str, tuple[str, ...], Callable[[sqlite3.Connection, set[str]], list[dict]]]] = [
    ("DB-01", "integrity and foreign keys", (), db01_integrity),
    ("DB-02", "cycle identity (university / faculty / department / method / entry year) and exam year", ("admission_cycles",), db02_cycles),
    ("DB-03", "source documents and page hashes", ("source_documents",), db03_sources),
    ("DB-04", "facts agree with their cycle (year, method, school) and with their own record", ("facts", "admission_cycles"), db04_facts),
    ("DB-05", "revision parents, ancestry, heads", ("evidence_revisions", "evidence_heads", "facts", "admission_cycles"), db05_revisions),
    ("DB-06", "articles cite only evidence of their own cycle; never publishable; heads are revisions of their base",
     ("article_versions", "facts"), db06_articles),
    ("DB-07", "update batches: states, bound QA, events, unrecovered candidates", ("update_batches",), db07_batches),
    ("DB-08", "no two revisions of one logical fact with identical content", ("evidence_revisions",), db08_duplicates),
    ("DB-10", "cycle_dimensions agrees with admission_cycles about the entry / exam year", ("cycle_dimensions", "admission_cycles"), db10_dimensions),
    ("DB-11", "every fact / revision uses a registered fact_key and a value of the registered shape", ("facts",), db11_registry),
    ("DB-12", "each quote of a fact is on the stored page it cites (the stored copy, not the original)", ("facts", "source_pages"), db12_quotes_on_pages),
    ("DB-14", "append-only tables are protected by triggers (structure; needs no rows)", ("facts",), db14_append_only_triggers),
    ("DB-15", "lookup columns are indexed (structure; needs no rows)", ("facts",), db15_lookup_indexes),
    ("DB-16", "every revision has a root (no cyclic or broken revision series)", ("evidence_revisions", "facts"), db16_roots),
    ("DB-17", "the schema that is there matches the applied migrations (history, applied SQL, objects, user_version)", ("schema_migrations",), db17_schema_state),
    ("DB-18", "the current heads equal the replay of the recorded approval and rollback events", ("update_events", "update_batches", "evidence_heads", "article_heads"), db18_head_replay),
]
STRUCTURAL = {"DB-14", "DB-15"}  # judged on the schema alone: no rows are needed, and they are never `pass` by accident


def db19_restore_check(db: sqlite3.Connection, tables: set[str], manifests: Any = None, archive_rows: Any = None) -> dict[str, Any]:
    """DB-19 (M1 gate g3): the check of RESTORED history (the five tables of migration 0010), wired to the pure function ``restore_check.verify_restore_records``.
    not_run: no 0010 table at all (a pre-0010 database). pass: all five exist and are empty ("no restore happened"). Anything else goes to the pure function with the evidence that was supplied
    (``manifests`` = the approval verifier's results by restore_id, ``archive_rows`` = the external archive baseline). A restore row without manifest evidence FAILS (never passes): the database alone
    cannot tell a signed restore from a forged row. Read-only; nothing is repaired."""
    from src.db_contract.historical_read import APPEND_ONLY_TABLES
    from src.db_contract.restore_check import verify_restore_records
    title = "restored history is explained by a signed approval and an archive (the 0010 tables)"
    present = [n for n in APPEND_ONLY_TABLES if n in tables]
    if not present:
        return {"title": title, "status": "not_run", "reason": "migration 0010 is not applied: there is no restore history table", "problems": []}
    if len(present) == len(APPEND_ONLY_TABLES) and all(db.execute(f"SELECT count(*) FROM {n}").fetchone()[0] == 0 for n in APPEND_ONLY_TABLES):
        return {"title": title, "status": "pass", "reason": "all five restore history tables exist and are empty: no restore happened", "problems": [], "problem_count": 0}
    result = verify_restore_records(db, manifests=manifests, archive_rows=archive_rows)
    problems = [_problem(what=m) for m in result["problems"]]
    status = "fail" if (problems or result["status"] != "pass") else "pass"
    return {"title": title, "status": status, "problems": problems[:50], "problem_count": len(problems),
            "evidence_supplied": {"manifests": manifests is not None, "archive_rows": archive_rows is not None}}


# ------------------------------------------------------------------------------------------ normalized v0.2 lineage

def v02_snapshots(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    for r in db.execute("SELECT id,content_sha256 FROM source_snapshots"):
        if not _HEX64.fullmatch(r["content_sha256"]):
            out.append(_problem(what="snapshot sha256 is not 64 lowercase hex", snapshot_id=r["id"]))
    return out


def v02_facts(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    supports: dict[str, list[str]] = {}
    official_docs = {r["id"] for r in db.execute("SELECT id FROM source_documents WHERE source_kind LIKE 'official%'")}
    snap_doc = {r["id"]: r["document_id"] for r in db.execute("SELECT id,document_id FROM source_snapshots")}
    for r in db.execute("SELECT fact_id,snapshot_id FROM fact_evidence WHERE relation='supports'"):
        supports.setdefault(r["fact_id"], []).append(r["snapshot_id"])
    for f in db.execute("SELECT id,basis,review_status,superseded_by FROM fact_claims"):
        if f["review_status"] == "verified":
            snaps = supports.get(f["id"], [])
            if not snaps:
                out.append(_problem(what="a verified fact has no supporting evidence", fact_id=f["id"]))
            elif f["basis"] == "official" and not any(snap_doc.get(s) in official_docs for s in snaps):
                out.append(_problem(what="an 'official' fact is supported by no official document", fact_id=f["id"]))
        if f["superseded_by"] and f["superseded_by"] == f["id"]:
            out.append(_problem(what="a fact supersedes itself", fact_id=f["id"]))
        if f["review_status"] == "superseded" and not f["superseded_by"]:
            out.append(_problem(what="a superseded fact does not say by which fact", fact_id=f["id"], severity="warn"))
    return out


def v02_articles(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    plan_cycle = {r["id"]: r["cycle_id"] for r in db.execute("SELECT id,cycle_id FROM article_plans")}
    version_plan = {r["id"]: (r["plan_id"], r["review_status"]) for r in db.execute("SELECT id,plan_id,review_status FROM article_versions")}
    fact_info = {r["id"]: (r["cycle_id"], r["review_status"]) for r in db.execute("SELECT id,cycle_id,review_status FROM fact_claims")}
    for r in db.execute("SELECT article_version_id,fact_id FROM article_version_facts"):
        plan, review = version_plan.get(r["article_version_id"], (None, None))
        cycle, fact_status = fact_info.get(r["fact_id"], (None, None))
        if plan and cycle and plan_cycle.get(plan) != cycle:
            out.append(_problem(what="an article version cites a fact of another cycle", article_version_id=r["article_version_id"], fact_id=r["fact_id"]))
        if review == "approved" and fact_status != "verified":
            out.append(_problem(what="an approved article version cites a fact that is not verified", article_version_id=r["article_version_id"],
                                fact_id=r["fact_id"], fact_status=fact_status))
    return out


def v02_publications(db: sqlite3.Connection, t: set[str]) -> list[dict]:
    out = []
    review = {r["id"]: r["review_status"] for r in db.execute("SELECT id,review_status FROM article_versions")}
    for p in db.execute("SELECT id,article_version_id,publish_status,external_url FROM publications"):
        if p["publish_status"] in ("draft", "published") and review.get(p["article_version_id"]) != "approved":
            out.append(_problem(what="a draft/published post belongs to an article version that is not approved", publication_id=p["id"]))
        if p["publish_status"] == "published" and not p["external_url"]:
            out.append(_problem(what="a published post has no external url", publication_id=p["id"]))
    return out


V02_INVARIANTS: list[tuple[str, str, tuple[str, ...], Callable[[sqlite3.Connection, set[str]], list[dict]]]] = [
    ("V02-02", "snapshot hashes", ("source_snapshots",), v02_snapshots),
    ("V02-03", "verified / official facts have supporting official evidence", ("fact_claims", "fact_evidence", "source_snapshots", "source_documents"), v02_facts),
    ("V02-04", "article versions cite facts of their own cycle; approved versions cite only verified facts",
     ("article_versions", "article_plans", "article_version_facts", "fact_claims"), v02_articles),
    ("V02-05", "posts: draft/published only for approved article versions; published has a url", ("publications", "article_versions"), v02_publications),
]


def lineage_of(tables: set[str]) -> str:
    if {"facts", "admission_cycles"} <= tables and "fact_claims" not in tables:
        return "flat"
    if {"fact_claims", "article_plans"} <= tables:
        return "normalized_v0_2"
    return "unknown"


def check_preserved(old: sqlite3.Connection, new: sqlite3.Connection) -> list[dict]:
    """Every row of every append-only table of the OLDER copy must still be in the newer database, unchanged."""
    out = []
    old_t, new_t = _tables(old), _tables(new)
    for table in APPEND_ONLY:
        if table not in old_t:
            continue
        if table not in new_t:
            out.append(_problem(what="a table of the older copy no longer exists", table=table))
            continue
        old_cols = [r[1] for r in old.execute(f"PRAGMA table_info({table})")]
        new_cols = {r[1] for r in new.execute(f"PRAGMA table_info({table})")}
        if not set(old_cols) <= new_cols:
            out.append(_problem(what="a column of the older copy no longer exists", table=table, columns=sorted(set(old_cols) - new_cols)))
            continue
        cols = ", ".join(old_cols)
        have = {tuple(r) for r in new.execute(f"SELECT {cols} FROM {table}")}
        missing = [tuple(r) for r in old.execute(f"SELECT {cols} FROM {table}") if tuple(r) not in have]
        if missing:
            out.append(_problem(what="rows of the older copy were changed or removed", table=table, rows=len(missing), first=str(missing[0][0])[:60]))
    return out


DESCRIBE_INPUTS = """Inputs needed to audit a REAL database (docs/DB_COPY_PROCEDURE.md):
 1. an independent copy made with sqlite3 ".backup" from a read-only connection (never the live file), scrubbed of local paths and secrets
 2. the copy's SHA-256 and byte size (the audit records them; --expect-sha256 refuses another file)
 3. the output of: sqlite3 <db> .schema  (indexes and triggers included)
 4. optionally, a copy made BEFORE the latest update (--baseline): without it DB-09 is not_run
 5. when and how the copy was made
Without a real copy every real-data gate stays unmet: not_run is never a pass. Never send the live database, keys, tokens or original PDFs."""

TARGET_KINDS = ("synthetic", "repository_sample", "copied_real_db", "production_read_only")


def copy_identity(path: Path) -> dict[str, Any]:
    """Which file was audited: its SHA-256 and size (the copy's identity). The file is only read."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"file_name": Path(path).name, "sha256": h.hexdigest(), "bytes": Path(path).stat().st_size}


def schema_diff(old: sqlite3.Connection, new: sqlite3.Connection) -> dict[str, Any]:
    def shape(db: sqlite3.Connection) -> dict[str, Any]:
        tables = {n: {r[1] for r in db.execute(f"PRAGMA table_info('{n}')")} for n in _tables(db)}
        objs = _schema_objects(db)
        return {"tables": tables, "indexes": {i[0] for i in objs["indexes"]}, "triggers": {t[0] for t in objs["triggers"]}}
    a, b = shape(old), shape(new)
    return {"tables_removed": sorted(set(a["tables"]) - set(b["tables"])), "tables_added": sorted(set(b["tables"]) - set(a["tables"])),
            "columns_removed": {n: sorted(a["tables"][n] - b["tables"][n]) for n in a["tables"] if n in b["tables"] and a["tables"][n] - b["tables"][n]},
            "columns_added": {n: sorted(b["tables"][n] - a["tables"][n]) for n in a["tables"] if n in b["tables"] and b["tables"][n] - a["tables"][n]},
            "indexes_removed": sorted(a["indexes"] - b["indexes"]), "indexes_added": sorted(b["indexes"] - a["indexes"]),
            "triggers_removed": sorted(a["triggers"] - b["triggers"]), "triggers_added": sorted(b["triggers"] - a["triggers"])}


def audit(db_path: Path, baseline: Path | None = None, target_kind: str = "synthetic", expect_sha256: str | None = None,
          restore_manifests: Any = None, restore_archive_rows: Any = None) -> dict[str, Any]:
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind must be one of {TARGET_KINDS}")
    identity = copy_identity(db_path)
    if expect_sha256 and identity["sha256"] != expect_sha256.lower():
        raise ValueError(f"the file is not the copy that was announced: sha256 {identity['sha256']} != {expect_sha256}")
    results: dict[str, Any] = {}
    schema_report: dict[str, Any] = {}
    with closing(sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = _tables(db)
        lineage = lineage_of(tables)
        objs = _schema_objects(db)
        schema_report = {"tables": sorted(tables), "indexes": sorted(i[0] for i in objs["indexes"]), "triggers": sorted(t[0] for t in objs["triggers"]),
                         "schema_versions": [r[0] for r in db.execute("SELECT version FROM schema_versions")] if "schema_versions" in tables else None,
                         "user_version": db.execute("PRAGMA user_version").fetchone()[0], "has_schema_migrations": "schema_migrations" in tables}
        chosen = INVARIANTS if lineage == "flat" else [i for i in INVARIANTS if i[0] == "DB-01"] + (V02_INVARIANTS if lineage == "normalized_v0_2" else [])
        for iid, title, needs, fn in chosen:
            missing = [n for n in needs if n not in tables]
            if missing:
                results[iid] = {"title": title, "status": "not_run", "reason": f"the database has no table {missing}", "problems": []}
                continue
            if needs and iid not in STRUCTURAL and db.execute(f"SELECT count(*) FROM {needs[0]}").fetchone()[0] == 0:
                results[iid] = {"title": title, "status": "not_run", "reason": f"table {needs[0]} has no rows: nothing was examined", "problems": []}
                continue
            problems = fn(db, tables)
            hard = [p for p in problems if p.get("severity") != "warn"]
            results[iid] = {"title": title, "status": "fail" if hard else ("warn" if problems else "pass"), "problems": problems[:50],
                            "problem_count": len(problems)}
        if lineage == "flat":
            results["DB-19"] = db19_restore_check(db, tables, restore_manifests, restore_archive_rows)
        if baseline is None:
            results["DB-09"] = {"title": "history preserved against an older copy", "status": "not_run", "reason": "no --baseline given", "problems": []}
        else:
            with closing(sqlite3.connect(f"{Path(baseline).resolve().as_uri()}?mode=ro", uri=True)) as old:
                old.row_factory = sqlite3.Row
                problems = check_preserved(old, db)
                schema_report["diff_from_baseline"] = schema_diff(old, db)
                schema_report["baseline_identity"] = copy_identity(baseline)
            results["DB-09"] = {"title": "history preserved against an older copy", "status": "fail" if problems else "pass", "problems": problems}
        counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in sorted(tables)}
    statuses = {k: v["status"] for k, v in results.items()}
    summary = {s: sorted(k for k, v in statuses.items() if v == s) for s in ("fail", "warn", "not_run", "pass")}
    return {"target_kind": target_kind, "copy_identity": identity, "schema": schema_report, "lineage": lineage, "original_source_comparison": "not_run", "table_row_counts": counts, "invariants": results, "summary": summary,
            "ok": not summary["fail"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("db", type=Path, nargs="?")
    parser.add_argument("--describe-inputs", action="store_true", help="print what is needed from Work to audit a real database, then exit")
    parser.add_argument("--expect-sha256", default=None, help="the SHA-256 Work announced for this copy: refuse any other file")
    parser.add_argument("--target-kind", default=None, choices=TARGET_KINDS, help="what kind of database this is (recorded in the report)")
    parser.add_argument("--baseline", type=Path, default=None, help="an older copy: its rows must all still be here, unchanged")
    parser.add_argument("--restore-evidence", type=Path, default=None, help="JSON {manifests: {restore_id: {...}}, archive_rows: {archive_sha256: [row sha256, ...]}} for DB-19")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.describe_inputs:
        print(DESCRIBE_INPUTS)
        return 0
    if args.db is None:
        parser.error("the database file is required")
    if args.target_kind is None:
        parser.error("--target-kind is required: a result on a synthetic database is not a result on a real one")
    manifests = archive_rows = None
    if args.restore_evidence:
        ev = json.loads(args.restore_evidence.read_text(encoding="utf-8"))
        manifests = ev.get("manifests")
        archive_rows = {k: frozenset(v) for k, v in (ev.get("archive_rows") or {}).items()} if ev.get("archive_rows") is not None else None
    report = audit(args.db, args.baseline, args.target_kind, args.expect_sha256, manifests, archive_rows)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "target_kind": report["target_kind"], "lineage": report["lineage"], **report["summary"],
                      "original_source_comparison": "not_run"}, ensure_ascii=False, indent=1))
    for iid, r in report["invariants"].items():
        if r["status"] in ("fail", "warn"):
            for p in r["problems"][:5]:
                print(f"  {iid} {r['status']}: {p}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
