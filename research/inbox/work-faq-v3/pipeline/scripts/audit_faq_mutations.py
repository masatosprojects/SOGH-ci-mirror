"""Independent Claude QA on old/new data using the SAME pinned QA and date."""
import argparse
import dataclasses
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from admissions_pipeline.claude_adapter import qa_provenance
from admissions_pipeline.faq_mutations import variants,classify


def main():
    p=argparse.ArgumentParser()
    for key in ('before','after','qa-root','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();qa,commit=qa_provenance(a.qa_root);sys.path.insert(0,str(qa))
    from src.article_qa.evaluate import evaluate_article
    from src.article_qa.flip_sweep import flip_sweep
    from src.verify.fact_registry import get_registry
    a.output.mkdir(parents=True,exist_ok=False);results={}
    for label,path in (('before',a.before),('after',a.after)):
        data=json.loads(path.read_text(encoding='utf-8'));eid=next(k for k,r in data['evidence'].items() if r.get('logical_id')=='tsukuba-ac-ai-faq')
        articles=[x for x in data['articles'] if '['+eid+']' in x['text']];rows=[];positives=[]
        for article in articles:
            positive=evaluate_article(article['article_id'],article['text'],article['claim'],data['evidence'],reference_date='2026-11-01',require_as_of=True)
            positives.append(dataclasses.asdict(positive))
            for mutation in variants(article,eid):
                negative=evaluate_article(article['article_id'],mutation['text'],article['claim'],data['evidence'],reference_date='2026-11-01',require_as_of=True)
                status=classify(positive,negative,mutation,eid)
                rows.append({'article_id':article['article_id'],'case':mutation['case'],'status':status,'findings':negative.findings,'coverage':negative.coverage})
        counts={s:sum(r['status']==s for r in rows) for s in ('detected','unverified_only','silent_miss','not_evaluable')}
        counts['false_positive_articles']=sum(not x['ok'] for x in positives)
        results[label]={'counts':counts,'targeted_mutations':rows,'positive_articles':positives,
                       'whole_view_flip':flip_sweep(data,reference_date='2026-11-01',require_as_of=True)}
    report={'qa_commit':commit,'registry_version':get_registry().version,'reference_date':'2026-11-01',
            'same_checker_for_before_after':True,'unverified_is_not_detection':True,'results':results}
    (a.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'qa_commit':commit,'results':{k:{'counts':v['counts'],'whole_flip':[v['whole_view_flip']['detected'],v['whole_view_flip']['instances']]} for k,v in results.items()}}))


if __name__=='__main__':main()
