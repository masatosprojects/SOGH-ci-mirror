"""Offline real-Claude SourceSnapshot -> diff -> impacted article integration smoke."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from admissions_pipeline.collector import Collector
from admissions_pipeline.monitor import Monitor
from admissions_pipeline.claude_adapter import qa_provenance


class LocalBodies:
    write_snapshot=Collector.write_snapshot
    def __init__(self,root):self.root=root;self.body=b'<p>quota 5</p>';root.mkdir(parents=True)
    def fetch(self,url):
        sha=hashlib.sha256(self.body).hexdigest();path=self.root/(sha+'.html');path.write_bytes(self.body)
        return {'url':url,'sha256':sha,'kind':'html','local_path':str(path),'retrieved_at':'2026-11-01T00:00:00Z'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--qa-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();qa,commit=qa_provenance(args.qa_root);args.output.mkdir(parents=True,exist_ok=False)
    collector=LocalBodies(args.output/'bodies');sha=hashlib.sha256(collector.body).hexdigest();url='https://fixture.ac.jp/guide'
    claim={'university':'検査大学','faculty':'検査学部','department':None,'admission_method':'一般選抜','fiscal_year':2027}
    ev={'evidence_id':'EV-FIX-1','fact_key':'quota','value':{'count':5},**claim,'scope':'target_admission_cycle','source_kind':'html','source_pdf_sha256':None,
        'source_sha256':sha,'source_url':url,'retrieved_at':'2026-11-01','proofs':[{'page':1,'quote':'quota 5'}]}
    export=args.output/'input.json';export.write_text(json.dumps({'evidence':{'EV-FIX-1':ev},'articles':[{'article_id':'fixture-article','claim':claim,'text':'募集人数5名[EV-FIX-1]。'}]}),encoding='utf-8')
    config={'allowed_hosts':['fixture.ac.jp'],'interval_seconds':60,'targets':[{'url':url,'source_id':'fixture-guide','case':'fixture','role':'guide'}]}
    monitor=Monitor(args.output/'state',config,collector=collector)
    first=monitor.run_once(True,export,qa)
    collector.body=b'<script>nonce 123</script><p>quota 5</p>'
    byte=monitor.run_once(True,export,qa)
    collector.body=b'<p>quota 6</p>'
    changed=monitor.run_once(True,export,qa)
    previous=changed['results'][0]['sha256'];config['targets'][0].update(url='https://fixture.ac.jp/moved',supersedes_sha256=[sha,previous])
    moved=monitor.run_once(True,export,qa)
    ok=(first['versioning']['summary']['evidence_intact']==1 and byte['versioning']['source_differences'][0]['change_class']=='byte_only'
        and changed['versioning']['republish_required']==['fixture-article'] and moved['results'][0]['source_id']=='fixture-guide'
        and moved['versioning']['republish_required']==['fixture-article'])
    result={'success':ok,'qa_commit':commit,'synthetic':True,'network_requests':0,'source_id':'fixture-guide','evidence_id':'EV-FIX-1','article_id':'fixture-article',
            'initial':first['versioning'],'byte_only':byte['versioning'],'value_changed':changed['versioning'],'moved_url':moved['versioning']}
    (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'success':ok,'network_requests':0}))
    raise SystemExit(0 if ok else 1)


if __name__=='__main__':main()
