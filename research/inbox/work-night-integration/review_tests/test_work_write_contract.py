"""Work-owned negative cases; synthetic data, frozen SQL, isolated Work code."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

QA = Path(os.environ['SOGH_REVIEW_QA_ROOT'])
PIPE = Path(os.environ['SOGH_PIPELINE_ROOT'])
sys.path[:0] = [str(QA), str(PIPE)]
from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
from admissions_pipeline.store import canonical
from src.db_contract import additive_schema as ad


def setup(tmp, migrate=True):
    path, profile = S.make_native(tmp)
    store = RevisionStore(path, tmp / 'before.sqlite')
    if migrate:
        assert not ad.apply(path, confirm_disposable_copy=True)['rolled_back']
    batch = store.stage([S.notice(profile)], S.REGISTRY)
    from datetime import date
    article = S.revise_article(S.base_article(store), store.effective_records(batch), date(2026, 11, 1))
    qa = {'success': True, 'batch_input_sha': batch['input_sha'],
          'articles_sha256': hashlib.sha256(canonical([article]).encode()).hexdigest()}
    with store.connect() as db:
        store._work_before_finalize = {t: sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM "' + t + '"'))
            for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
    return path, store, batch, article, qa


def reason(**changes):
    data = dict(reason_class='article_refresh', reason_text='explicit synthetic caller reason',
                source_changed='no', actor='Work-test-fixture-not-user-approval')
    data.update(changes)
    return data


def assert_not_activated(store, batch):
    assert store.heads() == {'evidence': {}, 'articles': {}}
    with store.connect() as db:
        assert db.execute('SELECT state FROM update_batches WHERE batch_id=?', (batch['batch_id'],)).fetchone()[0] == 'candidate'
        assert db.execute('SELECT count(*) FROM revised_articles').fetchone()[0] == 0
        after = {t: sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM "' + t + '"'))
            for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
        assert after == store._work_before_finalize


def test_explicit_reason_and_head_history_are_one_transaction(tmp_path):
    path, store, batch, article, qa = setup(tmp_path)
    supplied = reason()
    assert store.finalize(batch, [article], qa, S.REGISTRY, reason=supplied)
    with store.connect() as db:
        row = db.execute('SELECT * FROM revision_reasons').fetchone()
        assert row['reason_text'] == supplied['reason_text']
        assert row['actor'] == supplied['actor']
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert db.execute('PRAGMA recursive_triggers').fetchone()[0] == 1
        assert db.execute('SELECT sogh_write_ok()').fetchone()[0] == 1
    assert S.failing(path) == {}


@pytest.mark.parametrize('bad', [reason(reason_text=''), reason(reason_class='source_changed', source_changed='no')])
def test_invalid_reason_reverts_even_approved_batch_and_all_heads(tmp_path, bad):
    _, store, batch, article, qa = setup(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=bad)
    assert_not_activated(store, batch)


def test_head_failure_after_batch_approval_rolls_back_the_batch(tmp_path):
    path, store, batch, article, qa = setup(tmp_path)
    with store.connect() as db:
        db.execute("CREATE TRIGGER work_test_head_failure BEFORE INSERT ON article_heads BEGIN SELECT RAISE(ABORT,'injected write fault'); END")
    with pytest.raises(sqlite3.IntegrityError, match='injected write fault'):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    assert_not_activated(store, batch)


def test_reason_on_old_schema_is_refused_without_partial_approval(tmp_path):
    _, store, batch, article, qa = setup(tmp_path, migrate=False)
    with pytest.raises(ValueError, match='no revision_reasons'):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    assert_not_activated(store, batch)


def test_cli_forwards_reason_verbatim_instead_of_inventing_one(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('work_review_revise', PIPE / 'scripts/revise_notices.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    supplied = reason()
    file = tmp_path / 'reason.json'
    file.write_text(json.dumps(supplied), encoding='utf-8')
    observed = []
    monkeypatch.setattr(module, 'run', lambda *a, **kw: observed.append(kw['reason']) or {
        'approved': True, 'pending_contract': [], 'revised_articles': 0, 'source_review_pending': []})
    argv = ['revise_notices.py']
    for name in ('specs', 'monitor-root', 'base-export', 'base-db', 'work-db', 'qa-root', 'output'):
        argv.extend(['--' + name, str(tmp_path / name)])
    argv.extend(['--reason-json', str(file)])
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(SystemExit) as exit_code:
        module.main()
    assert exit_code.value.code == 0
    assert observed == [supplied]


def test_d2_structural_replay_does_not_authenticate_qa_producer(tmp_path):
    """Characterise a residual limit, NOT a claim that a forged approval is safe."""
    path, store, batch, article, qa = setup(tmp_path)
    assert 'signature' not in qa  # invented in this test, never obtained from independent QA
    assert store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    assert S.audit(path)['invariants']['DB-18']['status'] == 'pass'
    # Coherent histories are not proof of the producer's identity or user consent.


def test_deleted_index_is_detected_before_reapplication(tmp_path):
    path, store, *_ = setup(tmp_path)
    with store.connect() as db:
        index = db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchone()[0]
        db.execute('DROP INDEX "' + index.replace('"', '""') + '"')
    assert ad.plan(path)['drift']
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ad.MigrationError):
        ad.apply(path, confirm_disposable_copy=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
