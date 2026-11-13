"""Append-only evidence/article updates with optimistic, QA-gated activation."""
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from .store import EvidenceStore, canonical
from .supplements import contract_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_revisions(evidence_id TEXT PRIMARY KEY,logical_id TEXT NOT NULL,
 case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),fact_key TEXT NOT NULL,source_sha256 TEXT NOT NULL,
 parent_evidence_id TEXT,record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence_heads(logical_id TEXT PRIMARY KEY,evidence_id TEXT NOT NULL REFERENCES evidence_revisions(evidence_id));
CREATE TABLE IF NOT EXISTS update_batches(batch_id TEXT PRIMARY KEY,input_sha TEXT NOT NULL,state TEXT NOT NULL,
 created_at TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,registry_sha TEXT NOT NULL,qa_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batch_evidence(batch_id TEXT NOT NULL REFERENCES update_batches(batch_id),
 evidence_id TEXT NOT NULL REFERENCES evidence_revisions(evidence_id),PRIMARY KEY(batch_id,evidence_id));
CREATE TABLE IF NOT EXISTS revised_articles(article_id TEXT PRIMARY KEY,base_article_id TEXT NOT NULL REFERENCES article_versions(article_id),
 batch_id TEXT NOT NULL REFERENCES update_batches(batch_id),record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS article_heads(base_article_id TEXT PRIMARY KEY REFERENCES article_versions(article_id),
 article_id TEXT NOT NULL REFERENCES revised_articles(article_id));
CREATE TABLE IF NOT EXISTS update_events(id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES update_batches(batch_id),
 event TEXT NOT NULL,created_at TEXT NOT NULL,detail_json TEXT NOT NULL);
INSERT OR IGNORE INTO schema_versions VALUES ('admissions-v0.5-qa-gated-revisions');
"""


def clone_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists(): raise ValueError("new, separate update DB required")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError("copy invalid")
    return destination


class RevisionStore(EvidenceStore):
    def __init__(self, path, backup):
        super().__init__(path)
        self.snapshot(backup)  # Must complete before changing schema/heads.
        with self.connect() as db: db.executescript(SCHEMA)

    def heads(self, db=None):
        if db is None:
            with self.connect() as connection: return self.heads(connection)
        return {"evidence": dict(db.execute("SELECT logical_id,evidence_id FROM evidence_heads")),
                "articles": dict(db.execute("SELECT base_article_id,article_id FROM article_heads"))}

    def recover_candidates(self):
        """Call only after acquiring the update process lock."""
        with self.connect() as db:
            ids=[r[0] for r in db.execute("SELECT batch_id FROM update_batches WHERE state='candidate'")]
            db.execute("UPDATE update_batches SET state='interrupted' WHERE state='candidate'")
            db.executemany("INSERT INTO update_events(batch_id,event,created_at,detail_json) VALUES(?,'interrupted',?,'{}')",
                           [(bid,datetime.now(timezone.utc).isoformat()) for bid in ids])
        return ids

    def effective_records(self, batch):
        with self.connect() as db:
            records=[]
            for eid in batch["after"]["evidence"].values():
                row=db.execute("SELECT record_json,parent_evidence_id FROM evidence_revisions WHERE evidence_id=?",(eid,)).fetchone()
                record=json.loads(row[0]); ancestors=[]; parent=row[1]
                while parent:
                    if parent in ancestors: raise ValueError("revision ancestry cycle")
                    ancestors.append(parent)
                    p=db.execute("SELECT parent_evidence_id FROM evidence_revisions WHERE evidence_id=?",(parent,)).fetchone()
                    parent=p[0] if p else None
                if ancestors:
                    record["revision_ancestors"]=ancestors
                    native_ancestors=[eid for eid in ancestors if db.execute("SELECT 1 FROM facts WHERE evidence_id=?",(eid,)).fetchone()]
                    if native_ancestors: record["replaces_evidence_ids"]=native_ancestors
                records.append(record)
            return records

    def stage(self, records, registry, refresh_articles=False):
        if len({r["logical_id"] for r in records}) != len(records): raise ValueError("duplicate logical identity in update batch")
        before = self.heads()
        input_sha = hashlib.sha256(canonical([records, registry, before, refresh_articles]).encode()).hexdigest()
        batch_id = uuid.uuid4().hex
        pending = [r["evidence_id"] for r in records if contract_state(r, registry) != "candidate"]
        after = json.loads(canonical(before))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for record in records:
                cycle = db.execute("SELECT * FROM admission_cycles WHERE case_id=?", (record["case_id"],)).fetchone()
                if not cycle or any(cycle[k] != record[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")):
                    raise ValueError("cross-cycle update rejected")
                previous_head = before["evidence"].get(record["logical_id"])
                parent_id = record.get("parent_evidence_id") or previous_head
                if parent_id:
                    parent = db.execute("SELECT case_id,fact_key FROM facts WHERE evidence_id=?", (parent_id,)).fetchone()
                    if parent is None: parent = db.execute("SELECT case_id,fact_key FROM evidence_revisions WHERE evidence_id=?", (parent_id,)).fetchone()
                    if not parent or tuple(parent) != (record["case_id"], record["fact_key"]):
                        raise ValueError("correction parent has different case or fact key")
                if previous_head:
                    previous = db.execute("SELECT case_id,fact_key FROM evidence_revisions WHERE evidence_id=?", (previous_head,)).fetchone()
                    if tuple(previous) != (record["case_id"], record["fact_key"]): raise ValueError("logical identity changed")
                old = db.execute("SELECT record_json FROM evidence_revisions WHERE evidence_id=?", (record["evidence_id"],)).fetchone()
                if old and old[0] != canonical(record):
                    previous_record = json.loads(old[0])
                    if {k:v for k,v in previous_record.items() if k != "retrieved_at"} != {k:v for k,v in record.items() if k != "retrieved_at"}:
                        raise ValueError("immutable revision differs")
                db.execute("INSERT OR IGNORE INTO evidence_revisions VALUES(?,?,?,?,?,?,?)", (
                    record["evidence_id"], record["logical_id"], record["case_id"], record["fact_key"], record["source_sha256"], parent_id, canonical(record)))
                if record["evidence_id"] not in pending: after["evidence"][record["logical_id"]] = record["evidence_id"]
            state = "pending_contract" if pending else ("no_change" if after == before and not refresh_articles else "candidate")
            db.execute("INSERT INTO update_batches VALUES(?,?,?,?,?,?,?,?)", (batch_id, input_sha, state,
                datetime.now(timezone.utc).isoformat(), canonical(before), canonical(after), hashlib.sha256(canonical(registry).encode()).hexdigest(), "{}"))
            db.executemany("INSERT INTO batch_evidence VALUES(?,?)", [(batch_id, r["evidence_id"]) for r in records])
        return {"batch_id": batch_id, "input_sha": input_sha, "state": state, "pending_contract": pending, "before": before, "after": after}

    def finalize(self, batch, articles, qa, registry):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute("SELECT * FROM update_batches WHERE batch_id=?", (batch["batch_id"],)).fetchone()
            if saved["state"] != "candidate": raise ValueError("batch is not eligible for approval")
            if saved["registry_sha"] != hashlib.sha256(canonical(registry).encode()).hexdigest(): raise ValueError("registry changed during update")
            if self.heads(db) != json.loads(saved["before_json"]): raise ValueError("concurrent head change; rebase update")
            if not qa.get("success"):
                db.execute("UPDATE update_batches SET state='rejected',qa_json=? WHERE batch_id=?", (canonical(qa), batch["batch_id"]))
                return False
            if qa.get("batch_input_sha") != saved["input_sha"] or qa.get("articles_sha256") != hashlib.sha256(canonical(articles).encode()).hexdigest():
                raise ValueError("QA result is not bound to this exact update")
            expected_ids = {r[0] for r in db.execute("SELECT evidence_id FROM batch_evidence WHERE batch_id=?", (batch["batch_id"],))}
            if not articles or any(a.get("publish_allowed") is not False for a in articles): raise ValueError("unapproved article state")
            if not expected_ids <= {eid for a in articles for eid in a["evidence_ids"]}: raise ValueError("new evidence not covered by revised articles")
            after = json.loads(saved["after_json"])
            for article in articles:
                original = db.execute("SELECT case_id FROM article_versions WHERE article_id=?", (article["base_article_id"],)).fetchone()
                if not original or original[0] != article["case_id"]: raise ValueError("article case mismatch")
                cycle=db.execute('SELECT * FROM admission_cycles WHERE case_id=?',(original[0],)).fetchone()
                if any(article.get('claim',{}).get(k)!=cycle[k] for k in ('university','faculty','department','admission_method','fiscal_year')):
                    raise ValueError('article scope or year differs from its cycle')
                cited=set(re.findall(r'\[(EV-[A-Za-z0-9_-]+)\]',article['text']))
                if not cited or cited!=set(article['evidence_ids']):raise ValueError('article citation list differs or has no evidence')
                for eid in cited:
                    fact=db.execute('SELECT case_id FROM facts WHERE evidence_id=?',(eid,)).fetchone()
                    if fact is None:
                        if eid not in after['evidence'].values():raise ValueError('article cites unknown or inactive evidence')
                        fact=db.execute('SELECT case_id FROM evidence_revisions WHERE evidence_id=?',(eid,)).fetchone()
                    if not fact or fact[0]!=original[0]:raise ValueError('article cites a different cycle')
                db.execute("INSERT INTO revised_articles VALUES(?,?,?,?)", (article["article_id"], article["base_article_id"], batch["batch_id"], canonical(article)))
                after["articles"][article["base_article_id"]] = article["article_id"]
            for logical, eid in after["evidence"].items():
                db.execute("INSERT INTO evidence_heads VALUES(?,?) ON CONFLICT(logical_id) DO UPDATE SET evidence_id=excluded.evidence_id", (logical, eid))
            for base, aid in after["articles"].items():
                db.execute("INSERT INTO article_heads VALUES(?,?) ON CONFLICT(base_article_id) DO UPDATE SET article_id=excluded.article_id", (base, aid))
            db.execute("UPDATE update_batches SET state='approved',after_json=?,qa_json=? WHERE batch_id=?", (canonical(after), canonical(qa), batch["batch_id"]))
            db.execute("INSERT INTO update_events(batch_id,event,created_at,detail_json) VALUES(?,'approved',?,?)", (batch["batch_id"], datetime.now(timezone.utc).isoformat(), canonical({"evidence": len(expected_ids), "articles": len(articles)})))
        return True

    def rollback_batch(self, batch_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            batch = db.execute("SELECT * FROM update_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if not batch or batch["state"] != "approved" or self.heads(db) != json.loads(batch["after_json"]):
                raise ValueError("rollback would overwrite newer progress")
            before = json.loads(batch["before_json"])
            db.execute("DELETE FROM evidence_heads"); db.execute("DELETE FROM article_heads")
            db.executemany("INSERT INTO evidence_heads VALUES(?,?)", list(before["evidence"].items()))
            db.executemany("INSERT INTO article_heads VALUES(?,?)", list(before["articles"].items()))
            db.execute("UPDATE update_batches SET state='rolled_back' WHERE batch_id=?", (batch_id,))
            db.execute("INSERT INTO update_events(batch_id,event,created_at,detail_json) VALUES(?,'rolled_back',?,'{}')", (batch_id, datetime.now(timezone.utc).isoformat()))
