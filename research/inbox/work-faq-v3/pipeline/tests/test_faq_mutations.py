from types import SimpleNamespace
import pytest
from admissions_pipeline.faq_mutations import classify,variants
from admissions_pipeline.faq_policy import render_conditions


def test_seven_realistic_mutations_preserve_citation_identity():
    values={'ai_text_underline_required':True,'simple_spellcheck_underline_required':False,'human_advice_underline_required':False,
            'human_advice_activity_report_required':True,'ai_visual_disclosure_required':True}
    text=' '.join(s.rstrip('。')+'[EV-fixture]。' for s in render_conditions(values))
    rows=variants({'text':text},'EV-fixture')
    assert len(rows)==7 and len({x['case'] for x in rows})==7
    assert all(x['text']!=text and '[EV-fixture]' in x['text'] for x in rows)
    assert '電子メール' in next(x['text'] for x in rows if x['case']=='invented_permission_email')


@pytest.mark.parametrize('case,expected',[('detected','detected'),('unverified','unverified_only'),('other','silent_miss'),('bad_positive','not_evaluable')])
def test_unverified_is_not_detection_and_unrelated_coverage_is_not_credit(case,expected):
    positive=SimpleNamespace(ok=case!='bad_positive')
    negative=SimpleNamespace(ok=case!='detected',coverage={'unverified':[]})
    if case=='unverified':negative.coverage['unverified']=[{'evidence_id':'EV-one','what':'boolean field=False'}]
    if case=='other':negative.coverage['unverified']=[{'evidence_id':'EV-unrelated','what':'boolean field=False'}]
    assert classify(positive,negative,{'target_fields':['field'],'target_markers':[]},'EV-one')==expected
