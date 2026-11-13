"""Work's regression tests for Claude review F1/F2a/F2b/F3."""
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

BASE=Path(__file__).resolve().parents[1]


@pytest.fixture
def isolation(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('prepare_review',BASE/'prepare_isolation.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source,package=tmp_path/'source',tmp_path/'package';package.mkdir()
    for name in ('admissions_pipeline','admission_ai','scripts','tests','config'):(source/name).mkdir(parents=True)
    names=['admissions_pipeline/store.py','admissions_pipeline/generic.py','admissions_pipeline/revisions.py','scripts/revise_notices.py']
    for name in names:(source/name).write_bytes(b'before\n')
    (package/'preconditions.json').write_text(json.dumps({n:hashlib.sha256(b'before\n').hexdigest() for n in names}),encoding='utf-8')
    (package/'work-current-stage1.patch').write_bytes(b'--- a/admissions_pipeline/store.py\n+++ b/admissions_pipeline/store.py\n@@ -1 +1 @@\n-before\n+after\n')
    monkeypatch.setattr(module,'__file__',str(package/'prepare_isolation.py'))
    output=tmp_path/'output'
    monkeypatch.setattr(sys,'argv',['prepare_isolation.py','--source-root',str(source),'--output',str(output)])
    return module,source,output


def test_completed_marker_matches_exact_output(isolation):
    module,_,out=isolation;module.main();status=json.loads((out/'.work-isolation-status.json').read_text())
    assert status['state']=='completed'
    assert all(hashlib.sha256((out/n).read_bytes()).hexdigest()==digest for n,digest in status['output_sha256'].items())


def test_partial_copy_has_failed_marker_not_success(isolation):
    module,source,out=isolation;(source/'config').rmdir()
    before={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    with pytest.raises(FileNotFoundError):module.main()
    status=json.loads((out/'.work-isolation-status.json').read_text())
    assert status=={'state':'failed','step':'copy_code','error_type':'FileNotFoundError'}
    assert before=={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    with pytest.raises(SystemExit):module.main()


def test_patch_failure_marked_and_not_reported_completed(isolation,monkeypatch):
    module,_,out=isolation
    def fail(*a,**k):raise subprocess.CalledProcessError(1,['git'])
    monkeypatch.setattr(module.subprocess,'run',fail)
    with pytest.raises(subprocess.CalledProcessError):module.main()
    assert json.loads((out/'.work-isolation-status.json').read_text())['step']=='patch_check'
    assert json.loads((out/'.work-isolation-status.json').read_text())['state']=='failed'


@pytest.mark.parametrize('setting',['true','false','input'])
def test_applied_bytes_are_lf_even_under_external_autocrlf(isolation,monkeypatch,setting):
    module,_,out=isolation
    monkeypatch.setenv('GIT_CONFIG_COUNT','1');monkeypatch.setenv('GIT_CONFIG_KEY_0','core.autocrlf');monkeypatch.setenv('GIT_CONFIG_VALUE_0',setting)
    module.main();assert (out/'admissions_pipeline/store.py').read_bytes()==b'after\n'


@pytest.mark.parametrize('value',[None,False,0,[]])
def test_explicit_nonobject_reason_never_starts_update(tmp_path,monkeypatch,value):
    pipe=Path(os.environ['SOGH_PIPELINE_ROOT'])
    spec=importlib.util.spec_from_file_location('reviewed_reason_cli',pipe/'scripts/revise_notices.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    reason=tmp_path/'reason.json';reason.write_text(json.dumps(value),encoding='utf-8')
    argv=['revise_notices.py']
    for flag in ('specs','monitor-root','base-export','base-db','work-db','qa-root','output'):argv+=['--'+flag,str(tmp_path/flag)]
    argv+=['--reason-json',str(reason)]
    monkeypatch.setattr(sys,'argv',argv)
    called=[];monkeypatch.setattr(module,'run',lambda *a,**kw:called.append(True))
    with pytest.raises(SystemExit) as error:module.main()
    assert error.value.code==2 and not called


def test_all_six_interview_formats_have_actual_option_start_tags():
    class Options(HTMLParser):
        def __init__(self):super().__init__();self.active=False;self.options=[]
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='select':self.active=attrs.get('id')=='format'
            if tag=='option' and self.active:self.options.append(attrs.get('value'))
        def handle_endtag(self,tag):
            if tag=='select':self.active=False
    parser=Options();parser.feed((BASE/'demo/index.html').read_text(encoding='utf-8'))
    assert parser.options==['unknown','individual','group','presentation_then_qa','online','other']
