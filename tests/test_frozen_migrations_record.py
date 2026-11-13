"""The committed record of the frozen 0002 / 0003 run on disposable clones of the audited copy: it must not flatter the result."""
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "reports" / "db-audit" / "real_copy_additive_frozen_a_2026-11-02.json"
TEXT = PATH.read_text(encoding="utf-8")
REC = json.loads(TEXT)


def test_the_record_is_a_self_validation_on_clones_and_names_what_is_open():
    assert "SELF_VALIDATED" in REC["labels"] and REC["production_database_touched"] is False and REC["source_copy_unchanged"] is True
    assert any("D1-D4 stay open" in x for x in REC["limits"]) and any("not_run" in x for x in REC["limits"]) and "2/8" in REC["not_a_review"]


def test_every_case_passed_and_none_was_dropped():
    assert REC["fail"] == 0 and REC["pass"] == len(REC["cases"]) == 14 and all(c["result"] == "PASS" for c in REC["cases"])
    assert {c["case"].split("_")[0] for c in REC["cases"]} >= {"A1", "A2", "A5", "A6", "A7", "A8", "B1", "B2", "B3", "B4", "B5", "B6"}


def test_the_record_holds_no_local_path_and_no_address():
    assert not re.search(r"[A-Za-z]:[\\/]|Users|maruy|@[\w-]+\.", TEXT)
