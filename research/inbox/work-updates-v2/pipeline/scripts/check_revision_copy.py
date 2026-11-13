"""Fault injection on a NEW DB copy, actual Claude quote gate, never the live DB."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from admissions_pipeline.revisions import RevisionStore,clone_database
from admissions_pipeline.claude_adapter import run_quote_gate,qa_provenance


def main():
    p=argparse.ArgumentParser()
    for key in ('database','view','qa-root','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);qa,commit=qa_provenance(a.qa_root)
    registry=json.loads((qa/'src/verify/data/fact_keys.json').read_text(encoding='utf-8'))
    copy=clone_database(a.database,a.output/'working-copy.sqlite');store=RevisionStore(copy,a.output/'before.sqlite');before=store.heads()
    view=json.loads(a.view.read_text(encoding='utf-8'))
    record=next(r for r in view['evidence'].values() if r.get('logical_id')=='tsukuba-general-quota-proof')
    record=dict(record,evidence_id='EV-U-negative-copy',logical_id='negative-quota-test',value={'count':999999},sentences=['募集人数は999999名です。'])
    batch=store.stage([record],registry);export=a.output/'negative-export.json'
    export.write_text(json.dumps({'evidence':{record['evidence_id']:record},'articles':[]},ensure_ascii=False),encoding='utf-8')
    gate=run_quote_gate(qa,export,a.output/'quote-gate.json')
    rejected=not store.finalize(batch,[],{'success':gate['success']},registry)
    with store.connect() as db:
        old=db.execute("SELECT value_json FROM facts WHERE evidence_id='EV-G27-01-e1137e'").fetchone()
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    result={'success':not gate['success'] and rejected and store.heads()==before and json.loads(old[0])['count']==16 and integrity=='ok',
            'synthetic_on_real_db_copy':True,'injected_value':999999,'original_value':16,'qa_commit':commit,'heads_unchanged':store.heads()==before,
            'live_database_written':False,'quote_gate':gate}
    (a.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'success':result['success'],'heads_unchanged':result['heads_unchanged']}))
    raise SystemExit(0 if result['success'] else 1)


if __name__=='__main__':main()
