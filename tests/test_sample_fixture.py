"""Sanity test for tests/fixtures/sample_articles.json — the example a
human can run by hand via:

    python -m src.run_qa_suite --articles-json tests/fixtures/sample_articles.json

This pins down what that fixture is expected to find, so if someone edits
the fixture to add a new example, this test tells them what broke.
"""
import json
from pathlib import Path

from src import run_qa_suite

FIXTURE = Path(__file__).parent / "fixtures" / "sample_articles.json"


def _load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_loads_and_has_three_articles():
    data = _load()
    assert len(data["articles"]) == 3
    assert set(data["evidence"]) == {"EV-0001", "EV-0002"}


def test_fixture_clean_article_passes():
    result = run_qa_suite.run_articles(_load())
    by_id = {a["article_id"]: a for a in result["per_article"]}
    assert by_id["sample-clean"]["ok"] is True


def test_fixture_unsupported_number_article_flagged():
    result = run_qa_suite.run_articles(_load())
    by_id = {a["article_id"]: a for a in result["per_article"]}
    categories = {f["category"] for f in by_id["sample-unsupported-number"]["findings"]}
    assert "unsupported_number" in categories
    assert "missing_caveat" in categories


def test_fixture_overconfident_article_flagged():
    result = run_qa_suite.run_articles(_load())
    by_id = {a["article_id"]: a for a in result["per_article"]}
    categories = {f["category"] for f in by_id["sample-overconfident"]["findings"]}
    assert "overconfident_assertion" in categories


def test_fixture_batch_has_no_false_positive_duplicates():
    result = run_qa_suite.run_articles(_load())
    assert result["batch_findings"] == []
