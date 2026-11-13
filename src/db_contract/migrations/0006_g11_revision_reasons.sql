-- FROZEN SQL of migration 0006-g11-revision-reasons (M1 unified design, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Same file format as 0005 (a `requires` names tables that exist BEFORE the migration). G-11: why a batch changed things. One reason per batch, written once and never replaced; a mistake in a reason is
-- corrected by a NEW row in revision_reason_corrections (append-only, numbered), never by an update. The past stays unknown: no reason is made up for a batch written before this migration, and the
-- boundary is a ROW POSITION of update_batches (a clock tick is too coarse), recorded once in revision_reason_contract.
-- @@ requires: table update_batches
CREATE TABLE revision_reasons(
 batch_id TEXT PRIMARY KEY REFERENCES update_batches(batch_id),
 reason_class TEXT NOT NULL CHECK(reason_class IN ('source_changed', 'new_fact', 'correction', 'locator_correction', 'withdrawal', 'wording', 'article_refresh', 'other')),
 reason_text TEXT NOT NULL CHECK(length(trim(reason_text)) > 0),
 source_changed TEXT NOT NULL CHECK(source_changed IN ('yes', 'no', 'unknown')),
 source_sha256_before TEXT CHECK(source_sha256_before IS NULL OR length(source_sha256_before) = 64),
 source_sha256_after TEXT CHECK(source_sha256_after IS NULL OR length(source_sha256_after) = 64),
 actor TEXT NOT NULL CHECK(length(trim(actor)) > 0), recorded_at TEXT NOT NULL,
 CHECK(source_changed <> 'yes' OR (source_sha256_after IS NOT NULL AND source_sha256_after IS NOT source_sha256_before)),
 CHECK(reason_class <> 'locator_correction' OR source_changed IN ('no', 'unknown')),
 CHECK(reason_class <> 'source_changed' OR source_changed = 'yes'))
-- @@ requires: table update_batches
CREATE TABLE revision_reason_corrections(
 batch_id TEXT NOT NULL REFERENCES revision_reasons(batch_id), correction_no INTEGER NOT NULL CHECK(correction_no >= 1),
 reason_class TEXT NOT NULL CHECK(reason_class IN ('source_changed', 'new_fact', 'correction', 'locator_correction', 'withdrawal', 'wording', 'article_refresh', 'other')),
 reason_text TEXT NOT NULL CHECK(length(trim(reason_text)) > 0),
 source_changed TEXT NOT NULL CHECK(source_changed IN ('yes', 'no', 'unknown')),
 source_sha256_before TEXT CHECK(source_sha256_before IS NULL OR length(source_sha256_before) = 64),
 source_sha256_after TEXT CHECK(source_sha256_after IS NULL OR length(source_sha256_after) = 64),
 correction_note TEXT NOT NULL CHECK(length(trim(correction_note)) > 0),
 actor TEXT NOT NULL CHECK(length(trim(actor)) > 0), recorded_at TEXT NOT NULL,
 PRIMARY KEY(batch_id, correction_no),
 CHECK(source_changed <> 'yes' OR (source_sha256_after IS NOT NULL AND source_sha256_after IS NOT source_sha256_before)),
 CHECK(reason_class <> 'locator_correction' OR source_changed IN ('no', 'unknown')),
 CHECK(reason_class <> 'source_changed' OR source_changed = 'yes'))
-- @@ requires: table update_batches
CREATE TABLE revision_reason_contract(id INTEGER PRIMARY KEY CHECK(id = 1), applied_at TEXT NOT NULL, last_batch_rowid_before INTEGER NOT NULL)
-- @@ requires: table update_batches
INSERT INTO revision_reason_contract(id, applied_at, last_batch_rowid_before) SELECT 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), COALESCE(MAX(rowid), 0) FROM update_batches
-- @@ requires: table update_batches
CREATE TRIGGER trg_reason_only_for_a_batch_that_can_change_something BEFORE INSERT ON revision_reasons WHEN NOT EXISTS(SELECT 1 FROM update_batches WHERE batch_id = NEW.batch_id AND state IN ('candidate', 'approved')) BEGIN SELECT RAISE(ABORT, 'a reason is recorded only for a candidate or approved batch (a no_change retry gets none)'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_reason_append_only_update BEFORE UPDATE ON revision_reasons BEGIN SELECT RAISE(ABORT, 'revision_reasons is append-only: a reason is never replaced'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_reason_append_only_delete BEFORE DELETE ON revision_reasons BEGIN SELECT RAISE(ABORT, 'revision_reasons is append-only'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_gate_revision_reasons_insert BEFORE INSERT ON revision_reasons BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_correction_in_sequence BEFORE INSERT ON revision_reason_corrections WHEN NEW.correction_no <> COALESCE((SELECT MAX(correction_no) FROM revision_reason_corrections WHERE batch_id = NEW.batch_id), 0) + 1 BEGIN SELECT RAISE(ABORT, 'corrections are numbered one after another'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_correction_append_only_update BEFORE UPDATE ON revision_reason_corrections BEGIN SELECT RAISE(ABORT, 'revision_reason_corrections is append-only'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_correction_append_only_delete BEFORE DELETE ON revision_reason_corrections BEGIN SELECT RAISE(ABORT, 'revision_reason_corrections is append-only'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_gate_revision_reason_corrections_insert BEFORE INSERT ON revision_reason_corrections BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_reason_contract_append_only_update BEFORE UPDATE ON revision_reason_contract BEGIN SELECT RAISE(ABORT, 'revision_reason_contract is append-only'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_reason_contract_append_only_delete BEFORE DELETE ON revision_reason_contract BEGIN SELECT RAISE(ABORT, 'revision_reason_contract is append-only'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_gate_revision_reason_contract_insert BEFORE INSERT ON revision_reason_contract BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_batches
CREATE VIEW v_batch_reason_current AS SELECT r.batch_id, COALESCE(c.reason_class, r.reason_class) AS reason_class, COALESCE(c.reason_text, r.reason_text) AS reason_text, COALESCE(c.source_changed, r.source_changed) AS source_changed, COALESCE(c.source_sha256_before, r.source_sha256_before) AS source_sha256_before, COALESCE(c.source_sha256_after, r.source_sha256_after) AS source_sha256_after, COALESCE(c.correction_no, 0) AS corrections FROM revision_reasons r LEFT JOIN revision_reason_corrections c ON c.batch_id = r.batch_id AND c.correction_no = (SELECT MAX(correction_no) FROM revision_reason_corrections WHERE batch_id = r.batch_id)
-- @@ requires: table update_batches
CREATE VIEW v_batch_reason_status AS SELECT b.batch_id, b.state, b.created_at, CASE WHEN r.batch_id IS NOT NULL THEN 'recorded' WHEN b.state NOT IN ('candidate', 'approved') THEN 'not_applicable' WHEN b.rowid <= (SELECT last_batch_rowid_before FROM revision_reason_contract WHERE id = 1) THEN 'not_recorded_before_the_contract' ELSE 'missing' END AS reason_status FROM update_batches b LEFT JOIN revision_reasons r ON r.batch_id = b.batch_id
