import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_versions(version TEXT PRIMARY KEY);
INSERT OR IGNORE INTO schema_versions VALUES ('admissions-v0.3-source-facts');
CREATE TABLE IF NOT EXISTS admission_cycles(
  case_id TEXT PRIMARY KEY,university TEXT NOT NULL,faculty TEXT NOT NULL,department TEXT,
  admission_method TEXT NOT NULL,fiscal_year INTEGER NOT NULL CHECK(fiscal_year BETWEEN 2000 AND 2100),
  exam_year INTEGER NOT NULL CHECK(exam_year BETWEEN 2000 AND 2100),
  UNIQUE(university,faculty,department,admission_method,fiscal_year));
CREATE TABLE IF NOT EXISTS source_documents(
  sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64),url TEXT NOT NULL,local_path TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,revision_clearance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_pages(
  source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),page INTEGER NOT NULL CHECK(page>0),
  text TEXT NOT NULL,text_sha256 TEXT NOT NULL,PRIMARY KEY(source_sha256,page));
CREATE TABLE IF NOT EXISTS facts(
  evidence_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
  source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256),fact_key TEXT NOT NULL,
  value_json TEXT NOT NULL,record_json TEXT NOT NULL,
  verification TEXT NOT NULL CHECK(verification='source_checked_for_saved_version'),
  UNIQUE(case_id,source_sha256,fact_key));
CREATE TABLE IF NOT EXISTS article_versions(
  article_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),
  input_hash TEXT NOT NULL,series TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,
  artifact_path TEXT NOT NULL,publish_allowed INTEGER NOT NULL CHECK(publish_allowed=0));
CREATE TABLE IF NOT EXISTS article_evidence(
  article_id TEXT NOT NULL REFERENCES article_versions(article_id),
  evidence_id TEXT NOT NULL REFERENCES facts(evidence_id),PRIMARY KEY(article_id,evidence_id));
CREATE TABLE IF NOT EXISTS qa_runs(
  run_id TEXT PRIMARY KEY,claude_commit TEXT NOT NULL,report_path TEXT NOT NULL,
  success INTEGER NOT NULL CHECK(success IN (0,1)));
CREATE TABLE IF NOT EXISTS legacy_imports(
  file_sha256 TEXT PRIMARY KEY,original_path TEXT NOT NULL,copy_path TEXT NOT NULL,
  audit_json TEXT NOT NULL,facts_promoted INTEGER NOT NULL CHECK(facts_promoted=0));
"""


class EvidenceStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ingest(self, extracted, retrieved_at):
        p = extracted.profile
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO admission_cycles VALUES (?,?,?,?,?,?,?)",
                       (extracted.case_id, p["university"], p["faculty"], p["department"], p["admission_method"], p["fiscal_year"], p["exam_year"]))
            db.execute("INSERT OR IGNORE INTO source_documents VALUES (?,?,?,?,?)",
                       (p["sha256"], p["url"], str(extracted.pdf_path), retrieved_at, "not_cleared_for_publication"))
            for n, text in enumerate(extracted.pages, 1):
                db.execute("INSERT OR IGNORE INTO source_pages VALUES (?,?,?,?)",
                           (p["sha256"], n, text, hashlib.sha256(text.encode()).hexdigest()))
            for fact in extracted.facts:
                previous = db.execute("SELECT record_json FROM facts WHERE evidence_id=?", (fact["evidence_id"],)).fetchone()
                if previous and previous[0] != canonical(fact):
                    raise ValueError("immutable evidence differs; review profile version and migrate explicitly")
                db.execute("INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?,?)",
                           (fact["evidence_id"], extracted.case_id, p["sha256"], fact["key"], canonical(fact["value"]), canonical(fact), fact["verification"]))

    def pack(self, case_id, source_sha256):
        with self.connect() as db:
            cycle = dict(db.execute("SELECT * FROM admission_cycles WHERE case_id=?", (case_id,)).fetchone())
            source = dict(db.execute("SELECT * FROM source_documents WHERE sha256=?", (source_sha256,)).fetchone())
            facts = [json.loads(r[0]) for r in db.execute("SELECT record_json FROM facts WHERE case_id=? AND source_sha256=? ORDER BY evidence_id", (case_id, source_sha256))]
        if not facts:
            raise ValueError("cannot write article from an empty fact pack")
        for fact in facts:
            if fact["verification"] != "source_checked_for_saved_version" or fact["fiscal_year"] != cycle["fiscal_year"]:
                raise ValueError("ineligible fact in information pack")
        return {"cycle": cycle, "source": source, "facts": facts,
                "publish_allowed": False, "unresolved": ["latest_corrections_and_publication_approval"],
                "generation_method": "source_bound_python_template"}

    def save_article(self, article, path):
        with self.connect() as db:
            prior = db.execute("SELECT body,input_hash FROM article_versions WHERE article_id=?", (article["article_id"],)).fetchone()
            if prior and (prior["body"] != article["text"] or prior["input_hash"] != article["input_hash"]):
                raise ValueError("immutable article version changed; increment template/profile version")
            db.execute("INSERT OR IGNORE INTO article_versions VALUES (?,?,?,?,?,?,?,0)",
                       (article["article_id"], article["case_id"], article["input_hash"], article["series"], article["title"], article["text"], str(path)))
            for evidence_id in article["evidence_ids"]:
                db.execute("INSERT OR IGNORE INTO article_evidence VALUES (?,?)", (article["article_id"], evidence_id))

    def snapshot(self, path):
        path = Path(path)
        if path.exists():
            raise FileExistsError("refuse to overwrite a database snapshot")
        with self.connect() as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)
        return path

    def counts(self):
        with self.connect() as db:
            return {name: db.execute("SELECT count(*) FROM " + name).fetchone()[0]
                    for name in ("admission_cycles", "source_documents", "source_pages", "facts", "article_versions", "article_evidence")}
