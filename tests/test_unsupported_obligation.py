"""Issue #47: a duty / prohibition / exemption that the cited evidence does not contain must be REPORTED, even when the
same paragraph also holds correct, checked conditions.

Reported = in `semantic_coverage.unverified` with kind `unsupported_obligation` (its content words are not in the cited
evidence) or `obligation_without_rule` (no assertion governs the clause). It is never counted as a detection: the QA
cannot call it contradicted, only unsupported. No wording of any example is registered anywhere.
"""
import pytest

from src.article_qa.flip_sweep import flip_sweep
from src.verify.fact_registry import get_registry
from src.verify.qualitative import check_qualitative, semantic_coverage

REGISTRY = get_registry()
EID = "EV-U-faq"
VALUE = {"allowed": "生成AI使用時の表示方法がFAQで案内されている", "not_accepted": "",
         "ai_text_underline_required": True, "simple_spellcheck_underline_required": False,
         "human_advice_underline_required": False, "human_advice_activity_report_required": True,
         "ai_visual_disclosure_required": True}
QUOTES = ["文章チェックも含め、生成AIが実際に生成・修正した箇所には、すべて下線を引いてください。",
          "Microsoft WORD等の文書校正機能による単純な誤字脱字修正の場合は、下線を引く必要はありません。",
          "他人の添削・助言による修正等には、下線を引く必要はありませんが、活動経過報告書での記載は必須です。",
          "生成AIで作成した画像・図・表等は、説明文や脚注にその使用を明示してください。"]
RECORD = {"evidence_id": EID, "fact_key": "generative_ai_policy", "value": VALUE, "proofs": [{"section": "AC", "quote": q} for q in QUOTES]}

S1 = "AC入試のFAQでは、文章チェックを含め生成AIが生成・修正した箇所と、その修正で間接的に影響した箇所すべてに下線を引くよう案内しています"
S2 = "文書校正機能による単純な誤字脱字修正は下線不要です"
S3 = "他人の添削・助言の修正も下線不要ですが、活動経過報告書への記載は必須です"
S4 = "生成AIで作成した画像・図・表等は、説明文や脚注にその使用を明示します"
GOOD = [S1, S2, S3, S4]


def article(*sentences):
    return "# 〇〇大学\n\n" + "。".join(s + f"[{EID}]" for s in sentences) + "。\n"


def coverage(*sentences, record=RECORD):
    return semantic_coverage(article(*sentences), {EID: record}, REGISTRY)


def reported(*sentences, record=RECORD):
    return [u for u in coverage(*sentences, record=record)["unverified"] if u.get("kind") in ("unsupported_obligation", "obligation_without_rule")]


def test_the_correct_paragraph_reports_nothing():
    cov = coverage(*GOOD)
    assert cov["unverified"] == [] and cov["counts"]["unsupported_obligations"] == 0
    assert check_qualitative(article(*GOOD), {EID: RECORD}, REGISTRY) == []


INVENTED = {
    "prior permission by e-mail": "生成AIを使用した場合は、大学へ電子メールで事前許可申請することが必須です",
    "extra document": "出願の前に、推薦状を別途郵送で提出することが必須です",
    "extra interview": "合格者は追加の面接を受けなければなりません",
    "eligibility restriction": "高校の評定平均が4.0未満の場合は出願できません",
    "invented deadline": "10月1日までに生成AIの使用届を提出する必要があります",
    "invented prohibition": "生成AIで作成した文章を提出することは禁止されています",
    "invented exemption": "志望理由書の提出は免除されます",
}


@pytest.mark.parametrize("name", list(INVENTED))
def test_an_invented_duty_next_to_correct_checked_conditions_is_reported(name):
    found = reported(*GOOD, INVENTED[name])
    contradicted = check_qualitative(article(*GOOD, INVENTED[name]), {EID: RECORD}, REGISTRY)
    # reported as unsupported/unverified, or (when an assertion can say so) contradicted — never silent
    assert (found and any(u["snippet"][:8] in INVENTED[name] for u in found)) or contradicted, (name, found)
    # ...and the correct sentences are still not accused
    assert all(not u["snippet"].startswith(("文書校正", "AC入試")) for u in found)


@pytest.mark.parametrize("name", ["prior permission by e-mail", "extra document", "extra interview", "eligibility restriction"])
def test_a_duty_whose_words_are_not_in_the_evidence_is_called_unsupported_with_the_missing_words(name):
    found = [u for u in reported(*GOOD, INVENTED[name]) if u["kind"] == "unsupported_obligation"]
    assert found and found[0]["ungrounded_terms"]


def test_the_report_is_not_a_detection_and_not_a_pass():
    wrong = INVENTED["prior permission by e-mail"]
    assert check_qualitative(article(*GOOD, wrong), {EID: RECORD}, REGISTRY) == []  # no contradiction is claimed
    cov = coverage(*GOOD, wrong)
    assert cov["counts"]["unverified"] == 1 and cov["counts"]["unsupported_obligations"] == 1


def test_two_conditions_in_one_sentence_are_accounted_for_separately():
    sentence = "他人の添削・助言の修正も下線不要ですが、事前に大学へ電子メールで許可申請することが必須です"
    found = reported(S1, S2, sentence, S4)
    assert len(found) == 1 and found[0]["snippet"].startswith("事前に大学へ") and found[0]["kind"] == "unsupported_obligation"


def test_a_correct_two_condition_sentence_is_not_reported():
    assert reported(S1, S2, S3, S4) == []


def test_a_correct_citation_cannot_lend_its_support_to_content_it_does_not_contain():
    # the id is the right one, the sentence says something the quoted FAQ never says
    assert reported(*GOOD, "AC入試ではオンライン面接の事前登録が必須です")


def test_general_editing_advice_is_not_taken_for_an_official_duty():
    advice = ["提出前に、誤字脱字がないかもう一度読み返しましょう", "最新の情報は大学公式サイトでご確認ください", "文章は自分の言葉で書くことをおすすめします",
              "不明な点は入試担当窓口に問い合わせてください", "実質的な質疑時間が同じ長さだとは断定できません"]
    assert reported(*GOOD, *advice) == []


def test_a_hedge_is_not_a_duty():
    assert reported(*GOOD, "実際の運用は年度により異なるとは限りません") == []


def test_a_sentence_without_a_citation_is_out_of_scope_here():
    text = article(*GOOD) + "\n事前に大学へ電子メールで許可申請することが必須です。\n"
    assert semantic_coverage(text, {EID: RECORD}, REGISTRY)["unverified"] == []  # no cited evidence to compare with (uncited claims have their own checks)


def test_without_the_structured_fields_the_faq_sentences_themselves_are_unverified_not_verified():
    bare = {**RECORD, "value": {"allowed": VALUE["allowed"], "not_accepted": ""}}
    found = reported(*GOOD, record=bare)
    assert {u["snippet"][:6] for u in found} >= {"文書校正機能", "他人の添削・", "活動経過報告"}
    assert {u["kind"] for u in found} <= {"obligation_without_rule", "unsupported_obligation"}  # reported either way, never verified


def test_the_undetected_flip_next_to_checked_conditions_is_counted_as_declared_unverified_never_as_detected():
    body = "生成AIの利用は条件つきで認められ、" + "。".join(x + f"[{EID}]" for x in [*GOOD, "AC入試ではオンライン面接の事前登録が必須です"]) + "。"
    export = {"evidence": {EID: dict(RECORD, university="〇〇大学", faculty="環境学部", department=None, admission_method="夏秋AO入試", fiscal_year=2027,
                                      scope="target_admission_cycle", source_url="https://example.ac.jp/faq", retrieved_at="2026-11-01",
                                      source_pdf_sha256="0" * 64, source_sha256="0" * 64, source_kind="pdf")},
              "articles": [{"article_id": "a", "claim": {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027},
                            "text": "\n\n".join(["# 〇〇大学 環境学部 夏秋AO入試", "作業基準日：2026-11-01。", body, "最新情報は大学公式サイトでご確認ください。"]) + "\n"}]}
    catalog = [("t_required_to_optional", "polarity", "必須です", "任意です", "「必須です」→「任意です」")]
    r = flip_sweep(export, catalog=catalog, reference_date="2026-11-01", require_as_of=True)
    assert r["all_baselines_ok"] and r["instances"] == 2
    # the checked duty (活動経過報告書…必須) is DETECTED; the invented duty cannot be contradicted, so it is DECLARED, not detected
    assert (r["detected"], r["declared_unverified"], r["silent_misses"]) == (1, 1, 0)
    assert r["detection_rate"] == 0.5 and r["accounted_rate"] == 1.0


def test_obligation_wording_is_registry_data_and_validated():
    import copy
    from src.verify.fact_registry import validate_registry_data
    assert validate_registry_data(REGISTRY.data) == []
    data = copy.deepcopy(REGISTRY.data)
    data["claim_wording"]["obligation"] = ["re:("]
    assert any("bad regex" in p for p in validate_registry_data(data))
    data["claim_wording"]["obligation"] = []
    assert validate_registry_data(data)
