"""The committed record of the frozen 0005 / 0006 run on disposable clones of the audited copy: it must not flatter the result."""
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "reports" / "db-audit" / "real_copy_frozen_c_2026-11-02.json"
TEXT = PATH.read_text(encoding="utf-8")
REC = json.loads(TEXT)


def test_the_record_is_a_self_validation_on_clones_and_names_what_is_open():
    assert "SELF_VALIDATED" in REC["labels"] and REC["production_database_touched"] is False and REC["source_copy_unchanged"] is True and "2/8" in REC["not_a_review"]
    assert any("not_run" in x for x in REC["limits"]) and any("missing" in x for x in REC["limits"]) and any("G-06" in x for x in REC["limits"])


def test_every_case_passed_and_the_numbers_were_counted_from_the_records():
    g4, add = REC["runs"]["g4_update_path_on_clones_with_the_full_chain"], REC["runs"]["additive_audit_on_clones"]
    assert (g4["pass"], g4["fail"], g4["known_limit"]) == (22, 0, 0) and all(c["result"] == "PASS" for c in g4["cases"])
    assert (add["pass"], add["fail"]) == (17, 0) and {c["case"].split("_")[0] for c in add["cases"]} >= {"C1", "C2"}
    c1, c2 = REC["real_clone_numbers_counted_from_the_records"]["C1"], REC["real_clone_numbers_counted_from_the_records"]["C2"]
    assert c1["relation_rows"] == c1["expected_from_the_records"] == 220 and c1["revised_articles"] == 22 and c1["mismatches"] == 0 and c1["orphans"] == 0
    assert c2["reasons"] == 0 and "missing" not in c2["status"] and c2["status"]["not_recorded_before_the_contract"] == 10  # the unknown past stays unknown


def test_the_record_holds_no_local_path_and_no_address():
    assert not re.search(r"[A-Za-z]:[\\/]|Users|maruy|@[\w-]+\.", TEXT)
