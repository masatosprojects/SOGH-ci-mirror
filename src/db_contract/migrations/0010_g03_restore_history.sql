-- FROZEN SQL of migration 0010-g03-restore-history (M1.g3 restore history, SELF_VALIDATED, WORK_REVIEW_PENDING, INDEPENDENT_QA_PENDING, applied to no operational database).
-- Same file format as 0005. The storage of RESTORED history: restore_events (who approved which restore of which archive), restore_revocations, restored_articles (an article registered as restored is
-- read only from its pins), evidence_history_versions (the exact old rows, each with its digest) and article_history_pins (which version a restored article cites). Five tables and, for each, four
-- guards (no UPDATE, no DELETE, no REPLACE on any unique key or named rowid, no negative rowid): all five tables are append-only. The tables are EMPTY after the migration: it restores nothing, signs
-- nothing and changes no row of any other table (the restore itself, F-2 state B, is a separate step that needs the owner's signed approval). The text is generated from historical_read.history_ddl(True)
-- (PR #261, where the guards were tested); tests/test_m1_0010_restore_history.py compares the two so that they cannot drift. Decision of the owner (2026-11-08): registered as 0010, rowid tables, a
-- repeated row is refused. If a table of this name already exists the migration stops (preflight): it never adopts an unknown definition.
-- @@
CREATE TABLE restore_events(
 restore_id TEXT NOT NULL PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('f2_recovery')),
 archive_sha256 TEXT NOT NULL CHECK(length(archive_sha256)=64), source_db_sha256 TEXT NOT NULL CHECK(length(source_db_sha256)=64),
 approved_by TEXT NOT NULL CHECK(length(trim(approved_by))>0), approved_at TEXT NOT NULL, approval_ref TEXT NOT NULL CHECK(length(trim(approval_ref))>0));
-- @@
CREATE TABLE restore_revocations(
 restore_id TEXT NOT NULL PRIMARY KEY REFERENCES restore_events(restore_id), revoked_by TEXT NOT NULL, revoked_at TEXT NOT NULL, reason TEXT NOT NULL);
-- @@
CREATE TABLE restored_articles(
 article_id TEXT NOT NULL PRIMARY KEY, restore_id TEXT NOT NULL REFERENCES restore_events(restore_id));
-- @@
CREATE TABLE evidence_history_versions(
 version_id TEXT NOT NULL PRIMARY KEY, evidence_id TEXT NOT NULL, case_id TEXT NOT NULL, source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 row_json TEXT NOT NULL, row_digest TEXT NOT NULL UNIQUE CHECK(length(row_digest)=64), archive_row_sha256 TEXT NOT NULL,
 restore_id TEXT NOT NULL REFERENCES restore_events(restore_id), UNIQUE(restore_id, evidence_id));
-- @@
CREATE TABLE article_history_pins(
 article_id TEXT NOT NULL, evidence_id TEXT NOT NULL, version_id TEXT NOT NULL REFERENCES evidence_history_versions(version_id),
 case_id TEXT NOT NULL, scope TEXT NOT NULL CHECK(length(trim(scope))>0), source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 row_digest TEXT NOT NULL CHECK(length(row_digest)=64), restore_id TEXT NOT NULL REFERENCES restore_events(restore_id), PRIMARY KEY(article_id, evidence_id));
-- @@
CREATE TRIGGER trg_restore_events_no_update BEFORE UPDATE ON restore_events BEGIN SELECT RAISE(ABORT, 'restore_events is append-only'); END;
-- @@
CREATE TRIGGER trg_restore_events_no_delete BEFORE DELETE ON restore_events BEGIN SELECT RAISE(ABORT, 'restore_events is append-only'); END;
-- @@
CREATE TRIGGER trg_restore_events_no_replace BEFORE INSERT ON restore_events WHEN EXISTS (SELECT 1 FROM restore_events WHERE restore_id = NEW.restore_id) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM restore_events WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'restore_events is append-only: a row is never replaced'); END;
-- @@
CREATE TRIGGER trg_restore_events_no_negative_rowid AFTER INSERT ON restore_events WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'restore_events is append-only: rowid must not be negative'); END;
-- @@
CREATE TRIGGER trg_restore_revocations_no_update BEFORE UPDATE ON restore_revocations BEGIN SELECT RAISE(ABORT, 'restore_revocations is append-only'); END;
-- @@
CREATE TRIGGER trg_restore_revocations_no_delete BEFORE DELETE ON restore_revocations BEGIN SELECT RAISE(ABORT, 'restore_revocations is append-only'); END;
-- @@
CREATE TRIGGER trg_restore_revocations_no_replace BEFORE INSERT ON restore_revocations WHEN EXISTS (SELECT 1 FROM restore_revocations WHERE restore_id = NEW.restore_id) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM restore_revocations WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'restore_revocations is append-only: a row is never replaced'); END;
-- @@
CREATE TRIGGER trg_restore_revocations_no_negative_rowid AFTER INSERT ON restore_revocations WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'restore_revocations is append-only: rowid must not be negative'); END;
-- @@
CREATE TRIGGER trg_restored_articles_no_update BEFORE UPDATE ON restored_articles BEGIN SELECT RAISE(ABORT, 'restored_articles is append-only'); END;
-- @@
CREATE TRIGGER trg_restored_articles_no_delete BEFORE DELETE ON restored_articles BEGIN SELECT RAISE(ABORT, 'restored_articles is append-only'); END;
-- @@
CREATE TRIGGER trg_restored_articles_no_replace BEFORE INSERT ON restored_articles WHEN EXISTS (SELECT 1 FROM restored_articles WHERE article_id = NEW.article_id) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM restored_articles WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'restored_articles is append-only: a row is never replaced'); END;
-- @@
CREATE TRIGGER trg_restored_articles_no_negative_rowid AFTER INSERT ON restored_articles WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'restored_articles is append-only: rowid must not be negative'); END;
-- @@
CREATE TRIGGER trg_evidence_history_versions_no_update BEFORE UPDATE ON evidence_history_versions BEGIN SELECT RAISE(ABORT, 'evidence_history_versions is append-only'); END;
-- @@
CREATE TRIGGER trg_evidence_history_versions_no_delete BEFORE DELETE ON evidence_history_versions BEGIN SELECT RAISE(ABORT, 'evidence_history_versions is append-only'); END;
-- @@
CREATE TRIGGER trg_evidence_history_versions_no_replace BEFORE INSERT ON evidence_history_versions WHEN EXISTS (SELECT 1 FROM evidence_history_versions WHERE version_id = NEW.version_id) OR EXISTS (SELECT 1 FROM evidence_history_versions WHERE row_digest = NEW.row_digest) OR EXISTS (SELECT 1 FROM evidence_history_versions WHERE restore_id = NEW.restore_id AND evidence_id = NEW.evidence_id) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM evidence_history_versions WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'evidence_history_versions is append-only: a row is never replaced'); END;
-- @@
CREATE TRIGGER trg_evidence_history_versions_no_negative_rowid AFTER INSERT ON evidence_history_versions WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'evidence_history_versions is append-only: rowid must not be negative'); END;
-- @@
CREATE TRIGGER trg_article_history_pins_no_update BEFORE UPDATE ON article_history_pins BEGIN SELECT RAISE(ABORT, 'article_history_pins is append-only'); END;
-- @@
CREATE TRIGGER trg_article_history_pins_no_delete BEFORE DELETE ON article_history_pins BEGIN SELECT RAISE(ABORT, 'article_history_pins is append-only'); END;
-- @@
CREATE TRIGGER trg_article_history_pins_no_replace BEFORE INSERT ON article_history_pins WHEN EXISTS (SELECT 1 FROM article_history_pins WHERE article_id = NEW.article_id AND evidence_id = NEW.evidence_id) OR (NEW.rowid >= 0 AND EXISTS (SELECT 1 FROM article_history_pins WHERE rowid = NEW.rowid)) BEGIN SELECT RAISE(ABORT, 'article_history_pins is append-only: a row is never replaced'); END;
-- @@
CREATE TRIGGER trg_article_history_pins_no_negative_rowid AFTER INSERT ON article_history_pins WHEN NEW.rowid < 0 BEGIN SELECT RAISE(ABORT, 'article_history_pins is append-only: rowid must not be negative'); END;
