"""Controlled clause fixtures, not university HTML or a published article."""
import copy
import hashlib
import json
import sqlite3
import time
from datetime import date
from pathlib import Path
import pytest
from admissions_pipeline.faq_policy import extract_conditions,structured_record,render_conditions,validate_condition_bindings,audit_condition_source,FIELDS
from admissions_pipeline.supplements import contract_state
from admissions_pipeline.extract import Extracted
from admissions_pipeline.store import EvidenceStore,canonical
from admissions_pipeline.revisions import RevisionStore
from admissions_pipeline.notice_articles import revise_article


@pytest.fixture
def faq(tmp_path):
    # Deliberately explicit: changing the extractor's field mapping does not change this fixture.
    clauses=['文章チェックも含め、生成AIが実際に生成・修正した箇所には、すべて下線を引いてください。',
      'また、その修正によって間接的にでも内容が影響された場合には、影響した箇所すべてに下線を引いてください。',
      'MicrosoftWORD等の文書校正機能による単純な誤字脱字修正の場合は、下線を引く必要はありません。',
      '他人の添削・助言による修正等には、下線を引く必要はありませんが、活動経過報告書での記載は必須です。',
      '画像・図・表等の説明文や脚注に、生成AIで作成したことが分かるように明示してください。']
    text='<h2>AC開始</h2><p>'+''.join(clauses)+'</p><h2>他方式開始</h2><p>別方式の例外</p>'
    path=tmp_path/'fixture.html';path.write_text(text,encoding='utf-8');sha=hashlib.sha256(path.read_bytes()).hexdigest()
    record={'kind':'html','url':'https://fixture.ac.jp/faq','local_path':str(path),'sha256':sha,'retrieved_at':'2026-11-01T05:31:11Z'}
    cycle={'case_id':'tsukuba-klis-ac-2027','university':'筑波大学','faculty':'情報学群','department':'知識情報・図書館学類',
           'admission_method':'アドミッションセンター入試','fiscal_year':2027,'exam_year':2026}
    spec={'case_id':cycle['case_id'],'logical_id':'tsukuba-ac-ai-faq','fiscal_year':2027,'profile_version':'fixture','fact_key':'generative_ai_policy',
          'url':record['url'],'expected_sha256':sha,'section_start':'AC開始','section_end':'他方式開始','anchors':[{'page':1,'pattern':'文章チェックも含め.*?下線を引いてください。'}],
          'value':{'allowed':'生成AI利用の表示案内','not_accepted':''},'sentences':['生成AIの利用を明示します。'],'applicability':'controlled AC fixture','temporal_status':'fixture'}
    return record,spec,cycle


def test_extracts_each_condition_from_its_own_scope_and_quote(faq):
    r,s,c=faq;x=extract_conditions(r,s,c)
    assert x['values']=={'ai_text_underline_required':True,'simple_spellcheck_underline_required':False,'human_advice_underline_required':False,
      'human_advice_activity_report_required':True,'ai_visual_disclosure_required':True}
    p=structured_record(x,'EV-previous');validate_condition_bindings(p)
    assert len(p['proofs'])==6 and p['field_proofs']['ai_text_underline_required']['proof_indices']==[0,1]
    assert p['published_date'] is None and p['source_pdf_sha256'] is None
    assert '下線不要' in p['sentences'][1] and '記載は必須' in p['sentences'][1]


@pytest.mark.parametrize('change',['year','exam_year','method_case','source_hash','missing_clause','foreign_only','ambiguous'])
def test_unknown_or_out_of_scope_is_not_a_false_boolean(faq,change):
    r,s,c=faq
    if change=='year':c['fiscal_year']=2028
    if change=='exam_year':c['exam_year']=2027
    if change=='method_case':c['case_id']='tsukuba-general-2027'
    if change=='source_hash':r['sha256']='f'*64
    if change in ('missing_clause','foreign_only','ambiguous'):
        path=Path(r['local_path']);text=path.read_text(encoding='utf-8')
        clause='MicrosoftWORD等の文書校正機能による単純な誤字脱字修正の場合は、下線を引く必要はありません。'
        text=text.replace(clause,'') if change!='ambiguous' else text.replace(clause,clause*2)
        if change=='foreign_only':text+=clause
        path.write_text(text,encoding='utf-8');r['sha256']=s['expected_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):extract_conditions(r,s,c)


@pytest.mark.parametrize('field',list(FIELDS))
def test_flipped_boolean_cannot_pass_source_binding(faq,field):
    record=structured_record(extract_conditions(*faq),'EV-old')
    record['value'][field]=not record['value'][field]
    with pytest.raises(ValueError):validate_condition_bindings(record)


@pytest.mark.parametrize('mutation',['actor','exception','proof','invented_obligation','prose'])
def test_actor_swaps_missing_exceptions_and_invented_obligations_fail(faq,mutation):
    r=structured_record(extract_conditions(*faq),'EV-old');b=r['field_proofs']['human_advice_underline_required']
    if mutation=='actor':b['actor']='ai_text'
    if mutation=='exception':b['exceptions']=[]
    if mutation=='proof':b['proof_indices']=[0]
    if mutation=='invented_obligation':r['value']['send_AI_report_by_email']=True
    if mutation=='prose':r['sentences'][1]=r['sentences'][1].replace('下線不要','下線必要',1)
    with pytest.raises(ValueError):validate_condition_bindings(r)


@pytest.mark.parametrize('unknown',[None,0,'false'])
def test_renderer_does_not_turn_unknown_into_false(faq,unknown):
    values=extract_conditions(*faq)['values'];values['simple_spellcheck_underline_required']=unknown
    with pytest.raises(ValueError):render_conditions(values)


def test_contract_must_register_all_boolean_fields(faq):
    record=structured_record(extract_conditions(*faq),'EV-old')
    registry={'fact_keys':{'generative_ai_policy':{'status':'active','value':{}}}}
    assert contract_state(record,registry)=='pending_contract'
    registry['fact_keys']['generative_ai_policy']['value']={f:{'type':'boolean'} for f in FIELDS}
    assert contract_state(record,registry)=='candidate'


def test_contract_guard_cannot_be_disabled_by_removing_the_marker(faq):
    record=structured_record(extract_conditions(*faq),'EV-old');record.pop('required_contract_fields')
    registry={'fact_keys':{'generative_ai_policy':{'status':'active','value':{}}}}
    assert contract_state(record,registry)=='pending_contract'


def test_pending_cli_is_not_approved_just_because_other_heads_exist(faq,tmp_path):
    from scripts.revise_notices import run
    r,s,cycle=faq;db_path=tmp_path/'work.sqlite';base=EvidenceStore(db_path)
    profile=dict(cycle,sha256='a'*64,url='https://fixture.ac.jp/guide')
    base.ingest(Extracted(cycle['case_id'],profile,tmp_path/'dummy.pdf',['fixture'],[]),'2026-11-01')
    original={'article_id':'base','case_id':cycle['case_id'],'input_hash':'a'*64,'series':'overview','title':'fixture','text':'# fixture\n\n## 根拠資料\n',
              'claim':{k:cycle[k] for k in ('university','faculty','department','admission_method','fiscal_year')},'evidence_ids':[],'publish_allowed':False}
    base.save_article(original,tmp_path/'original.md');store=RevisionStore(db_path,tmp_path/'before.sqlite')
    old=dict(extract_conditions(r,s,cycle)['base_record'],evidence_id='EV-old');registry={'fact_keys':{'generative_ai_policy':{'status':'active','value':{}}}}
    batch=store.stage([old],registry);article=revise_article(original,[old],date(2026,11,1))
    store.finalize(batch,[article],{'success':True,'batch_input_sha':batch['input_sha'],'articles_sha256':hashlib.sha256(canonical([article]).encode()).hexdigest()},registry)
    before=store.heads();root=tmp_path/'monitor';bodies=root/'bodies';bodies.mkdir(parents=True)
    (bodies/(r['sha256']+'.html')).write_bytes(Path(r['local_path']).read_bytes())
    with sqlite3.connect(root/'monitor.sqlite') as db:
        db.execute('CREATE TABLE targets(url TEXT,last_success REAL,last_error TEXT,last_sha TEXT)');db.execute('INSERT INTO targets VALUES(?,?,NULL,?)',(r['url'],time.time(),r['sha256']))
    qa=tmp_path/'qa';(qa/'src/verify/data').mkdir(parents=True);(qa/'src/verify/data/fact_keys.json').write_text(json.dumps(registry))
    s.update(condition_profile='tsukuba-ac-faq-v1',parent_evidence_id='EV-old');spec=tmp_path/'spec.json';spec.write_text(json.dumps([s]),encoding='utf-8')
    report=run(spec,root,tmp_path/'unused.json',db_path,db_path,qa,tmp_path/'pending',date(2026,11,1))
    assert not report['approved'] and report['pending_contract']==['generative_ai_policy'] and report['revised_articles']==0
    assert store.heads()==before


def test_faq_is_placed_in_official_document_guidance_before_general_advice(faq):
    record=structured_record(extract_conditions(*faq),'EV-old')
    base={'article_id':'base','case_id':faq[2]['case_id'],'text':'# fixture\n\n## 書類\n\n公式の書類説明。\n\n### 練習（編集上の助言）\n\n練習。\n\n## 根拠資料\n',
          'evidence_ids':[],'claims':[]}
    article=revise_article(base,[record],date(2026,11,1))
    assert article['text'].index('提出書類と生成AI')<article['text'].index('編集上の助言')
    assert article['text'].count('AC入試のFAQでは')==1


def test_raw_source_hash_and_positions_bind_every_condition_reference(faq):
    record=structured_record(extract_conditions(*faq),'EV-old')
    report=audit_condition_source(record,faq[0]['local_path'])
    assert report['proof_references']==6 and report['unique_source_ranges']==5
    record['proofs'][0]['normalized_start']+=1
    with pytest.raises(ValueError,match='raw source position'):audit_condition_source(record,faq[0]['local_path'])
