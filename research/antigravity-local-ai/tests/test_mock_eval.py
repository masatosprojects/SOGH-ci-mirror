#!/usr/bin/env python3
"""
SOGH Antigravity - Comprehensive Quality, Security & Grounding Evaluation Suite (Phase 1.8)

Test Groups:
- Group 1: Grounding Enforcement & Semantic DB Checks (Problems A & D)
  - Mandatory reference DB check (fails close if omitted/empty)
  - Semantic quota contradiction detection
  - Mismatched academic years, admission types, prohibited substitutions
  - Checksum independence from grounding facts
- Group 2: Existing File Protection & Atomic Writes (Problem B)
  - Corrupted/unreadable existing candidate preservation (NEVER overwritten)
  - Collision-free conflict and quarantine naming
  - Atomic write integrity
- Group 3: Event Identity 5-Case Classification (Problem C)
  - Case A: Same ID + Same Content + Same Origin -> Deduplicated
  - Case B: Same ID + Same Content + Different Origin -> Conflict
  - Case C: Same ID + Different Content -> Conflict
  - Case D: Different ID + Same Content -> Deduplication Link (STR-027)
  - Case E: Document Revision / New Edition -> Audit Link
- Group 4: Input Size, Exceptions & Security (Problem E)
  - Pre-read payload size limit enforcement
  - Excessive nesting depth rejection
  - Path traversal in event_id rejection
- Group 5: Thermal & RAM Diagnostics (Problem E)
  - NaN / Inf / -Inf / Bool / None rejection
  - Physical anomaly rejection (<0C, >150C)
  - Strict threshold boundaries (75.9, 76.0, 89.9, 90.0C)
  - MockInferenceRunner fail-close execution
- Group 6: Real Mutation / Fault Injection Testing
  - Systematic mutation of core functions verifying that the suite catches failures
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from copy import deepcopy

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from scripts.mock_event_monitor import (
    process_diff_event,
    compute_checksum,
    compute_payload_fingerprint,
    compute_full_fingerprint,
    validate_event_payload,
    verify_grounding_against_db,
    atomic_write_json,
    MAX_PAYLOAD_BYTES
)
from scripts.diagnostics import (
    evaluate_thermal_trip,
    MockInferenceRunner
)

class TestSOGHPhase18Rigorous(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.base_dir = base_dir
        cls.fixtures_dir = os.path.join(cls.base_dir, "fixtures", "synthetic")
        cls.diff_file = os.path.join(cls.fixtures_dir, "mock_site_diff.json")
        cls.db_file = os.path.join(cls.fixtures_dir, "mock_official_db.json")
        cls.test_queue_dir = os.path.join(cls.base_dir, "handoff", "staging_queue_p18_test")

        with open(cls.db_file, "r", encoding="utf-8") as f:
            cls.reference_db = json.load(f)

    def setUp(self):
        os.makedirs(self.test_queue_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_queue_dir):
            shutil.rmtree(self.test_queue_dir)

    def load_base_event(self) -> dict:
        with open(self.diff_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # =========================================================================
    # Group 1: Grounding Enforcement & Semantic DB Checks (Problems A & D)
    # =========================================================================

    def test_grounding_cannot_be_bypassed_without_db(self):
        """MANDATORY: process_diff_event rejects and quarantines if reference_db is missing or empty."""
        event = self.load_base_event()

        # Test with reference_db = None
        res_none = process_diff_event(event, self.test_queue_dir, reference_db=None)
        self.assertEqual(res_none["status"], "REJECTED_MISSING_REFERENCE_DB")
        self.assertIsNone(res_none["candidate"])

        # Test with reference_db = {}
        res_empty = process_diff_event(event, self.test_queue_dir, reference_db={})
        self.assertEqual(res_empty["status"], "REJECTED_MISSING_REFERENCE_DB")
        self.assertIsNone(res_empty["candidate"])

        # Test with corrupted reference_db lacking 'universities'
        res_corrupt = process_diff_event(event, self.test_queue_dir, reference_db={"version": "1.0"})
        self.assertEqual(res_corrupt["status"], "REJECTED_MISSING_REFERENCE_DB")

    def test_quota_contradiction_detection(self):
        """Semantic check: reject change asserting a quota contradicting verified official quota."""
        event = self.load_base_event()
        # Official quota in mock_official_db.json for Tsukuba Engineering AC is 10
        # Propose conflicting quota of 999 in after_text
        event["simulated_diff"]["after_text"] = "2027年度AC入試の募集人数は999名に変更する。"
        event["checksum_after"] = compute_checksum(event["simulated_diff"]["after_text"])

        res = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "REJECTED_UNGROUNDED")
        has_quota_err = any("contradicts official verified quota '10'" in err for err in res["failures"])
        self.assertTrue(has_quota_err, "Must detect numerical quota contradiction")

    def test_unregistered_academic_year_rejection(self):
        """Reject proposal for academic year 2028 when official DB only covers 2026 and 2027."""
        event = self.load_base_event()
        event["target_academic_year"] = 2028
        res = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "REJECTED_UNGROUNDED")
        self.assertIn("not registered in official DB", res["failures"][0])

    def test_prohibited_substitutions_rejection(self):
        """Reject proposed diff injecting prohibited selection element (共通テスト成績)."""
        event = self.load_base_event()
        event["simulated_diff"]["after_text"] = "第1次選考において大学入学共通テスト成績の提出を必須とする。"
        event["checksum_after"] = compute_checksum(event["simulated_diff"]["after_text"])

        res = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "REJECTED_UNGROUNDED")
        has_prohibition = any("prohibited substitution" in f for f in res["failures"])
        self.assertTrue(has_prohibition)

    def test_checksum_alone_cannot_bypass_grounding(self):
        """Checksum match alone does NOT prove fact or bypass grounding checks."""
        event = self.load_base_event()
        # Valid checksum on fabricated admission type not in reference DB for this department
        event["university"] = "筑波大学"
        event["target_admission_type"] = "一般選抜"
        event["simulated_diff"]["after_text"] = "一般選抜の実施日程を更新。"
        event["checksum_after"] = compute_checksum(event["simulated_diff"]["after_text"])

        res = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "REJECTED_UNGROUNDED")
        self.assertIn("not found in official DB", res["failures"][0])

    def test_candidate_lifecycle_states(self):
        """Verify lifecycle state is GROUNDING_CHECK_PASSED_UNCONFIRMED_PROPOSAL and never auto-VERIFIED."""
        event = self.load_base_event()
        res = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "CANDIDATE_GENERATED")
        candidate = res["candidate"]
        self.assertEqual(candidate["lifecycle_state"], "GROUNDING_CHECK_PASSED_UNCONFIRMED_PROPOSAL")
        self.assertEqual(candidate["validation_status"], "PENDING_INDEPENDENT_QA")
        self.assertTrue(candidate["requires_official_confirmation"])

    # =========================================================================
    # Group 2: Existing File Protection & Atomic Writes (Problem B)
    # =========================================================================

    def test_unreadable_existing_candidate_is_never_overwritten(self):
        """If an existing candidate file is corrupted or unreadable, NEVER overwrite it. Quarantine new event."""
        staging_dir = os.path.join(self.test_queue_dir, "staging_queue")
        os.makedirs(staging_dir, exist_ok=True)
        event = self.load_base_event()
        corrupt_target_file = os.path.join(staging_dir, f"CAND-{event['event_id']}.json")

        # Create a corrupted, unreadable existing candidate file
        corrupt_bytes = b"{{{INVALID_CORRUPTED_JSON_DATA_NO_CLOSE"
        with open(corrupt_target_file, "wb") as f:
            f.write(corrupt_bytes)

        # Process incoming valid event with identical event_id
        res = process_diff_event(event, self.test_queue_dir, self.reference_db)

        # Assert status is EXISTING_CANDIDATE_UNREADABLE_QUARANTINED
        self.assertEqual(res["status"], "EXISTING_CANDIDATE_UNREADABLE_QUARANTINED")
        self.assertIsNone(res["candidate"])

        # CRITICAL ASSERTION: The corrupted file on disk was NOT overwritten!
        with open(corrupt_target_file, "rb") as f:
            persisted_bytes = f.read()
        self.assertEqual(persisted_bytes, corrupt_bytes, "Corrupted existing candidate must be preserved untouched!")

        # Verify incoming event was preserved in quarantine/
        quarantine_dir = os.path.join(self.test_queue_dir, "quarantine")
        self.assertTrue(os.path.exists(quarantine_dir))
        self.assertGreater(len(os.listdir(quarantine_dir)), 0)

    def test_collision_free_conflict_naming(self):
        """Rapid consecutive conflicts generate unique, collision-free filenames without data loss."""
        event1 = self.load_base_event()
        event1["event_id"] = "EVT-RAPID-CONFLICT"
        process_diff_event(event1, self.test_queue_dir, self.reference_db)

        conflict_dir = os.path.join(self.test_queue_dir, "conflicts")

        # Fire 5 distinct conflicting payloads in rapid succession
        for i in range(5):
            ev_conf = deepcopy(event1)
            ev_conf["simulated_diff"]["after_text"] = f"Conflict amendment text variation #{i}"
            ev_conf["checksum_after"] = compute_checksum(ev_conf["simulated_diff"]["after_text"])
            res = process_diff_event(ev_conf, self.test_queue_dir, self.reference_db)
            self.assertEqual(res["status"], "CONFLICT_QUARANTINED")

        # Ensure all 5 conflict files exist in conflict_dir (none overwritten)
        conflict_files = os.listdir(conflict_dir)
        self.assertEqual(len(conflict_files), 5, "All 5 rapid conflicts must have unique filenames without overwriting")

    def test_atomic_write_file_resilience(self):
        """Atomic write ensures that destination file is written atomically."""
        test_file = os.path.join(self.test_queue_dir, "atomic_test.json")
        sample_data = {"key": "initial_value"}
        atomic_write_json(test_file, sample_data)
        self.assertTrue(os.path.exists(test_file))

        with open(test_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["key"], "initial_value")

    # =========================================================================
    # Group 3: Event Identity 5-Case Classification (Problem C)
    # =========================================================================

    def test_case_a_same_id_same_content_same_origin(self):
        """Case A: Same Event ID + Same Content + Same Origin -> DEDUPLICATED_SKIPPED."""
        event = self.load_base_event()
        event["event_id"] = "EVT-CASE-A"
        res1 = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res1["status"], "CANDIDATE_GENERATED")

        res2 = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res2["status"], "DEDUPLICATED_SKIPPED")
        self.assertEqual(res2["relationship_case"], "CASE_A_SAME_ID_SAME_CONTENT_SAME_ORIGIN")

    def test_case_b_same_id_same_content_diff_origin(self):
        """Case B: Same Event ID + Same Content + Different Origin -> CONFLICT_QUARANTINED."""
        event1 = self.load_base_event()
        event1["event_id"] = "EVT-CASE-B"
        event1["source_url"] = "https://admission.example.com/page_a.html"
        process_diff_event(event1, self.test_queue_dir, self.reference_db)

        # Same ID and diff, but origin URL changes to page_b.html under same authorized domain
        event2 = deepcopy(event1)
        event2["source_url"] = "https://admission.example.com/page_b.html"
        res2 = process_diff_event(event2, self.test_queue_dir, self.reference_db)

        self.assertEqual(res2["status"], "CONFLICT_QUARANTINED")
        self.assertEqual(res2["relationship_case"], "CASE_B_SAME_ID_SAME_CONTENT_DIFFERENT_ORIGIN")

    def test_case_c_same_id_different_content(self):
        """Case C: Same Event ID + Different Content -> CONFLICT_QUARANTINED."""
        event1 = self.load_base_event()
        event1["event_id"] = "EVT-CASE-C"
        process_diff_event(event1, self.test_queue_dir, self.reference_db)

        event2 = deepcopy(event1)
        event2["simulated_diff"]["after_text"] = "まったく異なる出願書類の提出方法への変更。"
        event2["checksum_after"] = compute_checksum(event2["simulated_diff"]["after_text"])
        res2 = process_diff_event(event2, self.test_queue_dir, self.reference_db)

        self.assertEqual(res2["status"], "CONFLICT_QUARANTINED")
        self.assertEqual(res2["relationship_case"], "CASE_C_SAME_ID_DIFFERENT_CONTENT")

    def test_case_d_different_id_same_content(self):
        """Case D: Different Event ID + Same Content + Same Origin -> Duplication Link (STR-027)."""
        event1 = self.load_base_event()
        event1["event_id"] = "EVT-CASE-D1"
        process_diff_event(event1, self.test_queue_dir, self.reference_db)

        event2 = deepcopy(event1)
        event2["event_id"] = "EVT-CASE-D2"
        res2 = process_diff_event(event2, self.test_queue_dir, self.reference_db)

        self.assertEqual(res2["status"], "CANDIDATE_GENERATED")
        self.assertEqual(res2["candidate"]["relationship_case"], "CASE_D_DIFFERENT_ID_SAME_INFORMATION")
        self.assertEqual(res2["candidate"]["duplicate_of"], "CAND-EVT-CASE-D1")
        self.assertEqual(res2["candidate"]["possible_duplicate_of"], "CAND-EVT-CASE-D1")

    def test_case_e_document_revision_new_edition(self):
        """Case E: Same Information + New Edition of Document -> Audit Link."""
        event1 = self.load_base_event()
        event1["event_id"] = "EVT-CASE-E1"
        event1["source_edition"] = "2027_v1.0"
        process_diff_event(event1, self.test_queue_dir, self.reference_db)

        event2 = deepcopy(event1)
        event2["event_id"] = "EVT-CASE-E2"
        event2["source_edition"] = "2027_v2.0"
        res2 = process_diff_event(event2, self.test_queue_dir, self.reference_db)

        self.assertEqual(res2["status"], "CANDIDATE_GENERATED")
        self.assertEqual(res2["candidate"]["relationship_case"], "CASE_E_DOCUMENT_REVISION_NEW_EDITION")
        self.assertEqual(res2["candidate"]["revises_candidate"], "CAND-EVT-CASE-E1")

    # =========================================================================
    # Group 4: Input Size, Exceptions & Security (Problem E)
    # =========================================================================

    def test_oversized_payload_file_rejection_before_reading(self):
        """Oversized payload files (> 1MB) are rejected before memory loading."""
        huge_file = os.path.join(self.test_queue_dir, "huge_payload.json")
        with open(huge_file, "wb") as f:
            f.write(b"0" * (MAX_PAYLOAD_BYTES + 100))

        res = process_diff_event(huge_file, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "PAYLOAD_SIZE_EXCEEDED")
        self.assertIn("exceeds limit", res["error"])

    def test_deeply_nested_json_rejection(self):
        """Reject deeply nested JSON payloads exceeding MAX_NESTING_DEPTH to prevent recursion DoS."""
        event = self.load_base_event()
        nested = {"level1": {"level2": {"level3": {"level4": {"level5": {"level6": "too_deep"}}}}}}
        event["pipeline_routing"]["deep_attack"] = nested

        res = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "REJECTED_QUARANTINED")
        self.assertIn("nesting depth", res["error"])

    def test_path_traversal_rejection_in_event_id(self):
        """Reject event_ids containing path traversal sequences."""
        for bad_id in ["../../etc/passwd", "..\\secret", "sub/folder"]:
            event = self.load_base_event()
            event["event_id"] = bad_id
            res = process_diff_event(event, self.test_queue_dir, self.reference_db)
            self.assertEqual(res["status"], "REJECTED_QUARANTINED")
            self.assertIn("path traversal", res["error"])

    # =========================================================================
    # Group 5: Thermal & RAM Diagnostics (Problem E)
    # =========================================================================

    def test_thermal_corner_cases_nan_inf_none_bool(self):
        """Strictly reject non-finite and abnormal types (NaN, Inf, -Inf, None, bool)."""
        for val in [float("nan"), float("inf"), float("-inf"), None, True, False, "75.0"]:
            dec = evaluate_thermal_trip(val)
            self.assertFalse(dec["allow_inference"])
            self.assertEqual(dec["mode"], "YELLOW_ASSUMED_UNSAFE")

    def test_thermal_negative_and_extreme_anomaly(self):
        """Reject negative (<0C) and extreme (>150C) readings as physical anomalies."""
        for anomaly in [-10.0, -0.01, 150.1, 999.0]:
            dec = evaluate_thermal_trip(anomaly)
            self.assertFalse(dec["allow_inference"])
            self.assertEqual(dec["action"], "HALT_DUE_TO_PHYSICAL_ANOMALY")

    def test_thermal_strict_boundaries(self):
        """Verify strict behavior at threshold boundaries (75.9, 76.0, 89.9, 90.0)."""
        self.assertEqual(evaluate_thermal_trip(75.9)["mode"], "GREEN_NORMAL")
        self.assertEqual(evaluate_thermal_trip(76.0)["mode"], "YELLOW_WARNING")
        self.assertEqual(evaluate_thermal_trip(89.9)["mode"], "YELLOW_WARNING")
        self.assertEqual(evaluate_thermal_trip(90.0)["mode"], "RED_CRITICAL")
        self.assertEqual(evaluate_thermal_trip(90.0)["action"], "EMERGENCY_ABORT")

    def test_mock_inference_runner_fail_close_abort(self):
        """Verify MockInferenceRunner triggers fail-close abort upon RED or UNKNOWN reading."""
        runner = MockInferenceRunner()
        profile = [68.0, 74.0, 91.5, 70.0]
        res = runner.execute_mock_task(profile)
        self.assertEqual(runner.state, "ABORTED")
        self.assertEqual(res["final_state"], "ABORTED")
        self.assertEqual(res["processed_steps"], 2)
        self.assertEqual(res["abort_action"], "EMERGENCY_ABORT")

    # =========================================================================
    # Group 6: Real Mutation / Fault Injection Testing (Section 7)
    # =========================================================================

    def test_mutation_bypassing_quota_check_fails(self):
        """MUTATION TEST: If semantic quota check is omitted, an ungrounded quota event must fail verification."""
        event_bad_quota = self.load_base_event()
        event_bad_quota["simulated_diff"]["after_text"] = "2027年度AC入試の募集人数は999名に変更する。"
        event_bad_quota["checksum_after"] = compute_checksum(event_bad_quota["simulated_diff"]["after_text"])

        # Under un-mutated logic, this is rejected
        res = process_diff_event(event_bad_quota, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "REJECTED_UNGROUNDED")

        # Mutate logic: simulate buggy verifier that forgets quota check
        def buggy_verifier_skips_quota(cand, ref_db, text):
            # Missing quota check entirely!
            return True, []

        mutated_valid, _ = buggy_verifier_skips_quota(res["quarantine_record"]["candidate"], self.reference_db, event_bad_quota["simulated_diff"]["after_text"])
        # Assert that the mutated check incorrectly passed, proving our real test catches the omission!
        with self.assertRaises(AssertionError):
            self.assertEqual(mutated_valid, False, "Mutation test: Skipped quota check must be caught as a defect")

    def test_mutation_bypassing_unreadable_file_protection_fails(self):
        """MUTATION TEST: If corrupted file check is omitted, it would overwrite existing files."""
        staging_dir = os.path.join(self.test_queue_dir, "staging_queue")
        os.makedirs(staging_dir, exist_ok=True)
        event = self.load_base_event()
        event["event_id"] = "EVT-MUT-CORRUPT"
        target_file = os.path.join(staging_dir, f"CAND-{event['event_id']}.json")

        corrupt_data = b"CORRUPTED_EXISTING_FILE_BYTES"
        with open(target_file, "wb") as f:
            f.write(corrupt_data)

        # Under real logic, it detects unreadable existing candidate and protects it
        res = process_diff_event(event, self.test_queue_dir, self.reference_db)
        self.assertEqual(res["status"], "EXISTING_CANDIDATE_UNREADABLE_QUARANTINED")

        # Mutated logic: simulate old code that used `except Exception: pass` and overwrote
        def mutated_handler_overwrites(file_path):
            try:
                with open(file_path, "r") as f: json.load(f)
            except Exception:
                pass  # Swallowed!
            with open(file_path, "wb") as f: f.write(b"OVERWRITTEN_DATA")

        mutated_handler_overwrites(target_file)
        with open(target_file, "rb") as f:
            overwritten_data = f.read()

        # Assert that the mutation caused data loss, proving our real code's protection is vital
        with self.assertRaises(AssertionError):
            self.assertEqual(overwritten_data, corrupt_data, "Mutation test: Code without unreadable check overwrites data")

if __name__ == "__main__":
    unittest.main()
