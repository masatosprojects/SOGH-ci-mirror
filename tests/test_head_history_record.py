"""The committed record of the head-history run on disposable clones of the audited copy: it must not flatter the result."""
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "reports" / "db-audit" / "real_copy_head_history_2026-11-02.json"
TEXT = PATH.read_text(encoding="utf-8")
REC = json.loads(TEXT)


def test_the_record_is_a_self_validation_and_names_its_limits():
    assert "SELF_VALIDATED" in REC["labels"] and REC["production_database_touched"] is False and REC["source_copy_unchanged"] is True and "2/8" in REC["not_a_review"]
    assert any("NOT implemented" in x for x in REC["limits"]) and any("never a pass" in x for x in REC["limits"])


def test_every_case_passed_and_the_replay_matched_the_real_clone():
    g4, add = REC["runs"]["g4_update_path_on_clones_with_the_complete_chain"], REC["runs"]["additive_audit_on_clones"]
    assert (g4["pass"], g4["fail"], g4["known_limit"]) == (22, 0, 0) and (add["pass"], add["fail"]) == (20, 0)
    e1 = REC["real_clone_numbers"]["E1"]
    assert e1["db18"] == "pass" and e1["events"] > 0 and e1["evidence_heads"] > 0


def test_the_record_holds_no_local_path_and_no_address():
    assert not re.search(r"[A-Za-z]:[\\/]|Users|maruy|@[\w-]+\.", TEXT)
