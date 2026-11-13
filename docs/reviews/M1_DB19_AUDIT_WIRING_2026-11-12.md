# M1 g3: DB-19 (restore check) wired into the DB audit (SELF_TEST)

Author: Claude (contract owner). Status: SELF_TEST. Independent QA is requested from Antigravity; this is not independently QA'd and not an acceptance of g3.

## What changed
- `src/integration/db_audit.py`: new `db19_restore_check()`; `audit()` reports `DB-19` for the flat lineage. New optional arguments `restore_manifests` (the approval verifier's result by `restore_id`) and `restore_archive_rows` (external archive baseline); CLI `--restore-evidence <json>`.
- Rules: no 0010 table at all -> `not_run`; all five tables exist and are empty -> `pass` ("no restore happened"); otherwise the pure `restore_check.verify_restore_records` runs with the supplied evidence. A restore row without manifest evidence (or without an archive baseline for a stored version) **fails closed**; a partial/incomplete set of tables fails (`history_preflight`). Nothing is repaired or written.
- `DB-19` is not in `INVARIANTS` (its generic "first table empty -> not_run" rule would contradict "empty = pass"); existing ids and semantics are unchanged.
- Existing tests that hard-coded the invariant set / `not_run` count for a pre-0010 database were updated (`14 -> 15` not_run, `DB-19` added to the expected id set): the only expected effect of the new invariant. No other test was touched.
- New tests: `tests/test_m1_db19_audit_wiring.py` (8 tests: pre-0010 not_run, empty pass, forged row without evidence fails closed, matching evidence passes, bad signature / wrong archive row / missing baseline fail, partial tables fail, ids unchanged).

## Real v06 clone (disposable copy; the pinned file stayed read-only)
Source: the pinned v06 file, SHA-256 `a8e48b5b...539578` verified before and after (unchanged). The copy was audited, migrated with `additive_schema.apply(path, confirm_disposable_copy=True)` (13 migration rows in `schema_migrations`, 0002..0014), audited again.

| | before migration | after migration |
|---|---|---|
| fail | none | none |
| warn | DB-14, DB-15 | DB-14 (2), DB-15 (3) |
| not_run | DB-09 (no baseline), DB-17 (no `schema_migrations`), DB-19 (no 0010 tables) | DB-09 (no baseline) |
| pass | DB-01..08, 10, 11, 12, 16, 18 (13) | DB-01..08, 10, 11, 12, 16, 17, 18, 19 (15) |

- DB-19 after migration: `pass`, "all five restore history tables exist and are empty" (`restore_events`, `restore_revocations`, `restored_articles`, `evidence_history_versions`, `article_history_pins` = 0 rows each). `ok: true`.
- Every other invariant is unchanged; the two status changes (DB-17, DB-19 not_run -> pass) are the effect of the migrations having been applied (the tables they examine now exist). Row counts of the old 21 tables are unchanged by the audit (read-only connection).

## Not done / limits
- No real restore, no signature, no manifest was involved; the manifest verifier result is an argument only. The DB-19 acceptance and the g3 acceptance are the owner's.
- Full suite: 2638 passed (python -m pytest tests -q -p no:cacheprovider, 1014 s); the two edited audit test files were re-run separately after the last edit (all green).
