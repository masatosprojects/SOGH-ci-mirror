"""Read-only final audit: Claude PDF/value gates, exact HTML positions, old DB preservation."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from admissions_pipeline.supplements import source_pages
from admissions_pipeline.extract import normalize


def main():
    p=argparse.ArgumentParser()
    for key in ('export','bodies','database','baseline','qa-root','output'):p.add_argument('--'+key,type=Path,required=True)
    args=p.parse_args();sys.path.insert(0,str(args.qa_root.resolve()))
    from src.integration.audit_handoff import check_source_pdfs,check_values_in_quotes,check_export
    data=json.loads(args.export.read_text(encoding='utf-8'))
    pdfs={'evidence':{k:v for k,v in data['evidence'].items() if v.get('source_kind')!='html'},'articles':data['articles']}
    pdf=check_source_pdfs(pdfs,args.bodies);values=check_values_in_quotes(data);articles=check_export(data)
    html=[]
    for eid,r in data['evidence'].items():
        if r.get('source_kind')!='html':continue
        record={'sha256':r['source_sha256'],'local_path':str(args.bodies/(r['source_sha256']+'.html')),'kind':'html','url':r['source_url']}
        pages=source_pages(record);valid=True
        for proof in r['proofs']:
            if proof['page']!=1:valid=False;continue
            text=normalize(pages[0]);quote=normalize(proof['quote'])
            valid=valid and quote in text and text[proof['normalized_start']:proof['normalized_end']]==quote
        html.append({'evidence_id':eid,'hash_and_exact_positions_match':valid,'source_url':r['source_url']})
    missing=[]
    with closing(sqlite3.connect(args.baseline.resolve().as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True)) as current:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            q='"'+table.replace('"','""')+'"';cols=[r[1] for r in old.execute('PRAGMA table_info('+q+')')];selected=','.join('"'+c.replace('"','""')+'"' for c in cols)
            if not set(old.execute('SELECT '+selected+' FROM '+q))<=set(current.execute('SELECT '+selected+' FROM '+q)):missing.append(table)
        integrity=current.execute('PRAGMA integrity_check').fetchall();foreign=current.execute('PRAGMA foreign_key_check').fetchall()
        counts={'native_facts':current.execute('SELECT count(*) FROM facts').fetchone()[0],
                'active_update_heads':current.execute('SELECT count(*) FROM evidence_heads').fetchone()[0],
                'revised_original_articles':current.execute('SELECT count(*) FROM article_heads').fetchone()[0],
                'revision_history_versions':current.execute('SELECT count(*) FROM revised_articles').fetchone()[0]}
    report={'success':pdf['status']=='pass' and values['status']=='pass' and articles['status']=='pass' and all(r['hash_and_exact_positions_match'] for r in html) and not missing and integrity==[('ok',)] and not foreign,
            'pdf':pdf,'html':{'method':'Work byte hash + normalized exact quote/position check; not a PDF audit','records':html},
            'values':values,'articles':articles,'baseline_tables_checked':len(tables),'old_rows_missing_or_modified':missing,
            'baseline_sha256':hashlib.sha256(args.baseline.read_bytes()).hexdigest(),'integrity':integrity,'foreign_keys':foreign,
            'counts':counts,'effective_facts':len(data['evidence']),'current_articles':len(data['articles'])}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('success','counts','effective_facts','current_articles','old_rows_missing_or_modified')},ensure_ascii=False))
    raise SystemExit(0 if report['success'] else 1)


if __name__=='__main__':main()
