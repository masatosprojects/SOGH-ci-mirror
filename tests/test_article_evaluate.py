from src.article_qa.evaluate import evaluate_article

EVIDENCE = {
    "EV-1": {
        "university": "〇〇大学",
        "faculty": "理学部",
        "department": None,
        "admission_method": "総合型選抜",
        "fiscal_year": 2026,
        "quota": 30,
    }
}

CLAIM = {"university": "〇〇大学", "faculty": "理学部", "admission_method": "総合型選抜", "fiscal_year": 2026}


def test_clean_article_has_no_findings():
    text = "〇〇大学理学部の総合型選抜の募集人数は30名[EV-1]です。詳細は大学公式サイトでご確認ください。"
    report = evaluate_article("a1", text, CLAIM, EVIDENCE)
    assert report.ok, report.findings


def test_unsupported_number_and_missing_caveat_and_no_evidence():
    text = "募集人数は30名です。"
    report = evaluate_article("a2", text, CLAIM, EVIDENCE)
    categories = {f["category"] for f in report.findings}
    assert "unsupported_number" in categories
    assert "missing_caveat" in categories
    assert "no_resolved_evidence" in categories
    assert not report.ok


def test_fiscal_year_mismatch_detected():
    evidence = {**EVIDENCE, "EV-1": {**EVIDENCE["EV-1"], "fiscal_year": 2025}}
    text = "〇〇大学理学部の総合型選抜の募集人数は30名[EV-1]です。詳細は大学公式サイトでご確認ください。"
    report = evaluate_article("a3", text, CLAIM, evidence)
    categories = {f["category"] for f in report.findings}
    assert "fiscal_year_mismatch" in categories


def test_entity_confusion_detected():
    text = "〇〇大学工学部の総合型選抜の募集人数は30名[EV-1]です。詳細は大学公式サイトでご確認ください。"
    report = evaluate_article("a4", text, CLAIM, EVIDENCE)
    categories = {f["category"] for f in report.findings}
    assert "entity_mismatch" in categories


def test_unknown_citation_detected():
    text = "〇〇大学理学部の総合型選抜の募集人数は30名[EV-999]です。詳細は大学公式サイトでご確認ください。"
    report = evaluate_article("a5", text, CLAIM, EVIDENCE)
    categories = {f["category"] for f in report.findings}
    assert "unknown_citation" in categories


def test_unknown_citation_not_reported_twice():
    text = "〇〇大学理学部の総合型選抜の募集人数は30名[EV-999]です。詳細は大学公式サイトでご確認ください。"
    report = evaluate_article("a5b", text, CLAIM, EVIDENCE)
    unknown_citation_findings = [f for f in report.findings if f["category"] == "unknown_citation"]
    assert len(unknown_citation_findings) == 1


def test_quota_scope_mismatch_detected():
    claim = {**CLAIM, "admission_method": "学校推薦型選抜"}
    text = "〇〇大学理学部の総合型選抜の募集人数は30名[EV-1]です。詳細は大学公式サイトでご確認ください。"
    report = evaluate_article("a6", text, claim, EVIDENCE)
    categories = {f["category"] for f in report.findings}
    assert "quota_scope_mismatch" in categories
