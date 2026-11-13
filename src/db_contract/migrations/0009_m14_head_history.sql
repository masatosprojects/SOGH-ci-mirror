-- FROZEN SQL of migration 0009-m14-head-history (M1 unified design M-14, SELF_VALIDATED, WORK_REVIEW_PENDING, applied to no operational database).
-- Same file format as 0005. The heads of the past are not stored a second time: every approval stores the COMPLETE head state it produced (update_batches.after_json) and every rollback restores the
-- state before the batch (before_json). This view lists those two kinds of event in order; replaying it up to a time gives the heads at that time (additive_schema.heads_as_of / read_as_of), and the
-- replay up to now must equal the current heads (db_audit DB-18). Nothing here changes a row.
-- @@ requires: table update_events, table update_batches
CREATE VIEW v_head_events AS SELECT e.id AS event_id, e.batch_id, e.event, e.created_at, CASE e.event WHEN 'approved' THEN b.after_json ELSE b.before_json END AS heads_json FROM update_events e JOIN update_batches b ON b.batch_id = e.batch_id WHERE e.event IN ('approved', 'rolled_back')
