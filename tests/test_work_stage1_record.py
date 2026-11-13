"""The committed record of the stage-1 patch run on disposable clones of the audited copy: it must not flatter the result."""
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "reports" / "db-audit" / "real_copy_g4_stage1_patch_2026-11-01.json"
TEXT = PATH.read_text(encoding="utf-8")
REC = json.loads(TEXT)
RUNS = REC["runs"]


def test_the_record_is_a_self_validation_on_copies_and_says_what_was_not_run():
    assert "SELF_VALIDATED" in REC["labels"] and "WORK_REVIEW_PENDING" in REC["labels"]
    assert REC["production_database_touched"] is False and REC["source_copy_unchanged"] is True and len(REC["source_copy_sha256"]) == 64
    assert any("not_run" in x for x in REC["limits"]) and "not Work's independent audit" in REC["not_a_review"] and "2/8" in REC["not_a_review"]


def test_the_patched_runs_have_no_failure_and_the_delivered_run_is_recorded_as_stopped():
    plain = RUNS["patched_pipeline_on_the_unchanged_clone"]
    guarded = RUNS["patched_pipeline_on_a_clone_with_the_proposed_guard_rules"]
    delivered = RUNS["delivered_pipeline_on_a_clone_with_the_proposed_guard_rules"]
    assert (plain["pass"], plain["fail"], plain["known_limit"]) == (21, 0, 1) and plain["cases"][-1]["result"] == "KNOWN_LIMIT_G09"  # exactly the audit of PR #63
    assert (guarded["pass"], guarded["fail"], guarded["known_limit"]) == (22, 0, 0)
    assert [c["case"] for c in guarded["cases"] if c["result"] != "PASS"] == []
    assert delivered["result"] == "STOPPED" and "sogh_write_ok" in delivered["meaning"]


def test_the_record_holds_no_local_path_and_no_address():
    assert not re.search(r"[A-Za-z]:[\\/]|Users|maruy|@[\w-]+\.", TEXT)
