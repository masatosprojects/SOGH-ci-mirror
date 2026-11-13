"""The committed record of the independent audit of Work's real-database copies (PR #59): it must not flatter the result."""
import json
import re
from pathlib import Path

from src.db_contract import progress as pg

PATH = Path(__file__).resolve().parents[1] / "reports" / "db-audit" / "real_copy_independent_audit_2026-11-01.json"
TEXT = PATH.read_text(encoding="utf-8")
REC = json.loads(TEXT)


def test_the_record_states_its_independence_level_and_what_was_not_examined():
    assert "originals" in REC["independence_level"] and "not_run" in REC["independence_level"]
    assert all(r["original_source_comparison"] == "not_run" for r in REC["db_audit_runs"].values())
    assert REC["effective_view_recomputed_from_db_only"]["identity_with_the_delivered_view_of_PR42"].startswith("not_run")


def test_the_record_keeps_the_failing_comparison_and_the_findings():
    runs = REC["db_audit_runs"]
    assert runs["v04_vs_v03"]["ok"] is False and runs["v04_vs_v03"]["summary"]["fail"] == ["DB-09"]
    assert runs["v06_vs_v05"]["ok"] is True and "DB-09" in runs["v06_vs_v05"]["summary"]["pass"]
    assert {f["id"] for f in REC["findings"]} >= {"F-1", "F-2", "F-3"}
    for name in ("v02", "v03", "v04", "v05", "v06_vs_v05"):  # the results equal Work's reported ones (Work ran v06 with the v05 baseline)
        assert all(runs[name]["same_as_work_summary"].values()), name


def test_the_copies_were_not_changed_by_the_audit_and_match_the_delivered_inventory():
    assert REC["copies"]["sha256_before_and_after_audit_unchanged"] is True
    assert all(REC["copies"]["sha256_match_inventory"].values()) and len(REC["copies"]["sha256"]) == 5
    assert REC["copies"]["sidecar_files"] == []


def test_the_record_holds_no_local_path_no_address_and_no_row_values():
    assert not re.search(r"[A-Za-z]:[\\/]|Users|maruy|@[\w-]+\.", TEXT)
    for r in REC["row_preservation_independent_implementation"]:
        for table in r.get("tables", {}).values():
            assert set(table) <= {"old_rows", "new_rows", "pk", "removed", "changed", "changed_columns", "added", "cols_added", "first_removed", "first_changed", "status"}


def test_the_board_does_not_overstate_what_this_record_proves():
    gates = {g["id"]: g for g in pg.load()["m1_gates"]}
    assert [i for i, g in gates.items() if g["verified"]] == ["M1.g1", "M1.g2", "M1.g3", "M1.g4", "M1.g5", "M1.g6", "M1.g7", "M1.g8"]  # accepted by the user on 2026-11-13 (g1, g2, g3, g5, g6, g7), each with its stated scope
    assert "not_run" in gates["M1.g8"]["evidence"] and "原本" in gates["M1.g8"]["evidence"]
    assert "G-04" in gates["M1.g1"]["evidence"] and "未" in gates["M1.g3"]["work_real_db"]


DELTA = json.loads((PATH.parent / "real_copy_independent_audit_pr59_delta_2026-11-01.json").read_text(encoding="utf-8"))


def test_the_delta_record_does_not_close_what_is_still_open():
    assert DELTA["verdict"] == "PASS_WITH_WARNINGS" and DELTA["m1_gates_changed"] is False
    assert DELTA["F-2_history_v03_to_v04"]["status"] == "recorded_not_explained"
    assert DELTA["F-2_history_v03_to_v04"]["work_claims_append_only"] is False
    assert DELTA["F-2_history_v03_to_v04"]["decision_on_accepting_the_history_rewrite"].startswith("user")
    assert DELTA["F-1_privacy_report"]["claude_independent_count"] == DELTA["F-1_privacy_report"]["work_user_path_cells"]
    assert any("not_run" in x for x in DELTA["still_open"]) and "B (" in DELTA["independence_level"]
    assert not re.search(r"[A-Za-z]:[\/]|Users|maruy|@[\w-]+\.", json.dumps(DELTA))
    assert [g["id"] for g in pg.load()["m1_gates"] if g["verified"]] == ["M1.g1", "M1.g2", "M1.g3", "M1.g4", "M1.g5", "M1.g6", "M1.g7", "M1.g8"]  # accepted 2026-11-13


G4 = json.loads((PATH.parent / "real_copy_g4_audit_pr63_2026-11-01.json").read_text(encoding="utf-8"))


def test_the_g4_record_states_its_scope_the_unrun_conditions_and_the_known_limit():
    h = G4["claude_harness"]
    assert h["fail"] == 0 and h["pass"] >= 21 and len(h["cases"]) == h["pass"] + h["known_limit"]
    assert G4["work_driver_rerun_by_claude"]["passed"] == 6 and "not Claude's calculation" in G4["work_driver_rerun_by_claude"]["note"]
    assert G4["database"]["source_copy_unchanged"] is True and G4["database"]["production_database_touched"] is False
    assert any("disk full" in x for x in G4["not_run"]) and any("power loss" in x for x in G4["not_run"]) and any("original" in x for x in G4["not_run"])
    assert "G-09" in G4["known_limit"] and "Not counted as a pass" in G4["known_limit"]
    names = " ".join(c["case"] for c in h["cases"])
    for needle in ("S1_", "S2_", "S3_", "S4_", "S5_", "S6_", "X9A", "X9B", "X9C", "X11_0", "X12"):
        assert needle in names, needle
    assert not re.search(r"[A-Za-z]:[\/]|Users|maruy|@[\w-]+\.", json.dumps(G4))


def test_g4_is_verified_only_with_its_own_evidence_and_the_limits_in_the_text():
    g = {x["id"]: x for x in pg.load()["m1_gates"]}["M1.g4"]
    assert g["verified"] is True and "copied_real_db" in g["evidence"] and "real_copy_g4_audit_pr63_2026-11-01.json" in g["evidence"]
    assert "G-09" in g["evidence"] and "ディスク満杯" in g["evidence"] and "原本DB・原典は未検証" in g["evidence"]


LEDGER = json.loads((PATH.parents[2] / "docs" / "temporary_work_ledger.json").read_text(encoding="utf-8"))


def test_the_temporary_work_ledger_keeps_the_labels_and_never_touches_work_branches():
    assert LEDGER["mode"] == "claude_temporary_implementation_takeover" and set(LEDGER["labels"]) >= {"INDEPENDENTLY_VERIFIED", "SELF_VALIDATED", "WORK_REVIEW_PENDING"}
    for e in LEDGER["entries"]:
        assert e["claude_branch"].startswith("claude/") and "not touched" in e["work_branch"] or e["kind"] != "audit", e["id"]
        assert not e["claude_branch"].startswith("work/")
    text = json.dumps(LEDGER)
    assert "stop.request" in text or "worker or scheduler start" in text
    assert not re.search(r"[A-Za-z]:[\/]|Users|maruy", text)


STAGE = json.loads((PATH.parent / "real_copy_stage_audit_pr61_2026-11-01.json").read_text(encoding="utf-8"))


def test_the_stage_audit_record_keeps_the_meaning_of_stage_and_does_not_activate_anything():
    assert "NOT the selection stage" in STAGE["meaning_of_stage"]
    assert STAGE["decision"]["audit_result"] == "PASS_WITH_WARNINGS" and STAGE["m1_gates_changed"] is False
    assert STAGE["decision"]["activation_in_any_operational_database"].startswith("NOT DONE") and "stays open" in STAGE["decision"]["issue_12"]
    assert STAGE["mutation"]["claude_helper_active_view"] == [10, 14] and STAGE["mutation"]["claude_helper_candidate_view"] == [14, 14]
    assert STAGE["evidence_and_articles"]["evidence_counts"]["all_other_records_identical"] is True and len(STAGE["evidence_and_articles"]["evidence_counts"]["added_to_view"]) == 2
    assert STAGE["activation_on_disposable_clones"]["fail"] == 0 and STAGE["activation_on_disposable_clones"]["finding"] == 1
    assert all(v["detected"] == v["of"] for v in STAGE["negatives"]["N4_other_spellings_of_the_flipped_ordinal"].values())
    assert not re.search(r"[A-Za-z]:[\/]|Users|maruy|@[\w-]+\.", json.dumps(STAGE))


ADD = json.loads((PATH.parent / "real_copy_additive_g04_g05_2026-11-01.json").read_text(encoding="utf-8"))


def test_the_additive_schema_record_says_it_is_self_validated_and_applied_nowhere_operational():
    assert ADD["applied_to_any_original_or_the_audited_copy"] is False and ADD["source_copy_unchanged"] is True
    assert "SELF_VALIDATED" in ADD["label"] and "WORK_CONTRACT_REVIEW_PENDING" in ADD["label"]
    assert ADD["real_copy_clone_cases"]["fail"] == 0 and ADD["real_copy_clone_cases"]["pass"] >= 8
    assert ADD["work_update_path_on_the_migrated_clone"]["fail"] == 0 and ADD["work_update_path_on_the_migrated_clone"]["pass"] >= 21
    assert ADD["m1_gates_changed"] is False and any("operational" in x for x in ADD["still_open"])
    assert not re.search(r"[A-Za-z]:[\/]|Users|maruy", json.dumps(ADD))
    gates = {g["id"]: g for g in pg.load()["m1_gates"]}
    assert gates["M1.g1"]["verified"] is True and "未適用" in gates["M1.g1"]["evidence"] and gates["M1.g5"]["verified"] is True  # accepted by the user 2026-11-13 (chain 0002-0014 on the real copy; operational DB and v0.2 excluded)


G09 = json.loads((PATH.parent / "real_copy_g02_g09_2026-11-01.json").read_text(encoding="utf-8"))


def test_the_g02_g09_record_states_its_limits_and_that_the_past_is_neither_repaired_nor_accepted():
    assert G09["applied_to_any_original_or_the_audited_copy"] is False and G09["source_copy_unchanged"] is True and G09["target_kind"] == "copied_real_db_disposable_clone"
    assert G09["real_copy_clone_cases"]["fail"] == 0 and G09["real_copy_clone_cases"]["pass"] >= 14
    assert G09["work_update_path_on_the_migrated_clone"]["fail"] == 0 and G09["work_update_path_on_the_migrated_clone"]["pass"] >= 22
    text = " ".join(G09["limits"])
    assert "INSERT OR REPLACE" in text and "DDL" in text and "neither repaired nor accepted" in text
    assert "USER_APPROVAL_REQUIRED" in G09["label"] and G09["m1_gates_changed"] is False
    assert not re.search(r"[A-Za-z]:[\/]|Users|maruy", json.dumps(G09))
    g = {x["id"]: x for x in pg.load()["m1_gates"]}
    assert g["M1.g3"]["verified"] is True and "F-2" in g["M1.g3"]["evidence"] and "未適用" in g["M1.g3"]["evidence"]  # accepted 2026-11-13 with the F-2 loss explicitly unrestored
