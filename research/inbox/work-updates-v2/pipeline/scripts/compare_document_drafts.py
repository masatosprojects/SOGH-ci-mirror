"""Source-bound differentiation proposal only; no DB activation or publication."""
import argparse
import difflib
import json
import sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from admissions_pipeline.profiles import extract_profile,load_profile
from admissions_pipeline.generic import draft
from admissions_pipeline.store import canonical


def main():
    p=argparse.ArgumentParser();p.add_argument('--bodies',type=Path,required=True);p.add_argument('--view',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False);view=json.loads(args.view.read_text(encoding='utf-8'))
    results=[];proposals=[];previous=[];shared_values=[]
    for filename in ('niigata-law-recommendation-2027.json','niigata-humanities-recommendation-2027.json'):
        profile=load_profile(ROOT/'config/profiles'/filename);path=args.bodies/(profile['sha256']+'.pdf')
        source=extract_profile(profile,path);profile['article_policy']={'documents':{'fact_keys':['quota','common_test','interview_scope','interview','postal_period'],'shared_fact_keys':['postal_period']}}
        pack={'cycle':{k:profile[k] for k in ('university','faculty','department','admission_method','fiscal_year','exam_year')},
              'source':{'local_path':str(path),'sha256':profile['sha256'],'url':profile['url']},'facts':sorted(source.facts,key=lambda f:f['evidence_id'])}
        article=draft(pack,profile,'documents',date(2026,11,1));proposals.append(article)
        old=next(a for a in view['articles'] if a['article_id'].startswith(profile['case_id']+':documents:'));previous.append(old)
        shared_values.append(next(f['value'] for f in source.facts if f['key']=='postal_period'))
        (args.output/(profile['code']+'-documents.md')).write_text(article['text'],encoding='utf-8')
        results.append({'case_id':profile['case_id'],'base_article_id':old['article_id'],'candidate_article_id':article['article_id'],
                        'distinct_official_keys':['quota','common_test','interview_scope','interview'],'shared_official_keys':['postal_period'],
                        'advice':'existing generic advice, separately labeled; no new university claims','unconfirmed':'full required document list, personal eligibility, later changes',
                        'activation':False})
    if canonical(shared_values[0])!=canonical(shared_values[1]):raise ValueError('postal procedure is not actually shared')
    ratio=lambda articles:round(difflib.SequenceMatcher(None,articles[0]['text'],articles[1]['text'],autojunk=False).ratio(),4)
    report={'prior_similarity':ratio(previous),'proposed_similarity':ratio(proposals),'similarity_is_not_a_quality_gate':True,'results':results,
            'publication_allowed':False,'main_active_view_changed':False}
    (args.output/'proposal.json').write_text(json.dumps({'articles':proposals,'analysis':report},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
