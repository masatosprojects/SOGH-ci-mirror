-- FROZEN SQL of migration 0011-g05-alias-provenance (M1.g1 / G-05 owner decision 2026-11-08, SELF_TEST, INDEPENDENT_QA_PENDING, applied to no operational database).
-- Same file format as 0005. Two APPEND-ONLY tables, EMPTY after the migration (it records nothing and changes no row): alias_provenance_bundles (one content-addressed provenance bundle per alias: the alias's
-- original record with its extractor `pattern`, the proof order, the profile SHA, the extractor version and the normaliser id; the SHA-256 of the bundle is checked by the audit and by register_alias, SQLite cannot
-- compute it) and source_representations (the MEDIUM of a stored source, pdf / html / unknown, versioned, with the basis it was derived from; 0007's source_kind is the document's ROLE and is not changed).
-- Four guards per table as in 0010 (no UPDATE, no DELETE, no REPLACE on any unique key or named rowid, no negative rowid). docs/G05_ALIAS_PROVENANCE_STORAGE_PROPOSAL_2026-11-08.md has the reasons.
-- @@ requires: table evidence_aliases
CREATE TABLE alias_provenance_bundles(
 alias_id TEXT NOT NULL PRIMARY KEY REFERENCES evidence_aliases(alias_id),
 bundle_sha256 TEXT NOT NULL CHECK(length(bundle_sha256)=64),
 bundle_json TEXT NOT NULL CHECK(json_valid(bundle_json)),
 recorded_by TEXT NOT NULL CHECK(length(trim(recorded_by))>0), recorded_at TEXT NOT NULL);
-- @@ requires: table source_documents
CREATE TABLE source_representations(
 source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256), rep_version INTEGER NOT NULL CHECK(rep_version>=1),
 medium TEXT NOT NULL CHECK(medium IN ('pdf','html','unknown')), basis_json TEXT NOT NULL CHECK(json_valid(basis_json)),
 recorded_by TEXT NOT NULL CHECK(length(trim(recorded_by))>0), recorded_at TEXT NOT NULL, PRIMARY KEY(source_sha256, rep_version));
-- @@ requires: table evidence_aliases
CREATE TRIGGER trg_alias_provenance_bundles_no_update BEFORE UPDATE ON alias_provenance_bundles BEGIN SELECT RAISE(ABORT, 'alias_provenance_bundles is append-only'); END;
-- @@ requires: table evidence_aliases
CREATE TRIGGER trg_alias_provenance_bundles_no_delete BEFORE DELETE ON alias_provenance_bundles BEGIN SELECT RAISE(ABORT, 'alias_provenance_bundles is append-only'); END;
-- @@ requires: table evidence_aliases
CREATE TRIGGER trg_alias_provenance_bundles_no_replace BEFORE INSERT ON alias_provenance_bundles WHEN EXISTS (SELECT 1 FROM alias_provenance_bundles WHERE alias_id = NEW.alias_id) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM alias_provenance_bundles WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'alias_provenance_bundles is append-only: a row is never replaced'); END;
-- @@ requires: table evidence_aliases
CREATE TRIGGER trg_alias_provenance_bundles_no_negative_rowid AFTER INSERT ON alias_provenance_bundles WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'alias_provenance_bundles is append-only: rowid must not be negative'); END;
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_representations_no_update BEFORE UPDATE ON source_representations BEGIN SELECT RAISE(ABORT, 'source_representations is append-only'); END;
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_representations_no_delete BEFORE DELETE ON source_representations BEGIN SELECT RAISE(ABORT, 'source_representations is append-only'); END;
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_representations_no_replace BEFORE INSERT ON source_representations WHEN EXISTS (SELECT 1 FROM source_representations WHERE source_sha256 = NEW.source_sha256 AND rep_version = NEW.rep_version) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM source_representations WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'source_representations is append-only: a row is never replaced'); END;
-- @@ requires: table source_documents
CREATE TRIGGER trg_source_representations_no_negative_rowid AFTER INSERT ON source_representations WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'source_representations is append-only: rowid must not be negative'); END;
