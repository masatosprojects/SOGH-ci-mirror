-- FROZEN SQL of migration 0007-g06-source-metadata-and-verification (M1 unified design, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Same file format as 0005 (a `requires` names tables that exist BEFORE the migration). G-06: facts about a stored source document that are learned LATER (when it was published, what kind of document it is, how far it
-- was checked) cannot be written into source_documents, which is append-only. They go into two separate append-only tables:
--   source_document_metadata    versioned: a new version is a new row; the latest is a view; an unknown publication date stays NULL with certainty 'unknown' (never guessed); the retrieval date is another column of source_documents
--   source_verification_events  one row per check that was really done: bytes equal the recorded SHA / the stored file matches the record / authenticity at the official site / meaning checked by QA.
--                               Each level is its own evidence and its own outcome ('pass', 'fail', 'not_run'); v_source_verification_status says 'not_run' for every level without an event, so a stored copy is
--                               never called "verified as an official source" unless an official-site check passed and said how.
-- @@ requires: table source_documents
CREATE TABLE source_document_metadata(
 source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256), meta_version INTEGER NOT NULL CHECK(meta_version >= 1),
 published_at TEXT CHECK(published_at IS NULL OR published_at GLOB '[0-9][0-9][0-9][0-9]*'),
 published_at_certainty TEXT NOT NULL CHECK(published_at_certainty IN ('exact', 'month', 'year', 'unknown')),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('admission_guide', 'faq', 'notice', 'briefing', 'other')),
 title TEXT NOT NULL CHECK(length(trim(title)) > 0),
 applies_to_fiscal_year INTEGER CHECK(applies_to_fiscal_year IS NULL OR applies_to_fiscal_year BETWEEN 2000 AND 2100),
 basis TEXT NOT NULL CHECK(length(trim(basis)) > 0),
 recorded_by TEXT NOT NULL CHECK(length(trim(recorded_by)) > 0), recorded_at TEXT NOT NULL,
 PRIMARY KEY(source_sha256, meta_version),
 CHECK((published_at IS NULL) = (published_at_certainty = 'unknown')))
-- @@ requires: table source_documents
CREATE TABLE source_verification_events(
 source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256), event_no INTEGER NOT NULL CHECK(event_no >= 1),
 level TEXT NOT NULL CHECK(level IN ('bytes_match_recorded_sha', 'stored_file_matches_record', 'official_site_authenticity', 'content_meaning_checked')),
 outcome TEXT NOT NULL CHECK(outcome IN ('pass', 'fail', 'not_run')),
 evidence TEXT NOT NULL CHECK(length(trim(evidence)) > 0), performed_by TEXT NOT NULL CHECK(length(trim(performed_by)) > 0), performed_at TEXT NOT NULL,
 PRIMARY KEY(source_sha256, event_no))
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_meta_source_exists BEFORE INSERT ON source_document_metadata WHEN NOT EXISTS(SELECT 1 FROM source_documents WHERE sha256 = NEW.source_sha256) BEGIN SELECT RAISE(ABORT, 'metadata of a source document that is not stored'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_event_source_exists BEFORE INSERT ON source_verification_events WHEN NOT EXISTS(SELECT 1 FROM source_documents WHERE sha256 = NEW.source_sha256) BEGIN SELECT RAISE(ABORT, 'a verification event of a source document that is not stored'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_meta_in_sequence BEFORE INSERT ON source_document_metadata WHEN NEW.meta_version <> COALESCE((SELECT MAX(meta_version) FROM source_document_metadata WHERE source_sha256 = NEW.source_sha256), 0) + 1 BEGIN SELECT RAISE(ABORT, 'metadata versions are numbered one after another'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_event_in_sequence BEFORE INSERT ON source_verification_events WHEN NEW.event_no <> COALESCE((SELECT MAX(event_no) FROM source_verification_events WHERE source_sha256 = NEW.source_sha256), 0) + 1 BEGIN SELECT RAISE(ABORT, 'verification events are numbered one after another'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_meta_append_only_update BEFORE UPDATE ON source_document_metadata BEGIN SELECT RAISE(ABORT, 'source_document_metadata is append-only: a new version is a new row'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_meta_append_only_delete BEFORE DELETE ON source_document_metadata BEGIN SELECT RAISE(ABORT, 'source_document_metadata is append-only'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_event_append_only_update BEFORE UPDATE ON source_verification_events BEGIN SELECT RAISE(ABORT, 'source_verification_events is append-only'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_event_append_only_delete BEFORE DELETE ON source_verification_events BEGIN SELECT RAISE(ABORT, 'source_verification_events is append-only'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_gate_source_document_metadata_insert BEFORE INSERT ON source_document_metadata BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_gate_source_verification_events_insert BEFORE INSERT ON source_verification_events BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table source_documents
CREATE VIEW v_source_document_current AS SELECT m.* FROM source_document_metadata m WHERE m.meta_version = (SELECT MAX(meta_version) FROM source_document_metadata WHERE source_sha256 = m.source_sha256)
-- @@ requires: table source_documents
CREATE VIEW v_source_verification_status AS SELECT d.sha256 AS source_sha256, COALESCE((SELECT e.outcome FROM source_verification_events e WHERE e.source_sha256 = d.sha256 AND e.level = 'bytes_match_recorded_sha' ORDER BY e.event_no DESC LIMIT 1), 'not_run') AS bytes_match_recorded_sha, COALESCE((SELECT e.outcome FROM source_verification_events e WHERE e.source_sha256 = d.sha256 AND e.level = 'stored_file_matches_record' ORDER BY e.event_no DESC LIMIT 1), 'not_run') AS stored_file_matches_record, COALESCE((SELECT e.outcome FROM source_verification_events e WHERE e.source_sha256 = d.sha256 AND e.level = 'official_site_authenticity' ORDER BY e.event_no DESC LIMIT 1), 'not_run') AS official_site_authenticity, COALESCE((SELECT e.outcome FROM source_verification_events e WHERE e.source_sha256 = d.sha256 AND e.level = 'content_meaning_checked' ORDER BY e.event_no DESC LIMIT 1), 'not_run') AS content_meaning_checked FROM source_documents d
