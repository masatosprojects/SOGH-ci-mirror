#!/usr/bin/env python3
"""
SOGH Antigravity - Test Suite for Local LLM Grounding Response Parser (STR-068 & Self-Audit)

Verifies that grounding_response_parser.py strictly adheres to:
1. Exact parsing of VERIFIED_MATCH, CONTRADICTION, UNVERIFIED, PROHIBITED_SUBSTITUTION
2. Automatic stripping of markdown codeblocks (```text / ```json)
3. Strict fail-close (UNKNOWN_FORMAT_FAIL_CLOSE) on narrative, ambiguous, or empty output
4. Immediate quarantine on PII / secret pattern detection
5. Rejection and quarantine on ANSI control injection, null bytes, prompt template leaks, and noise
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.grounding_response_parser import parse_grounding_verdict, unwrap_codeblock, enforce_strict_output_contract


class TestGroundingResponseParser(unittest.TestCase):
    """Test suite for LLM grounding response parsing and fail-close invariants."""

    def test_verified_match_parsing(self):
        """Verify clean VERIFIED_MATCH output resolves to MATCH with quarantined=False."""
        raw = "VERIFIED_MATCH"
        res = parse_grounding_verdict(raw)
        self.assertTrue(res["success"])
        self.assertEqual(res["verdict"], "MATCH")
        self.assertFalse(res["quarantined"])

    def test_verified_match_with_markdown_fencing(self):
        """Verify VERIFIED_MATCH wrapped in markdown fences resolves accurately."""
        raw = "```text\nVERIFIED_MATCH\n```"
        res = parse_grounding_verdict(raw)
        self.assertTrue(res["success"])
        self.assertEqual(res["verdict"], "MATCH")
        self.assertFalse(res["quarantined"])

    def test_contradiction_parsing(self):
        """Verify CONTRADICTION: <reason> extracts reason and is quarantined."""
        raw = "CONTRADICTION: The quota stated is 20, but official DB specifies 15."
        res = parse_grounding_verdict(raw)
        self.assertTrue(res["success"])
        self.assertEqual(res["verdict"], "CONTRADICTION")
        self.assertIn("official DB specifies 15", res["reason"])
        self.assertTrue(res["quarantined"])

    def test_unverified_parsing(self):
        """Verify UNVERIFIED: <missing facts> is properly recognized and quarantined."""
        raw = "UNVERIFIED: Specific interview time limits are missing from source document."
        res = parse_grounding_verdict(raw)
        self.assertTrue(res["success"])
        self.assertEqual(res["verdict"], "UNVERIFIED")
        self.assertTrue(res["quarantined"])

    def test_prohibited_substitution_parsing(self):
        """Verify PROHIBITED_SUBSTITUTION: <reason> is properly quarantined."""
        raw = "PROHIBITED_SUBSTITUTION: Candidate asserts 共通テスト成績 requirement for AC admission."
        res = parse_grounding_verdict(raw)
        self.assertTrue(res["success"])
        self.assertEqual(res["verdict"], "PROHIBITED_SUBSTITUTION")
        self.assertTrue(res["quarantined"])

    def test_json_formatted_output(self):
        """Verify JSON output is correctly parsed into valid verdict."""
        raw = '```json\n{"verdict": "CONTRADICTION", "reason": "Academic year mismatch (2024 vs 2026)"}\n```'
        res = parse_grounding_verdict(raw)
        self.assertTrue(res["success"])
        self.assertEqual(res["verdict"], "CONTRADICTION")
        self.assertTrue(res["quarantined"])

    def test_empty_or_none_output_fails_close(self):
        """Verify empty, whitespace, or None outputs strictly fail close."""
        for empty_val in [None, "", "   \n\t  "]:
            res = parse_grounding_verdict(empty_val)
            self.assertFalse(res["success"])
            self.assertEqual(res["verdict"], "UNKNOWN_FORMAT_FAIL_CLOSE")
            self.assertTrue(res["quarantined"])

    def test_hallucinatory_or_narrative_output_fails_close(self):
        """Verify conversational/narrative hallucinations fail close and are quarantined."""
        hallucination = (
            "I have analyzed the provided admission guidelines. In my opinion, the student's statement "
            "seems quite accurate, although there are minor differences. I recommend accepting it."
        )
        res = parse_grounding_verdict(hallucination)
        self.assertFalse(res["success"])
        self.assertEqual(res["verdict"], "UNKNOWN_FORMAT_FAIL_CLOSE")
        self.assertTrue(res["quarantined"])

    def test_pii_and_token_leak_fails_close(self):
        """Verify output containing potential GitHub token / password is immediately quarantined."""
        leaky_output = "VERIFIED_MATCH - Processed using key ghp_111122223333444455556666777788889999"
        res = parse_grounding_verdict(leaky_output)
        self.assertFalse(res["success"])
        self.assertEqual(res["verdict"], "UNKNOWN_FORMAT_FAIL_CLOSE")
        self.assertTrue(res["quarantined"])
        self.assertIn("Potential secret/PII detected", res["reason"])

    def test_ansi_escape_injection_fails_close(self):
        """Verify ANSI escape control injection triggers fail-close."""
        malicious_output = "\x1b[31;1mVERIFIED_MATCH\x1b[0m"
        res = parse_grounding_verdict(malicious_output)
        self.assertFalse(res["success"])
        self.assertEqual(res["verdict"], "UNKNOWN_FORMAT_FAIL_CLOSE")
        self.assertTrue(res["quarantined"])
        self.assertIn("ANSI escape sequences", res["reason"])

    def test_null_byte_corruption_fails_close(self):
        """Verify stream containing null bytes triggers immediate corruption fail-close."""
        corrupted_output = "VERIFIED\x00_MATCH"
        res = parse_grounding_verdict(corrupted_output)
        self.assertFalse(res["success"])
        self.assertEqual(res["verdict"], "UNKNOWN_FORMAT_FAIL_CLOSE")
        self.assertTrue(res["quarantined"])
        self.assertIn("corruption detected", res["reason"])

    def test_prompt_leak_fails_close(self):
        """Verify output echoing system prompt or instruction template is quarantined."""
        echoed_output = "System Prompt: You are an AI assistant. Verdict is VERIFIED_MATCH."
        res = parse_grounding_verdict(echoed_output)
        self.assertFalse(res["success"])
        self.assertEqual(res["verdict"], "UNKNOWN_FORMAT_FAIL_CLOSE")
        self.assertTrue(res["quarantined"])
        self.assertIn("SECURITY_VIOLATION", res["reason"])

    def test_trivial_short_noise_fails_close(self):
        """Verify trivial noise (< 3 chars) is quarantined."""
        for noise in ["..", "a", "\n "]:
            res = parse_grounding_verdict(noise)
            self.assertFalse(res["success"])
            self.assertEqual(res["verdict"], "UNKNOWN_FORMAT_FAIL_CLOSE")
            self.assertTrue(res["quarantined"])


if __name__ == "__main__":
    unittest.main()
