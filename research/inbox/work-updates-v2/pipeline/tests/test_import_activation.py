import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path

import pytest
from admissions_pipeline.generic import fingerprint,promote_candidate,run
from admissions_pipeline.revisions import clone_database
from admissions_pipeline.store import EvidenceStore


@contextmanager
def connection(path):
    db=sqlite3.connect(path)
    try:
        yield db
        db.commit()
    finally:
        db.close()


@pytest.fixture
def databases(tmp_path):
    target=tmp_path/'target.sqlite';store=EvidenceStore(target)
    with store.connect() as db:
        db.execute("INSERT INTO admission_cycles VALUES('old','旧大学','学部',NULL,'方式',2027,2026)")
        before=fingerprint(db)
    candidate=clone_database(target,tmp_path/'candidate.sqlite')
    with connection(candidate) as db:
        db.execute("INSERT INTO admission_cycles VALUES('new','新大学','学部',NULL,'一般選抜',2027,2027)")
    return target,candidate,before


def test_validated_append_preserves_existing_data(databases):
    target,candidate,before=databases
    promote_candidate(candidate,target,before)
    with connection(target) as db:
        assert db.execute('SELECT case_id FROM admission_cycles ORDER BY case_id').fetchall()==[('new',),('old',)]


def test_concurrent_progress_is_not_overwritten(databases):
    target,candidate,before=databases
    with connection(target) as db:db.execute("INSERT INTO schema_versions VALUES('concurrent-progress')")
    with pytest.raises(ValueError,match='changed during validation'):promote_candidate(candidate,target,before)
    with connection(target) as db:
        assert db.execute("SELECT 1 FROM schema_versions WHERE version='concurrent-progress'").fetchone()
        assert not db.execute("SELECT 1 FROM admission_cycles WHERE case_id='new'").fetchone()


def test_candidate_cannot_replace_existing_rows(databases):
    target,candidate,before=databases
    with connection(candidate) as db:db.execute("UPDATE admission_cycles SET university='wrong' WHERE case_id='old'")
    with pytest.raises(ValueError,match='modify existing rows'):promote_candidate(candidate,target,before)
    with connection(target) as db:assert db.execute("SELECT university FROM admission_cycles WHERE case_id='old'").fetchone()[0]=='旧大学'


@pytest.mark.parametrize('qa_success,source_success',[(False,True),(True,False)])
def test_failed_article_or_original_gate_never_commits_import(databases,tmp_path,monkeypatch,qa_success,source_success):
    target,_,before=databases
    def staged(profile,pdf,candidate,output,collab,as_of):
        Path(output).mkdir()
        with connection(candidate) as db:db.execute("INSERT INTO admission_cycles VALUES('unsafe','候補大学','学部',NULL,'方式',2027,2026)")
        return {'success':qa_success,'after':EvidenceStore(candidate).counts()}
    monkeypatch.setattr('admissions_pipeline.generic._run',staged)
    monkeypatch.setattr('admissions_pipeline.generic.independent_gate',lambda *args:source_success)
    r=run('profile','source.pdf',target,tmp_path/'rejected','qa-root',date(2026,11,1))
    assert r['success'] is False and r['promoted'] is False
    with connection(target) as db:assert fingerprint(db)==before
    assert (tmp_path/'rejected/candidate.sqlite').exists()
