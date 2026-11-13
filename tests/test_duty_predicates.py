"""Registry 1.7.1: a sentence about a duty / permission / prohibition must KEEP its predicate (a closed class), whatever
replaced it. The wrong wordings below are not listed anywhere; the rule only knows what the right sentence has to contain.
"""
import pytest

from src.article_qa.flip_sealed_f import FLIPS_SEALED_F
from src.article_qa.flip_sweep import FLIPS, FLIPS_HELD_OUT, FLIPS_HELD_OUT_B, FLIPS_HELD_OUT_C
from src.article_qa.flip_sealed import FLIPS_SEALED_D
from src.article_qa.flip_sealed_e import FLIPS_SEALED_E
from src.verify.fact_registry import get_registry
from src.verify.qualitative import check_qualitative

REGISTRY = get_registry()


def run(sentence, key, value, **extra):
    record = {"evidence_id": "EV-1", "fact_key": key, "value": value, **extra}
    return [i.detail for i in check_qualitative(f"# 見出し\n\n{sentence}[EV-1]\n", {"EV-1": record}, REGISTRY)]


ELIG = ("eligibility", {"logic": "all"})
RIGHT_ELIG = ["出願資格は募集要項p.10の共通条件(1)〜(4)を全て満たすことが必要です。", "出願資格として、次の条件をすべて満たす必要があります。",
              "出願資格は、(1)〜(4)を満たすことが求められます。", "出願資格を満たすことが条件です。"]
WRONG_ELIG = ["出願資格は募集要項p.10の共通条件(1)〜(4)を全て満たすことが問われません。", "出願資格は、(1)〜(4)を満たすかどうかは各自の判断です。",
              "出願資格については、(1)〜(4)を満たすことは考慮されません。", "出願資格は、(1)〜(4)を満たすことが望ましいです。"]


@pytest.mark.parametrize("sentence", RIGHT_ELIG)
def test_the_right_eligibility_sentence_passes(sentence):
    assert run(sentence, *ELIG) == []


@pytest.mark.parametrize("sentence", WRONG_ELIG)
def test_an_eligibility_sentence_that_lost_its_duty_predicate_is_reported(sentence):
    assert run(sentence, *ELIG), sentence


AI = ("generative_ai_policy", {"allowed": "学びを深める補助として利用", "not_accepted": "AI生成の出願書類を本人独自成果物とすること"})


def test_ai_use_keeps_its_permission_predicate():
    ok = "生成AIを学びを深める補助的なツールとして使うことは認められています。AI生成の出願書類は本人の独自成果物とはみなされません。"
    assert run(ok, *AI) == []
    for wrong in ["生成AIを学びを深めるために使うことは見送られています。AI生成の出願書類は本人の独自成果物とはみなされません。",
                  "生成AIを学びのために利用するかどうかは各自で決めます。AI生成の出願書類は本人の独自成果物とはみなされません。"]:
        assert run(wrong, *AI), wrong


def test_the_faq_record_without_a_permission_value_is_not_asked_for_a_permission_predicate():
    faq = ("generative_ai_policy", {"allowed": "生成AI使用時の表示方法がFAQで案内されている", "not_accepted": ""})
    assert run("生成AIの使用時の表示方法は、FAQで案内されています。", *faq) == []


VISIT = {"qualifier": "簡易書留・速達で郵送必着。持参不可"}


def test_no_visit_keeps_its_prohibition_predicate():
    deadline = ("deadline", {"date": "2026-10-27", **VISIT})
    for ok in ["書類は郵送必着で、持参はできません。", "持参・宅配便は不可です。", "持参は受け付けません。"]:
        assert run(ok, *deadline) == [], ok
    for wrong in ["書類は郵送必着で、持参も歓迎します。", "持参についてはご自由にどうぞ。", "書類は郵送必着で、持参するかは自由です。"]:
        assert run(wrong, *deadline), wrong


def test_a_sentence_about_something_else_is_not_touched_by_these_rules():
    assert run("募集人員は150名です。", "quota", {"count": 150, "unit": "名"}) == []


def test_no_catalogue_wording_is_registered_as_a_forbidden_phrase():
    """The rules above know right predicates, not wrong wordings: none of the flip catalogues' replacements is in them."""
    import json
    registry_text = json.dumps(REGISTRY.data, ensure_ascii=False)
    for cat in (FLIPS_SEALED_F,):
        for _, _, _, replacement, _ in cat:
            assert replacement not in registry_text, replacement
