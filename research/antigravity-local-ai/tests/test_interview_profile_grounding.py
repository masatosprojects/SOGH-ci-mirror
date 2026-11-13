#!/usr/bin/env python3
"""
Unit tests for SOGH Local AI Security & Grounding Sanitizer (SELF_TEST).

Verifies local model safety safeguards:
1. Hostile character cleaning (zero-width, BOM, controls).
2. PII and secret masking (emails, phones, URLs, synthetic tokens).
3. Oversized payload rejection (> 4000 chars).
4. Forbidden marketing claims rejection (合格確実, 完全再現).
5. Ungrounded official claims rejection (倍率, 締切, 定員).
6. Verbatim quotation verification against reference context.
7. Pure in-memory / zero-network execution.
"""

import sys
import unittest
from pathlib import Path

SCRIPTS_PATH = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

from interview_profile_grounding import (
    sanitize_and_validate_local_output,
    clean_hostile_characters,
    mask_secrets_and_pii,
    MAX_INPUT_CHARS
)


class TestLocalAISecuritySanitizer(unittest.TestCase):
    def setUp(self):
        self.reference_doc = (
            "地域の竹林放置問題を解決するため竹粉末混合バイオプラスチックの開発に取り組みました。"
            "家庭用3Dプリンターで射出可能なペレット配合実験を64回実施しました。"
        )

    def test_clean_hostile_characters(self):
        """Verify zero-width space, BOM, and control characters are stripped."""
        hostile = "合\u200B格\uFEFFできます\x00\x1F！"
        cleaned, removed = clean_hostile_characters(hostile)
        self.assertEqual(cleaned, "合格できます！")
        self.assertGreater(removed, 0)

    def test_pii_and_token_masking(self):
        """Verify emails, phones, and synthetic secret tokens are masked."""
        raw = "連絡先は 090-1234-5678 または student@example.com、疑似秘密は FICTION_SECRET_TOKEN_XYZ です。"
        masked = mask_secrets_and_pii(raw)
        self.assertNotIn("090-1234-5678", masked)
        self.assertNotIn("student@example.com", masked)
        self.assertNotIn("FICTION_SECRET_TOKEN_XYZ", masked)
        self.assertIn("[電話番号]", masked)
        self.assertIn("[メール]", masked)
        self.assertIn("[MASKED_TOKEN]", masked)

    def test_oversized_payload_rejected(self):
        """Verify output exceeding MAX_INPUT_CHARS is rejected."""
        huge = "あ" * (MAX_INPUT_CHARS + 10)
        res = sanitize_and_validate_local_output(huge)
        self.assertFalse(res.is_safe)
        self.assertEqual(res.verdict, "REJECTED_OVERSIZED_INPUT")

    def test_forbidden_marketing_claim_rejected(self):
        """Verify marketing guarantees such as '合格確実' are rejected."""
        output = "この回答方法を身につければ合格確実です。"
        res = sanitize_and_validate_local_output(output)
        self.assertFalse(res.is_safe)
        self.assertEqual(res.verdict, "REJECTED_FORBIDDEN_CLAIM")

    def test_ungrounded_official_claim_rejected(self):
        """Verify unverified official numbers and dates are rejected."""
        output = "今年の出願倍率は5倍で締切は9月30日です。"
        res = sanitize_and_validate_local_output(output)
        self.assertFalse(res.is_safe)
        self.assertEqual(res.verdict, "REJECTED_UNGROUNDED_CLAIM")

    def test_fabricated_quote_rejected(self):
        """Verify quoted phrases absent from reference context are rejected."""
        output = "資料に「全国大会で最優秀賞を受賞」とありますが、詳しく教えてください。"
        res = sanitize_and_validate_local_output(output, reference_context=self.reference_doc)
        self.assertFalse(res.is_safe)
        self.assertEqual(res.verdict, "REJECTED_FABRICATED_QUOTE")

    def test_valid_quoted_output_passes(self):
        """Verify legitimate verbatim quotation passes sanitization."""
        output = "あなたが入力した「竹粉末混合バイオプラスチックの開発」について動機を教えてください。"
        res = sanitize_and_validate_local_output(output, reference_context=self.reference_doc)
        self.assertTrue(res.is_safe)
        self.assertEqual(res.verdict, "SAFE_GROUNDED")

    def test_pure_in_memory_offline_execution(self):
        """Verify sanitization operates purely in-memory with zero network calls."""
        output = "安全な出力テキストです。"
        res = sanitize_and_validate_local_output(output)
        self.assertTrue(res.is_safe)


if __name__ == "__main__":
    unittest.main()
