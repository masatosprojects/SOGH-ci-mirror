-- FROZEN SQL of migration 0014-g06-source-series (M1.g6 document series and revision impacts, SELF_TEST, INDEPENDENT_QA_PENDING, applied to no operational database).
-- Same file format as 0005. Two tables and their guards for the lineage of a source document's editions (PR #306, the product candidate of Antigravity, independent QA by Claude on head 59028ebc):
-- source_document_series_editions (append-only: an edition's hash must equal its content, the revision numbers are consecutive, an edition supersedes exactly the previous one, no REPLACE / DELETE, labels are immutable)
-- and series_revision_article_impacts (append-only, the editions must exist in the same series). Both are EMPTY after the migration. The text is the SCHEMA_SQL of src/versioning/series.py without comments and
-- without IF NOT EXISTS; tests/test_m1_0013_0014_g7_g6_tables.py compares the two so that they cannot drift. The guards call the connection function _g6_sha256_hex (register_series_connection_guards): a connection that
-- does not register it cannot insert an edition (fail closed). If a table of these names already exists the migration stops (pre-flight).
-- @@
CREATE TABLE source_document_series_editions (
    edition_id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL,
    university TEXT NOT NULL,
    document_title TEXT NOT NULL,
    rev_number INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    content_text TEXT NOT NULL,
    supersedes_id TEXT,
    is_frozen INTEGER NOT NULL DEFAULT 0 CHECK(is_frozen IN (0, 1)),
    UNIQUE(series_id, rev_number)
);
-- @@
CREATE TABLE series_revision_article_impacts (
    impact_id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL,
    old_edition_id TEXT NOT NULL,
    new_edition_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    impact_status TEXT NOT NULL DEFAULT 'REVISION_REQUIRED',
    FOREIGN KEY(old_edition_id) REFERENCES source_document_series_editions(edition_id),
    FOREIGN KEY(new_edition_id) REFERENCES source_document_series_editions(edition_id)
);
-- @@
CREATE TRIGGER trg_series_editions_prevent_replace
BEFORE INSERT ON source_document_series_editions
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM source_document_series_editions
    WHERE edition_id = NEW.edition_id
       OR (series_id = NEW.series_id AND rev_number = NEW.rev_number)
)
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Cannot overwrite existing series edition via INSERT OR REPLACE');
END;
-- @@
CREATE TRIGGER trg_series_editions_validate_insert
BEFORE INSERT ON source_document_series_editions
FOR EACH ROW
WHEN NEW.sha256_hash != _g6_sha256_hex(NEW.content_text)
  OR trim(NEW.university) = ''
  OR trim(NEW.document_title) = ''
  OR NEW.rev_number < 1
  OR (NEW.rev_number = 1 AND NEW.supersedes_id IS NOT NULL)
  OR (
      NEW.rev_number > 1
      AND NOT EXISTS (
          SELECT 1 FROM source_document_series_editions p
          WHERE p.series_id = NEW.series_id
            AND p.rev_number = NEW.rev_number - 1
            AND p.edition_id = NEW.supersedes_id
      )
  )
  OR EXISTS (
      SELECT 1 FROM source_document_series_editions s
      WHERE s.series_id = NEW.series_id
        AND (s.university != NEW.university OR s.document_title != NEW.document_title)
  )
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Edition content hash mismatch, broken rev_number/supersedes chain, or inconsistent series metadata on INSERT');
END;
-- @@
CREATE TRIGGER trg_series_editions_prevent_delete
BEFORE DELETE ON source_document_series_editions
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Document series editions are append-only; DELETE prohibited');
END;
-- @@
CREATE TRIGGER trg_series_editions_immutable_payload
BEFORE UPDATE ON source_document_series_editions
FOR EACH ROW
WHEN NEW.edition_id != OLD.edition_id
  OR NEW.series_id != OLD.series_id
  OR NEW.university != OLD.university
  OR NEW.document_title != OLD.document_title
  OR NEW.rev_number != OLD.rev_number
  OR NEW.sha256_hash != OLD.sha256_hash
  OR NEW.content_text != OLD.content_text
  OR COALESCE(NEW.supersedes_id, '') != COALESCE(OLD.supersedes_id, '')
  OR (OLD.is_frozen = 1 AND NEW.is_frozen != 1)
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Edition identity, labels, hash, and content are immutable');
END;
-- @@
CREATE TRIGGER trg_series_impacts_validate_insert
BEFORE INSERT ON series_revision_article_impacts
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM series_revision_article_impacts
    WHERE impact_id = NEW.impact_id
)
  OR NEW.old_edition_id = NEW.new_edition_id
  OR NOT EXISTS (
      SELECT 1 FROM source_document_series_editions e1
      WHERE e1.edition_id = NEW.old_edition_id
        AND e1.series_id = NEW.series_id
  )
  OR NOT EXISTS (
      SELECT 1 FROM source_document_series_editions e2
      WHERE e2.edition_id = NEW.new_edition_id
        AND e2.series_id = NEW.series_id
  )
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Impact record must reference existing distinct editions in the same series and cannot be overwritten');
END;
-- @@
CREATE TRIGGER trg_series_impacts_prevent_update
BEFORE UPDATE ON series_revision_article_impacts
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Revision impact records are append-only; UPDATE prohibited');
END;
-- @@
CREATE TRIGGER trg_series_impacts_prevent_delete
BEFORE DELETE ON series_revision_article_impacts
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'G-06 VIOLATION: Revision impact records are append-only; DELETE prohibited');
END;
