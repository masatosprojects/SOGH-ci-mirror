"""Use one atomic QA batch per admissions cycle, reporting every failure/pending item."""
import argparse
import json
import re
from datetime import date
from pathlib import Path
from revise_notices import run


def main():
    p=argparse.ArgumentParser()
    for key in ('specs','monitor-root','base-export','base-db','work-db','qa-root','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--refresh-articles',action='store_true');p.add_argument('--as-of',type=date.fromisoformat,default=date.today())
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    grouped={}
    for record in json.loads(args.specs.read_text(encoding='utf-8')):grouped.setdefault(record['case_id'],[]).append(record)
    results=[]
    for case,records in grouped.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+',case):raise ValueError('unsafe case id')
        spec=args.output/(case+'.config.json');spec.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        try:
            report=run(spec,args.monitor_root,args.base_export,args.base_db,args.work_db,args.qa_root,args.output/case,args.as_of,args.refresh_articles)
            results.append({'case_id':case,**report})
        except Exception as exc:
            results.append({'case_id':case,'approved':False,'error':type(exc).__name__})
    summary={'success':all(r['approved'] and not r.get('pending_contract') and not r.get('source_review_pending') for r in results),
             'new_evidence':sum(r.get('registered_evidence',0) for r in results),'revised_articles':sum(r.get('revised_articles',0) for r in results),
             'results':results,'publication_allowed':False}
    (args.output/'batch-report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('success','new_evidence','revised_articles')},ensure_ascii=False))
    raise SystemExit(0 if summary['success'] else 1)


if __name__=='__main__':main()
