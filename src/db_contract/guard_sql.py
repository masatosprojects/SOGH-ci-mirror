"""Renders the FROZEN SQL file of migration 0004 (G-09: capability gate, append-only tables, approved-only heads). The migration is NOT generated when it is applied: the file under migrations/
is what runs, and tests/test_guard_migration.py proves that the file is exactly what this renderer produces (so the table lists below and the file cannot drift apart unseen).
SELF_VALIDATED, WORK_REVIEW_PENDING; applied to no operational database.

What the rules are (docs/architecture/M1_UNIFIED_DATA_ARCHITECTURE_RFC.md §9, plan B):
  * capability gate: every write to a guarded table calls `sogh_write_ok()`. Only SOGH's own connections register it, so any other connection fails closed ("no such function"). Reading is free.
  * append-only: no UPDATE and no DELETE of an old row of the history tables (with PRAGMA recursive_triggers=ON an INSERT OR REPLACE fires the DELETE trigger as well).
  * heads: a head may only point at a revision (of its own logical id / base article) whose batch is APPROVED; a candidate or rolled-back batch can never become a head. Deleting heads stays possible (rollback).
  * update_batches: only candidate -> interrupted | rejected | approved and approved -> rolled_back, identity columns unchanged, no delete.
What they do NOT do: stop someone who can rewrite the database file or register the capability function (detected by the schema-state check, not prevented), or prove that a QA result is genuine (G-08, signatures).
"""
from __future__ import annotations

APPEND_ONLY = ("facts", "source_documents", "source_pages", "evidence_revisions", "article_versions", "revised_articles", "article_evidence", "batch_evidence", "update_events",
               "cycle_editions", "qa_runs", "schema_versions", "schema_migrations")
UNGATED = ("schema_migrations",)  # written by the migration runner, which is not a store connection (it registers the capability for its own transaction only)
OWN_APPEND_ONLY_LINK_TABLES = ("evidence_aliases", "offering_sources")  # append-only by their own migrations (0002, 0003); here they only get the gate
IDENTITY_TABLES = ("admission_cycles", "admission_offerings", "cycle_dimensions")

BATCH_IMMUTABLE = "OLD.batch_id = NEW.batch_id AND OLD.input_sha = NEW.input_sha AND OLD.created_at = NEW.created_at AND OLD.before_json = NEW.before_json AND OLD.registry_sha = NEW.registry_sha"
BATCH_MOVES = ("((OLD.state = 'candidate' AND NEW.state IN ('interrupted', 'rejected', 'approved')) "
               "OR (OLD.state = 'approved' AND NEW.state = 'rolled_back' AND NEW.after_json = OLD.after_json AND NEW.qa_json = OLD.qa_json))")
BATCH_QA_ONLY_ON_DECISION = "(NEW.state IN ('rejected', 'approved') OR (NEW.after_json = OLD.after_json AND NEW.qa_json = OLD.qa_json))"

HEADER = """-- FROZEN SQL of migration 0004-g09-append-only-and-head-integrity (M1 unified design, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Rendered by src/db_contract/guard_sql.py (tests/test_guard_migration.py checks that this file is exactly that output). Same file format as 0002: statements are separated by `-- @@` lines,
-- `requires: table NAME` makes a statement conditional on those tables (the schema lineages differ), a statement holds no comment.
-- The rules: capability gate (`sogh_write_ok()`), append-only history tables, heads only for APPROVED batches, update_batches transitions. They guard future writes: they never repair the
-- past (F-2 stays open) and they do not stop anyone who can rewrite the database file or register the capability (that is detected by the schema-state check, not prevented).
-- The application's connection must register `sogh_write_ok` and turn PRAGMA recursive_triggers ON (patches/m1-stage1/work-pipeline-stage1.patch).
"""


def _stmt(requires: tuple[str, ...], sql: str) -> str:
    return f"-- @@ requires: {', '.join('table ' + t for t in requires)}\n{sql}\n"


def statements() -> list[tuple[tuple[str, ...], str]]:
    out: list[tuple[tuple[str, ...], str]] = []

    def gate(table: str, op: str) -> None:
        out.append(((table,), f"CREATE TRIGGER trg_gate_{table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT sogh_write_ok(); END"))

    for name in APPEND_ONLY:
        if name not in UNGATED:
            gate(name, "INSERT")
        out.append(((name,), f"CREATE TRIGGER trg_ao_{name}_update BEFORE UPDATE ON {name} BEGIN SELECT RAISE(ABORT, '{name} is append-only: a row is never updated'); END"))
        out.append(((name,), f"CREATE TRIGGER trg_ao_{name}_delete BEFORE DELETE ON {name} BEGIN SELECT RAISE(ABORT, '{name} is append-only: a row is never deleted'); END"))
    for name in OWN_APPEND_ONLY_LINK_TABLES:
        gate(name, "INSERT")
    for name in ("evidence_heads", "article_heads", "update_batches"):
        for op in ("INSERT", "UPDATE", "DELETE"):
            gate(name, op)
    out.append((("update_batches",), "CREATE TRIGGER trg_batch_delete BEFORE DELETE ON update_batches BEGIN SELECT RAISE(ABORT, 'update_batches rows are never deleted'); END"))
    out.append((("update_batches",), f"CREATE TRIGGER trg_batch_update BEFORE UPDATE ON update_batches WHEN NOT ({BATCH_IMMUTABLE} AND {BATCH_MOVES} AND {BATCH_QA_ONLY_ON_DECISION}) "
                "BEGIN SELECT RAISE(ABORT, 'update_batches: only candidate to interrupted, rejected or approved, and approved to rolled_back, with the identity columns unchanged'); END"))
    for op in ("INSERT", "UPDATE"):
        out.append((("evidence_heads", "evidence_revisions", "batch_evidence", "update_batches"),
                    f"CREATE TRIGGER trg_head_evidence_{op.lower()} BEFORE {op} ON evidence_heads WHEN NOT EXISTS(SELECT 1 FROM evidence_revisions r JOIN batch_evidence e ON e.evidence_id = r.evidence_id "
                    "JOIN update_batches b ON b.batch_id = e.batch_id WHERE r.evidence_id = NEW.evidence_id AND r.logical_id = NEW.logical_id AND b.state = 'approved') "
                    "BEGIN SELECT RAISE(ABORT, 'a head must be a revision of its own logical id that belongs to an approved batch'); END"))
        out.append((("article_heads", "revised_articles", "update_batches"),
                    f"CREATE TRIGGER trg_head_article_{op.lower()} BEFORE {op} ON article_heads WHEN NOT EXISTS(SELECT 1 FROM revised_articles r JOIN update_batches b ON b.batch_id = r.batch_id "
                    "WHERE r.article_id = NEW.article_id AND r.base_article_id = NEW.base_article_id AND b.state = 'approved') "
                    "BEGIN SELECT RAISE(ABORT, 'an article head must be a revision of its own base article that belongs to an approved batch'); END"))
    out.append((("admission_cycles",), "CREATE TRIGGER trg_cycle_identity_update BEFORE UPDATE OF university, faculty, department, admission_method, fiscal_year, exam_year ON admission_cycles "
                "BEGIN SELECT RAISE(ABORT, 'the identity columns of a cycle are never updated: a correction is a new cycle'); END"))
    for name in IDENTITY_TABLES:
        gate(name, "INSERT")
        out.append(((name,), f"CREATE TRIGGER trg_{name}_delete BEFORE DELETE ON {name} BEGIN SELECT RAISE(ABORT, '{name} rows are never deleted'); END"))
    return out


def render() -> str:
    return HEADER + "".join(_stmt(req, sql) for req, sql in statements())
