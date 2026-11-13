-- FROZEN SQL of migration 0013-g07-quarantine-staging (M1.g7 quarantine staging of candidates, SELF_TEST, INDEPENDENT_QA_PENDING, applied to no operational database).
-- Same file format as 0005. Three tables and their guards for the quarantine of extracted candidates (PR #306, the product candidate of Antigravity, independent QA by Claude on head 59028ebc): quarantine_staging_candidates
-- (a candidate is staged QUARANTINED / PENDING, with its stager recorded and immutable; promotion needs an APPROVED review by an authorized human who is not the stager), _quarantine_approval_seals (the authority seal of
-- an approval, checked by the guard through the connection function _g7_verify_hmac_seal) and canonical_facts_staging_target (the promoted copy: only from a PROMOTED + APPROVED candidate with the same key and value).
-- All three are append-only and EMPTY after the migration (it stages, approves and promotes nothing). The text is the SCHEMA_SQL of src/db_contract/quarantine_staging.py without comments and without IF NOT EXISTS;
-- tests/test_m1_0013_0014_g7_g6_tables.py compares the two so that they cannot drift. The guards call a connection function (registered by register_quarantine_connection_guards): a connection that does not
-- register it cannot approve or promote (fail closed), as with sogh_write_ok of 0004. If a table of these names already exists the migration stops (pre-flight): it never adopts an unknown definition.
-- @@
CREATE TABLE quarantine_staging_candidates (
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
-- @@
CREATE TABLE _quarantine_approval_seals (
    staging_id TEXT PRIMARY KEY,
    reviewer TEXT NOT NULL,
    approval_token TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    sealed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
-- @@
CREATE TABLE canonical_facts_staging_target (
    fact_id TEXT PRIMARY KEY,
    staging_id TEXT NOT NULL UNIQUE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    promoted_at TEXT NOT NULL,
    FOREIGN KEY(staging_id) REFERENCES quarantine_staging_candidates(staging_id)
);
-- @@
CREATE TRIGGER trg_quarantine_enforce_initial_insert
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
-- @@
CREATE TRIGGER trg_quarantine_prevent_terminal_mutation
BEFORE UPDATE ON quarantine_staging_candidates
FOR EACH ROW
WHEN OLD.quarantine_status = 'REJECTED'
  OR OLD.review_status = 'REJECTED'
  OR OLD.quarantine_status = 'PROMOTED'
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Cannot mutate status of REJECTED candidate or terminal PROMOTED record');
END;
-- @@
CREATE TRIGGER trg_quarantine_immutable_payload
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
-- @@
CREATE TRIGGER trg_quarantine_prevent_delete
BEFORE DELETE ON quarantine_staging_candidates
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Quarantine staging table is append-only; DELETE is prohibited');
END;
-- @@
CREATE TRIGGER trg_quarantine_enforce_approval_credentials
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
-- @@
CREATE TRIGGER trg_quarantine_lock_approved_review
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
-- @@
CREATE TRIGGER trg_quarantine_enforce_promotion_flow
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
-- @@
CREATE TRIGGER trg_canonical_block_unquarantined
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
-- @@
CREATE TRIGGER trg_canonical_prevent_update
BEFORE UPDATE ON canonical_facts_staging_target
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Canonical target table is append-only; UPDATE prohibited');
END;
-- @@
CREATE TRIGGER trg_canonical_prevent_delete
BEFORE DELETE ON canonical_facts_staging_target
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-07 VIOLATION: Canonical target table is append-only; DELETE prohibited');
END;
