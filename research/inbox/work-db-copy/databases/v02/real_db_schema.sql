CREATE INDEX ix_academic_units_university ON academic_units(university_id);

CREATE INDEX ix_cycles_year ON admission_cycles(entry_year);

CREATE INDEX ix_fact_cycle_field ON fact_claims(cycle_id,field_key);

CREATE INDEX ix_fact_review ON fact_claims(review_status);

CREATE INDEX ix_routes_unit ON admission_routes(academic_unit_id);

CREATE INDEX ix_snapshots_doc_time ON source_snapshots(document_id,retrieved_at);

CREATE TABLE academic_units (
  id TEXT PRIMARY KEY,
  university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE RESTRICT,
  parent_unit_id TEXT REFERENCES academic_units(id) ON DELETE RESTRICT,
  unit_type TEXT NOT NULL CHECK (unit_type IN ('faculty','department','college','course','graduate_school','other')),
  name TEXT NOT NULL,
  active_from_year INTEGER,
  active_to_year INTEGER,
  CHECK (active_to_year IS NULL OR active_from_year IS NULL OR active_to_year >= active_from_year)
);

CREATE TABLE admission_cycles (
  id TEXT PRIMARY KEY,
  route_id TEXT NOT NULL REFERENCES admission_routes(id) ON DELETE RESTRICT,
  entry_year INTEGER NOT NULL CHECK (entry_year BETWEEN 2000 AND 2200),
  round_name TEXT NOT NULL DEFAULT 'main',
  cycle_status TEXT NOT NULL DEFAULT 'researching'
    CHECK (cycle_status IN ('researching','open','closed','archived')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(route_id, entry_year, round_name)
);

CREATE TABLE admission_routes (
  id TEXT PRIMARY KEY,
  academic_unit_id TEXT NOT NULL REFERENCES academic_units(id) ON DELETE RESTRICT,
  route_name TEXT NOT NULL,
  route_category TEXT NOT NULL CHECK (route_category IN ('comprehensive','school_recommendation','general','special','other')),
  official_route_url TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

CREATE TABLE article_plans (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL REFERENCES admission_cycles(id) ON DELETE RESTRICT,
  series_id TEXT NOT NULL REFERENCES article_series(id) ON DELETE RESTRICT,
  subject_key TEXT NOT NULL,
  working_title TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'planned'
    CHECK (state IN ('planned','collecting','ready_to_generate','generated','reviewing','approved','published','paused')),
  priority INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(cycle_id,series_id,subject_key)
);

CREATE TABLE article_series (
  id TEXT PRIMARY KEY,
  series_key TEXT NOT NULL UNIQUE,
  series_name TEXT NOT NULL,
  template_version TEXT NOT NULL,
  audience TEXT,
  purpose TEXT
);

CREATE TABLE article_version_facts (
  article_version_id TEXT NOT NULL REFERENCES article_versions(id) ON DELETE CASCADE,
  fact_id TEXT NOT NULL REFERENCES fact_claims(id) ON DELETE RESTRICT,
  PRIMARY KEY (article_version_id,fact_id)
);

CREATE TABLE article_versions (
  id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES article_plans(id) ON DELETE RESTRICT,
  version_no INTEGER NOT NULL CHECK (version_no > 0),
  markdown_path TEXT,
  generation_model TEXT,
  prompt_version TEXT,
  input_fingerprint TEXT NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'draft'
    CHECK (review_status IN ('draft','needs_fact_review','approved','rejected','stale')),
  approved_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(plan_id,version_no),
  CHECK (review_status <> 'approved' OR approved_at IS NOT NULL)
);

CREATE TABLE audit_events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json)),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE experience_observations (
  id TEXT PRIMARY KEY,
  experience_id TEXT NOT NULL REFERENCES experience_reports(id) ON DELETE CASCADE,
  stage_id TEXT REFERENCES selection_stages(id) ON DELETE RESTRICT,
  observation_type TEXT NOT NULL CHECK (observation_type IN ('question','panel','duration','setting','advice','other')),
  anonymized_summary TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'self_reported'
    CHECK (confidence IN ('self_reported','corroborated','disputed'))
);

CREATE TABLE experience_reports (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL REFERENCES admission_cycles(id) ON DELETE RESTRICT,
  anonymous_token TEXT NOT NULL UNIQUE,
  consent_scope TEXT NOT NULL CHECK (consent_scope IN ('internal_only','anonymized_public','withdrawn')),
  consent_recorded_at TEXT,
  outcome TEXT NOT NULL DEFAULT 'unreported'
    CHECK (outcome IN ('accepted','rejected','pending','unreported')),
  submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
  redaction_status TEXT NOT NULL DEFAULT 'needs_review'
    CHECK (redaction_status IN ('needs_review','approved','blocked')),
  CHECK (consent_scope <> 'anonymized_public' OR consent_recorded_at IS NOT NULL)
);

CREATE TABLE fact_claims (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL REFERENCES admission_cycles(id) ON DELETE RESTRICT,
  stage_id TEXT REFERENCES selection_stages(id) ON DELETE RESTRICT,
  field_key TEXT NOT NULL,
  display_statement TEXT NOT NULL,
  value_json TEXT NOT NULL CHECK (json_valid(value_json)),
  basis TEXT NOT NULL CHECK (basis IN ('official','experience','third_party')),
  review_status TEXT NOT NULL DEFAULT 'candidate'
    CHECK (review_status IN ('candidate','verified','disputed','superseded','rejected')),
  observed_at TEXT,
  last_verified_at TEXT,
  superseded_by TEXT REFERENCES fact_claims(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE fact_evidence (
  fact_id TEXT NOT NULL REFERENCES fact_claims(id) ON DELETE CASCADE,
  snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id) ON DELETE RESTRICT,
  relation TEXT NOT NULL CHECK (relation IN ('supports','contradicts','context')),
  locator TEXT NOT NULL, -- PDF p.4 / 公式ページの見出し・アンカー等
  excerpt TEXT,          -- 短い確認用抜粋。著作権と保存目的に注意。
  PRIMARY KEY (fact_id,snapshot_id,relation,locator)
);

CREATE TABLE publications (
  id TEXT PRIMARY KEY,
  article_version_id TEXT NOT NULL REFERENCES article_versions(id) ON DELETE RESTRICT,
  platform TEXT NOT NULL CHECK (platform IN ('note','website','other')),
  idempotency_key TEXT NOT NULL,
  external_post_id TEXT,
  external_url TEXT,
  publish_status TEXT NOT NULL DEFAULT 'queued'
    CHECK (publish_status IN ('queued','draft','published','failed','unpublished')),
  last_attempt_at TEXT,
  published_at TEXT,
  UNIQUE(platform,idempotency_key),
  UNIQUE(platform,external_post_id)
);

CREATE TABLE selection_stages (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL REFERENCES admission_cycles(id) ON DELETE RESTRICT,
  stage_order INTEGER NOT NULL CHECK (stage_order > 0),
  stage_name TEXT NOT NULL,
  stage_type TEXT NOT NULL CHECK (stage_type IN ('document','interview','oral_exam','essay','written','practical','other')),
  stage_format TEXT,
  UNIQUE(cycle_id, stage_order)
);

CREATE TABLE source_documents (
  id TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('official_guideline','official_web','official_notice','third_party','consented_experience','other')),
  title TEXT NOT NULL,
  publisher TEXT,
  canonical_url TEXT,
  issued_at TEXT,
  license_notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE source_snapshots (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE RESTRICT,
  retrieved_at TEXT NOT NULL,
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  storage_uri TEXT,
  drive_file_id TEXT,
  media_type TEXT,
  status TEXT NOT NULL DEFAULT 'captured'
    CHECK (status IN ('captured','parsed','reviewed','failed')),
  UNIQUE(document_id, content_sha256)
);

CREATE TABLE universities (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  official_url TEXT,
  school_type TEXT NOT NULL DEFAULT 'unspecified'
    CHECK (school_type IN ('national','public','private','unspecified')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER trg_fact_stage_cycle_insert
BEFORE INSERT ON fact_claims WHEN NEW.stage_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT,'fact.stage_id must belong to fact.cycle_id')
   WHERE NOT EXISTS (SELECT 1 FROM selection_stages s WHERE s.id=NEW.stage_id AND s.cycle_id=NEW.cycle_id);
END;

CREATE TRIGGER trg_fact_stage_cycle_update
BEFORE UPDATE OF cycle_id, stage_id ON fact_claims WHEN NEW.stage_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT,'fact.stage_id must belong to fact.cycle_id')
   WHERE NOT EXISTS (SELECT 1 FROM selection_stages s WHERE s.id=NEW.stage_id AND s.cycle_id=NEW.cycle_id);
END;

CREATE VIEW v_article_fact_health AS
SELECT v.id AS article_version_id, v.review_status,
 COUNT(af.fact_id) AS fact_count,
 SUM(CASE WHEN f.review_status <> 'verified' THEN 1 ELSE 0 END) AS unverified_fact_count,
 SUM(CASE WHEN f.id IS NOT NULL AND NOT EXISTS (
   SELECT 1 FROM fact_evidence fe WHERE fe.fact_id=f.id AND fe.relation='supports'
 ) THEN 1 ELSE 0 END) AS missing_evidence_count
FROM article_versions v
LEFT JOIN article_version_facts af ON af.article_version_id=v.id
LEFT JOIN fact_claims f ON f.id=af.fact_id
GROUP BY v.id;
