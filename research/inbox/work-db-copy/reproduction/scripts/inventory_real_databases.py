"""W-03: read-only SQLite online copies and text-only, non-value inventory.

Never migrates a source. Copies contain real data and stay outside the handoff.
"""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1 << 20), b''):
            h.update(part)
    return h.hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def connect(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    db.execute('PRAGMA query_only=ON')
    return db


def tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def rows_digest(db, table):
    hashes = []
    for row in db.execute('SELECT * FROM ' + quote(table)):
        normalized = [{'blob_hex': v.hex()} if isinstance(v, bytes) else v for v in row]
        hashes.append(hashlib.sha256(json.dumps(normalized, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest())
    return hashlib.sha256('\n'.join(sorted(hashes)).encode()).hexdigest()


PATTERNS = {
    'credential_pattern': re.compile(r'(?i)(?:gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|AIza[a-z0-9_-]{30,}|sk-[a-z0-9]{20,}|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY)'),
    'secret_assignment': re.compile(r'(?i)\b(?:api[_-]?key|password|cookie|access_token)\s*[=:]\s*[\"\x27]?\w{8,}'),
    'email': re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),
    'user_path': re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"\x27]+'),
}


def privacy(db):
    hits = []; scanned = 0; blobs = 0
    for table in tables(db):
        cols = [r[1] for r in db.execute('PRAGMA table_info(' + quote(table) + ')')]
        counts = {}
        for row in db.execute('SELECT * FROM ' + quote(table)):
            for col, value in zip(cols, row):
                if isinstance(value, bytes):
                    blobs += 1
                    continue
                if not isinstance(value, str):
                    continue
                scanned += 1
                for category, pattern in PATTERNS.items():
                    if pattern.search(value):
                        counts[col, category] = counts.get((col, category), 0) + 1
        hits += [{'table': table, 'column': col, 'category': cat, 'cells': n} for (col, cat), n in sorted(counts.items())]
    return {'text_cells_scanned': scanned, 'binary_cells_not_text_scanned': blobs, 'findings': hits,
            'values_disclosed': False, 'database_upload_allowed': False,
            'scope': 'pattern scan; absence of all personal information is not proven'}


def sidecars(path):
    return {suffix: {'exists': Path(str(path) + suffix).exists(),
                     'sha256': sha(Path(str(path) + suffix)) if Path(str(path) + suffix).is_file() else None}
            for suffix in ('-wal', '-shm')}


def inspect(label, source, copies, output):
    final_target = copies / (label + '.sqlite')
    target = final_target.with_name(final_target.name + '.partial')
    if final_target.exists() or target.exists():
        raise FileExistsError('refusing to overwrite an audit copy')
    before = sha(source); before_sidecars = sidecars(source)
    started = datetime.now(timezone.utc).isoformat()
    with closing(connect(source)) as src:
        src.execute('BEGIN')
        names = tables(src)
        source_digests = {t: rows_digest(src, t) for t in names}
        estimated = src.execute('PRAGMA page_count').fetchone()[0] * src.execute('PRAGMA page_size').fetchone()[0]
        if shutil.disk_usage(copies).free < estimated + 10 * 1024 * 1024:
            raise OSError('insufficient free space for online copy')
        try:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=128, sleep=0.01)
        except BaseException as exc:
            output.mkdir(parents=True, exist_ok=True)
            (output / 'copy_failure.json').write_text(json.dumps({'copy_valid': False, 'phase': 'online_backup',
                'error_type': type(exc).__name__, 'partial_file': target.name, 'final_file_created': False}), encoding='utf-8')
            raise
        src.rollback()
    with closing(connect(target)) as db:
        metadata = {}; counts = {}
        for table in tables(db):
            cols = [dict(zip(('cid', 'name', 'type', 'notnull', 'default', 'pk'), r)) for r in db.execute('PRAGMA table_info(' + quote(table) + ')')]
            indexes = []
            for row in db.execute('PRAGMA index_list(' + quote(table) + ')'):
                indexes.append({'name': row[1], 'unique': bool(row[2]), 'origin': row[3], 'partial': bool(row[4]),
                                'columns': [r[2] for r in db.execute('PRAGMA index_info(' + quote(row[1]) + ')')]})
            ddl = db.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone()[0]
            metadata[table] = {'columns': cols, 'foreign_keys': list(db.execute('PRAGMA foreign_key_list(' + quote(table) + ')')),
                               'indexes': indexes, 'has_check_constraint': bool(re.search(r'\bCHECK\s*\(', ddl or '', re.I))}
            counts[table] = db.execute('SELECT count(*) FROM ' + quote(table)).fetchone()[0]
        objects = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name"))
        ddl = '\n\n'.join(r[3].rstrip(';') + ';' for r in objects) + '\n'
        integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
        fk_errors = list(db.execute('PRAGMA foreign_key_check'))
        identical = source_digests == {t: rows_digest(db, t) for t in tables(db)}
        lineage = {}
        wanted = {'evidence_heads': ('logical_id', 'evidence_id'), 'article_heads': ('base_article_id', 'article_id'),
                  'evidence_revisions': ('evidence_id', 'logical_id', 'parent_evidence_id', 'case_id', 'batch_id'),
                  'revised_articles': ('article_id', 'base_article_id', 'case_id', 'batch_id'),
                  'update_batches': ('batch_id', 'state', 'created_at', 'input_sha')}
        for table, columns in wanted.items():
            if table not in metadata:
                continue
            available = {c['name'] for c in metadata[table]['columns']}
            columns = [c for c in columns if c in available]
            if not columns:
                lineage[table] = {'status': 'not_run', 'reason': 'no recognized lineage key columns'}
                continue
            lineage[table] = [dict(zip(columns, r)) for r in db.execute('SELECT ' + ','.join(map(quote, columns)) + ' FROM ' + quote(table))]
        if 'update_events' in names:
            eventcols = {r[1] for r in db.execute('PRAGMA table_info(update_events)')}
            kind = 'event' if 'event' in eventcols else ('event_type' if 'event_type' in eventcols else None)
            if kind:
                lineage['event_counts'] = dict(db.execute('SELECT ' + quote(kind) + ',count(*) FROM update_events GROUP BY ' + quote(kind)))
        versions = list(db.execute('SELECT * FROM schema_versions')) if 'schema_versions' in names else None
        version = db.execute('PRAGMA user_version').fetchone()[0]
        private = privacy(db)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in [('row_counts', counts), ('lineage', lineage), ('privacy_report', private),
                       ('integrity_report', {'integrity_check': integrity, 'foreign_key_errors': fk_errors, 'logical_copy_matches_source_snapshot': identical})]:
        (output / ('real_db_' + name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'real_db_schema.sql').write_text(ddl, encoding='utf-8')
    after = sha(source); after_sidecars = sidecars(source)
    valid = integrity == ['ok'] and not fk_errors and identical
    if valid:
        target.rename(final_target)
        target = final_target
    report = {'label': label, 'status': 'confirmed' if valid else 'copy_invalid', 'target_kind': 'copied_real_db',
              'source_location_kind': 'user_download' if label == 'v02' else 'local_runtime_development_storage',
              'production_designation': 'not_confirmed', 'source_file_sha256_before': before, 'source_file_sha256_after': after,
              'source_main_file_unchanged': before == after, 'sidecars_before': before_sidecars, 'sidecars_after': after_sidecars,
              'copy': {'file_name': target.name, 'bytes': target.stat().st_size, 'sha256': sha(target), 'started_at': started,
                       'finished_at': datetime.now(timezone.utc).isoformat(), 'method': 'SQLite online backup from mode=ro read transaction',
                       'sanitized': False, 'read_snapshot_logically_identical': identical, 'copy_valid': bool(valid),
                       'atomic_final_filename_after_validation': True},
              'user_version': version, 'schema_versions': versions, 'tables': metadata,
              'objects': [{'type': r[0], 'name': r[1], 'table': r[2]} for r in objects],
              'source_writes_performed_by_this_tool': False, 'copy_binary_not_for_github': True}
    (output / 'real_db_inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not valid:
        raise ValueError('copy integrity or identity failed; do not proceed')
    return {'label': label, 'tables': len(metadata), 'rows': counts, 'copy_sha256': report['copy']['sha256'],
            'source_main_file_unchanged': before == after, 'privacy_findings': len(private['findings'])}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runtime', type=Path, required=True); p.add_argument('--v02', type=Path, required=True)
    p.add_argument('--copies', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.copies.mkdir(parents=True, exist_ok=False); a.output.mkdir(parents=True, exist_ok=False)
    inputs = [('v02', a.v02)] + [('v0' + str(n), a.runtime / ('admission_media_v0_' + str(n) + '.sqlite')) for n in (3, 4, 5, 6)]
    results = []
    for label, source in inputs:
        if not source.is_file():
            results.append({'label': label, 'status': 'not_found_at_explicit_path'})
            continue
        results.append(inspect(label, source, a.copies, a.output / label))
    (a.output / 'inventory-summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=True))


if __name__ == '__main__':
    main()
