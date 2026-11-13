"""Issue #34 (Work PR #33): a correct sentence must not be rejected just because it words the topic differently.

The cues decide whether a paragraph is about the fact it cites. They were too narrow for two real, correct
sentences: a 小作文 (essay) length limit and an interview sentence with a comma before what is evaluated.
Widening them must not let a swapped citation through, so each correct wording is paired with a swap.
"""
import pytest

from tests.test_citation_semantics import CLAIM, EVIDENCE, SENTENCES, article, topic

from src.verify.strict_claims import check_article_strict

STATEMENT = ["志願理由書は800字以内でまとめます。", "面接の前に小作文（800字以内）を課します。", "小作文は800字以内です。",
             "志望理由に関する文章は800字以内です。"]
INTERVIEW = ["面接の配点には、書類審査を含みます。", "個別面接では、論理的思考力・表現力・コミュニケーション能力を評価すると記載されています。",
             "面接では、人物を総合的に評価します。", "口述試験では、専門分野の基礎知識が問われます。"]


def one(eid, sentence, cited=None):
    return f"# 〇〇大学 環境学部 夏秋AO入試\n\n{sentence}[{cited or eid}]\n\n最新情報は大学公式サイトでご確認ください。\n"


@pytest.mark.parametrize("sentence", STATEMENT)
def test_every_natural_way_to_state_the_length_limit_is_accepted(sentence):
    assert [i for i in check_article_strict(one("EV-SL", sentence), CLAIM, EVIDENCE) if i.category == "citation_topic_mismatch"] == []


@pytest.mark.parametrize("sentence", INTERVIEW)
def test_every_natural_way_to_state_what_the_interview_covers_is_accepted(sentence):
    assert [i for i in check_article_strict(one("EV-IS", sentence), CLAIM, EVIDENCE) if i.category == "citation_topic_mismatch"] == []


@pytest.mark.parametrize("other", [e for e in SENTENCES if e not in ("EV-SL", "EV-PS")])
def test_the_length_limit_citation_on_an_unrelated_sentence_is_still_reported(other):
    swapped = article(**{other: "EV-SL"})
    assert any("EV-SL" in i.detail for i in topic(swapped)), other


@pytest.mark.parametrize("other", [e for e in SENTENCES if e not in ("EV-IS", "EV-IV")])
def test_the_interview_scope_citation_on_an_unrelated_sentence_is_still_reported(other):
    swapped = article(**{other: "EV-IS"})
    assert any("EV-IS" in i.detail for i in topic(swapped)), other


def test_the_wider_interview_pattern_does_not_cross_a_sentence_end():
    text = one("EV-IS", "面接では、日時を確認してください。出願資料を評価する方法は別に示します。")
    assert any(i.category == "citation_topic_mismatch" for i in check_article_strict(text, CLAIM, EVIDENCE))
