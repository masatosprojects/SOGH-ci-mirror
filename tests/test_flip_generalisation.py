"""Generalisation of the meaning checks to wordings nobody listed.

* article_sentence_rules guard the STRUCTURE of boilerplate caveat sentences (確認・必要 must stay), so a rewrite
  that no rule lists ("…は済んでいます") is still caught.
* The sealed set D (src/article_qa/flip_sealed.py) must stay disjoint from the development catalogs.
"""
import copy

import pytest

from src.article_qa.flip_sealed import FLIPS_SEALED_D
from src.article_qa.flip_sweep import FLIPS, FLIPS_HELD_OUT, FLIPS_HELD_OUT_B, FLIPS_HELD_OUT_C
from src.verify.fact_registry import get_registry, validate_registry_data
from src.verify.qualitative import check_qualitative

REGISTRY = get_registry()


def found(sentence):
    return [i.detail for i in check_qualitative(f"# 見出し\n\n{sentence}\n", {}, REGISTRY)]


RIGHT = ["出願資格の個別判定、必要書類の全件、最新の訂正・追加案内は別途確認が必要です。",
         "出願資格の個別判定と公開前の最新版確認は別途必要です。",
         "最新情報は大学公式サイトでご確認ください。",
         "最新の募集要項は公式サイトをご覧ください。",
         "個別判定が必要な場合は、入試担当窓口に問い合わせてください。"]

WRONG = ["出願資格の個別判定と公開前の最新版確認は済んでいます。",
         "出願資格の個別判定と公開前の最新版確認は完了しています。",
         "出願資格の個別判定と公開前の最新版確認は不要になりました。",
         "出願資格の個別判定は別途確認が行われました。",
         "最新の訂正・追加案内は反映済みです。",
         "最新情報は大学公式サイトに掲載されています。",
         "個別判定は大学が行います。"]


@pytest.mark.parametrize("sentence", RIGHT)
def test_the_boilerplate_caveat_in_its_right_forms_passes(sentence):
    assert found(sentence) == []


@pytest.mark.parametrize("sentence", WRONG)
def test_a_boilerplate_caveat_that_lost_its_action_is_reported_whatever_the_new_wording(sentence):
    assert found(sentence), sentence


def test_a_sentence_that_does_not_mention_the_boilerplate_topic_is_not_touched():
    assert found("募集人員は150名です。") == []


def _broken(mutate):
    data = copy.deepcopy(REGISTRY.data)
    mutate(data)
    return validate_registry_data(data)


def test_sentence_rules_are_validated():
    assert validate_registry_data(REGISTRY.data) == []
    assert _broken(lambda d: d["article_sentence_rules"][0].pop("must_any"))
    assert _broken(lambda d: d["article_sentence_rules"][0].update(applies_to=["re:("]))
    assert _broken(lambda d: d["article_sentence_rules"][0].update(category="made_up"))


def test_the_sealed_set_is_disjoint_from_every_development_catalogue():
    development = {(p, r) for cat in (FLIPS, FLIPS_HELD_OUT, FLIPS_HELD_OUT_B, FLIPS_HELD_OUT_C) for _, _, p, r, _ in cat}
    assert not [(p, r) for _, _, p, r, _ in FLIPS_SEALED_D if (p, r) in development]
    ids = [row[0] for row in FLIPS_SEALED_D]
    assert len(ids) == len(set(ids)) == 29 and all(i.startswith("d_") for i in ids)
    assert all(old != new for _, _, old, new, _ in FLIPS_SEALED_D)


def test_the_sealed_set_e_is_disjoint_from_every_other_catalogue_and_from_d():
    from src.article_qa.flip_sealed_e import FLIPS_SEALED_E
    others = {(p, r) for cat in (FLIPS, FLIPS_HELD_OUT, FLIPS_HELD_OUT_B, FLIPS_HELD_OUT_C, FLIPS_SEALED_D) for _, _, p, r, _ in cat}
    assert not [(p, r) for _, _, p, r, _ in FLIPS_SEALED_E if (p, r) in others]
    ids = [row[0] for row in FLIPS_SEALED_E]
    assert len(ids) == len(set(ids)) == 29 and all(i.startswith("e_") for i in ids)
    assert all(old != new for _, _, old, new, _ in FLIPS_SEALED_E)
