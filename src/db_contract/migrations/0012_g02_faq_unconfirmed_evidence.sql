-- FROZEN SQL of migration 0012-g02-faq-unconfirmed-evidence (M1.g2 / STR-100 H2=A, approved 2026-11-10; implementation approved 2026-11-11 (U6), SELF_TEST, INDEPENDENT_QA_PENDING, applied to no operational database).
-- Same file format as 0005. ONE append-only table, EMPTY after the migration (it records nothing and changes no row): faq_unconfirmed_evidence, the evidence an official FAQ page gives when the page does NOT say which
-- year / faculty / method it applies to (STR-076, STR-101, STR-102). It is NOT a fact: facts.case_id stays NOT NULL and this table has NO fiscal_year, faculty, department or method column, so no row can state an applicability.
-- storage_case_id is an ADMINISTRATIVE storage reference to an admission cycle (where the row is filed); it is never evidence that the FAQ applies to that cycle, and scope_status is fixed to 'unknown' (a CHECK): there is no
-- promotion path to 'verified' (STR-102). An evidence id that already exists as a fact cannot be filed here (no double registration). Four guards as in 0010 / 0011 (no UPDATE, no DELETE, no REPLACE on a key or a named rowid,
-- no negative rowid). docs/DB17_MIGRATION_DESIGN_DRAFT_20261111.md section 3-D has the reasons.
-- @@ requires: table admission_cycles, table source_documents
CREATE TABLE faq_unconfirmed_evidence(
 evidence_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(evidence_id))>0),
 storage_case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
 source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),
 question_sha256 TEXT NOT NULL CHECK(length(question_sha256)=64),
 quote TEXT NOT NULL CHECK(length(trim(quote))>0),
 normalized_start INTEGER NOT NULL CHECK(normalized_start>=0),
 normalized_end INTEGER NOT NULL CHECK(normalized_end>normalized_start),
 page INTEGER CHECK(page IS NULL OR page>=1),
 scope_status TEXT NOT NULL DEFAULT 'unknown' CHECK(scope_status='unknown'),
 recorded_by TEXT NOT NULL CHECK(length(trim(recorded_by))>0), recorded_at TEXT NOT NULL);
-- @@ requires: table admission_cycles, table source_documents
CREATE TRIGGER trg_faq_unconfirmed_evidence_no_update BEFORE UPDATE ON faq_unconfirmed_evidence BEGIN SELECT RAISE(ABORT, 'faq_unconfirmed_evidence is append-only'); END;
-- @@ requires: table admission_cycles, table source_documents
CREATE TRIGGER trg_faq_unconfirmed_evidence_no_delete BEFORE DELETE ON faq_unconfirmed_evidence BEGIN SELECT RAISE(ABORT, 'faq_unconfirmed_evidence is append-only'); END;
-- @@ requires: table admission_cycles, table source_documents
CREATE TRIGGER trg_faq_unconfirmed_evidence_no_replace BEFORE INSERT ON faq_unconfirmed_evidence WHEN EXISTS (SELECT 1 FROM faq_unconfirmed_evidence WHERE evidence_id = NEW.evidence_id) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM faq_unconfirmed_evidence WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'faq_unconfirmed_evidence is append-only: a row is never replaced'); END;
-- @@ requires: table admission_cycles, table source_documents
CREATE TRIGGER trg_faq_unconfirmed_evidence_no_negative_rowid AFTER INSERT ON faq_unconfirmed_evidence WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'faq_unconfirmed_evidence is append-only: rowid must not be negative'); END;
-- @@ requires: table admission_cycles, table source_documents, table facts
CREATE TRIGGER trg_faq_unconfirmed_evidence_not_a_fact BEFORE INSERT ON faq_unconfirmed_evidence WHEN EXISTS (SELECT 1 FROM facts WHERE evidence_id = NEW.evidence_id) BEGIN SELECT RAISE(ABORT, 'faq_unconfirmed_evidence: this evidence id is already a fact'); END;
