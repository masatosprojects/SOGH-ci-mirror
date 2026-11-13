#!/usr/bin/env python3
"""
SOGH Antigravity - Real Model Grounding Evaluation Unit Tests (Phase 3 Integration)

Validates output cleaner and real model evaluation harness data structures.
"""

import unittest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from evaluate_real_model_grounding import clean_llama_output


class TestRealModelGroundingHarness(unittest.TestCase):
    """Test suite for real model grounding output cleaner and parser."""

    def test_clean_llama_output_strips_banner_and_thinking(self):
        sample_output = (
            "Loading model...\n"
            "build      : b12109-13ec8f614\n"
            "available commands:\n"
            "  /exit or Ctrl+C\n"
            "> 【回答】\n"
            "[Start thinking]\n"
            "Thinking about Tsukuba entrance exam.\n"
            "[End thinking]\n"
            "出願書類は書留・速達郵便にて送付してください。\n"
            "[ Prompt: 25.1 t/s | Generation: 9.4 t/s ]\n"
            "Exiting...\n"
        )
        cleaned = clean_llama_output(sample_output, prompt="【回答】")
        self.assertNotIn("Loading model", cleaned)
        self.assertNotIn("build      :", cleaned)
        self.assertNotIn("[Start thinking]", cleaned)
        self.assertNotIn("Exiting...", cleaned)
        self.assertEqual(cleaned, "出願書類は書留・速達郵便にて送付してください。")

    def test_clean_llama_output_empty_returns_empty(self):
        self.assertEqual(clean_llama_output("", "prompt"), "")


if __name__ == "__main__":
    unittest.main()
