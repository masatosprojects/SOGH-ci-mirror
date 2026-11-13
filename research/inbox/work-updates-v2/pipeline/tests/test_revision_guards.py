import copy
import hashlib
import json
from datetime import date
import pytest
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.store import canonical
from test_updates import revision_setup
from test_updates import approve


@pytest.mark.parametrize('mutation',['empty','unknown','wrong_method','wrong_year','different_cycle','lying_list'])
def test_activation_rechecks_structural_evidence_even_if_qa_boolean_is_true(revision_setup,mutation):
    store,record,article,registry=revision_setup
    batch=store.stage([record],registry);revised=revise_article(article,store.effective_records(batch),date(2026,11,1))
    if mutation=='empty':revised['text']='no evidence';revised['evidence_ids']=[]
    if mutation=='unknown':revised['text']+=' [EV-missing]';revised['evidence_ids'].append('EV-missing')
    if mutation=='lying_list':revised['text']='[EV-missing]'
    if mutation=='wrong_method':revised['claim']=dict(revised['claim'],admission_method='異なる方式')
    if mutation=='wrong_year':revised['claim']=dict(revised['claim'],fiscal_year=2028)
    if mutation=='different_cycle':
        with store.connect() as db:
            db.execute("INSERT INTO admission_cycles VALUES('other','他大学','学部',NULL,'方式',2027,2026)")
            db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?)',('EV-other','other','a'*64,'quota',canonical({'count':1}),'{}','source_checked_for_saved_version'))
        revised['text']+=' [EV-other]';revised['evidence_ids'].append('EV-other')
    qa={'success':True,'batch_input_sha':batch['input_sha'],'articles_sha256':hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    with pytest.raises(ValueError):store.finalize(batch,[revised],qa,registry)
    assert store.heads()=={'evidence':{},'articles':{}}
    with store.connect() as db:assert db.execute('SELECT count(*) FROM revised_articles').fetchone()[0]==0


def test_reapproval_creates_a_new_version_and_retains_previous_qa_history(revision_setup):
    store,record,article,registry=revision_setup
    _,first,_=approve(store,record,article,registry)
    batch=store.stage([record],registry,refresh_articles=True)
    revised=revise_article(article,store.effective_records(batch),date(2026,11,1),previous_id=first['article_id'])
    assert revised['article_id']!=first['article_id'] and revised['parent_article_id']==first['article_id']
    qa={'success':True,'batch_input_sha':batch['input_sha'],'articles_sha256':hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    assert store.finalize(batch,[revised],qa,registry)
    with store.connect() as db:assert db.execute('SELECT count(*) FROM revised_articles').fetchone()[0]==2
