import copy
from datetime import date
import pytest
from test_faq_policy import faq
from admissions_pipeline.faq_policy import extract_conditions,structured_record,check_article_conditions
from admissions_pipeline.faq_mutations import variants
from admissions_pipeline.notice_articles import revise_article


def article(faq):
    record=structured_record(extract_conditions(*faq),'EV-old')
    base={'article_id':'base','case_id':faq[2]['case_id'],'text':'# fixture\n\n## 書類\n\n### 練習（編集上の助言）\n\n助言。\n\n## 根拠資料\n',
          'evidence_ids':[],'claims':[]}
    return record,revise_article(base,[record],date(2026,11,1))


def test_positive_value_driven_block_passes(faq):
    record,positive=article(faq)
    assert check_article_conditions(positive,record)


@pytest.mark.parametrize('index',range(7))
def test_controlled_output_rejects_all_seven_variants_without_claiming_independent_detection(faq,index):
    record,positive=article(faq)
    mutation=variants(positive,record['evidence_id'])[index]
    negative=dict(positive,text=mutation['text'])
    with pytest.raises(ValueError):check_article_conditions(negative,record)


def test_extra_FAQ_claim_cannot_escape_to_another_section(faq):
    record,positive=article(faq)
    positive['text']=positive['text'].replace('助言。','追加の義務が必要です['+record['evidence_id']+']。')
    with pytest.raises(ValueError,match='outside'):check_article_conditions(positive,record)
