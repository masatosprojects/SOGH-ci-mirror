"""Historical comparison without changing or excusing any lost row."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def fingerprint(row):
    return hashlib.sha256(json.dumps(list(row), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    for key in ('copies', 'qa-root', 'output'):
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(a.qa_root.resolve()))
    from src.integration.db_audit import audit, APPEND_ONLY
    old_path, new_path = a.copies / 'v03.sqlite', a.copies / 'v04.sqlite'
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (old_path, new_path)}
    raw = audit(new_path, baseline=old_path, target_kind='copied_real_db')
    (a.output / 'v04-baseline-v03.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
    differences = []
    with closing(sqlite3.connect(old_path.resolve().as_uri() + '?mode=ro', uri=True)) as old, closing(sqlite3.connect(new_path.resolve().as_uri() + '?mode=ro', uri=True)) as new:
        tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        new_tables = {r[0] for r in new.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in sorted(tables & new_tables):
            info = list(old.execute('PRAGMA table_info("' + table + '")'))
            columns = [r[1] for r in info]; pk = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
            before = list(old.execute('SELECT * FROM "' + table + '"')); after = list(new.execute('SELECT * FROM "' + table + '"'))
            remaining = set(after); after_by_pk = {tuple(r[columns.index(k)] for k in pk): r for r in after}
            changed = []
            for row in before:
                if row in remaining:
                    continue
                identity = tuple(row[columns.index(k)] for k in pk)
                current = after_by_pk.get(identity)
                item = {'key': dict(zip(pk, identity)), 'old_row_sha256': fingerprint(row), 'kind': 'changed' if current else 'missing'}
                if current:
                    item['new_row_sha256'] = fingerprint(current)
                    item['changed_columns'] = [k for k, b, c in zip(columns, row, current) if b != c]
                    json_diff = {}
                    for k in ('record_json', 'value_json'):
                        if k not in item['changed_columns']:
                            continue
                        b = json.loads(row[columns.index(k)]); c = json.loads(current[columns.index(k)])
                        json_diff[k] = {'removed_keys': sorted(b.keys() - c.keys()), 'added_keys': sorted(c.keys() - b.keys()),
                                        'changed_keys': sorted(k for k in b.keys() & c.keys() if b[k] != c[k])}
                    if json_diff:
                        item['json_key_diff'] = json_diff
                changed.append(item)
            if changed:
                differences.append({'table': table, 'old_rows_missing_or_changed': len(changed), 'rows': changed})
    preserved = hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (old_path, new_path)}
    report = {'target_kind': 'copied_real_db', 'actor': 'Work executing unchanged Claude audit and separate row comparison',
              'row_comparison_scope': 'all common user tables; DB09 itself covers its documented append-only subset',
              'DB09_status': raw['invariants']['DB-09']['status'], 'copy_files_unchanged': preserved,
              'differences': differences, 'execution_cause': 'not_confirmed_from_current_code_or_saved_history',
              'historical_missing_rows_were_not_repaired_or_relabelled': True,
              'old_v03_is_still_preserved_separately': True, 'append_only_migration_claim': False}
    (a.output / 'F2-history-diff.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'DB09': report['DB09_status'], 'tables': [(d['table'], d['old_rows_missing_or_changed']) for d in differences], 'copies_unchanged': preserved}))


if __name__ == '__main__':
    main()
