"""Scope-bound FAQ conditions, exact field proofs, and value-driven prose.

Contract names remain proposals until the pinned Claude registry contains them.
No unknown condition is coerced to False; original v0.5 heads are not changed here.
"""
import hashlib
import re
from .extract import normalized_with_positions,normalize
from .store import canonical
from .supplements import extract_notice,source_pages

FIELDS={
 'ai_text_underline_required':{'actor':'ai_text','action':'underline','clauses':[
    '文章チェックも含め、生成AIが実際に生成・修正した箇所には、すべて下線を引いてください。',
    'また、その修正によって間接的にでも内容が影響された場合には、影響した箇所すべてに下線を引いてください。'],
    'polarity':'下線を引いてください','exceptions':['simple_spellcheck_is_a_different_condition']},
 'simple_spellcheck_underline_required':{'actor':'simple_spellcheck','action':'underline','clauses':[
    'MicrosoftWORD等の文書校正機能による単純な誤字脱字修正の場合は、下線を引く必要はありません。'],
    'polarity':'下線を引く必要はありません','exceptions':['not_an_exemption_for_AI_content_generation_or_revision']},
 'human_advice_underline_required':{'actor':'human_advice','action':'underline','clauses':[
    '他人の添削・助言による修正等には、下線を引く必要はありませんが、活動経過報告書での記載は必須です。'],
    'polarity':'下線を引く必要はありません','exceptions':['activity_report_still_required']},
 'human_advice_activity_report_required':{'actor':'human_advice','action':'activity_report','clauses':[
    '他人の添削・助言による修正等には、下線を引く必要はありませんが、活動経過報告書での記載は必須です。'],
    'polarity':'記載は必須です','exceptions':[]},
 'ai_visual_disclosure_required':{'actor':'ai_visual','action':'disclosure','clauses':[
    '画像・図・表等の説明文や脚注に、生成AIで作成したことが分かるように明示してください。'],
    'polarity':'明示してください','exceptions':['visual_disclosure_is_not_text_underlining']},
}
POLARITY={'下線を引いてください':True,'下線を引く必要はありません':False,'記載は必須です':True,'明示してください':True}


def extract_conditions(record,spec,cycle):
    if (cycle['case_id']!='tsukuba-klis-ac-2027' or cycle['fiscal_year']!=2027 or cycle['exam_year']!=2026
        or spec['case_id']!=cycle['case_id']):raise ValueError('FAQ AC cycle not reviewed; no year/method extrapolation')
    original=extract_notice(spec,record,cycle)
    raw=source_pages(record)[0];text,positions=normalized_with_positions(raw)
    a=text.find(normalize(spec['section_start']));b=text.find(normalize(spec['section_end']),a)
    if a<0 or b<=a:raise ValueError('AC section boundaries missing')
    values={};proofs=[];field_proofs={}
    for name,rule in FIELDS.items():
        indices=[]
        for clause in rule['clauses']:
            quote=normalize(clause);hits=list(re.finditer(re.escape(quote),text[a:b]))
            if len(hits)!=1:raise ValueError('condition is unknown or ambiguous: '+name)
            start=a+hits[0].start();end=a+hits[0].end()
            proof={'page':1,'quote':raw[positions[start]:positions[end-1]+1],'normalized_start':start,'normalized_end':end,
                   'section':spec['section_start'],'source_kind':'html'}
            if rule['polarity'] not in quote:raise ValueError('condition polarity missing from its own quote')
            indices.append(len(proofs));proofs.append(proof)
        values[name]=POLARITY[rule['polarity']]
        field_proofs[name]={'value':values[name],'actor':rule['actor'],'action':rule['action'],'proof_indices':indices,
                            'exceptions':rule['exceptions'],'applies_to':'tsukuba-klis-ac-2027'}
    return {'base_record':original,'values':values,'proofs':proofs,'field_proofs':field_proofs,'unknown_conditions':[],
            'retrieved_at':record['retrieved_at'],'published_date':None,'contract_status':'pending'}


def validate_condition_bindings(record):
    if record.get('case_id')!='tsukuba-klis-ac-2027' or record.get('fiscal_year')!=2027:
        raise ValueError('FAQ condition scope was not reviewed')
    if set(record['value'])-{'allowed','not_accepted'}-set(FIELDS):raise ValueError('unsupported FAQ obligation')
    for name,rule in FIELDS.items():
        value=record['value'].get(name)
        if type(value) is not bool:raise ValueError('condition not confirmed: '+name)
        binding=record.get('field_proofs',{}).get(name,{})
        if binding.get('actor')!=rule['actor'] or binding.get('action')!=rule['action'] or binding.get('applies_to')!=record['case_id']:
            raise ValueError('condition actor/action/scope mismatch')
        if binding.get('exceptions')!=rule['exceptions']:raise ValueError('condition exception metadata missing or changed')
        indices=binding.get('proof_indices',[])
        if len(indices)!=len(rule['clauses']):raise ValueError('condition proof coverage incomplete')
        for i,clause in zip(indices,rule['clauses']):
            if type(i) is not int or i<0 or i>=len(record['proofs']):raise ValueError('condition proof index invalid')
            if normalize(record['proofs'][i]['quote'])!=normalize(clause):raise ValueError('condition proof content mismatch')
        if value!=POLARITY[rule['polarity']] or binding.get('value')!=value:raise ValueError('condition contradicts its own source quote')
    if record.get('sentences')!=render_conditions(record['value']):raise ValueError('FAQ prose is not derived from the confirmed conditions')


def render_conditions(values):
    if any(type(values.get(k)) is not bool for k in FIELDS):raise ValueError('unconfirmed FAQ condition; do not invent a boolean')
    ai=('下線を引くよう案内しています' if values['ai_text_underline_required'] else '下線は不要と案内しています')
    spelling=('必要' if values['simple_spellcheck_underline_required'] else '不要')
    human=('必要' if values['human_advice_underline_required'] else '不要')
    report=('必須' if values['human_advice_activity_report_required'] else '任意')
    visual=('生成AIで作成した画像・図・表等は、説明文や脚注にその使用を明示します。' if values['ai_visual_disclosure_required']
            else '生成AIで作成した画像・図・表等について、説明文や脚注での使用明示は任意です。')
    return [f'AC入試のFAQでは、文章チェックを含め生成AIが生成・修正した箇所と、その修正で間接的に影響した箇所すべてに{ai}。',
            f'文書校正機能による単純な誤字脱字修正は下線{spelling}です。他人の添削・助言の修正も下線{human}ですが、活動経過報告書への記載は{report}です。',
            visual]


def audit_condition_source(record,body_path):
    """Mechanical raw-file/position audit, separate from independent semantic QA."""
    validate_condition_bindings(record)
    if record.get('source_kind')!='html':raise ValueError('FAQ condition source must be HTML')
    pages=source_pages({'local_path':str(body_path),'kind':'html','url':record['source_url'],'sha256':record['source_sha256']})
    text=normalize(pages[0]);unique=set()
    for proof in record['proofs']:
        start,end=proof.get('normalized_start'),proof.get('normalized_end')
        if (proof.get('page')!=1 or type(start) is not int or type(end) is not int or not 0<=start<end<=len(text)
            or text[start:end]!=normalize(proof['quote'])):raise ValueError('FAQ proof does not match its raw source position')
        unique.add((1,start,end))
    return {'status':'pass','field_count':len(FIELDS),'proof_references':len(record['proofs']),'unique_source_ranges':len(unique),
            'source_sha256':record['source_sha256'],'semantic_independent_QA':False}


def check_article_conditions(article,record):
    """Controlled-template boundary, not a replacement for independent QA."""
    validate_condition_bindings(record)
    heading='## 提出書類と生成AIの条件・例外（公式FAQ）'
    if article['text'].count(heading)!=1:raise ValueError('FAQ article section is absent or duplicated')
    prefix,body=article['text'].split(heading,1)
    following=re.search(r'\n#{1,3} ',body)
    tail=body[following.start():] if following else ''
    if following:body=body[:following.start()]
    outside=(prefix+tail).split('## 根拠資料',1)[0]
    if '['+record['evidence_id']+']' in outside:raise ValueError('FAQ evidence is cited outside its controlled section')
    cited=set(re.findall(r'\[(EV-[A-Za-z0-9_-]+)\]',body))
    if cited!={record['evidence_id']}:raise ValueError('FAQ article section cites different evidence')
    clean=re.sub(r'\[EV-[A-Za-z0-9_-]+\]','',body)
    if normalize(clean)!=normalize(' '.join(render_conditions(record['value']))):
        raise ValueError('FAQ section differs from the confirmed value-driven template')
    return True


def structured_record(candidate,parent_id,profile_version='faq-conditions-2026-11-01-v1'):
    record=dict(candidate['base_record']);record['value']=dict(record['value'],**candidate['values'])
    record.update(proofs=candidate['proofs'],field_proofs=candidate['field_proofs'],required_contract_fields=list(FIELDS),
                  profile_version=profile_version,parent_evidence_id=parent_id,condition_profile='tsukuba-ac-faq-v1')
    record['evidence_id']='EV-U-'+hashlib.sha256(canonical([record['logical_id'],record['source_sha256'],record['value'],profile_version]).encode()).hexdigest()[:12]
    record['sentences']=render_conditions(record['value'])
    validate_condition_bindings(record)
    return record
