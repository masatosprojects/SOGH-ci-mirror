"""Seven explicit semantic negatives. Detection is not inferred from coverage."""
def variants(article,eid):
    text=article['text'];rows=[]
    def add(key,old,new,fields,markers):
        if old not in text:raise ValueError('negative no longer applies: '+key)
        changed=text.replace(old,new,1)
        if changed==text:raise ValueError('no mutation')
        rows.append({'case':key,'text':changed,'target_fields':fields,'target_markers':markers})
    add('ai_underline_unnecessary','その修正で間接的に影響した箇所すべてに下線を引くよう案内しています',
        'その修正で間接的に影響した箇所すべての下線は不要です',['ai_text_underline_required'],['文章チェック','生成AIが生成'])
    add('spellcheck_requires_underline','文書校正機能による単純な誤字脱字修正は下線不要',
        '文書校正機能による単純な誤字脱字修正は下線必要',['simple_spellcheck_underline_required'],['単純な誤字脱字'])
    add('human_report_optional','活動経過報告書への記載は必須','活動経過報告書への記載は任意',
        ['human_advice_activity_report_required'],['活動経過報告書への記載は任意'])
    # Swapped ACTORS, not just the presence of 必要/不要 elsewhere in the paragraph.
    swapped=text.replace('文章チェックを含め生成AIが生成・修正した箇所','HUMAN_SWAP_MARKER',1).replace('他人の添削・助言の修正','生成AIが生成・修正した箇所',1).replace('HUMAN_SWAP_MARKER','他人の添削・助言の修正')
    rows.append({'case':'AI_human_actor_swap','text':swapped,'target_fields':['ai_text_underline_required','human_advice_underline_required'],'target_markers':['他人の添削','生成AIが生成']})
    add('mixed_paragraph_wrong_condition','他人の添削・助言の修正も下線不要','他人の添削・助言の修正も下線必要',
        ['human_advice_underline_required'],['他人の添削'])
    anchor='生成AIで作成した画像・図・表等は、説明文や脚注にその使用を明示します。'
    # There is a citation inserted before the full stop in generated articles.
    cited=anchor[:-1]+'['+eid+']。'
    add('invented_permission_email',cited,cited+' 生成AIを使用した場合は、大学へ電子メールで事前許可申請することが必須です['+eid+']。',[],['電子メール','事前許可申請'])
    sentence='文書校正機能による単純な誤字脱字修正は下線不要です'
    sentence+=('['+eid+']' if sentence+'['+eid+']' in text else '')+'。'
    add('spellcheck_exception_deleted',sentence,'',
        ['simple_spellcheck_underline_required'],['単純な誤字脱字'])
    if len(rows)!=7 or any(r['text']==text for r in rows):raise ValueError('mutation coverage incomplete')
    return rows


def classify(positive,negative,mutation,eid):
    if not positive.ok:return 'not_evaluable'
    if not negative.ok:return 'detected'
    for row in negative.coverage.get('unverified',[]):
        if eid not in row.get('evidence_id','').split(','):continue
        description=row.get('what','')
        if any(f in description for f in mutation['target_fields']):return 'unverified_only'
        if any(m in description for m in mutation['target_markers']):return 'unverified_only'
    return 'silent_miss'
