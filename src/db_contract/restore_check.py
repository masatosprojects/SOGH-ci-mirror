"""DB-19: the whole-database check of RESTORED history (the five tables of migration 0010). Status: SELF_TEST, a pure READ-ONLY function; connected to no product path, applied to no database.

The database alone cannot know who may append a row (a capability is not an authentication), so this check DETECTS rows that no signed approval and no archive explains. It takes the two things only
the outside world can give, as arguments:

* ``manifests``: for each restore_id, the result of the approval verifier (``approval_manifest.py``: the signed commit of the owner): ``archive_sha256``, ``source_db_sha256``, ``approval_ref`` and
  ``signature_verified``. This module does not verify a signature and never signs anything.
* ``archive_rows``: for each archive SHA-256, the set of the SHA-256 of the archive's rows (the external baseline of the stored old versions).

Result: ``{"status": "pass" | "fail" | "not_applicable", "problems": [...]}``. ``not_applicable`` means migration 0010 is not applied (no history table at all); five EMPTY tables mean "no restore": pass.
A table that is missing or incomplete, a restore without a verified signed approval that matches it, a stored version whose digest or archive row cannot be reproduced, a pin that disagrees with
its version, and a restored article without a pin are failures. Nothing is repaired and nothing is written.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .historical_read import APPEND_ONLY_TABLES, digest_of, history_preflight

EVENT_KEYS = ("archive_sha256", "source_db_sha256", "approval_ref")


def verify_restore_records(db: sqlite3.Connection, *, manifests: Mapping[str, Mapping[str, Any]] | None = None,
                           archive_rows: Mapping[str, frozenset[str] | set[str]] | None = None) -> dict[str, Any]:
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not (set(APPEND_ONLY_TABLES) & tables):
        return {"status": "not_applicable", "problems": ["migration 0010 is not applied: there is no restore history table"]}
    pre = history_preflight(db)
    if pre:
        return {"status": "fail", "problems": pre}
    manifests, archive_rows = manifests or {}, archive_rows or {}
    problems: list[str] = []
    events = {r[0]: r for r in db.execute("SELECT restore_id, archive_sha256, source_db_sha256, approved_by, approved_at, approval_ref FROM restore_events")}
    for rid, archive, source_db, _by, _at, ref in events.values():
        m = manifests.get(rid)
        if m is None:
            problems.append(f"restore {rid!r}: no signed approval manifest was given for it")
            continue
        if m.get("signature_verified") is not True:
            problems.append(f"restore {rid!r}: the approval's signature is not verified")
        for key, stored in zip(EVENT_KEYS, (archive, source_db, ref)):
            if m.get(key) != stored:
                problems.append(f"restore {rid!r}: {key} differs from the signed approval")
    for (rid,) in db.execute("SELECT restore_id FROM restore_revocations"):
        if rid not in events:
            problems.append(f"revocation of {rid!r}: there is no such restore event")
    pins_by_article: dict[str, list[tuple]] = {}
    versions = {r[0]: r for r in db.execute("SELECT version_id, evidence_id, case_id, source_sha256, row_json, row_digest, archive_row_sha256, restore_id FROM evidence_history_versions")}
    for row in db.execute("SELECT article_id, evidence_id, version_id, case_id, scope, source_sha256, row_digest, restore_id FROM article_history_pins"):
        pins_by_article.setdefault(row[0], []).append(row)
    for vid, evidence, case, source, raw, digest, archive_row, rid in versions.values():
        if rid not in events:
            problems.append(f"version {vid!r}: restore {rid!r} does not exist")
            continue
        try:
            row = json.loads(raw)
        except (TypeError, ValueError):
            problems.append(f"version {vid!r}: the stored row is not JSON")
            continue
        if not isinstance(row, dict) or digest_of(row) != digest:
            problems.append(f"version {vid!r}: the stored row does not reproduce its digest")
            continue
        if row.get("evidence_id") != evidence or row.get("case_id") != case or row.get("source_sha256") != source:
            problems.append(f"version {vid!r}: the stored row names another evidence id, case or source than its columns")
        known = archive_rows.get(events[rid][1])
        if known is None:
            problems.append(f"version {vid!r}: no external baseline was given for archive {events[rid][1][:12]}")
        elif archive_row not in known:
            problems.append(f"version {vid!r}: archive_row_sha256 is not a row of the archive")
    for (article_id, rid) in db.execute("SELECT article_id, restore_id FROM restored_articles"):
        if rid not in events:
            problems.append(f"restored article {article_id!r}: restore {rid!r} does not exist")
        pins = pins_by_article.get(article_id, [])
        if not pins:
            problems.append(f"restored article {article_id!r}: no history pin")
        for p in pins:
            if p[7] != rid:
                problems.append(f"article {article_id!r}: pin of {p[1]!r} names restore {p[7]!r}, the registration names {rid!r}")
    registered = {r[0] for r in db.execute("SELECT article_id FROM restored_articles")}
    for article_id, pins in pins_by_article.items():
        if article_id not in registered:
            problems.append(f"article {article_id!r}: has history pins but is not registered as restored")
        for _a, evidence, vid, case, scope, source, digest, rid in pins:
            v = versions.get(vid)
            if v is None:
                problems.append(f"pin ({article_id!r}, {evidence!r}): version {vid!r} does not exist")
                continue
            if (v[1], v[2], v[3], v[5], v[7]) != (evidence, case, source, digest, rid):
                problems.append(f"pin ({article_id!r}, {evidence!r}): evidence, case, source, digest or restore differ from its stored version")
            if not isinstance(scope, str) or not scope.strip() or scope.strip().upper() == "UNKNOWN":
                problems.append(f"pin ({article_id!r}, {evidence!r}): the scope is empty or UNKNOWN (never inferred)")
    return {"status": "fail" if problems else "pass", "problems": problems}
