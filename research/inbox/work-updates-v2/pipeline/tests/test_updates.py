import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from admissions_pipeline.collector import Collector
from admissions_pipeline.extract import Extracted
from admissions_pipeline.monitor import Monitor
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.process_lock import ProcessLock
from admissions_pipeline.revisions import RevisionStore
from admissions_pipeline.store import EvidenceStore, canonical


class FakeCollector:
    write_snapshot = Collector.write_snapshot
    def __init__(self, root, responses):
        self.root, self.responses, self.calls = root, list(responses), 0
        root.mkdir(parents=True)
    def fetch(self, url):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        sha = hashlib.sha256(response).hexdigest(); path = self.root / (sha + ".html"); path.write_bytes(response)
        return {"url": url, "sha256": sha, "kind": "html", "local_path": str(path), "retrieved_at": "2026-11-01T00:00:00Z"}


@pytest.fixture
def monitor_setup(tmp_path):
    config = {"allowed_hosts": ["example.ac.jp"], "interval_seconds": 60, "max_attempts": 2,
              "failure_backoff_seconds": 300, "targets": [{"url": "https://example.ac.jp/guide", "case": "test", "role": "faq"}]}
    clock = [1000.0]
    return config, clock


def test_monitor_initial_repeat_restart_change(tmp_path, monitor_setup):
    config, clock = monitor_setup
    config["targets"] *= 2
    collector = FakeCollector(tmp_path / "bodies", [b"<p>old</p>", b"<p>old</p>", b"<p>new</p>"])
    root = tmp_path / "state"
    monitor = Monitor(root, config, clock=lambda:clock[0], collector=collector)
    assert monitor.run_once()["results"][0]["status"] == "first_fetch"
    assert monitor.run_once()["results"][0]["status"] == "not_due" and collector.calls == 1
    clock[0] += 61
    restarted = Monitor(root, config, clock=lambda:clock[0], collector=collector)
    assert restarted.run_once()["results"][0]["status"] == "unchanged"
    clock[0] += 61
    changed = restarted.run_once()["results"][0]
    assert changed["status"] == "changed" and changed["previous_sha256"] != changed["sha256"]
    assert Path(changed["old_snapshot"]).exists() and Path(changed["new_snapshot"]).exists()
    with restarted.connect() as db:
        row = db.execute("SELECT * FROM targets").fetchone()
        assert row["last_success"] == clock[0] and row["last_attempt"] == clock[0]


def test_monitor_failure_backoff_then_recovery(tmp_path, monitor_setup, monkeypatch):
    config, clock = monitor_setup
    monkeypatch.setattr("admissions_pipeline.monitor.time.sleep", lambda _:None)
    errors = [urllib.error.HTTPError("https://example.ac.jp/guide", 503, "unavailable", {}, None) for _ in range(2)]
    collector = FakeCollector(tmp_path / "bodies", errors + [b"<p>recovered</p>"])
    monitor = Monitor(tmp_path / "state", config, clock=lambda:clock[0], collector=collector)
    assert monitor.run_once()["success"] is False and collector.calls == 2
    assert monitor.run_once()["results"][0]["status"] == "not_due" and collector.calls == 2
    clock[0] += 301
    assert monitor.run_once()["success"] is True and collector.calls == 3


@pytest.mark.parametrize("bad", [b"\xff", "<p>\ufffd</p>".encode()])
def test_encoding_error_does_not_replace_successful_version(tmp_path, monitor_setup, bad):
    config, clock = monitor_setup
    collector = FakeCollector(tmp_path / "bodies", [b"<p>valid</p>", bad])
    monitor = Monitor(tmp_path / "state", config, clock=lambda:clock[0], collector=collector)
    first = monitor.run_once()["results"][0]
    clock[0] += 61
    assert monitor.run_once()["success"] is False
    with monitor.connect() as db:
        row = db.execute("SELECT * FROM targets").fetchone()
        assert row["last_sha"] == first["sha256"] and row["last_success"] == 1000


def test_interrupted_run_and_unassessed_change_survive_restart(tmp_path, monitor_setup, monkeypatch):
    config, clock = monitor_setup
    collector = FakeCollector(tmp_path / "bodies", [b"<p>old</p>", b"<p>changed</p>"])
    monitor = Monitor(tmp_path / "state", config, clock=lambda:clock[0], collector=collector)
    monitor.run_once(); clock[0] += 61
    with monitor.connect() as db: db.execute("INSERT INTO runs VALUES('crashed',999,NULL,'running')")
    def fail_analysis(*args): raise TimeoutError()
    monkeypatch.setattr(monitor, "versioning", fail_analysis)
    report = monitor.run_once(export_path=tmp_path / "x.json", collab_root=tmp_path)
    assert not report["success"] and report["versioning"]["pending_checks_retained"]
    with monitor.connect() as db:
        assert db.execute("SELECT status FROM runs WHERE id='crashed'").fetchone()[0] == "interrupted"
        assert db.execute("SELECT count(*) FROM checks WHERE old_snapshot IS NOT NULL AND analysis_status='pending'").fetchone()[0] == 1


def test_stop_flag_never_fetches(tmp_path, monitor_setup):
    config, clock = monitor_setup
    collector = FakeCollector(tmp_path / "bodies", [])
    monitor = Monitor(tmp_path / "state", config, collector=collector)
    (monitor.root / "STOP").touch()
    assert monitor.run_once()["stopped"] and collector.calls == 0


def test_kernel_lock_prevents_duplicate_and_recovers_after_crash(tmp_path):
    path = tmp_path / "lock"
    with ProcessLock(path):
        with pytest.raises(RuntimeError):
            with ProcessLock(path): pass
    code = "from admissions_pipeline.process_lock import ProcessLock;import os,sys;lock=ProcessLock(sys.argv[1]);lock.__enter__();os._exit(31)"
    result = subprocess.run([sys.executable, "-B", "-c", code, str(path)], timeout=30)
    assert result.returncode == 31
    with ProcessLock(path): pass


@pytest.fixture
def revision_setup(tmp_path):
    path = tmp_path / "db.sqlite"; base = EvidenceStore(path)
    profile = {"university":"試験大学","faculty":"試験学部","department":None,"admission_method":"試験方式","fiscal_year":2027,"exam_year":2026,"sha256":"a"*64,"url":"https://example.ac.jp/guide"}
    base.ingest(Extracted("case",profile,tmp_path / "source.pdf",["fixture"],[]),"2026-11-01")
    article = {"article_id":"base","case_id":"case","input_hash":"a"*64,"series":"overview","title":"試験記事","text":"# 試験記事\n\n## 根拠資料\n","evidence_ids":[],"claim":{k:profile[k] for k in ("university","faculty","department","admission_method","fiscal_year")},"publish_allowed":False}
    base.save_article(article,tmp_path / "base.md")
    store = RevisionStore(path,tmp_path / "before.sqlite")
    record = {"evidence_id":"EV-U-test","logical_id":"notice","case_id":"case",**{k:profile[k] for k in ("university","faculty","department","admission_method","fiscal_year")},
              "fact_key":"generative_ai_policy","source_sha256":"b"*64,"source_kind":"html","source_url":"https://example.ac.jp/faq","proofs":[{"page":1}],
              "value":{"allowed":"FAQの説明"},"sentences":["生成AIの使用を明示します。"],"temporal_status":"current_faq","retrieved_at":"2026-11-01"}
    registry = {"fact_keys":{"generative_ai_policy":{"status":"active"}}}
    return store, record, article, registry


def approve(store, record, article, registry):
    batch = store.stage([record], registry)
    revised = revise_article(article, store.effective_records(batch), date(2026,11,1))
    qa = {"success":True,"batch_input_sha":batch["input_sha"],"articles_sha256":hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    assert store.finalize(batch,[revised],qa,registry)
    return batch,revised,qa


def test_rejected_qa_never_activates(revision_setup):
    store,record,article,registry = revision_setup
    before=store.heads();batch=store.stage([record],registry)
    assert store.finalize(batch,[],{"success":False},registry) is False
    assert store.heads()==before
    with store.connect() as db: assert db.execute("SELECT state FROM update_batches").fetchone()[0]=='rejected'


@pytest.mark.parametrize("status", [None,"proposed"])
def test_unagreed_contract_is_not_verified(revision_setup,status):
    store,record,article,registry=revision_setup
    registry['fact_keys']={} if status is None else {'generative_ai_policy':{'status':status}}
    batch=store.stage([record],registry)
    assert batch['pending_contract']==[record['evidence_id']]
    with pytest.raises(ValueError): store.finalize(batch,[],{'success':True},registry)
    assert store.heads()=={'evidence':{},'articles':{}}


def test_approval_history_no_change_and_rollback(revision_setup):
    store,record,article,registry=revision_setup
    batch,_,_=approve(store,record,article,registry)
    assert store.stage([record],registry)['state']=='no_change'
    assert store.heads()['evidence']['notice']==record['evidence_id']
    store.rollback_batch(batch['batch_id'])
    assert store.heads()=={'evidence':{},'articles':{}}
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM evidence_revisions').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM revised_articles').fetchone()[0]==1
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_wrong_year_and_parent_are_rejected(revision_setup):
    store,record,article,registry=revision_setup
    changed=copy.deepcopy(record);changed['fiscal_year']=2028
    with pytest.raises(ValueError): store.stage([changed],registry)
    changed=copy.deepcopy(record);changed['parent_evidence_id']='nonexistent'
    with pytest.raises(ValueError): store.stage([changed],registry)


def test_qa_for_different_article_and_stale_heads_are_rejected(revision_setup):
    store,record,article,registry=revision_setup
    batch=store.stage([record],registry)
    revised=revise_article(article,[record],date(2026,11,1))
    with pytest.raises(ValueError): store.finalize(batch,[revised],{'success':True,'batch_input_sha':batch['input_sha'],'articles_sha256':'wrong'},registry)
    second=store.stage([record],registry)
    approve(store,record,article,registry)
    qa={'success':True,'batch_input_sha':second['input_sha'],'articles_sha256':hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    with pytest.raises(ValueError): store.finalize(second,[revised],qa,registry)


def test_rollback_cannot_discard_later_approved_update(revision_setup):
    store,record,article,registry=revision_setup
    first,_,_=approve(store,record,article,registry)
    new=copy.deepcopy(record);new.update(evidence_id='EV-U-next',parent_evidence_id=record['evidence_id']);new['value']['allowed']='訂正された説明'
    approve(store,new,article,registry)
    with pytest.raises(ValueError): store.rollback_batch(first['batch_id'])
    assert store.heads()['evidence']['notice']=='EV-U-next'


def test_same_pdf_correction_replaces_current_citation_but_retains_old_fact(revision_setup):
    store,record,article,registry=revision_setup
    with store.connect() as db:
        db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?)',('EV-OLD','case','a'*64,'quota',canonical({'count':5}),canonical({'key':'quota','value':{'count':5}}),'source_checked_for_saved_version'))
    article.update(text='募集人員は5名[EV-OLD]です。\n\n## 根拠資料\n\n- [EV-OLD] 公式PDF\n',evidence_ids=['EV-OLD'])
    record.update(fact_key='quota',parent_evidence_id='EV-OLD',value={'count':6},sentences=['募集人員は6名です。'])
    registry['fact_keys']['quota']={'status':'active'}
    batch=store.stage([record],registry);effective=store.effective_records(batch)
    revised=revise_article(article,effective,date(2026,11,1))
    assert 'EV-OLD' not in revised['text'] and '5名' not in revised['text'] and '6名' in revised['text']
    qa={'success':True,'batch_input_sha':batch['input_sha'],'articles_sha256':hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    assert store.finalize(batch,[revised],qa,registry)
    with store.connect() as db:assert json.loads(db.execute("SELECT value_json FROM facts WHERE evidence_id='EV-OLD'").fetchone()[0])=={'count':5}


def test_mixed_claim_paragraph_requires_explicit_rewrite(revision_setup):
    store,record,article,registry=revision_setup
    article.update(text='人数5名[EV-OLD]と別の条件[EV-OTHER]。\n\n## 根拠資料\n',evidence_ids=['EV-OLD','EV-OTHER'])
    record['replaces_evidence_ids']=['EV-OLD']
    with pytest.raises(ValueError):revise_article(article,[record],date(2026,11,1))


def test_failed_second_article_rolls_back_entire_activation(revision_setup):
    store,record,article,registry=revision_setup
    batch=store.stage([record],registry);first=revise_article(article,[record],date(2026,11,1));second=dict(first,article_id='bad',base_article_id='missing')
    articles=[first,second];qa={'success':True,'batch_input_sha':batch['input_sha'],'articles_sha256':hashlib.sha256(canonical(articles).encode()).hexdigest()}
    with pytest.raises(ValueError):store.finalize(batch,articles,qa,registry)
    with store.connect() as db:assert db.execute('SELECT count(*) FROM revised_articles').fetchone()[0]==0
    assert store.heads()=={'evidence':{},'articles':{}}


@pytest.mark.parametrize('mode',['retired','expired','failed'])
def test_versioning_excludes_unmonitored_stale_or_failed_sources(tmp_path,monitor_setup,mode):
    config,clock=monitor_setup;collector=FakeCollector(tmp_path/'bodies',[b'<p>source</p>'])
    monitor=Monitor(tmp_path/'state',config,clock=lambda:clock[0],collector=collector);monitor.run_once()
    if mode=='retired':monitor.config['targets']=[]
    if mode=='expired':clock[0]+=100000
    if mode=='failed':
        with monitor.connect() as db:db.execute("UPDATE targets SET last_error='TimeoutError'")
    r=monitor.versioning([],tmp_path/'export.json',tmp_path)
    assert not r['success'] and r['reason']=='no_successful_snapshots'


def test_unexpired_deadline_cannot_be_written_as_past(revision_setup):
    _,record,article,_=revision_setup
    record.update(temporal_status='deadline_elapsed',value={'deadline':'2026-11-02'})
    with pytest.raises(ValueError):revise_article(article,[record],date(2026,11,1))


def test_legacy_pack_cannot_silently_drop_approved_updates(revision_setup):
    store,record,article,registry=revision_setup
    approve(store,record,article,registry)
    with pytest.raises(ValueError,match='revision pipeline'):store.pack('case','a'*64)


def test_crashed_candidate_recovers_without_activating(revision_setup):
    store,record,article,registry=revision_setup
    batch=store.stage([record],registry)
    assert store.recover_candidates()==[batch['batch_id']]
    assert store.heads()=={'evidence':{},'articles':{}}
    with store.connect() as db:assert db.execute('SELECT state FROM update_batches').fetchone()[0]=='interrupted'


def test_parse_failure_is_reported_and_other_url_continues(tmp_path,monitor_setup):
    config,_=monitor_setup
    config['targets'].append({'url':'https://example.ac.jp/other','case':'test','role':'news'})
    collector=FakeCollector(tmp_path/'bodies',[RuntimeError('invalid document'),b'<p>valid other source</p>'])
    report=Monitor(tmp_path/'state',config,collector=collector).run_once()
    assert not report['success'] and [r['status'] for r in report['results']]==['failed','first_fetch']


def test_process_exits_during_collection_then_resumes_previous_data(tmp_path,monitor_setup):
    config,_=monitor_setup;state=tmp_path/'state';collector=FakeCollector(tmp_path/'bodies',[b'<p>last good</p>'])
    monitor=Monitor(state,config,collector=collector);monitor.run_once()
    config_path=tmp_path/'config.json';config_path.write_text(json.dumps(config))
    code='''import json,os,sys
from pathlib import Path
from admissions_pipeline.monitor import Monitor
class Crash:
 def fetch(self,url):os._exit(23)
Monitor(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text()),collector=Crash()).run_once(force=True)
'''
    result=subprocess.run([sys.executable,'-B','-c',code,str(state),str(config_path)],timeout=20)
    assert result.returncode==23
    with monitor.connect() as db:
        old=dict(db.execute('SELECT * FROM targets').fetchone());assert db.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0]==1
    collector.responses.append(b'<p>last good</p>')
    assert Monitor(state,config,collector=collector).run_once(force=True)['results'][0]['status']=='unchanged'
    with monitor.connect() as db:
        assert db.execute("SELECT count(*) FROM runs WHERE status='interrupted'").fetchone()[0]==1
        assert dict(db.execute('SELECT * FROM targets').fetchone())['last_sha']==old['last_sha']


def test_restart_does_not_cancel_a_stop_for_the_running_service(tmp_path):
    state=tmp_path/'state';state.mkdir();stop=state/'STOP';stop.write_text('requested')
    config=tmp_path/'config.json';config.write_text(json.dumps({'allowed_hosts':[],'targets':[]}))
    command=[sys.executable,'-B','-m','admissions_pipeline.monitor','--restart','--state',str(state),'--config',str(config)]
    with ProcessLock(state/'service.lock'):
        rejected=subprocess.run(command,capture_output=True,timeout=20)
    assert rejected.returncode!=0 and stop.exists()
    resumed=subprocess.run(command,capture_output=True,timeout=20)
    assert resumed.returncode==0 and not stop.exists()


@pytest.mark.parametrize('mode',['missing_evidence','wrong_value','wrong_body'])
def test_active_export_rejects_a_base_different_from_native(revision_setup,tmp_path,mode):
    from scripts.export_active import export_active
    store,record,article,registry=revision_setup
    with store.connect() as db:
        db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?)',('EV-OLD','case','a'*64,'quota',canonical({'count':5}),canonical({'key':'quota','value':{'count':5}}),'source_checked_for_saved_version'))
    base={'evidence':{'EV-OLD':{'fact_key':'quota','value':{'count':5},'source_pdf_sha256':'a'*64}},'articles':[article]}
    path=tmp_path/'base.json';path.write_text(json.dumps(base),encoding='utf-8')
    approve(store,record,article,registry)
    assert export_active(store.path,path)['articles'][0]['base_article_id']=='base'
    if mode=='missing_evidence':base['evidence']['unknown']=base['evidence'].pop('EV-OLD')
    if mode=='wrong_value':base['evidence']['EV-OLD']['value']['count']=999
    if mode=='wrong_body':base['articles'][0]['text']='unverified replacement'
    path.write_text(json.dumps(base),encoding='utf-8')
    with pytest.raises(ValueError,match='base .* differs'):export_active(store.path,path)
