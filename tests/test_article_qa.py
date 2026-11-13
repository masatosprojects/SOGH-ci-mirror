from src.article_qa import checks


def test_unsupported_number_detected():
    findings = checks.find_unsupported_numbers("募集人数は約50名です。", known_evidence_ids=set())
    assert any(f.category == "unsupported_number" for f in findings)


def test_supported_number_not_flagged():
    findings = checks.find_unsupported_numbers("募集人数は約50名[EV-1]です。", known_evidence_ids={"EV-1"})
    assert findings == []


def test_overconfident_assertion_detected():
    findings = checks.find_overconfident_assertions("この対策をすれば必ず合格します。")
    assert findings


def test_neutral_text_not_flagged_as_overconfident():
    findings = checks.find_overconfident_assertions("この対策は合格率を高める可能性があります。")
    assert findings == []


def test_caveat_present_detected():
    assert checks.has_sufficient_caveat("募集人数は変更される場合があります。最新情報は大学公式サイトでご確認ください。")


def test_caveat_absent_detected():
    assert not checks.has_sufficient_caveat("募集人数は50名です。")


def test_near_duplicate_score_identical_text_is_one():
    assert checks.near_duplicate_score("同じ文章です。", "同じ文章です。") == 1.0


def test_near_duplicate_score_unrelated_text_is_low():
    score = checks.near_duplicate_score("大学入試の総合型選抜について解説します。", "今日の天気は晴れで気温は20度です。")
    assert score < 0.3


def test_find_near_duplicates_flags_similar_articles():
    articles = {
        "a1": "〇〇大学理学部の総合型選抜の募集人数は30名です。詳細は公式サイトを確認してください。",
        "a2": "〇〇大学理学部の総合型選抜の募集人数は30名です。詳細は公式サイトをご覧ください。",
        "a3": "△△大学工学部の学校推薦型選抜の特徴について解説します。出願資格は高校の評定が重要です。",
    }
    findings = checks.find_near_duplicates(articles, threshold=0.6)
    flagged_pairs = {f.detail for f in findings}
    assert any("a1" in d and "a2" in d for d in flagged_pairs)
    assert not any("a3" in d for d in flagged_pairs)


def test_find_overused_phrases_detects_template_stamping():
    template = "この記事は大学入試情報を基に作成した参考情報であり実際の出願前に必ず大学公式サイトを確認してください"
    articles = {f"a{i}": template + f"補足情報その{i}" for i in range(6)}
    findings = checks.find_overused_phrases(articles, phrase_len=12, min_occurrences=5)
    assert findings
