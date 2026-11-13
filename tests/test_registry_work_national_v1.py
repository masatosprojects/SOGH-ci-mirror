"""Compatibility of the fact_key registry with Work's national-v1 handoff
(PR #24: Niigata University, law and humanities). The registry follows Work's
real data; Work is not asked to change anything.

Findings that shaped registry 1.1.0 (see its changelog): Work uses `interview`
for the interview DATE/time as well as its duration, `interview_scope` carries
`text`, and `postal_period` has a late-arrival field.
"""
import json
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.integration.validate_export import validate_records
from src.verify.fact_registry import get_registry

ROOT = Path(__file__).parent.parent / "research" / "inbox" / "work-national-v1" / "samples"
DIRS = sorted(p.parent.name for p in ROOT.glob("*/claude-compatible-export.json"))
assert DIRS == ["humanities", "law"], f"expected Work's two Niigata samples, found {DIRS}"


def load(name):
    return json.loads((ROOT / name / "claude-compatible-export.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", DIRS)
def test_registry_has_no_errors_and_no_warnings_on_work_data(name):
    report = get_registry().check_evidence(load(name)["evidence"])
    assert report["ok"] and report["unregistered_fact_keys"] == [], report["issues"]
    assert report["by_severity"] == {"error": 0, "warning": 0, "notice": 0}, report["issues"]


@pytest.mark.parametrize("name", DIRS)
def test_export_gate_passes_every_record(name):
    result = validate_records(load(name)["evidence"])
    assert result["invalid_count"] == 0 and result["total"] == 5, result["records"]


@pytest.mark.parametrize("name", DIRS)
def test_every_draft_passes_the_strict_qa_with_no_notices(name):
    data = load(name)
    assert len(data["articles"]) == 3
    for article in data["articles"]:
        report = evaluate_article(article["article_id"], article["text"], article["claim"], data["evidence"])
        assert report.ok and report.notices == [], (article["article_id"], report.findings, report.notices)


def test_the_interview_date_use_of_the_interview_key_is_registered_not_mistaken_for_a_duration():
    data = load("law")
    interview = next(e for e in data["evidence"].values() if e["fact_key"] == "interview")
    assert "minutes" not in interview["value"] and interview["value"]["type"] == "interview_date_not_duration"
    assert get_registry().check_record(interview) == []
