"""Execute pinned Claude audit code as Work; never claim independent execution."""
import argparse
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    for name in ('qa-root', 'copies', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    sys.path.insert(0, str(a.qa_root.resolve()))
    from src.integration.db_audit import audit, copy_identity
    a.output.mkdir(parents=True, exist_ok=False)
    result = []
    for label in ('v02', 'v03', 'v04', 'v05', 'v06'):
        path = a.copies / (label + '.sqlite')
        report = audit(path, baseline=a.copies / 'v05.sqlite' if label == 'v06' else None,
                       target_kind='copied_real_db', expect_sha256=copy_identity(path)['sha256'])
        report['execution_actor'] = 'Work executing pinned Claude code; not Claude independent execution'
        report['qa_commit'] = json.loads((a.qa_root / 'QA_PROVENANCE.json').read_text(encoding='utf-8'))['commit']
        (a.output / (label + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        result.append({'label': label, 'ok': report['ok'], 'lineage': report['lineage'], 'summary': report['summary']})
    (a.output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
