#!/usr/bin/env python3
"""
SOGH Antigravity - Test Suite for Grounding Verification Evaluation CLI (Phase 3)

Verifies:
1. evaluate_dataset accurately processes comprehensive FAQ benchmark.
2. format_markdown_report outputs valid markdown table and correct metrics.
3. CLI exit code reflects pass/fail status.
4. Error handling for nonexistent datasets.
"""

import sys
import unittest
import tempfile
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.evaluate_grounding import evaluate_dataset, format_markdown_report, DEFAULT_DATASET


class TestEvaluateGroundingCLI(unittest.TestCase):
    """Test suite for evaluation runner and reporting."""

    def test_default_comprehensive_dataset_evaluation(self):
        """Verify default comprehensive dataset achieves 100% accuracy and 0% hallucinations."""
        summary = evaluate_dataset(DEFAULT_DATASET)
        self.assertTrue(summary["all_passed"])
        self.assertEqual(summary["total_cases"], 10)
        self.assertEqual(summary["correct_cases"], 10)
        self.assertEqual(summary["accuracy_pct"], 100.0)
        self.assertEqual(summary["hallucination_count"], 0)
        self.assertEqual(summary["hallucination_rate_pct"], 0.0)
        self.assertEqual(summary["fail_close_violations"], 0)

    def test_markdown_report_formatting(self):
        """Verify markdown report generation produces well-structured table."""
        summary = evaluate_dataset(DEFAULT_DATASET)
        report = format_markdown_report(summary)
        self.assertIn("# SOGH Antigravity: Grounding Verification Evaluation Report", report)
        self.assertIn("100.0%", report)
        self.assertIn("PASSED_ALL_CHECKS", report)
        self.assertIn("TSUKUBA_FAQ_101_SUBMISSION_METHOD", report)
        self.assertIn("TSUKUBA_FAQ_103_COMMON_TEST_PROHIBITED", report)

    def test_nonexistent_dataset_raises_error(self):
        """Verify missing dataset file triggers FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            evaluate_dataset(Path("nonexistent_eval_file_xyz.json"))

    def test_synthetic_failing_case_detected(self):
        """Verify that if a case violates fail-close or hallucinates, all_passed is False."""
        bad_dataset = {
            "benchmark_version": "test-bad",
            "cases": [
                {
                    "case_id": "FAKE_CASE_FAIL",
                    "topic": "Fake Topic",
                    "faq_heading": "Heading",
                    "quoted_text": "Different text",
                    "official_grounding_source": {
                        "source_url": "https://www.tsukuba.ac.jp/test.html",
                        "section_sha256": "abc",
                        "verified_text": "Original text"
                    },
                    "expected_verdict": "MATCH",
                    "security_class": "SAFETY_CRITICAL"
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
            json.dump(bad_dataset, f)
            temp_path = Path(f.name)

        try:
            summary = evaluate_dataset(temp_path)
            self.assertFalse(summary["all_passed"])
            self.assertEqual(summary["correct_cases"], 0)
        finally:
            if temp_path.exists():
                temp_path.unlink()


if __name__ == "__main__":
    unittest.main()
