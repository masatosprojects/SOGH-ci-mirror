"""Pending-contract preview only. No head activation or original DB writes."""
import argparse
import copy
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.revisions import RevisionStore
from admissions_pipeline.store import canonical


def main():
    p=argparse.ArgumentParser()
    for key in ('candidate','database','base-export','current-view','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);record=json.loads(a.candidate.read_text(encoding='utf-8'))
    before=json.loads(a.current_view.read_text(encoding='utf-8'));originals=json.loads(a.base_export.read_text(encoding='utf-8'))
    store=RevisionStore(a.database,a.output/'before.sqlite');heads=store.heads();preview=copy.deepcopy(heads)
    preview['evidence'][record['logical_id']]=record['evidence_id'];effective=store.effective_records({'after':preview})
    articles=[]
    with store.connect() as db:
        for article in originals['articles']:
            native=db.execute('SELECT * FROM article_versions WHERE article_id=?',(article['article_id'],)).fetchone()
            if native['case_id']!=record['case_id']:continue
            article.update(case_id=native['case_id'],series=native['series'],evidence_ids=sorted(set(re.findall(r'\[(EV-[A-Za-z0-9_-]+)\]',article['text']))))
            revised=revise_article(article,effective,date(2026,11,1),heads['articles'].get(article['article_id']))
            articles.append(revised);(a.output/(article['series']+'.md')).write_text(revised['text'],encoding='utf-8')
    view=copy.deepcopy(before);view['evidence'].pop(record['parent_evidence_id'],None);view['evidence'][record['evidence_id']]=record
    bases={x['base_article_id'] for x in articles}
    view['articles']=[x for x in view['articles'] if x.get('base_article_id',x['article_id']) not in bases]+articles
    view['approval_state']='candidate_pending_contract'
    (a.output/'candidate-state.json').write_text(json.dumps(view,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'approved':False,'head_activation':False,'candidate_articles':len(articles),'facts':len(view['evidence']),'articles':len(view['articles']),
            'original_heads_unchanged':store.heads()==heads,'old_evidence_id':record['parent_evidence_id'],'candidate_evidence_id':record['evidence_id']}
    (a.output/'preview-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':main()
