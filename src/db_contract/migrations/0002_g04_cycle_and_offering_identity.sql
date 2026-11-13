-- FROZEN SQL of migration 0002-g04-cycle-and-offering-identity (M1 unified design, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Statements are separated by lines that start with "-- @@". A separator may say "requires: table NAME[, table NAME]": the statement after it is applied only when those tables exist
-- (the schema lineage without offerings still gets the cycle identity). A statement holds no comment. The SHA-256 of this file's bytes is the definition checksum in schema_migrations.
-- Once this file has been applied to a first operational database it is NEVER edited: a change is a new migration.
-- @@
CREATE UNIQUE INDEX ux_cycles_identity ON admission_cycles(university, faculty, COALESCE(department, ''), admission_method, fiscal_year)
-- @@ requires: table admission_offerings
CREATE UNIQUE INDEX ux_offerings_identity ON admission_offerings(case_id, round_name, COALESCE(entry_month, -1), scope_json)
-- @@ requires: table admission_offerings
CREATE TABLE offering_sources(
 offering_id TEXT NOT NULL REFERENCES admission_offerings(offering_id),
 source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),
 PRIMARY KEY(offering_id, source_sha256))
-- @@ requires: table admission_offerings
INSERT INTO offering_sources(offering_id, source_sha256) SELECT offering_id, source_sha256 FROM admission_offerings
-- @@ requires: table admission_offerings
CREATE TRIGGER trg_offering_source_of_a_new_offering AFTER INSERT ON admission_offerings BEGIN INSERT OR IGNORE INTO offering_sources(offering_id, source_sha256) VALUES(NEW.offering_id, NEW.source_sha256); END
-- @@ requires: table admission_offerings
CREATE TRIGGER trg_offering_source_of_a_repeated_offering BEFORE INSERT ON admission_offerings WHEN EXISTS(SELECT 1 FROM admission_offerings o WHERE o.case_id = NEW.case_id AND o.round_name = NEW.round_name AND COALESCE(o.entry_month, -1) = COALESCE(NEW.entry_month, -1) AND o.scope_json = NEW.scope_json) BEGIN INSERT OR IGNORE INTO offering_sources(offering_id, source_sha256) SELECT o.offering_id, NEW.source_sha256 FROM admission_offerings o WHERE o.case_id = NEW.case_id AND o.round_name = NEW.round_name AND COALESCE(o.entry_month, -1) = COALESCE(NEW.entry_month, -1) AND o.scope_json = NEW.scope_json; END
-- @@ requires: table admission_offerings
CREATE TRIGGER trg_offering_sources_append_only_update BEFORE UPDATE ON offering_sources BEGIN SELECT RAISE(ABORT, 'offering_sources is append-only'); END
-- @@ requires: table admission_offerings
CREATE TRIGGER trg_offering_sources_append_only_delete BEFORE DELETE ON offering_sources BEGIN SELECT RAISE(ABORT, 'offering_sources is append-only'); END
