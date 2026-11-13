import json
import sqlite3
from pathlib import Path

import pytest

from scripts.inventory_real_databases import inspect, sha
from scripts import inventory_real_databases as inventory


def test_online_backup_includes_committed_wal_without_changing_source(tmp_path):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE evidence(id TEXT PRIMARY KEY, value TEXT)')
        writer.execute('INSERT INTO evidence VALUES(?,?)', ('stable-id', 'committed-in-wal'))
        writer.commit()
        assert Path(str(source) + '-wal').stat().st_size > 0
        before = sha(source)
        copies = tmp_path / 'copies'; copies.mkdir()
        result = inspect('real', source, copies, tmp_path / 'report')
        assert result['source_main_file_unchanged'] and sha(source) == before
        with sqlite3.connect(copies / 'real.sqlite') as copy:
            assert copy.execute('SELECT * FROM evidence').fetchall() == [('stable-id', 'committed-in-wal')]
        assert writer.execute('SELECT count(*) FROM evidence').fetchone()[0] == 1


def test_existing_copy_is_never_overwritten(tmp_path):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE facts(id PRIMARY KEY)')
    copies = tmp_path / 'copies'; copies.mkdir()
    target = copies / 'real.sqlite'; target.write_bytes(b'keep-this-artifact')
    with pytest.raises(FileExistsError):
        inspect('real', source, copies, tmp_path / 'report')
    assert target.read_bytes() == b'keep-this-artifact'


def test_copy_with_broken_foreign_key_is_not_reported_as_valid(tmp_path):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE parents(id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE children(parent_id REFERENCES parents(id))')
        db.execute('INSERT INTO children VALUES(999)')
    copies = tmp_path / 'copies'; copies.mkdir()
    with pytest.raises(ValueError, match='integrity or identity'):
        inspect('real', source, copies, tmp_path / 'report')
    report = json.loads((tmp_path / 'report/real_db_integrity_report.json').read_text(encoding='utf-8'))
    assert report['foreign_key_errors']
    assert not (copies / 'real.sqlite').exists()
    assert (copies / 'real.sqlite.partial').exists()


def test_secret_values_are_not_disclosed_in_inventory_or_privacy_report(tmp_path):
    source = tmp_path / 'source.sqlite'
    marker = 'ghp_' + 'X' * 36
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE config(name TEXT, value TEXT)')
        db.execute('INSERT INTO config VALUES(?,?)', ('credential', marker))
    copies = tmp_path / 'copies'; copies.mkdir()
    inspect('real', source, copies, tmp_path / 'report')
    texts = [p.read_text(encoding='utf-8') for p in (tmp_path / 'report').glob('*')]
    assert all(marker not in text for text in texts)
    report = json.loads((tmp_path / 'report/real_db_privacy_report.json').read_text(encoding='utf-8'))
    assert any(f['category'] == 'credential_pattern' for f in report['findings'])
    assert report['database_upload_allowed'] is False


def test_quoted_table_names_are_inspected_without_executing_name_as_sql(tmp_path):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE "facts\"\"; DROP TABLE innocent;--" (id INTEGER)')
        db.execute('CREATE TABLE innocent(id INTEGER)')
        db.execute('INSERT INTO innocent VALUES(4)')
    copies = tmp_path / 'copies'; copies.mkdir()
    result = inspect('real', source, copies, tmp_path / 'report')
    assert result['tables'] == 2 and result['rows']['innocent'] == 1


def test_json_escaped_user_path_is_found_without_disclosing_the_value(tmp_path):
    source = tmp_path / 'source.sqlite'
    synthetic_path = 'C:' + chr(92) + 'Users' + chr(92) + 'fixture-user' + chr(92) + 'file'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE update_batches(qa_json TEXT)')
        db.execute('INSERT INTO update_batches VALUES(?)', (json.dumps({'report': synthetic_path}),))
    copies = tmp_path / 'copies'; copies.mkdir()
    inspect('real', source, copies, tmp_path / 'report')
    text = (tmp_path / 'report/real_db_privacy_report.json').read_text(encoding='utf-8')
    assert 'fixture-user' not in text
    assert any(f['table'] == 'update_batches' and f['category'] == 'user_path' for f in json.loads(text)['findings'])


def test_insufficient_space_never_creates_a_final_copy(tmp_path, monkeypatch):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as db: db.execute('CREATE TABLE facts(id INTEGER)')
    copies = tmp_path / 'copies'; copies.mkdir()
    from collections import namedtuple
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(inventory.shutil, 'disk_usage', lambda _: usage(100, 99, 1))
    with pytest.raises(OSError, match='insufficient free space'):
        inspect('real', source, copies, tmp_path / 'report')
    assert not (copies / 'real.sqlite').exists()


def test_interrupted_backup_keeps_only_an_explicitly_invalid_partial(tmp_path, monkeypatch):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as db: db.execute('CREATE TABLE facts(id INTEGER)')
    copies = tmp_path / 'copies'; copies.mkdir()
    original = inventory.connect
    class BrokenBackup:
        def __init__(self, db): self.db = db
        def __getattr__(self, name): return getattr(self.db, name)
        def backup(self, dst, **kwargs):
            dst.execute('CREATE TABLE partial_content(id INTEGER)')
            raise sqlite3.OperationalError('injected failure')
    monkeypatch.setattr(inventory, 'connect', lambda path: BrokenBackup(original(path)))
    before = sha(source)
    with pytest.raises(sqlite3.OperationalError):
        inspect('real', source, copies, tmp_path / 'report')
    assert sha(source) == before and not (copies / 'real.sqlite').exists()
    assert (copies / 'real.sqlite.partial').exists()
    failure = json.loads((tmp_path / 'report/copy_failure.json').read_text(encoding='utf-8'))
    assert failure['copy_valid'] is False and failure['final_file_created'] is False
