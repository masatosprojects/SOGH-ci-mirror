"""Behaviour of the second g2 patch (patches/g2-faq/work-faq-g2-unconfirmed-section.patch): the article section for an official FAQ whose applicability is UNCONFIRMED (STR-076; wording adopted by the owner 2026-11-08).
Run by tests/test_g2_unconfirmed_patch.py inside a COPY of Work's pipeline that carries BOTH patches, together with tests/behaviour_g2_faq.py (its fixtures). SELF_TEST; synthetic FAQ page only."""
import copy
from datetime import date

import pytest

from admissions_pipeline.faq_policy import check_article_conditions, extract_conditions, structured_record
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.unconfirmed_faq import HEADING, NOTICE, check_unconfirmed_section, is_unconfirmed_faq, render_unconfirmed_section
from test_behaviour_g2_faq import CASE, CYCLE, spec_for, world  # noqa: F401  (world is a fixture)

BASE = {"article_id": "base", "case_id": CASE, "text": "# fixture\n\n## 書類\n\n公式の書類説明。\n\n### 練習（編集上の助言）\n\n練習。\n\n## 根拠資料\n", "evidence_ids": [], "claims": []}
AS_OF = date(2026, 11, 8)


def unknown_record(world, eid=None):
    record, sha, _ = world
    rec = structured_record(extract_conditions(record, spec_for(sha, unknown=True), None), None, "fixture-g2")
    return rec


def bound_record(world):
    record, sha, _ = world
    return structured_record(extract_conditions(record, spec_for(sha, unknown=False), copy.deepcopy(CYCLE)), None, "fixture-g2")


def test_an_unconfirmed_record_gets_its_own_section_that_says_so_first_and_cites_every_sentence(world):
    rec = unknown_record(world)
    assert is_unconfirmed_faq(rec) and rec["case_id"] is None
    art = revise_article(BASE, [rec], AS_OF)
    text = art["text"]
    assert text.count(HEADING) == 1 and check_unconfirmed_section(text, rec) is True
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    assert section.lstrip().startswith(NOTICE.split("{url}")[0][:20])  # the unconfirmed notice comes before any condition
    cite = "[" + rec["evidence_id"] + "]"
    derived = section.split("\n\n")[2]  # after the notice: the derived sentences, EACH cited (an element of render_conditions may hold two sentences: STR-099 / D03 finding)
    sentences = [x for x in derived.replace("。 ", "。\n").split("\n") if x.strip()]
    assert len(sentences) >= 4 and all(cite in x for x in sentences) and section.count(cite) == 1 + len(sentences) and cite in section.split("\n\n")[1]  # the notice (once) and every derived sentence
    for word in ("2027", "情報学群", "知識情報", "tsukuba-klis"):
        assert word not in section  # it states no year, faculty or cycle
    assert text.index(HEADING) < text.index("編集上の助言") and rec["evidence_id"] in art["evidence_ids"] and any(c["evidence_id"] == rec["evidence_id"] for c in art["claims"])
    assert any("適用年度・学類は未確認" in line and rec["evidence_id"] in line for line in text.split("## 根拠資料", 1)[1].splitlines())


def test_a_case_bound_faq_and_an_unconfirmed_one_stay_two_sections_and_both_checks_pass(world):
    bound, unknown = bound_record(world), unknown_record(world)
    unknown = dict(unknown, evidence_id="EV-U-unconfirmed1")
    art = revise_article(BASE, [bound, unknown], AS_OF)
    text = art["text"]
    assert text.index("## 提出書類と生成AIの条件・例外（公式FAQ）") < text.index(HEADING) < text.index("編集上の助言")
    assert check_article_conditions(art, bound) is True and check_unconfirmed_section(text, unknown) is True
    assert "[" + unknown["evidence_id"] + "]" not in text.split(HEADING)[0] and "[" + bound["evidence_id"] + "]" not in text.split(HEADING, 1)[1].split("\n## ", 1)[0]


def test_the_article_without_an_unconfirmed_record_is_what_it_was(world):
    bound = bound_record(world)
    art = revise_article(BASE, [bound], AS_OF)
    assert HEADING not in art["text"] and check_article_conditions(art, bound) is True
    with pytest.raises(ValueError, match="no applicable notices"):
        revise_article(BASE, [], AS_OF)


def test_the_identity_of_the_revision_changes_with_the_unconfirmed_section(world):
    bound, unknown = bound_record(world), unknown_record(world)
    a, b = revise_article(BASE, [bound], AS_OF), revise_article(BASE, [bound, dict(unknown, evidence_id="EV-U-unconfirmed1")], AS_OF)
    assert a["article_id"] != b["article_id"] and a["revision_hash"] != b["revision_hash"]


@pytest.mark.parametrize("tamper", ["sentence", "heading_twice", "cited_outside", "notice_removed", "year_added", "other_evidence", "missing"])
def test_the_check_refuses_a_section_that_is_not_the_controlled_one(world, tamper):
    rec = unknown_record(world)
    text = revise_article(BASE, [rec], AS_OF)["text"]
    cite = "[" + rec["evidence_id"] + "]"
    if tamper == "sentence":
        text = text.replace("生成AIが生成・修正した箇所", "生成AIが生成した箇所だけ")
    if tamper == "heading_twice":
        text = text.replace("## 根拠資料", HEADING + "\n\n## 根拠資料", 1)
    if tamper == "cited_outside":
        text = text.replace("公式の書類説明。", "公式の書類説明。" + cite, 1)
    if tamper == "notice_removed":
        text = text.replace("ただし、このFAQの文面からは、どの年度・どの学類の出願に当てはまるかを確認できていません。", "")
    if tamper == "year_added":
        text = text.replace("が書かれています。", "が書かれています（2027年度の学類向け）。", 1)
    if tamper == "other_evidence":
        text = text.replace(cite, "[EV-U-other]", 1)
    if tamper == "missing":
        text = text.replace(HEADING, "## 別の見出し")
    with pytest.raises(ValueError):
        check_unconfirmed_section(text, rec)


def test_a_case_bound_record_is_not_an_unconfirmed_one_and_cannot_be_rendered_as_one(world):
    bound = bound_record(world)
    assert not is_unconfirmed_faq(bound)
    with pytest.raises(ValueError, match="not an unconfirmed"):
        render_unconfirmed_section(bound)


def test_a_record_that_claims_unknown_but_carries_a_binding_cannot_be_rendered(world):
    rec = unknown_record(world)
    rec["fiscal_year"] = 2027
    with pytest.raises(ValueError, match="STR-076"):
        render_unconfirmed_section(rec)
