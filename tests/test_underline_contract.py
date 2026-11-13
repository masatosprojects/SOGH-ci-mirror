"""Issue #39: the FAQ's underline rules as structured values (registry 1.6.0, generative_ai_policy).

The sentences below are the three Work generates from those values (they are identical to the ones now in the
delivery). Every wrong version changes ONE thing; each must be reported, the right wording must not.
"""
import pytest

from src.verify.fact_registry import get_registry
from src.verify.qualitative import check_qualitative, semantic_coverage

REGISTRY = get_registry()
EID = "EV-U-faq"
VALUE = {"allowed": "生成AI使用時の表示方法がFAQで案内されている", "not_accepted": "",
         "ai_text_underline_required": True, "simple_spellcheck_underline_required": False,
         "human_advice_underline_required": False, "human_advice_activity_report_required": True,
         "ai_visual_disclosure_required": True}
RECORD = {"evidence_id": EID, "fact_key": "generative_ai_policy", "value": VALUE}

S1 = "AC入試のFAQでは、文章チェックを含め生成AIが生成・修正した箇所と、その修正で間接的に影響した箇所すべてに下線を引くよう案内しています"
S2 = "文書校正機能による単純な誤字脱字修正は下線不要です"
S3 = "他人の添削・助言の修正も下線不要ですが、活動経過報告書への記載は必須です"
S4 = "生成AIで作成した画像・図・表等は、説明文や脚注にその使用を明示します"


def article(*sentences):
    return "# 〇〇大学\n\n" + "。".join(s + f"[{EID}]" for s in sentences) + "。\n"


def found(*sentences, record=RECORD):
    return [i.detail for i in check_qualitative(article(*sentences), {EID: record}, REGISTRY)]


def test_the_right_wording_is_accepted():
    assert found(S1, S2, S3, S4) == []


def test_the_right_wording_in_other_natural_phrasings_is_accepted():
    assert found(S1, "文書校正機能による単純な誤字脱字の修正には、下線を引く必要はありません", S3.replace("下線不要です", "下線を引く必要はありません"),
                 "AIが作成した画像や図の使用は、説明文で明示します") == []


NEGATIVES = {
    "spellcheck exception turned into a duty": (S1, "文書校正機能による単純な誤字脱字修正は下線必要です", S3, S4),
    "human advice underline turned into a duty (the spellcheck exception stays)": (S1, S2, "他人の添削・助言の修正は下線が必要です。活動経過報告書への記載は必須です", S4),
    "activity report made optional": (S1, S2, "他人の添削・助言の修正も下線不要です。活動経過報告書への記載は任意です", S4),
    "activity report made unnecessary": (S1, S2, "他人の添削・助言の修正も下線不要で、活動経過報告書への記載も不要です", S4),
    "AI revision also exempt from the underline": ("AIが修正した箇所も下線不要です", S2, S3, S4),
    "AI text underline said unnecessary": ("生成AIが生成した箇所は下線を引く必要はありません。AIの修正も下線不要です", S2, S3, S4),
    "actors swapped (AI exempt, human advice underlined)": ("生成AIが修正した箇所は下線不要です", "文書校正機能による単純な誤字脱字修正は下線を引きます", "他人の添削・助言の修正は下線を引きます。活動経過報告書への記載は必須です", S4),
    "spellcheck exception deleted": (S1, S3, S4),
    "human advice exception deleted": (S1, S2, "活動経過報告書への記載は必須です", S4),
    "visual disclosure made unnecessary": (S1, S2, S3, "生成AIで作成した画像・図・表等は、明示不要です"),
    "visual disclosure deleted": (S1, S2, S3),
    "visual disclosure demoted": (S1, S2, S3, "生成AIで作成した画像・図・表等の使用は、説明文や脚注に明示する必要はありません"),
}


@pytest.mark.parametrize("name", list(NEGATIVES))
def test_every_wrong_version_is_reported(name):
    assert found(*NEGATIVES[name]), name


def test_a_remaining_exception_word_in_the_same_paragraph_does_not_rescue_a_flipped_one():
    # '下線不要' still appears (for human advice) but the spellcheck sentence now demands the underline
    assert found(S1, "文書校正機能による単純な誤字脱字修正にも下線を引きます", S3, S4)


def test_an_omitted_field_checks_nothing_for_it_and_is_listed_as_unverified_wording_not_as_correct():
    value = {k: v for k, v in VALUE.items() if k == "allowed" or k == "not_accepted"}
    record = {**RECORD, "value": value}
    # nothing to compare it with: the flip below is NOT detected, and the report says so instead of calling it right
    assert found(S1, "文書校正機能による単純な誤字脱字修正は下線必要です", S3, S4, record=record) == []
    cov = semantic_coverage(article(S2, S3), {EID: record}, REGISTRY)
    assert [u for u in cov["unverified"] if u["what"].startswith("obligation wording")]  # said, but nothing to compare it with


def test_all_five_fields_are_checked_not_listed_as_unverified():
    cov = semantic_coverage(article(S1, S2, S3, S4), {EID: RECORD}, REGISTRY)
    assert cov["unverified"] == []
    assert set(cov["checked"][EID]) >= {"ai_text_underline_true", "simple_spellcheck_underline_false", "human_advice_underline_false",
                                       "human_advice_report_true", "ai_visual_disclosure_true"}


def test_a_boolean_without_a_source_position_is_unverified_when_field_proofs_are_given():
    proofs = {k: [{"section": "AC", "quote": "x"}] for k in VALUE if isinstance(VALUE[k], bool) and k != "ai_visual_disclosure_required"}
    cov = semantic_coverage(article(S1, S2, S3, S4), {EID: {**RECORD, "field_proofs": proofs}}, REGISTRY)
    assert [u["what"] for u in cov["unverified"]] == ["boolean ai_visual_disclosure_required=True"]


def _registry_issues(value):
    record = {"evidence_id": EID, "university": "〇〇大学", "faculty": "x", "department": None, "admission_method": "y", "fiscal_year": 2027,
              "fact_key": "generative_ai_policy", "scope": "target_admission_cycle", "source_url": "https://example.ac.jp/faq",
              "value": value, "proofs": [{"page": 1, "quote": "q"}]}
    return {(i.severity, i.category) for i in REGISTRY.check_record(record, EID)}


def test_the_fields_are_optional_not_nullable_and_must_be_boolean():
    assert not [i for i in _registry_issues({"allowed": "x", "not_accepted": ""}) if i[0] == "error"]  # old records stay valid
    assert not [i for i in _registry_issues(VALUE) if i[0] == "error"]
    assert ("error", "value_type_mismatch") in _registry_issues({**VALUE, "ai_text_underline_required": None})
    assert ("error", "value_type_mismatch") in _registry_issues({**VALUE, "ai_visual_disclosure_required": "true"})


def test_a_bibliography_block_that_cites_the_evidence_is_not_checked_as_a_statement():
    # Work's HTML source lines carry no "PDF p." so they are not dropped earlier; they assert nothing
    text = (article(S1, S2, S3, S4) + "\n## 根拠資料\n- [" + EID + "] 公式FAQ・お知らせ HTML（本文の該当節）：https://example.ac.jp/faq\n")
    assert [i.detail for i in check_qualitative(text, {EID: RECORD}, REGISTRY)] == []
    assert semantic_coverage(text, {EID: RECORD}, REGISTRY)["unverified"] == []
    # ...but a flipped sentence next to that bibliography is still reported
    flipped = article(S1, "文書校正機能による単純な誤字脱字修正は下線必要です", S3, S4) + "\n## 根拠資料\n- [" + EID + "] 公式FAQ\n"
    assert check_qualitative(flipped, {EID: RECORD}, REGISTRY)
