"""Consume the agreed Claude versioning API. Never publish full snapshots."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--collab", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--export", dest="exports", type=Path, action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    code = '''
import json,sys
from pathlib import Path
from src.versioning.snapshot import load_snapshot,snapshot_from_pdf,save_snapshot
from src.versioning.diff import diff_snapshots
from src.versioning.impact import assess_export,exit_code
audit,sources,output=map(Path,sys.argv[1:4])
new=[load_snapshot(Path(p)) for p in json.loads((audit/'snapshot-paths.json').read_text(encoding='utf-8'))]
export={'evidence':{},'articles':[]}
for path in sys.argv[4:]:
 e=json.loads(Path(path).read_text(encoding='utf-8'));export['evidence'].update(e['evidence']);export['articles'].extend(e['articles'])
old=[];diffs=[]
for sha in sorted({r['source_pdf_sha256'] for r in export['evidence'].values()}):
 path=sources/(sha+'.pdf')
 if not path.exists():continue
 current=next(s for s in new if s.sha256==sha)
 snapshot=snapshot_from_pdf(path,current.source_id,current.url,'2026-11-01')
 save_snapshot(snapshot,output/(sha+'.old.snapshot.json'));old.append(snapshot)
 diffs.append({'sha256':sha,'result':diff_snapshots(snapshot,current).to_dict()})
report=assess_export(export,new,old)
(output/'version-impact-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(output/'pdf-version-diff.json').write_text(json.dumps(diffs,ensure_ascii=False,indent=2),encoding='utf-8')
(output/'snapshot-manifest.json').write_text(json.dumps([{'source_id':s.source_id,'url':s.url,'sha256':s.sha256,'retrieved_at':s.retrieved_at,'page_count':len(s.pages)} for s in new],ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'summary':report['summary'],'existing_pdf_comparisons':len(diffs),'same_saved_pdf_text':all(d['result']['identical_text'] for d in diffs)},ensure_ascii=False))
raise SystemExit(exit_code(report,True))
'''
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(args.audit.resolve()),
                             str(args.sources.resolve()), str(args.output.resolve()), *[str(p.resolve()) for p in args.exports]],
                            cwd=args.collab, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=120)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
