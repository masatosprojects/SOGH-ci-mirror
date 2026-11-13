#!/usr/bin/env python3
"""
SOGH Antigravity - Diagnostics CLI Unit Tests (v0.4.1)

Verifies run_comprehensive_diagnostics report structure, threshold evaluation,
and safety invariants.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from diagnostics import run_comprehensive_diagnostics


class TestDiagnosticsCLI(unittest.TestCase):
    """Test suite for unified hardware diagnostics tool."""

    def test_run_comprehensive_diagnostics_structure(self):
        report = run_comprehensive_diagnostics()
        self.assertIn("timestamp", report)
        self.assertIn("overall_hardware_green", report)
        self.assertIn("can_execute_real_model", report)
        self.assertIn("ram", report)
        self.assertIn("power", report)
        self.assertIn("thermal", report)
        self.assertIn("user_hold", report)
        self.assertIn("assets", report)

    def test_user_hold_blocks_real_model_execution(self):
        """When hold file exists, can_execute_real_model must be False."""
        report = run_comprehensive_diagnostics()
        if report["user_hold"]["hold_active"]:
            self.assertFalse(
                report["can_execute_real_model"],
                "Real model execution must be strictly BLOCKED when hold file is present."
            )

    def test_low_ram_fails_preflight(self):
        """Simulated low RAM triggers RAM_INSUFFICIENT_FAILCLOSE and blocks execution."""
        mock_low_ram = {"avail_mb": 1500.0, "total_mb": 8000.0, "load_pct": 81}
        with patch("supervised_inference_runner.get_ram_metrics", return_value=mock_low_ram):
            report = run_comprehensive_diagnostics()
            self.assertFalse(report["ram"]["passed"])
            self.assertEqual(report["ram"]["status_code"], "RAM_INSUFFICIENT_FAILCLOSE")
            self.assertFalse(report["can_execute_real_model"])


if __name__ == "__main__":
    unittest.main()
