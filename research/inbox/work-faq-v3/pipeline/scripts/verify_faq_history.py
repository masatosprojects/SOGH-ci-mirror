"""Read-only old/new preservation audit; mutable heads are changes, not missing history."""
import argparse
import difflib
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    for key in ('before-db','after-db','before-view','after-view','baseline','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    baseline=json.loads(a.baseline.read_text(encoding='utf-8'));before=json.loads(a.before_view.read_text(encoding='utf-8'));after=json.loads(a.after_view.read_text(encoding='utf-8'))
    losses=[];head_changes={};illegal_states=[];checked=[]
    with closing(sqlite3.connect(a.before_db.resolve().as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(a.after_db.resolve().as_uri()+'?mode=ro',uri=True)) as new:
        old.row_factory=new.row_factory=sqlite3.Row;old.execute('BEGIN');new.execute('BEGIN')
        for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            q='"'+table.replace('"','""')+'"'
            if table in ('evidence_heads','article_heads'):
                b=dict(old.execute('SELECT * FROM '+q));c=dict(new.execute('SELECT * FROM '+q))
                head_changes[table]=[{'key':k,'before':b.get(k),'after':c.get(k)} for k in sorted(b.keys()|c.keys()) if b.get(k)!=c.get(k)];continue
            if table=='update_batches':
                cols='batch_id,input_sha,created_at,before_json,registry_sha'
                if not set(map(tuple,old.execute('SELECT '+cols+' FROM '+q)))<=set(map(tuple,new.execute('SELECT '+cols+' FROM '+q))):losses.append('update_batch_identity')
                for r in old.execute('SELECT * FROM update_batches'):
                    current=new.execute('SELECT * FROM update_batches WHERE batch_id=?',(r['batch_id'],)).fetchone()
                    if not current:illegal_states.append(r['batch_id']);continue
                    if r['state']=='candidate' and current['state']=='interrupted':continue
                    if tuple(r)!=tuple(current):illegal_states.append(r['batch_id'])
                continue
            checked.append(table)
            if not set(map(tuple,old.execute('SELECT * FROM '+q)))<=set(map(tuple,new.execute('SELECT * FROM '+q))):losses.append(table)
        evidence_changes=head_changes['evidence_heads'];article_changes=head_changes['article_heads']
        lineage=True
        for h in evidence_changes:
            row=new.execute('SELECT parent_evidence_id FROM evidence_revisions WHERE evidence_id=?',(h['after'],)).fetchone()
            lineage=lineage and bool(row) and row[0]==h['before']
        for h in article_changes:
            row=new.execute('SELECT record_json FROM revised_articles WHERE article_id=?',(h['after'],)).fetchone()
            r=json.loads(row[0]) if row else {};lineage=lineage and r.get('parent_article_id')==h['before'] and r.get('case_id')=='tsukuba-klis-ac-2027'
        integrity=new.execute('PRAGMA integrity_check').fetchone()[0];foreign=list(new.execute('PRAGMA foreign_key_check'))
        revisions=new.execute('SELECT count(*) FROM revised_articles').fetchone()[0]
    articles_before={r.get('base_article_id',r['article_id']):r for r in before['articles']};articles_after={r.get('base_article_id',r['article_id']):r for r in after['articles']}
    diffs=[];unchanged=[]
    for key in articles_before:
        b=articles_before[key];c=articles_after[key]
        if b==c:unchanged.append(b['article_id']);continue
        name='article-'+str(len(diffs)+1)+'.diff'
        (a.output/name).write_text(''.join(difflib.unified_diff(b['text'].splitlines(True),c['text'].splitlines(True),fromfile=b['article_id'],tofile=c['article_id'])),encoding='utf-8')
        diffs.append({'base_article_id':key,'before':b['article_id'],'after':c['article_id'],'diff':name})
    original_unchanged=hashlib.sha256(a.before_db.read_bytes()).hexdigest()==baseline['original_v05_sha256']
    view_unchanged=hashlib.sha256(a.before_view.read_bytes()).hexdigest()==baseline['view_sha256']
    ok=(not losses and not illegal_states and original_unchanged and view_unchanged and lineage and integrity=='ok' and not foreign
        and len(evidence_changes)==1 and evidence_changes[0]['key']=='tsukuba-ac-ai-faq' and len(article_changes)==2 and len(unchanged)==11
        and len(after['evidence'])==50 and len(after['articles'])==13)
    report={'success':ok,'original_v05_sha_unchanged':original_unchanged,'original_view_sha_unchanged':view_unchanged,'immutable_tables_checked':checked,'old_rows_missing_or_changed':losses,
            'illegal_batch_changes':illegal_states,'head_changes':head_changes,'lineage_ok':lineage,'article_diffs':diffs,'unchanged_articles':unchanged,
            'effective_facts':len(after['evidence']),'current_articles':len(after['articles']),'retained_article_versions':revisions,'integrity':integrity,'foreign_key_errors':len(foreign)}
    (a.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:report[k] for k in ('success','original_v05_sha_unchanged','old_rows_missing_or_changed','retained_article_versions')}))
    raise SystemExit(0 if ok else 1)


if __name__=='__main__':main()
