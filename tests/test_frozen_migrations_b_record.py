"""The committed record of the frozen 0004 run on disposable clones of the audited copy: it must not flatter the result."""
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "reports" / "db-audit" / "real_copy_frozen_b_2026-11-02.json"
TEXT = PATH.read_text(encoding="utf-8")
REC = json.loads(TEXT)


def test_the_record_is_a_self_validation_on_clones_and_keeps_the_residual_limits():
    assert "SELF_VALIDATED" in REC["labels"] and REC["production_database_touched"] is False and REC["source_copy_unchanged"] is True
    assert "residual" in REC["defects"]["D2"] and "residual" in REC["defects"]["D4"] and any("not_run" in x for x in REC["limits"]) and "2/8" in REC["not_a_review"]
    assert any("stage-1 patch must be adopted" in x or "patch must be adopted" in x for x in REC["limits"])


def test_every_case_of_both_harnesses_passed_with_nothing_dropped():
    g4, add = REC["runs"]["g4_update_path_on_clones_with_the_final_chain"], REC["runs"]["additive_audit_on_clones"]
    assert (g4["pass"], g4["fail"], g4["known_limit"]) == (22, 0, 0) and len(g4["cases"]) == 22 and all(c["result"] == "PASS" for c in g4["cases"])
    assert (add["pass"], add["fail"]) == (15, 0) and len(add["cases"]) == 15 and any(c["case"].startswith("B7_") for c in add["cases"])


def test_the_record_holds_no_local_path_and_no_address():
    assert not re.search(r"[A-Za-z]:[\\/]|Users|maruy|@[\w-]+\.", TEXT)
