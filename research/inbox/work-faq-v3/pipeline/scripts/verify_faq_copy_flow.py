"""Rollback/reapply/idempotency and false-QA fault injection on a NEW DB copy."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from admissions_pipeline.revisions import clone_database,RevisionStore
from admissions_pipeline.store import canonical
from admissions_pipeline.faq_mutations import variants
from revise_notices import run


def main():
    p=argparse.ArgumentParser()
    for key in ('database','specs','monitor-root','base-export','qa-root','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);original_sha=hashlib.sha256(a.database.read_bytes()).hexdigest()
    target=clone_database(a.database,a.output/'working.sqlite');store=RevisionStore(target,a.output/'before.sqlite')
    with store.connect() as db:
        last=db.execute("SELECT * FROM update_batches WHERE state='approved' ORDER BY created_at DESC LIMIT 1").fetchone()
        versions_before=db.execute('SELECT count(*) FROM revised_articles').fetchone()[0]
    store.rollback_batch(last['batch_id']);rolled=store.heads()==json.loads(last['before_json'])
    from datetime import date
    approved=run(a.specs,a.monitor_root,a.base_export,a.database,target,a.qa_root,a.output/'reapply',date(2026,11,1))
    repeat=run(a.specs,a.monitor_root,a.base_export,a.database,target,a.qa_root,a.output/'repeat',date(2026,11,1))
    before_fault=store.heads()
    registry=json.loads((a.qa_root/'src/verify/data/fact_keys.json').read_text(encoding='utf-8'))
    with store.connect() as db:
        record=json.loads(db.execute('SELECT record_json FROM evidence_revisions WHERE evidence_id=?',(before_fault['evidence']['tsukuba-ac-ai-faq'],)).fetchone()[0])
        aid=next(v for k,v in before_fault['articles'].items() if k.startswith(record['case_id']+':overview:'))
        article=json.loads(db.execute('SELECT record_json FROM revised_articles WHERE article_id=?',(aid,)).fetchone()[0])
    mutation=next(m for m in variants(article,record['evidence_id']) if m['case']=='invented_permission_email')
    bad=dict(article,article_id='fault-only-new-id',text=mutation['text'])
    batch=store.stage([record],registry,refresh_articles=True)
    fake_qa={'success':True,'batch_input_sha':batch['input_sha'],'articles_sha256':hashlib.sha256(canonical([bad]).encode()).hexdigest()}
    rejected=False
    try:store.finalize(batch,[bad],fake_qa,registry)
    except ValueError:rejected=True
    with store.connect() as db:
        versions_after=db.execute('SELECT count(*) FROM revised_articles').fetchone()[0]
        absent=db.execute("SELECT count(*) FROM revised_articles WHERE article_id='fault-only-new-id'").fetchone()[0]==0
    unchanged=hashlib.sha256(a.database.read_bytes()).hexdigest()==original_sha
    ok=rolled and approved['approved'] and repeat['approved'] and repeat['registered_evidence']==0 and repeat['revised_articles']==0 and rejected and absent and store.heads()==before_fault and unchanged and versions_after==versions_before+2
    result={'success':ok,'copy_only':True,'live_database_unchanged':unchanged,'rollback_success':rolled,'reapply_approved':approved['approved'],
            'repeat_registered':repeat['registered_evidence'],'repeat_articles':repeat['revised_articles'],'versions_before':versions_before,'versions_after':versions_after,
            'invented_obligation_rejected_even_with_QA_true':rejected,'heads_unchanged_after_fault':store.heads()==before_fault,
            'fake_QA_used_only_for_fault_injection':True,'not_an_independent_QA_detection':True}
    (a.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result))
    raise SystemExit(0 if ok else 1)


if __name__=='__main__':main()
