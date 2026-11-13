"""Regression tests on EVERY handoff Work has delivered (research/inbox/**/claude-compatible-export.json).

Nothing here names a university: a new delivery is picked up by file name and must
pass the same checks. A new delivery that breaks an OLD delivery's results fails the
baseline test. See docs/REGRESSION.md for what to do when one of these fails.
"""
import re
from pathlib import Path

import pytest

from src.integration import audit_handoff
from src.regression import report as rr
from src.regression.checks import evaluate_export, evaluate_isolation, golden_view
from src.regression.handoffs import find_exports, find_handoffs
from src.verify.fact_registry import get_registry

EXPORTS = find_exports()
assert EXPORTS, "no delivered export found under research/inbox — collection must fail, not skip"
LOADED = {ref.key: ref.load() for ref in EXPORTS}
RESULTS = {key: evaluate_export(key, data) for key, data in LOADED.items()}
TESTS_DIR = Path(__file__).parent


@pytest.mark.parametrize("key", list(RESULTS))
def test_every_delivered_export_passes_all_checks(key):
    result = RESULTS[key]
    assert result["ok"], result["failures"]


def test_the_known_deliveries_are_all_found():
    keys = set(RESULTS)
    assert "work-db-v02-20261101/samples/claude-compatible-export.json" in keys
    assert {"work-national-v1/samples/humanities/claude-compatible-export.json",
            "work-national-v1/samples/law/claude-compatible-export.json"} <= keys


def test_old_deliveries_still_give_the_committed_golden_results():
    baseline = rr.load_baseline()
    assert baseline, "tests/golden/qa_baseline.json is missing or empty"
    diffs = []
    for key, expected in baseline.items():
        assert key in RESULTS, f"{key} is in the baseline but is no longer delivered"
        diffs += compare_(key, expected)
    assert not diffs, (
        "an old delivery's QA result changed:\n  " + "\n  ".join(diffs)
        + "\nIf this is intended, run `python -m src.regression.report --update-baseline` and review the diff (docs/REGRESSION.md).")


def compare_(key, expected):
    from src.regression.checks import compare_to_baseline
    return compare_to_baseline(key, golden_view(RESULTS[key]), expected)


def test_deliveries_do_not_collide_or_change_each_others_results():
    result = evaluate_isolation(LOADED)
    assert result["ok"], result["failures"]
    assert result["exports"] == len(EXPORTS)


def test_every_fact_key_in_delivered_data_is_registered():
    used = {e["fact_key"] for data in LOADED.values() for e in data["evidence"].values() if e.get("fact_key")}
    assert used and used <= set(get_registry().fact_keys), used - set(get_registry().fact_keys)
    for data in LOADED.values():
        assert all(e.get("fact_key") for e in data["evidence"].values()), "a delivered record has no fact_key"


@pytest.mark.parametrize("handoff", [p.name for p in find_handoffs()])
def test_independent_audit_of_each_handoff_has_no_failure(handoff):
    report = audit_handoff.audit(next(p for p in find_handoffs() if p.name == handoff))
    assert report["summary"]["failed"] == [], report["summary"]
    assert report["export"]["status"] in ("pass", "review") and report["manifest"]["status"] == "pass"


def test_no_test_in_this_repository_can_skip():
    """A skip is not a pass. Tests that need data fail when it is missing."""
    pattern = re.compile(r"pytest\.(?:skip|mark\.skip|mark\.skipif|mark\.xfail|importorskip)|@unittest\.skip")
    offenders = [p.name for p in TESTS_DIR.glob("test_*.py") if p.name != Path(__file__).name
                 and pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"skip/xfail markers in: {offenders}"
