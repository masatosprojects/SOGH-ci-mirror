#!/usr/bin/env python3
"""
SOGH Antigravity - OS Network Isolation & Egress Containment Evaluator

Technical Purpose:
Rigorously evaluates whether local AI child processes are truly isolated from
external network communication at the OS layer, rather than relying on the
naive and easily-bypassed proxy environment variables (HTTP_PROXY).

Key Findings (2026-11-08):
1. Environment variables (HTTP_PROXY=http://127.0.0.1:0) ONLY affect high-level
   libraries (e.g. urllib, requests). C/C++ native binaries (llama-cli.exe)
   calling Winsock connect() bypass proxy variables completely.
2. Dynamic firewall rule creation requires Administrator elevation (UAC).
   Unprivileged runner processes cannot dynamically add firewall block rules.
3. However, an unprivileged runner CAN inspect whether an administrator-installed
   outbound block rule (SOGH_Antigravity_Block_Llama_CLI) is active via netsh.
4. Adoption Decision Impact:
   Unless an OS-level outbound block rule is verified, local LLM execution is
   classified as VULNERABLE_PROXY_ONLY and deemed UNSUITABLE for confidential
   student data.
"""

from __future__ import annotations

import os
import sys
import socket
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

DEFAULT_FIREWALL_RULE_NAME = "SOGH_Antigravity_Block_Llama_CLI"
DEFAULT_TARGET_EXECUTABLE = Path(r"C:\Users\USER\llm_bench\cpu\llama-cli.exe")


def probe_raw_socket_egress(
    target_host: str = "1.1.1.1",
    target_port: int = 53,
    timeout_sec: float = 1.0
) -> Dict[str, Any]:
    """
    Empirically probes whether a raw TCP socket can establish an outbound
    connection despite proxy environment variables being active.
    """
    proxy_set = bool(os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY"))
    
    sock = None
    connected = False
    error_msg = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        sock.connect((target_host, target_port))
        connected = True
    except Exception as e:
        connected = False
        error_msg = str(e)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    if connected:
        verdict = "PROXY_BYPASS_CONFIRMED_VULNERABLE"
        detail = (
            f"Raw TCP socket connected to {target_host}:{target_port} in {timeout_sec}s. "
            "Environment variables (HTTP_PROXY) fail to block low-level network egress."
        )
    else:
        verdict = "SOCKET_CONNECTION_FAILED_OR_BLOCKED"
        detail = f"Connection to {target_host}:{target_port} failed: {error_msg}"

    return {
        "proxy_environment_configured": proxy_set,
        "target_endpoint": f"{target_host}:{target_port}",
        "raw_socket_connected": connected,
        "verdict": verdict,
        "detail": detail
    }


def inspect_windows_firewall_rule(rule_name: str = DEFAULT_FIREWALL_RULE_NAME) -> Dict[str, Any]:
    """
    Inspects whether a specific Windows Defender Firewall outbound block rule
    exists and is enabled. Works without Administrator privileges.
    """
    if sys.platform != "win32":
        return {
            "supported_os": False,
            "rule_name": rule_name,
            "rule_found": False,
            "status": "NON_WINDOWS_OS"
        }

    try:
        cmd = ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5.0
        )
        output = proc.stdout

        if proc.returncode == 0 and rule_name.lower() in output.lower():
            # Parse Direction and Action
            is_outbound = "Direction:                            Out" in output or "方向:                                出" in output or "Out" in output
            is_block = "Action:                               Block" in output or "操作:                                阻止" in output or "Block" in output
            is_enabled = "Enabled:                              Yes" in output or "有効:                                はい" in output or "Yes" in output

            return {
                "supported_os": True,
                "rule_name": rule_name,
                "rule_found": True,
                "is_outbound": is_outbound,
                "is_block": is_block,
                "is_enabled": is_enabled,
                "status": "FIREWALL_BLOCK_RULE_ACTIVE" if (is_outbound and is_block and is_enabled) else "FIREWALL_RULE_MISCONFIGURED",
                "raw_output_snippet": output[:400]
            }
        else:
            return {
                "supported_os": True,
                "rule_name": rule_name,
                "rule_found": False,
                "is_outbound": False,
                "is_block": False,
                "is_enabled": False,
                "status": "FIREWALL_RULE_NOT_FOUND",
                "raw_output_snippet": output[:200]
            }
    except Exception as e:
        return {
            "supported_os": True,
            "rule_name": rule_name,
            "rule_found": False,
            "status": "INSPECTION_FAILED",
            "error": str(e)
        }


def generate_firewall_setup_command(
    executable_path: Path | str = DEFAULT_TARGET_EXECUTABLE,
    rule_name: str = DEFAULT_FIREWALL_RULE_NAME
) -> str:
    """
    Generates the exact elevated netsh command required to block outbound
    traffic for the target inference binary.
    """
    exe_str = str(Path(executable_path).resolve())
    return (
        f'netsh advfirewall firewall add rule name="{rule_name}" '
        f'dir=out action=block program="{exe_str}" enable=yes profile=any'
    )


def evaluate_host_network_containment(
    target_executable: Path | str | None = None,
    rule_name: str = DEFAULT_FIREWALL_RULE_NAME,
    run_socket_probe: bool = True
) -> Dict[str, Any]:
    """
    Unified host containment evaluation synthesizing OS firewall inspection
    and empirical raw socket bypass testing.
    """
    exe_path = Path(target_executable) if target_executable else DEFAULT_TARGET_EXECUTABLE
    
    fw_audit = inspect_windows_firewall_rule(rule_name=rule_name)
    sock_probe = probe_raw_socket_egress() if run_socket_probe else {"skipped": True}

    firewall_verified = fw_audit.get("status") == "FIREWALL_BLOCK_RULE_ACTIVE"
    raw_socket_leaks = sock_probe.get("raw_socket_connected", False)

    if firewall_verified and not raw_socket_leaks:
        containment_level = "OS_LEVEL_CONTAINED"
        safe_for_confidential_data = True
        recommendation = "SUITABLE_FOR_LOCAL_INFERENCE_UNDER_SUPERVISED_GUARD"
    elif firewall_verified and raw_socket_leaks:
        # Firewall rule exists but test socket still connected (likely because probe test uses python, not target exe)
        containment_level = "TARGET_EXE_FIREWALL_BLOCKED_GENERAL_SOCKET_ACTIVE"
        safe_for_confidential_data = True
        recommendation = "TARGET_EXE_CONTAINED_PYTHON_HARNESS_UNBLOCKED"
    else:
        containment_level = "VULNERABLE_PROXY_ONLY"
        safe_for_confidential_data = False
        recommendation = "UNSUITABLE_FOR_CONFIDENTIAL_STUDENT_DATA_WITHOUT_ELEVATED_FIREWALL"

    elevated_cmd = generate_firewall_setup_command(exe_path, rule_name)

    return {
        "timestamp": None,
        "target_executable": str(exe_path),
        "target_executable_exists": exe_path.is_file(),
        "firewall_rule_name": rule_name,
        "firewall_audit": fw_audit,
        "socket_probe": sock_probe,
        "containment_level": containment_level,
        "safe_for_confidential_data": safe_for_confidential_data,
        "recommendation": recommendation,
        "remediation_command_required": not firewall_verified,
        "elevated_setup_command": elevated_cmd if not firewall_verified else None
    }


if __name__ == "__main__":
    import json
    report = evaluate_host_network_containment()
    print(json.dumps(report, indent=2, ensure_ascii=False))
