-- FROZEN SQL of migration 0003-g05-evidence-root-alias (M1 unified design, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Same file format as 0002. The root of a revision series is decided by the view v_evidence_root (any depth; a series that has no root is listed in v_evidence_orphans, never dropped silently);
-- a pinned alias is checked against that view, not against a fixed number of generations.
-- @@
CREATE UNIQUE INDEX ux_facts_identity_case_key ON facts(evidence_id, case_id, fact_key)
-- @@
CREATE TABLE evidence_aliases(
 alias_id TEXT PRIMARY KEY,
 root_evidence_id TEXT NOT NULL, case_id TEXT NOT NULL, fact_key TEXT NOT NULL,
 pinned_evidence_id TEXT REFERENCES evidence_revisions(evidence_id),
 kind TEXT NOT NULL CHECK(kind IN ('legacy_compat_id', 'locator_corrected_copy')),
 reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
 created_at TEXT NOT NULL,
 CHECK(alias_id <> root_evidence_id),
 FOREIGN KEY(root_evidence_id, case_id, fact_key) REFERENCES facts(evidence_id, case_id, fact_key))
-- @@
CREATE VIEW v_evidence_root AS WITH RECURSIVE chain(evidence_id, root_evidence_id) AS (
 SELECT evidence_id, evidence_id FROM facts
 UNION ALL SELECT evidence_id, evidence_id FROM evidence_revisions WHERE parent_evidence_id IS NULL OR parent_evidence_id NOT IN (SELECT evidence_id FROM facts UNION SELECT evidence_id FROM evidence_revisions)
 UNION ALL SELECT r.evidence_id, c.root_evidence_id FROM evidence_revisions r JOIN chain c ON r.parent_evidence_id = c.evidence_id)
 SELECT evidence_id, root_evidence_id FROM chain
-- @@
CREATE VIEW v_evidence_orphans AS SELECT evidence_id FROM evidence_revisions WHERE evidence_id NOT IN (SELECT evidence_id FROM v_evidence_root)
-- @@
CREATE TRIGGER trg_alias_root_exists_in_the_same_case BEFORE INSERT ON evidence_aliases WHEN NOT EXISTS(SELECT 1 FROM facts WHERE evidence_id = NEW.root_evidence_id AND case_id = NEW.case_id AND fact_key = NEW.fact_key) BEGIN SELECT RAISE(ABORT, 'unknown root, or another case or fact_key'); END
-- @@
CREATE TRIGGER trg_alias_no_id_reuse BEFORE INSERT ON evidence_aliases WHEN EXISTS(SELECT 1 FROM facts WHERE evidence_id = NEW.alias_id) OR EXISTS(SELECT 1 FROM evidence_revisions WHERE evidence_id = NEW.alias_id) BEGIN SELECT RAISE(ABORT, 'alias id is already an evidence id'); END
-- @@
CREATE TRIGGER trg_alias_root_is_not_an_alias BEFORE INSERT ON evidence_aliases WHEN EXISTS(SELECT 1 FROM evidence_aliases WHERE alias_id = NEW.root_evidence_id) BEGIN SELECT RAISE(ABORT, 'an alias cannot point at an alias'); END
-- @@
CREATE TRIGGER trg_alias_pinned_version_descends BEFORE INSERT ON evidence_aliases WHEN NEW.pinned_evidence_id IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM evidence_revisions WHERE evidence_id = NEW.pinned_evidence_id AND case_id = NEW.case_id AND fact_key = NEW.fact_key) OR (SELECT root_evidence_id FROM v_evidence_root WHERE evidence_id = NEW.pinned_evidence_id) IS NOT NEW.root_evidence_id) BEGIN SELECT RAISE(ABORT, 'pinned version is not a revision of the root'); END
-- @@
CREATE TRIGGER trg_alias_is_append_only_update BEFORE UPDATE ON evidence_aliases BEGIN SELECT RAISE(ABORT, 'aliases are append-only'); END
-- @@
CREATE TRIGGER trg_alias_is_append_only_delete BEFORE DELETE ON evidence_aliases BEGIN SELECT RAISE(ABORT, 'aliases are append-only'); END
-- @@
CREATE TRIGGER trg_new_fact_id_is_not_an_alias BEFORE INSERT ON facts WHEN EXISTS(SELECT 1 FROM evidence_aliases WHERE alias_id = NEW.evidence_id) BEGIN SELECT RAISE(ABORT, 'evidence id is already an alias'); END
-- @@
CREATE TRIGGER trg_new_revision_id_is_not_an_alias BEFORE INSERT ON evidence_revisions WHEN EXISTS(SELECT 1 FROM evidence_aliases WHERE alias_id = NEW.evidence_id) BEGIN SELECT RAISE(ABORT, 'evidence id is already an alias'); END
