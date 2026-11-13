-- FROZEN SQL of migration 0004-g09-append-only-and-head-integrity (M1 unified design, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Rendered by src/db_contract/guard_sql.py (tests/test_guard_migration.py checks that this file is exactly that output). Same file format as 0002: statements are separated by `-- @@` lines,
-- `requires: table NAME` makes a statement conditional on those tables (the schema lineages differ), a statement holds no comment.
-- The rules: capability gate (`sogh_write_ok()`), append-only history tables, heads only for APPROVED batches, update_batches transitions. They guard future writes: they never repair the
-- past (F-2 stays open) and they do not stop anyone who can rewrite the database file or register the capability (that is detected by the schema-state check, not prevented).
-- The application's connection must register `sogh_write_ok` and turn PRAGMA recursive_triggers ON (patches/m1-stage1/work-pipeline-stage1.patch).
-- @@ requires: table facts
CREATE TRIGGER trg_gate_facts_insert BEFORE INSERT ON facts BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table facts
CREATE TRIGGER trg_ao_facts_update BEFORE UPDATE ON facts BEGIN SELECT RAISE(ABORT, 'facts is append-only: a row is never updated'); END
-- @@ requires: table facts
CREATE TRIGGER trg_ao_facts_delete BEFORE DELETE ON facts BEGIN SELECT RAISE(ABORT, 'facts is append-only: a row is never deleted'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_gate_source_documents_insert BEFORE INSERT ON source_documents BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_ao_source_documents_update BEFORE UPDATE ON source_documents BEGIN SELECT RAISE(ABORT, 'source_documents is append-only: a row is never updated'); END
-- @@ requires: table source_documents
CREATE TRIGGER trg_ao_source_documents_delete BEFORE DELETE ON source_documents BEGIN SELECT RAISE(ABORT, 'source_documents is append-only: a row is never deleted'); END
-- @@ requires: table source_pages
CREATE TRIGGER trg_gate_source_pages_insert BEFORE INSERT ON source_pages BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table source_pages
CREATE TRIGGER trg_ao_source_pages_update BEFORE UPDATE ON source_pages BEGIN SELECT RAISE(ABORT, 'source_pages is append-only: a row is never updated'); END
-- @@ requires: table source_pages
CREATE TRIGGER trg_ao_source_pages_delete BEFORE DELETE ON source_pages BEGIN SELECT RAISE(ABORT, 'source_pages is append-only: a row is never deleted'); END
-- @@ requires: table evidence_revisions
CREATE TRIGGER trg_gate_evidence_revisions_insert BEFORE INSERT ON evidence_revisions BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table evidence_revisions
CREATE TRIGGER trg_ao_evidence_revisions_update BEFORE UPDATE ON evidence_revisions BEGIN SELECT RAISE(ABORT, 'evidence_revisions is append-only: a row is never updated'); END
-- @@ requires: table evidence_revisions
CREATE TRIGGER trg_ao_evidence_revisions_delete BEFORE DELETE ON evidence_revisions BEGIN SELECT RAISE(ABORT, 'evidence_revisions is append-only: a row is never deleted'); END
-- @@ requires: table article_versions
CREATE TRIGGER trg_gate_article_versions_insert BEFORE INSERT ON article_versions BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table article_versions
CREATE TRIGGER trg_ao_article_versions_update BEFORE UPDATE ON article_versions BEGIN SELECT RAISE(ABORT, 'article_versions is append-only: a row is never updated'); END
-- @@ requires: table article_versions
CREATE TRIGGER trg_ao_article_versions_delete BEFORE DELETE ON article_versions BEGIN SELECT RAISE(ABORT, 'article_versions is append-only: a row is never deleted'); END
-- @@ requires: table revised_articles
CREATE TRIGGER trg_gate_revised_articles_insert BEFORE INSERT ON revised_articles BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table revised_articles
CREATE TRIGGER trg_ao_revised_articles_update BEFORE UPDATE ON revised_articles BEGIN SELECT RAISE(ABORT, 'revised_articles is append-only: a row is never updated'); END
-- @@ requires: table revised_articles
CREATE TRIGGER trg_ao_revised_articles_delete BEFORE DELETE ON revised_articles BEGIN SELECT RAISE(ABORT, 'revised_articles is append-only: a row is never deleted'); END
-- @@ requires: table article_evidence
CREATE TRIGGER trg_gate_article_evidence_insert BEFORE INSERT ON article_evidence BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table article_evidence
CREATE TRIGGER trg_ao_article_evidence_update BEFORE UPDATE ON article_evidence BEGIN SELECT RAISE(ABORT, 'article_evidence is append-only: a row is never updated'); END
-- @@ requires: table article_evidence
CREATE TRIGGER trg_ao_article_evidence_delete BEFORE DELETE ON article_evidence BEGIN SELECT RAISE(ABORT, 'article_evidence is append-only: a row is never deleted'); END
-- @@ requires: table batch_evidence
CREATE TRIGGER trg_gate_batch_evidence_insert BEFORE INSERT ON batch_evidence BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table batch_evidence
CREATE TRIGGER trg_ao_batch_evidence_update BEFORE UPDATE ON batch_evidence BEGIN SELECT RAISE(ABORT, 'batch_evidence is append-only: a row is never updated'); END
-- @@ requires: table batch_evidence
CREATE TRIGGER trg_ao_batch_evidence_delete BEFORE DELETE ON batch_evidence BEGIN SELECT RAISE(ABORT, 'batch_evidence is append-only: a row is never deleted'); END
-- @@ requires: table update_events
CREATE TRIGGER trg_gate_update_events_insert BEFORE INSERT ON update_events BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_events
CREATE TRIGGER trg_ao_update_events_update BEFORE UPDATE ON update_events BEGIN SELECT RAISE(ABORT, 'update_events is append-only: a row is never updated'); END
-- @@ requires: table update_events
CREATE TRIGGER trg_ao_update_events_delete BEFORE DELETE ON update_events BEGIN SELECT RAISE(ABORT, 'update_events is append-only: a row is never deleted'); END
-- @@ requires: table cycle_editions
CREATE TRIGGER trg_gate_cycle_editions_insert BEFORE INSERT ON cycle_editions BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table cycle_editions
CREATE TRIGGER trg_ao_cycle_editions_update BEFORE UPDATE ON cycle_editions BEGIN SELECT RAISE(ABORT, 'cycle_editions is append-only: a row is never updated'); END
-- @@ requires: table cycle_editions
CREATE TRIGGER trg_ao_cycle_editions_delete BEFORE DELETE ON cycle_editions BEGIN SELECT RAISE(ABORT, 'cycle_editions is append-only: a row is never deleted'); END
-- @@ requires: table qa_runs
CREATE TRIGGER trg_gate_qa_runs_insert BEFORE INSERT ON qa_runs BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table qa_runs
CREATE TRIGGER trg_ao_qa_runs_update BEFORE UPDATE ON qa_runs BEGIN SELECT RAISE(ABORT, 'qa_runs is append-only: a row is never updated'); END
-- @@ requires: table qa_runs
CREATE TRIGGER trg_ao_qa_runs_delete BEFORE DELETE ON qa_runs BEGIN SELECT RAISE(ABORT, 'qa_runs is append-only: a row is never deleted'); END
-- @@ requires: table schema_versions
CREATE TRIGGER trg_gate_schema_versions_insert BEFORE INSERT ON schema_versions BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table schema_versions
CREATE TRIGGER trg_ao_schema_versions_update BEFORE UPDATE ON schema_versions BEGIN SELECT RAISE(ABORT, 'schema_versions is append-only: a row is never updated'); END
-- @@ requires: table schema_versions
CREATE TRIGGER trg_ao_schema_versions_delete BEFORE DELETE ON schema_versions BEGIN SELECT RAISE(ABORT, 'schema_versions is append-only: a row is never deleted'); END
-- @@ requires: table schema_migrations
CREATE TRIGGER trg_ao_schema_migrations_update BEFORE UPDATE ON schema_migrations BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only: a row is never updated'); END
-- @@ requires: table schema_migrations
CREATE TRIGGER trg_ao_schema_migrations_delete BEFORE DELETE ON schema_migrations BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only: a row is never deleted'); END
-- @@ requires: table evidence_aliases
CREATE TRIGGER trg_gate_evidence_aliases_insert BEFORE INSERT ON evidence_aliases BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table offering_sources
CREATE TRIGGER trg_gate_offering_sources_insert BEFORE INSERT ON offering_sources BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table evidence_heads
CREATE TRIGGER trg_gate_evidence_heads_insert BEFORE INSERT ON evidence_heads BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table evidence_heads
CREATE TRIGGER trg_gate_evidence_heads_update BEFORE UPDATE ON evidence_heads BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table evidence_heads
CREATE TRIGGER trg_gate_evidence_heads_delete BEFORE DELETE ON evidence_heads BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table article_heads
CREATE TRIGGER trg_gate_article_heads_insert BEFORE INSERT ON article_heads BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table article_heads
CREATE TRIGGER trg_gate_article_heads_update BEFORE UPDATE ON article_heads BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table article_heads
CREATE TRIGGER trg_gate_article_heads_delete BEFORE DELETE ON article_heads BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_gate_update_batches_insert BEFORE INSERT ON update_batches BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_gate_update_batches_update BEFORE UPDATE ON update_batches BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_gate_update_batches_delete BEFORE DELETE ON update_batches BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_batch_delete BEFORE DELETE ON update_batches BEGIN SELECT RAISE(ABORT, 'update_batches rows are never deleted'); END
-- @@ requires: table update_batches
CREATE TRIGGER trg_batch_update BEFORE UPDATE ON update_batches WHEN NOT (OLD.batch_id = NEW.batch_id AND OLD.input_sha = NEW.input_sha AND OLD.created_at = NEW.created_at AND OLD.before_json = NEW.before_json AND OLD.registry_sha = NEW.registry_sha AND ((OLD.state = 'candidate' AND NEW.state IN ('interrupted', 'rejected', 'approved')) OR (OLD.state = 'approved' AND NEW.state = 'rolled_back' AND NEW.after_json = OLD.after_json AND NEW.qa_json = OLD.qa_json)) AND (NEW.state IN ('rejected', 'approved') OR (NEW.after_json = OLD.after_json AND NEW.qa_json = OLD.qa_json))) BEGIN SELECT RAISE(ABORT, 'update_batches: only candidate to interrupted, rejected or approved, and approved to rolled_back, with the identity columns unchanged'); END
-- @@ requires: table evidence_heads, table evidence_revisions, table batch_evidence, table update_batches
CREATE TRIGGER trg_head_evidence_insert BEFORE INSERT ON evidence_heads WHEN NOT EXISTS(SELECT 1 FROM evidence_revisions r JOIN batch_evidence e ON e.evidence_id = r.evidence_id JOIN update_batches b ON b.batch_id = e.batch_id WHERE r.evidence_id = NEW.evidence_id AND r.logical_id = NEW.logical_id AND b.state = 'approved') BEGIN SELECT RAISE(ABORT, 'a head must be a revision of its own logical id that belongs to an approved batch'); END
-- @@ requires: table article_heads, table revised_articles, table update_batches
CREATE TRIGGER trg_head_article_insert BEFORE INSERT ON article_heads WHEN NOT EXISTS(SELECT 1 FROM revised_articles r JOIN update_batches b ON b.batch_id = r.batch_id WHERE r.article_id = NEW.article_id AND r.base_article_id = NEW.base_article_id AND b.state = 'approved') BEGIN SELECT RAISE(ABORT, 'an article head must be a revision of its own base article that belongs to an approved batch'); END
-- @@ requires: table evidence_heads, table evidence_revisions, table batch_evidence, table update_batches
CREATE TRIGGER trg_head_evidence_update BEFORE UPDATE ON evidence_heads WHEN NOT EXISTS(SELECT 1 FROM evidence_revisions r JOIN batch_evidence e ON e.evidence_id = r.evidence_id JOIN update_batches b ON b.batch_id = e.batch_id WHERE r.evidence_id = NEW.evidence_id AND r.logical_id = NEW.logical_id AND b.state = 'approved') BEGIN SELECT RAISE(ABORT, 'a head must be a revision of its own logical id that belongs to an approved batch'); END
-- @@ requires: table article_heads, table revised_articles, table update_batches
CREATE TRIGGER trg_head_article_update BEFORE UPDATE ON article_heads WHEN NOT EXISTS(SELECT 1 FROM revised_articles r JOIN update_batches b ON b.batch_id = r.batch_id WHERE r.article_id = NEW.article_id AND r.base_article_id = NEW.base_article_id AND b.state = 'approved') BEGIN SELECT RAISE(ABORT, 'an article head must be a revision of its own base article that belongs to an approved batch'); END
-- @@ requires: table admission_cycles
CREATE TRIGGER trg_cycle_identity_update BEFORE UPDATE OF university, faculty, department, admission_method, fiscal_year, exam_year ON admission_cycles BEGIN SELECT RAISE(ABORT, 'the identity columns of a cycle are never updated: a correction is a new cycle'); END
-- @@ requires: table admission_cycles
CREATE TRIGGER trg_gate_admission_cycles_insert BEFORE INSERT ON admission_cycles BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table admission_cycles
CREATE TRIGGER trg_admission_cycles_delete BEFORE DELETE ON admission_cycles BEGIN SELECT RAISE(ABORT, 'admission_cycles rows are never deleted'); END
-- @@ requires: table admission_offerings
CREATE TRIGGER trg_gate_admission_offerings_insert BEFORE INSERT ON admission_offerings BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table admission_offerings
CREATE TRIGGER trg_admission_offerings_delete BEFORE DELETE ON admission_offerings BEGIN SELECT RAISE(ABORT, 'admission_offerings rows are never deleted'); END
-- @@ requires: table cycle_dimensions
CREATE TRIGGER trg_gate_cycle_dimensions_insert BEFORE INSERT ON cycle_dimensions BEGIN SELECT sogh_write_ok(); END
-- @@ requires: table cycle_dimensions
CREATE TRIGGER trg_cycle_dimensions_delete BEFORE DELETE ON cycle_dimensions BEGIN SELECT RAISE(ABORT, 'cycle_dimensions rows are never deleted'); END
