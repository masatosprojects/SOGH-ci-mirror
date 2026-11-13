"""Real loopback HTTP transport; production HTTPS/host/redirect rules remain intact."""
import gzip
import http.client
import json
import socket
import threading
import time
import urllib.request
from collections import defaultdict
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

import pytest
from admissions_pipeline.collector import Collector
from admissions_pipeline.monitor import Monitor


@pytest.fixture
def server(monkeypatch):
    actions=defaultdict(list);calls=defaultdict(int)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            calls[self.path]+=1
            action=actions[self.path].pop(0) if actions[self.path] else (200,b'<p>source</p>',{})
            if action=='disconnect':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if action=='timeout':threading.Event().wait(.15);action=(200,b'late',{})
            status,body,headers=action
            self.send_response(status)
            self.send_header('Content-Type',headers.pop('Content-Type','text/html; charset=utf-8'))
            self.send_header('Content-Length',str(headers.pop('Content-Length',len(body))))
            for k,v in headers.items():self.send_header(k,v)
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
    httpd=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    # Only TCP transport changes. Request URLs and Redirect(host) are the real ones.
    def open_local(self,request):
        return self.do_open(lambda host,**kw:http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=.04),request)
    monkeypatch.setattr(urllib.request.HTTPSHandler,'https_open',open_local)
    monkeypatch.setattr('admissions_pipeline.collector.time.sleep',lambda _:None)
    yield actions,calls
    httpd.shutdown();httpd.server_close();thread.join(timeout=2)


def setup(tmp_path):
    config={'allowed_hosts':['fixture.ac.jp'],'interval_seconds':60,'max_attempts':2,'failure_backoff_seconds':1,
            'targets':[{'url':'https://fixture.ac.jp/source','source_id':'fixture-source','case':'fixture','role':'guide'}]}
    return Monitor(tmp_path/'state',config,collector=Collector(tmp_path/'state/bodies',config['allowed_hosts'],delay=0))


def head(monitor):
    with monitor.connect() as db:return dict(db.execute('SELECT * FROM targets').fetchone())


@pytest.mark.parametrize('status,attempts',[(403,1),(404,1),(429,2),(500,2)])
def test_http_status_retains_previous_success_and_recovers(tmp_path,server,status,attempts):
    actions,calls=server;m=setup(tmp_path);assert m.run_once()['success'];before=head(m)
    actions['/source']=[(status,b'error',{}) for _ in range(attempts)]
    failed=m.run_once(force=True);after=head(m)
    assert not failed['success'] and after['last_sha']==before['last_sha'] and after['last_success']==before['last_success']
    assert failed['results'][0]['error']=='HTTPError:'+str(status) and calls['/source']==1+attempts
    assert m.run_once(force=True)['success'] and head(m)['last_error'] is None


@pytest.mark.parametrize('action',['timeout','disconnect'])
def test_temporary_network_failure_bounded_and_recoverable(tmp_path,server,action):
    actions,calls=server;m=setup(tmp_path);assert m.run_once()['success'];old=head(m)
    actions['/source']=[action,action]
    assert not m.run_once(force=True)['success']
    assert head(m)['last_sha']==old['last_sha']
    assert m.run_once(force=True)['success']


@pytest.mark.parametrize('body,headers',[(b'\xff',{}),(b'bad gzip',{'Content-Encoding':'gzip'}),
    (gzip.compress(b'<p>ok</p>')[:-4],{'Content-Encoding':'gzip'}),(b'<p>br</p>',{'Content-Encoding':'br'}),
    (b'<p>short</p>',{'Content-Length':999}),(b'%PDF-1.7\ntruncated',{'Content-Type':'application/pdf'})])
def test_invalid_transfer_or_document_keeps_successful_snapshot(tmp_path,server,body,headers):
    actions,_=server;m=setup(tmp_path);m.run_once();before=head(m)
    actions['/source']=[(200,body,dict(headers))]
    assert not m.run_once(force=True)['success']
    after=head(m);assert after['last_sha']==before['last_sha'] and after['last_snapshot']==before['last_snapshot']
    assert Path(after['last_snapshot']).is_file()


def test_compressed_html_repeat_byte_only_and_body_change(tmp_path,server):
    actions,_=server;m=setup(tmp_path)
    actions['/source']=[(200,gzip.compress(b'<p>body 5</p>'),{'Content-Encoding':'gzip'})]
    first=m.run_once()['results'][0]
    actions['/source']=[(200,b'<p>body 5</p>',{})];repeat=m.run_once(force=True)['results'][0]
    assert repeat['status']=='unchanged' and first['sha256']==repeat['sha256']
    actions['/source']=[(200,b'<script>random</script><p>body 5</p>',{})];byte=m.run_once(force=True)['results'][0]
    previous=json.loads(Path(byte['old_snapshot']).read_text());current=json.loads(Path(byte['new_snapshot']).read_text())
    assert byte['status']=='changed' and previous['pages']==current['pages']
    actions['/source']=[(200,b'<p>body 6</p>',{})];changed=m.run_once(force=True)['results'][0]
    assert json.loads(Path(changed['new_snapshot']).read_text())['pages']!=current['pages']
    assert current['source_id']==previous['source_id']=='fixture-source'


def test_redirect_link_change_and_disallowed_host(tmp_path,server):
    actions,calls=server;m=setup(tmp_path)
    actions['/source']=[(302,b'',{'Location':'https://fixture.ac.jp/new'})]
    actions['/new']=[(200,b'<a href="/guide-v2.pdf">new</a>',{})]
    assert m.run_once()['success'];before=head(m)
    snapshot=json.loads(Path(before['last_snapshot']).read_text());assert snapshot['url']=='https://fixture.ac.jp/source'
    actions['/source']=[(302,b'',{'Location':'https://unapproved.example/other'})]
    assert not m.run_once(force=True)['success'] and calls['/other']==0
    assert head(m)['last_sha']==before['last_sha']
    # An explicitly reconfigured URL is a new baseline, with the same logical source id.
    m.config['targets'][0]['url']='https://fixture.ac.jp/new'
    m.config['targets'][0]['supersedes_sha256']=[before['last_sha']]
    actions['/new']=[(200,b'<a href="/guide-v2.pdf">new</a>',{})]
    r=m.run_once(force=True)['results'][0];assert r['status']=='first_fetch' and r['source_id']=='fixture-source'
    assert r['sha256']==before['last_sha'] and r['new_snapshot']!=before['last_snapshot']
    assert json.loads(Path(r['new_snapshot']).read_text())['supersedes']==[before['last_sha']]


def test_stop_then_restart_preserves_version_history(tmp_path,server):
    m=setup(tmp_path);m.run_once();before=head(m)
    (m.root/'STOP').write_text('stop')
    assert m.run_once(force=True)['stopped'] and head(m)['last_sha']==before['last_sha']
    (m.root/'STOP').unlink()
    restarted=Monitor(m.root,m.config,collector=m.collector)
    assert restarted.run_once(force=True)['results'][0]['status']=='unchanged'
