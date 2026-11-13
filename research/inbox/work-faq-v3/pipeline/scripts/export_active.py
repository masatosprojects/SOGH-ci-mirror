"""Materialize only approved heads; retain historical native facts in the DB."""
import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def export_active(database, base_export):
    from src.db_contract.historical_read import read_cited_evidence

    data=json.loads(Path(base_export).read_text(encoding="utf-8"))
    articles={a["article_id"]:a for a in data["articles"]}
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')  # All heads and their approved rows come from one read snapshot.
        for eid,record in data['evidence'].items():
            native=db.execute('SELECT f.*,c.university,c.faculty,c.department,c.admission_method,c.fiscal_year FROM facts f JOIN admission_cycles c ON c.case_id=f.case_id WHERE evidence_id=?',(eid,)).fetchone()
            if (not native or record['fact_key']!=native['fact_key'] or canonical(record['value'])!=canonical(json.loads(native['value_json']))
                or record['source_pdf_sha256']!=native['source_sha256']
                or any(k in record and record[k]!=native[k] for k in ('university','faculty','department','admission_method','fiscal_year'))):
                raise ValueError('base evidence differs from the native database')
        for article in data['articles']:
            native=db.execute('SELECT body,case_id FROM article_versions WHERE article_id=?',(article['article_id'],)).fetchone()
            if not native or native["body"]!=article['text']:
                raise ValueError('base article differs from the native database')
            if "case_id" in article and article["case_id"] != native["case_id"]:
                raise ValueError('base article belongs to another case')
            ids = article.get("evidence_ids")
            if "evidence_ids" not in article:
                ids = sorted(set(re.findall(r"\[(EV-[A-Za-z0-9_-]+)\]", article["text"])))
            if not isinstance(ids, list) or len(ids) != len(set(ids)):
                raise ValueError('article must state unique evidence ids')
            related = [row[0] for row in db.execute(
                "SELECT evidence_id FROM article_evidence WHERE article_id=?", (article["article_id"],))]
            if len(related) != len(set(related)) or set(ids) != set(related):
                raise ValueError('article evidence differs from its stored citations')
            for eid in ids:
                record = data["evidence"].get(eid)
                if not isinstance(record, dict):
                    raise ValueError('article evidence is missing from the base export')
                expect = {"case_id": native["case_id"], "source_sha256": record["source_pdf_sha256"]}
                if "case_id" in record:
                    if record["case_id"] != native["case_id"]:
                        raise ValueError('base evidence belongs to another case')
                if "scope" in record:
                    expect["scope"] = record["scope"]
                expect["record_subset"] = {key: record[key] for key in
                    ("value", "locator", "proofs", "field_proofs") if key in record}
                bound = read_cited_evidence(db, article["article_id"], eid, expect=expect, require_restored=False)
                if bound.row["fact_key"] != record["fact_key"]:
                    raise ValueError('base evidence key differs from cited evidence')
        for row in db.execute("SELECT r.* FROM evidence_heads h JOIN evidence_revisions r ON r.evidence_id=h.evidence_id"):
            if not db.execute("SELECT 1 FROM batch_evidence e JOIN update_batches b ON b.batch_id=e.batch_id WHERE e.evidence_id=? AND b.state='approved'",(row["evidence_id"],)).fetchone():
                raise ValueError("head lacks an approved QA batch")
            record=json.loads(row["record_json"]); parent=row["parent_evidence_id"]; seen=set()
            while parent:
                if parent in seen:raise ValueError("revision ancestry cycle")
                seen.add(parent);data["evidence"].pop(parent,None)
                previous=db.execute("SELECT parent_evidence_id FROM evidence_revisions WHERE evidence_id=?",(parent,)).fetchone()
                parent=previous[0] if previous else None
            data["evidence"][record["evidence_id"]]=record
        for row in db.execute("SELECT r.*,b.state FROM article_heads h JOIN revised_articles r ON r.article_id=h.article_id JOIN update_batches b ON b.batch_id=r.batch_id"):
            if row["state"]!='approved':raise ValueError("article head lacks approved QA")
            articles.pop(row["base_article_id"],None)
            record=json.loads(row["record_json"]);articles[record["article_id"]]=record
    data["articles"]=list(articles.values())
    return data


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--database",type=Path,required=True);p.add_argument("--base-export",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    args = p.parse_args()
    # Direct script execution puts scripts/, rather than the checkout root, on sys.path.
    parents = Path(__file__).resolve().parents
    repository = parents[5] if len(parents) > 5 else None
    if repository is None or not (repository / "src/db_contract/historical_read.py").is_file():
        p.error("run export_active.py from the full SOGH-collab checkout with the g3 read contract")
    sys.path.insert(0, str(repository))
    data = export_active(args.database, args.base_export)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"effective_evidence":len(data["evidence"]),"current_articles":len(data["articles"])}))


if __name__=="__main__":main()
