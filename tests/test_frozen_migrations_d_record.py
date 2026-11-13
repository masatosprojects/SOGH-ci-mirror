"""The committed record of the frozen 0007 / 0008 run (the complete chain) on disposable clones of the audited copy: it must not flatter the result."""
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "reports" / "db-audit" / "real_copy_frozen_d_2026-11-02.json"
TEXT = PATH.read_text(encoding="utf-8")
REC = json.loads(TEXT)


def test_the_record_is_a_self_validation_on_clones_and_says_nothing_was_verified():
    assert "SELF_VALIDATED" in REC["labels"] and REC["production_database_touched"] is False and REC["source_copy_unchanged"] is True and "2/8" in REC["not_a_review"]
    assert any("NO source document" in x and "not_run" in x for x in REC["limits"]) and any("not a performance figure" in x for x in REC["limits"])


def test_every_case_passed_and_the_real_clone_holds_no_invented_verification():
    g4, add = REC["runs"]["g4_update_path_on_clones_with_the_complete_chain"], REC["runs"]["additive_audit_on_clones"]
    assert (g4["pass"], g4["fail"], g4["known_limit"]) == (22, 0, 0) and all(c["result"] == "PASS" for c in g4["cases"])
    assert (add["pass"], add["fail"]) == (19, 0) and {c["case"].split("_")[0] for c in add["cases"]} >= {"D1", "D2"}
    d1 = REC["real_clone_numbers"]["D1"]
    assert d1["metadata_rows"] == 0 and d1["verification_events"] == 0 and d1["all_levels_not_run"] == d1["stored_sources"] > 0


def test_the_record_holds_no_local_path_and_no_address():
    assert not re.search(r"[A-Za-z]:[\\/]|Users|maruy|@[\w-]+\.", TEXT)
