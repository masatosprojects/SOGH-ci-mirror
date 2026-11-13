-- FROZEN SQL of migration 0008-g03-lookup-indexes (M1 unified design, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Same file format as 0005. G-03: the lookups that EXPLAIN QUERY PLAN showed as full scans on the audited copy (5 cases) and that the root view, the impact analysis and the audit repeat: the parent and the logical id of a
-- revision, the evidence of an article citation (first version and revised), the source of a fact, the batch of an event, the evidence of a batch. Six indexes plus the one the revised-article relation needs.
-- Nothing else is indexed (a column of every table would slow writes and grow the file). That the planner uses them is checked on small data; performance at national scale is NOT_RUN.
-- @@ requires: table evidence_revisions
CREATE INDEX ix_evidence_revisions_parent ON evidence_revisions(parent_evidence_id)
-- @@ requires: table evidence_revisions
CREATE INDEX ix_evidence_revisions_logical ON evidence_revisions(logical_id)
-- @@ requires: table article_evidence
CREATE INDEX ix_article_evidence_evidence ON article_evidence(evidence_id)
-- @@ requires: table facts
CREATE INDEX ix_facts_source ON facts(source_sha256)
-- @@ requires: table update_events
CREATE INDEX ix_update_events_batch ON update_events(batch_id)
-- @@ requires: table batch_evidence
CREATE INDEX ix_batch_evidence_evidence ON batch_evidence(evidence_id)
-- @@ requires: table revised_article_evidence
CREATE INDEX ix_revised_article_evidence_evidence ON revised_article_evidence(evidence_id)
