import copy
from datetime import date
import pytest
from admissions_pipeline.full_view import article_metadata,check_reuse,compare,evidence_identity,load_json


@pytest.fixture
def view():
    record={'fact_key':'quota','value':{'count':5},'university':'大学','faculty':'学部','department':None,'admission_method':'一般選抜','fiscal_year':2027,
            'source_pdf_sha256':'a'*64,'source_url':'https://example.ac.jp/guide.pdf','retrieved_at':'2026-11-01','proofs':[{'page':1,'quote':'募集人数5名'}]}
    article={'article_id':'article','text':'募集人数5名[EV-one]。','claim':{k:record[k] for k in ('university','faculty','department','admission_method','fiscal_year')}}
    return {'evidence':{'EV-one':record},'articles':[article]}


def test_materialized_view_reuse_is_not_a_collision(view):
    older=copy.deepcopy(view);older['evidence']['EV-one']['retrieved_at']='2026-10-31'
    r=check_reuse(view,[('previous',older)])
    assert r['status']=='pass' and r['reused_evidence']==['EV-one'] and r['reused_articles']==['article']


@pytest.mark.parametrize('field',['value','source_url','fiscal_year','proofs','applicability','temporal_status'])
def test_different_evidence_with_same_id_is_rejected(view,field):
    older=copy.deepcopy(view)
    older['evidence']['EV-one'][field]={'value':{'count':6},'source_url':'https://example.ac.jp/other.pdf','fiscal_year':2028,'proofs':[{'page':2,'quote':'別の引用'}],
        'applicability':'別の適用条件','temporal_status':'different'}[field]
    assert check_reuse(view,[('old',older)])['status']=='fail'


def test_different_article_with_same_id_is_rejected(view):
    prior=copy.deepcopy(view);prior['articles'][0]['text']='different body'
    assert check_reuse(view,[('old',prior)])['conflicts']==[{'kind':'article','id':'article','in':'active-view'}]


@pytest.mark.parametrize('mutation',['method','year','unknown_id','bad_date','future_date'])
def test_article_metadata_checks_scope_year_sources_and_retrieval(view,mutation):
    a=view['articles'][0];e=view['evidence']
    if mutation=='method':a['claim']['admission_method']='推薦'
    if mutation=='year':a['claim']['fiscal_year']=2028
    if mutation=='unknown_id':a['text']='[EV-missing]'
    if mutation=='bad_date':e['EV-one']['retrieved_at']='unknown'
    if mutation=='future_date':e['EV-one']['retrieved_at']='2026-11-02'
    assert article_metadata(a,e,date(2026,11,1))['status']=='fail'


def test_repeat_result_and_changed_conditions_are_visible():
    original={'fingerprint':'old','conditions':{'qa':'a'},'articles':[{'article_id':'a','ok':True,'content_sha256':'x'}]}
    assert compare(original,copy.deepcopy(original))['changed']==[]
    changed=copy.deepcopy(original);changed['conditions']['qa']='b';changed['articles'][0]['ok']=False
    r=compare(original,changed)
    assert r['conditions_changed'] and r['changed']==[{'article_id':'a','fields':['ok']}]


def test_duplicate_keys_and_duplicate_article_rows_are_not_silent(tmp_path,view):
    p=tmp_path/'bad.json';p.write_text('{"EV-one":1,"EV-one":2}')
    with pytest.raises(ValueError,match='duplicate JSON key'):load_json(p)
    view['articles']*=2
    assert check_reuse(view,[])['status']=='fail'
