CREATE TABLE admission_cycles(
  case_id TEXT PRIMARY KEY,university TEXT NOT NULL,faculty TEXT NOT NULL,department TEXT,
  admission_method TEXT NOT NULL,fiscal_year INTEGER NOT NULL CHECK(fiscal_year BETWEEN 2000 AND 2100),
  exam_year INTEGER NOT NULL CHECK(exam_year BETWEEN 2000 AND 2100),
  UNIQUE(university,faculty,department,admission_method,fiscal_year));
CREATE TABLE admission_offerings(
 offering_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
 round_name TEXT NOT NULL,entry_month INTEGER CHECK(entry_month BETWEEN 1 AND 12),
 scope_json TEXT NOT NULL,source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256));
CREATE TABLE article_evidence(
  article_id TEXT NOT NULL REFERENCES article_versions(article_id),
  evidence_id TEXT NOT NULL REFERENCES facts(evidence_id),PRIMARY KEY(article_id,evidence_id));
CREATE TABLE article_versions(
  article_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
  input_hash TEXT NOT NULL,series TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,
  artifact_path TEXT NOT NULL,publish_allowed INTEGER NOT NULL CHECK(publish_allowed=0));
CREATE TABLE cycle_dimensions(
 case_id TEXT PRIMARY KEY REFERENCES admission_cycles(case_id),
 selection_category TEXT NOT NULL CHECK(selection_category IN
 ('comprehensive','school_recommendation','general','common_test','special')),
 entry_year INTEGER NOT NULL CHECK(entry_year BETWEEN 2000 AND 2100),
 exam_year INTEGER NOT NULL CHECK(exam_year BETWEEN 2000 AND 2100),
 entry_months_json TEXT NOT NULL,round_name TEXT NOT NULL,scope_json TEXT NOT NULL);
CREATE TABLE cycle_editions(
 case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
 source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),
 profile_sha256 TEXT NOT NULL,profile_version TEXT NOT NULL,observed_at TEXT NOT NULL, profile_json TEXT,
 PRIMARY KEY(case_id,source_sha256,profile_sha256));
CREATE TABLE facts(
  evidence_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
  source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),fact_key TEXT NOT NULL,
  value_json TEXT NOT NULL,record_json TEXT NOT NULL,
  verification TEXT NOT NULL CHECK(verification='source_checked_for_saved_version'),
  UNIQUE(case_id,source_sha256,fact_key));
CREATE TABLE legacy_fact_links(
          legacy_sha256 TEXT NOT NULL REFERENCES legacy_imports(file_sha256),legacy_fact_id TEXT NOT NULL,
          case_id TEXT REFERENCES admission_cycles(case_id),evidence_id TEXT REFERENCES facts(evidence_id),
          status TEXT NOT NULL,report_json TEXT NOT NULL,PRIMARY KEY(legacy_sha256,legacy_fact_id));
CREATE TABLE legacy_imports(
  file_sha256 TEXT PRIMARY KEY,original_path TEXT NOT NULL,copy_path TEXT NOT NULL,
  audit_json TEXT NOT NULL,facts_promoted INTEGER NOT NULL CHECK(facts_promoted=0));
CREATE TABLE legacy_records(
          legacy_sha256 TEXT NOT NULL REFERENCES legacy_imports(file_sha256),table_name TEXT NOT NULL,
          record_key TEXT NOT NULL,record_json TEXT NOT NULL,PRIMARY KEY(legacy_sha256,table_name,record_key));
CREATE TABLE qa_runs(
  run_id TEXT PRIMARY KEY,claude_commit TEXT NOT NULL,report_path TEXT NOT NULL,
  success INTEGER NOT NULL CHECK(success IN (0,1)));
CREATE TABLE schema_versions(version TEXT PRIMARY KEY);
CREATE TABLE source_documents(
  sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64),url TEXT NOT NULL,local_path TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,revision_clearance TEXT NOT NULL);
CREATE TABLE source_pages(
  source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),page INTEGER NOT NULL CHECK(page>0),
  text TEXT NOT NULL,text_sha256 TEXT NOT NULL,PRIMARY KEY(source_sha256,page));
