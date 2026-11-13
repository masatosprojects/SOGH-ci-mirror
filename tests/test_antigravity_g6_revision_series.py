"""Self-test suite for M1.g6 Document Series Contract & Article Revision Product Implementation Candidate.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.article_qa.dedup_mitigation import (
    diversify_article_advice,
    mitigate_article_corpus,
    run_strict_article_qa_audit,
)
from src.versioning.series import (
    append_revision,
    create_series,
    verify_series_lineage,
)


def test_series_creation_and_append_lineage():
    """Test creation and append-only progression of document series."""
    series = create_series(
        series_id="tsukuba_ac_2026",
        university="筑波大学",
        document_title="総合選抜要項",
        initial_content="令和8年度 筑波大学総合選抜要項 初版。募集人員は35名。",
    )
    assert series.latest_edition.rev_number == 1
    assert series.latest_edition.supersedes_id is None
    assert series.latest_edition.is_frozen is False

    # Append revision
    rev2 = append_revision(
        series,
        new_content="令和8年度 筑波大学総合選抜要項 第2版。募集人員は38名に改訂。",
    )
    assert rev2.rev_number == 2
    assert rev2.supersedes_id == "tsukuba_ac_2026_rev1"
    assert rev2.is_frozen is False

    # Previous edition must be frozen
    assert series.editions[0].is_frozen is True

    # Lineage verification
    ok, errors = verify_series_lineage(series)
    assert ok, f"Lineage verification failed: {errors}"


def test_redundant_revision_rejection():
    """Test rejection when appending revision with identical SHA-256."""
    series = create_series(
        series_id="kyoto_sci_2027",
        university="京都大学",
        document_title="理学部特色入試要項",
        initial_content="京都大学理学部特色入試案内 原文。",
    )
    raised = False
    try:
        append_revision(series, new_content="京都大学理学部特色入試案内 原文。")
    except ValueError as e:
        raised = True
        assert "Redundant revision" in str(e)
    assert raised, "Expected ValueError on identical revision content"


def test_14_articles_repetition_failure_and_mitigation():
    """Reproduces the 14-article QA failure mode and verifies that dedup mitigation

    restores 100% compliance without lowering any QA thresholds.
    """
    # Overused template sentence that triggers find_overused_phrases (>4 articles)
    repeating_template = "この記事は大学入試情報を基に作成した参考情報であり実際の出願前に必ず大学公式サイトを確認してください"

    # Construct 14 articles with realistic distinct discipline advice,
    # but where an identical boilerplate disclaimer causes QA failure.
    discipline_advice = [
        "日頃の読書と思考の蓄積を大切にしてください",
        "教育課題への関心と考察を深めておきましょう",
        "行動や思考のメカニズムに関心を持ちましょう",
        "社会事象に対する論理的思考力を養いましょう",
        "経済動向とデータ分析に日常的に触れましょう",
        "自然現象への探究心と数理的思考を鍛えましょう",
        "科学技術の応用に関する基礎力を磨きましょう",
        "生命倫理と医療現場への高い志を持ちましょう",
        "創薬と人体の仕組みに関心を広げてください",
        "他者への共感とケアの専門性を学びましょう",
        "食糧と環境の未来に目を向けて準備しましょう",
        "アルゴリズムと情報社会の課題を探究しましょう",
        "自らの表現技術と感性を研ぎ澄ませてください",
        "身体能力とスポーツ科学の理解を深めましょう",
    ]

    intros = [
        "筑波大学人文学類の公式要項の骨子です。同専攻の募集枠は5名[EV-1]に設定されています",
        "筑波大学比較文化学類の選抜概要をまとめました。対象枠は10名[EV-2]が公表されています",
        "筑波大学日本文化学類の募集情報です。募集人員は15名[EV-3]の予定です",
        "筑波大学社会学類に関する入試の要点です。今期の定員は20名[EV-4]と公表されました",
        "筑波大学経済学類の選抜ポイントを整理しました。受入定員は25名[EV-5]となります",
        "筑波大学生物学類の入試データ概要です。出願受入枠は30名[EV-6]と規定されています",
        "筑波大学地球学類について選考の要旨をお届けします。募集数は35名[EV-7]です",
        "筑波大学数学類の入試情報をまとめました。本学科の定員枠は40名[EV-8]に確定しました",
        "筑波大学物理学類の選抜要領を整理しました。公表定員は45名[EV-9]となっています",
        "筑波大学化学類に関する選考案内の要旨です。設定募集数は50名[EV-10]と発表されました",
        "筑波大学応用理工学類の募集概要となります。募集枠は55名[EV-11]と示されています",
        "筑波大学工学システム学類の入試ポイントです。今期の募集人員は60名[EV-12]です",
        "筑波大学情報科学類の入試ガイダンスです。募集受入数は65名[EV-13]とされています",
        "筑波大学情報メディア創成学類の募集情報です。今春の募集定員は70名[EV-14]となります",
    ]

    evidence_ids = {f"EV-{i}" for i in range(1, 15)}
    raw_articles = {}
    for i in range(1, 15):
        raw_articles[f"art_{i:02d}"] = (
            f"{intros[i-1]}。"
            f"{repeating_template}。"
            f"{discipline_advice[i-1]}。"
        )

    # 1. Verify that raw corpus FAILS QA due to overused phrases
    initial_passed, initial_findings = run_strict_article_qa_audit(raw_articles, evidence_ids)
    assert not initial_passed, "Initial corpus was expected to fail QA"
    assert any(f.category == "overused_template_phrase" for f in initial_findings)

    # 2. Apply dedup mitigation
    clean_articles = mitigate_article_corpus(raw_articles, evidence_ids)

    # 3. Verify that mitigated corpus strictly PASSES all QA checks (0 findings)
    final_passed, final_findings = run_strict_article_qa_audit(clean_articles, evidence_ids)
    assert final_passed, f"Mitigated corpus failed QA: {[f.detail for f in final_findings]}"
    assert len(final_findings) == 0


def test_factual_and_citation_preservation_during_mitigation():
    """Verify that sentences with numbers, dates, and [EV-...] citations are NEVER dropped or damaged."""
    text = (
        "筑波大学社会学類の入試案内です。"
        "出願前に公式サイトの公表事項を必ず確認してください。"
        "重要な注意点として、第2次選考は11月20日[EV-DATE]に実施され定員は20名[EV-QUOTA]です。"
    )
    mitigated = diversify_article_advice(text, index=0)

    # Both citations and facts must be 100% preserved
    assert "[EV-DATE]" in mitigated
    assert "[EV-QUOTA]" in mitigated
    assert "11月20日" in mitigated
    assert "20名" in mitigated
    assert "最新情報は大学公式の案内原本にてご確認ください" in mitigated


if __name__ == "__main__":
    tests = [
        test_series_creation_and_append_lineage,
        test_redundant_revision_rejection,
        test_14_articles_repetition_failure_and_mitigation,
        test_factual_and_citation_preservation_during_mitigation,
    ]
    passed = 0
    for t in tests:
        t()
        passed += 1
        print(f"  PASS: {t.__name__}")
    print(f"\nAll {passed}/{len(tests)} self-tests PASSED (100%).")
