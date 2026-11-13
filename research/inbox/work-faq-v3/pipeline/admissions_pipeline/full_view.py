"""Reproducible materialized-view QA; legitimate reuse is not a new delivery."""
import argparse
import dataclasses
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
from datetime import date
from pathlib import Path
from .claude_adapter import qa_provenance
from .store import canonical
from .supplements import source_pages
from .extract import normalize


def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def raw_flip_status(detected,total,threshold=.95):
    if not total:return 'not_run'
    if not 0<=detected<=total:raise ValueError('invalid raw flip counts')
    return 'pass' if detected/total>=threshold else 'fail'


def load_json(path):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('duplicate JSON key: '+k)
            result[k]=v
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=unique)


def evidence_identity(record):
    core={k:record.get(k) for k in ('fact_key','value','university','faculty','department','admission_method','fiscal_year','scope','source_url',
         'applicability','published_date','temporal_status','source_role','parent_evidence_id','logical_id','notes','related_keys')}
    core['hash']=record.get('source_pdf_sha256') or record.get('source_sha256')
    core['kind']=record.get('source_kind','pdf')
    core['proofs']=[{**{k:p.get(k) for k in ('page','normalized_start','normalized_end','section')},'quote':normalize(p.get('quote',''))} for p in record.get('proofs',[])]
    return core


def article_identity(record):
    return {'text':record['text'].replace('\r\n','\n'),'claim':record['claim']}


def check_reuse(view,prior_exports):
    seen_e={};seen_a={};reused_e=set();reused_a=set();conflicts=[]
    article_ids=[a['article_id'] for a in view['articles']]
    if len(set(article_ids))!=len(article_ids):conflicts.append({'kind':'article','reason':'duplicate article row in active view'})
    for label,data in [*prior_exports,('active-view',view)]:
        for kind,items,seen,reused,identity in (
            ('evidence',data['evidence'].items(),seen_e,reused_e,evidence_identity),
            ('article',((a['article_id'],a) for a in data['articles']),seen_a,reused_a,article_identity)):
            for key,record in items:
                if kind=='evidence' and record.get('evidence_id',key)!=key:conflicts.append({'kind':kind,'id':key,'reason':'record id differs from map key'})
                value=identity(record)
                if key in seen:
                    if seen[key]!=value:conflicts.append({'kind':kind,'id':key,'in':label})
                    else:reused.add(key)
                else:seen[key]=value
    return {'status':'fail' if conflicts else 'pass','reused_evidence':sorted(reused_e),'reused_articles':sorted(reused_a),'conflicts':conflicts}


def article_metadata(article,evidence,reference):
    cited=sorted(set(re.findall(r'\[(EV-[A-Za-z0-9_-]+)\]',article['text'])))
    findings=[];sources=[]
    if not cited:findings.append('no_citations')
    if 'evidence_ids' in article and set(article['evidence_ids'])!=set(cited):findings.append('declared_citations_differ_from_body')
    for eid in cited:
        record=evidence.get(eid)
        if record is None:findings.append('unknown_citation:'+eid);continue
        for key in ('university','faculty','department','admission_method','fiscal_year'):
            if article['claim'].get(key)!=record.get(key):findings.append('scope_mismatch:'+key+':'+eid)
        observed=record.get('retrieved_at')
        try:
            if date.fromisoformat(observed[:10])>reference:findings.append('retrieval_in_future:'+eid)
        except (ValueError,TypeError):findings.append('retrieval_unknown_or_invalid:'+eid)
        sources.append({'evidence_id':eid,'url':record.get('source_url'),'sha256':record.get('source_pdf_sha256') or record.get('source_sha256'),
                        'retrieved_at':observed,'published_date':record.get('published_date'),'fiscal_year':record.get('fiscal_year'),'admission_method':record.get('admission_method')})
    return {'status':'fail' if findings else 'pass','findings':findings,'sources':sources}


def compare(previous,current):
    old={a['article_id']:a for a in previous.get('articles',[])};new={a['article_id']:a for a in current['articles']}
    changed=[]
    for aid in sorted(old.keys()&new.keys()):
        keys=[k for k in ('content_sha256','ok','findings','metadata','coverage') if old[aid].get(k)!=new[aid].get(k)]
        if keys:changed.append({'article_id':aid,'fields':keys})
    return {'previous_fingerprint':previous.get('fingerprint'),'current_fingerprint':current['fingerprint'],
            'added':sorted(new.keys()-old.keys()),'removed':sorted(old.keys()-new.keys()),'changed':changed,
            'conditions_changed':previous.get('conditions')!=current['conditions']}


def audit(args):
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'state.json').write_text('{"state":"running","success":false}',encoding='utf-8')
    root,commit=qa_provenance(args.qa_root);sys.path.insert(0,str(root))
    from src.integration.validate_export import validate_records
    from src.article_qa.evaluate import evaluate_article
    from src.regression.checks import evaluate_export,Thresholds
    from src.integration.audit_handoff import check_source_pdfs,check_values_in_quotes
    view=load_json(args.view)
    prior_paths=list(args.prior_export)
    if args.prior_inbox:prior_paths+=sorted(args.prior_inbox.rglob('claude-compatible-export.json'))
    prior=[(p.name,load_json(p)) for p in prior_paths if p.resolve()!=args.view.resolve()]
    registry=root/'src/verify/data/fact_keys.json'
    versions={}
    for package in ('pymupdf','pypdf','jsonschema'):
        try:versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:versions[package]='not_installed'
    conditions={'reference_date':args.reference_date.isoformat(),'scope':args.scope,'qa_commit':commit,
                'registry_sha256':hashlib.sha256(registry.read_bytes()).hexdigest(),'python':platform.python_version(),'dependencies':versions,
                'view_sha256':digest(view),'prior_exports':sorted(digest(d) for _,d in prior),'expected_evidence':args.expected_evidence,'expected_articles':args.expected_articles}
    conditions['work_code_sha256']=digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))})
    conditions['local_source_hashes']=None
    if args.bodies:
        conditions['local_source_hashes']={}
        for r in view['evidence'].values():
            sha=r.get('source_pdf_sha256') or r.get('source_sha256');suffix='.html' if r.get('source_kind')=='html' else '.pdf'
            path=args.bodies/(sha+suffix)
            conditions['local_source_hashes'][sha]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'missing'
    gate=validate_records(view['evidence']);reuse=check_reuse(view,prior);articles=[]
    for a in view['articles']:
        report=dataclasses.asdict(evaluate_article(a['article_id'],a['text'],a['claim'],view['evidence'],reference_date=args.reference_date,require_as_of=True))
        report['content_sha256']=digest(article_identity(a));report['metadata']=article_metadata(a,view['evidence'],args.reference_date)
        from src.verify.as_of import extract_as_of
        dates,_=extract_as_of(a['text']);report['metadata']['article_check_dates']=[d.isoformat() for d in dates]
        report['metadata']['timestamp_precision']='date; time of day not asserted'
        if a.get('as_of') is not None and a['as_of'] not in report['metadata']['article_check_dates']:
            report['metadata']['status']='fail';report['metadata']['findings'].append('declared_as_of_differs_from_body')
        report['ok']=report['ok'] and report['metadata']['status']=='pass';articles.append(report)
    regression=evaluate_export('active-view',view)
    flip_detected,flip_total=regression['mutation']['flip']
    flip_unverified=regression['mutation'].get('flip_declared_unverified')
    raw_flip={'detected':flip_detected,'total':flip_total,'declared_unverified':flip_unverified,
              'silent_misses':None if flip_unverified is None else flip_total-flip_detected-flip_unverified,
              'threshold':Thresholds().flip_detection_min,'status':raw_flip_status(flip_detected,flip_total,Thresholds().flip_detection_min)}
    counts_ok=len(view['evidence'])==args.expected_evidence and len(articles)==args.expected_articles
    checks={'counts':'pass' if counts_ok else 'fail','ids':reuse['status'],'schema':'pass' if gate['invalid_count']==0 else 'fail',
            'articles':'pass' if articles and all(a['ok'] for a in articles) else 'fail','regression':'pass' if regression['ok'] else 'fail',
            'raw_sources':'not_run'}
    checks['meaning_flip_raw']=raw_flip['status']
    sources={'status':'not_run','reason':'raw originals not supplied; not counted as a successful original audit'}
    if args.bodies:
        pdf={'evidence':{k:r for k,r in view['evidence'].items() if r.get('source_kind')!='html'},'articles':[]}
        pdf_result=check_source_pdfs(pdf,args.bodies);html=[]
        for eid,r in view['evidence'].items():
            if r.get('source_kind')!='html':continue
            sha=r['source_sha256'];ok=False
            try:
                pages=source_pages({'kind':'html','url':r['source_url'],'sha256':sha,'local_path':str(args.bodies/(sha+'.html'))})
                ok=bool(r.get('proofs')) and all(p['page']==1 and normalize(pages[0])[p['normalized_start']:p['normalized_end']]==normalize(p['quote']) for p in r['proofs'])
            except (OSError,ValueError,KeyError):pass
            html.append({'evidence_id':eid,'exact_hash_quote_positions':ok})
        values=check_values_in_quotes(view)
        sources={'status':'pass' if pdf_result['status']=='pass' and all(r['exact_hash_quote_positions'] for r in html) and values['status']=='pass' else 'fail',
                 'pdf_independent':pdf_result,'html_Work_exact_check':html,'values':values,'html_semantic_independent':'not_run'}
        checks['raw_sources']=sources['status']
    required=['counts','ids','schema','articles','regression','meaning_flip_raw']+(['raw_sources'] if args.scope=='full' else [])
    summary={'passed':sum(v=='pass' for v in checks.values()),'failed':sum(v=='fail' for v in checks.values()),'not_run':sum(v=='not_run' for v in checks.values()),
             'required_in_scope':required,'passed_in_scope':all(checks[k]=='pass' for k in required),'all_semantics_verified':False,
             'semantic_unverified':sum(a.get('coverage',{}).get('counts',{}).get('unverified',0) for a in articles),
             'execution':args.execution_origin}
    report={'conditions':conditions,'fingerprint':digest(conditions),'summary':summary,'checks':checks,'reuse':reuse,'gate':gate,'articles':articles,'regression':regression,'sources':sources,'raw_meaning_flip':raw_flip}
    if args.previous:report['delta']=compare(json.loads(args.previous.read_text(encoding='utf-8')),report)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 全体ビュー回帰検査',f"実行範囲: {args.scope} / QA: {commit}",f"範囲内合格: {summary['passed_in_scope']} / 不合格: {summary['failed']} / 未実施: {summary['not_run']}",
           '未検証の意味・原典の最新性・公開可否を合格と扱わない。','', '| 記事ID | QA | 年度/方式/取得日 | 未検証意味項目 |','|---|---|---|---|']
    for a in articles:lines.append(f"| {a['article_id']} | {'pass' if a['ok'] else 'fail'} | {a['metadata']['status']} | {a.get('coverage',{}).get('counts',{}).get('unverified',0)} |")
    (args.output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (args.output/'state.json').write_text(json.dumps({'state':'completed','passed_in_scope':summary['passed_in_scope']}),encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser()
    for key in ('view','qa-root','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--reference-date',type=date.fromisoformat,required=True);p.add_argument('--prior-export',type=Path,action='append',default=[])
    p.add_argument('--previous',type=Path);p.add_argument('--prior-inbox',type=Path);p.add_argument('--bodies',type=Path);p.add_argument('--scope',choices=('export','full'),default='export')
    p.add_argument('--expected-evidence',type=int,default=50);p.add_argument('--expected-articles',type=int,default=13)
    p.add_argument('--execution-origin',choices=('work-local','github-ci'),default='work-local')
    args=p.parse_args()
    if args.output.exists():p.error('use a fresh output directory')
    try:report=audit(args)
    except Exception as exc:
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'state.json').write_text(json.dumps({'state':'error','success':False,'error_type':type(exc).__name__}),encoding='utf-8')
        raise
    print(json.dumps(report['summary'],ensure_ascii=False))
    raise SystemExit(0 if report['summary']['passed_in_scope'] else 1)


if __name__=='__main__':main()
