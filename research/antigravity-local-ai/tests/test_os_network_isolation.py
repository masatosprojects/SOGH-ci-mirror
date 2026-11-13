#!/usr/bin/env python3
"""
SOGH Antigravity - OS Network Isolation Unit Tests

Verifies:
1. Raw socket probe detection of proxy bypass.
2. Windows firewall rule parser handling of missing and active rules.
3. Host containment classification (VULNERABLE_PROXY_ONLY vs OS_LEVEL_CONTAINED).
4. Elevated remediation command generation.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import os_network_isolation_evaluator as evaluator


class TestOSNetworkIsolation(unittest.TestCase):
    """Test suite for OS-level network isolation and containment evaluation."""

    def test_probe_raw_socket_egress_structure(self):
        """Verify probe returns expected dictionary schema."""
        res = evaluator.probe_raw_socket_egress(target_host="127.0.0.1", target_port=1, timeout_sec=0.1)
        self.assertIn("proxy_environment_configured", res)
        self.assertIn("target_endpoint", res)
        self.assertIn("raw_socket_connected", res)
        self.assertIn("verdict", res)
        self.assertIn("detail", res)

    @patch("socket.socket")
    def test_probe_raw_socket_detects_connection_success(self, mock_socket_cls):
        """When socket.connect succeeds, verdict must be PROXY_BYPASS_CONFIRMED_VULNERABLE."""
        mock_instance = MagicMock()
        mock_instance.connect.return_value = None
        mock_socket_cls.return_value = mock_instance

        res = evaluator.probe_raw_socket_egress(target_host="1.1.1.1", target_port=53)
        self.assertTrue(res["raw_socket_connected"])
        self.assertEqual(res["verdict"], "PROXY_BYPASS_CONFIRMED_VULNERABLE")

    @patch("socket.socket")
    def test_probe_raw_socket_handles_connection_refusal(self, mock_socket_cls):
        """When socket.connect raises exception, verdict must reflect failure."""
        mock_instance = MagicMock()
        mock_instance.connect.side_effect = ConnectionRefusedError("Connection refused by test mock")
        mock_socket_cls.return_value = mock_instance

        res = evaluator.probe_raw_socket_egress(target_host="127.0.0.1", target_port=9999)
        self.assertFalse(res["raw_socket_connected"])
        self.assertEqual(res["verdict"], "SOCKET_CONNECTION_FAILED_OR_BLOCKED")

    def test_inspect_windows_firewall_rule_not_found(self):
        """Non-existent rule returns FIREWALL_RULE_NOT_FOUND."""
        res = evaluator.inspect_windows_firewall_rule("NON_EXISTENT_RULE_NAME_XYZ_123")
        self.assertFalse(res["rule_found"])
        self.assertEqual(res["status"], "FIREWALL_RULE_NOT_FOUND")

    @patch("subprocess.run")
    def test_inspect_windows_firewall_rule_active_parsing(self, mock_run):
        """Properly detects enabled outbound block rule from netsh output."""
        mock_output = (
            "Rule Name:                            SOGH_Antigravity_Block_Llama_CLI\n"
            "----------------------------------------------------------------------\n"
            "Enabled:                              Yes\n"
            "Direction:                            Out\n"
            "Profiles:                             Domain,Private,Public\n"
            "Grouping:                             \n"
            "LocalIP:                              Any\n"
            "RemoteIP:                             Any\n"
            "Protocol:                             Any\n"
            "Edge traversal:                       No\n"
            "Action:                               Block\n"
            "Ok.\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)

        res = evaluator.inspect_windows_firewall_rule("SOGH_Antigravity_Block_Llama_CLI")
        self.assertTrue(res["rule_found"])
        self.assertTrue(res["is_outbound"])
        self.assertTrue(res["is_block"])
        self.assertTrue(res["is_enabled"])
        self.assertEqual(res["status"], "FIREWALL_BLOCK_RULE_ACTIVE")

    @patch("os_network_isolation_evaluator.inspect_windows_firewall_rule")
    @patch("os_network_isolation_evaluator.probe_raw_socket_egress")
    def test_evaluate_host_network_containment_vulnerable(self, mock_probe, mock_fw):
        """When firewall rule is missing, host containment must be VULNERABLE_PROXY_ONLY."""
        mock_fw.return_value = {"status": "FIREWALL_RULE_NOT_FOUND", "rule_found": False}
        mock_probe.return_value = {"raw_socket_connected": True}

        report = evaluator.evaluate_host_network_containment()
        self.assertEqual(report["containment_level"], "VULNERABLE_PROXY_ONLY")
        self.assertFalse(report["safe_for_confidential_data"])
        self.assertTrue(report["remediation_command_required"])
        self.assertIsNotNone(report["elevated_setup_command"])

    @patch("os_network_isolation_evaluator.inspect_windows_firewall_rule")
    @patch("os_network_isolation_evaluator.probe_raw_socket_egress")
    def test_evaluate_host_network_containment_firewall_active(self, mock_probe, mock_fw):
        """When firewall rule is active, containment level confirms target exe is blocked."""
        mock_fw.return_value = {"status": "FIREWALL_BLOCK_RULE_ACTIVE", "rule_found": True}
        mock_probe.return_value = {"raw_socket_connected": False}

        report = evaluator.evaluate_host_network_containment()
        self.assertEqual(report["containment_level"], "OS_LEVEL_CONTAINED")
        self.assertTrue(report["safe_for_confidential_data"])
        self.assertFalse(report["remediation_command_required"])

    def test_generate_firewall_setup_command_formatting(self):
        """Verify generated netsh command contains required parameters."""
        cmd = evaluator.generate_firewall_setup_command(
            executable_path=r"C:\test\my_llama.exe",
            rule_name="MyTestRule"
        )
        self.assertIn("netsh advfirewall firewall add rule", cmd)
        self.assertIn('name="MyTestRule"', cmd)
        self.assertIn("dir=out", cmd)
        self.assertIn("action=block", cmd)
        self.assertIn("program=", cmd)
        self.assertIn("enable=yes", cmd)


if __name__ == "__main__":
    unittest.main()
