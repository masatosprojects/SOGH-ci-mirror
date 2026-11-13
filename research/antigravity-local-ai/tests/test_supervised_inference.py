#!/usr/bin/env python3
"""
Unit and integration tests for SupervisedInferenceRunner using dummy child processes.
Phase 2A.3 Core Safety and Pre-Inference Hardening Tests:
- 1. Watchdog startup race prevention (pre-launch failure aborts before child spawn).
- 2. Watchdog in-flight crash containment (child killed immediately on watchdog death).
- 3. Ingestion-time output memory limit enforcement (runaway stdout flood terminates child).
- 4. Strict monotonic deadline enforcement (hard timeout termination).
- 5. Lock concurrency & tampering verification (different process, re-acquisition, tampered token).
- 6. Zero-bypass production API (strictly blocks if component temperature is unverified).
- 7. CLI parameter generator and validator bounds.
- 8. Defined PII and credential masking boundaries.

NEVER executes actual heavy LLM models or touches other AI processes.
"""

import os
import sys
import time
import json
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts"
FIXTURES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "eval"

if str(MODULE_PATH) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH))

from supervised_inference_runner import (
    SupervisedInferenceRunner,
    SafeInferenceConfig,
    build_safe_llama_command,
    validate_cli_args,
    get_ram_metrics,
    get_power_status,
    read_acpi_temperature,
    mask_sensitive_data,
    ALLOWED_MODEL_PATH,
    ALLOWED_LLAMA_CLI_PATH
)

class TestSupervisedInferenceRunner(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="sogh_runner_test_")
        self.runner = SupervisedInferenceRunner(lock_dir=self.test_dir)
        # Hermeticity guarantee: create dummy allowed files for hermetic tests across any machine (G1)
        self.patches = []
        import supervised_inference_runner as sir
        dummy_exe = Path(self.test_dir) / "llama-cli.exe"
        dummy_model = Path(self.test_dir) / "Qwen3-1.7B-Q4_K_M.gguf"
        dummy_exe.write_bytes(b"")
        dummy_model.write_bytes(b"")
        p1 = patch.object(sir, "ALLOWED_LLAMA_CLI_PATH", dummy_exe)
        p2 = patch.object(sir, "ALLOWED_MODEL_PATH", dummy_model)
        p3 = patch.object(sir.SafeInferenceConfig, "llama_cli_path", str(dummy_exe))
        p4 = patch.object(sir.SafeInferenceConfig, "model_path", str(dummy_model))
        p5 = patch.object(sys.modules[__name__], "ALLOWED_LLAMA_CLI_PATH", dummy_exe)
        p6 = patch.object(sys.modules[__name__], "ALLOWED_MODEL_PATH", dummy_model)
        for p in (p1, p2, p3, p4, p5, p6):
            p.start()
            self.patches.append(p)

    def tearDown(self):
        if hasattr(self, "patches"):
            for p in reversed(self.patches):
                p.stop()
        if hasattr(self, "runner"):
            self.runner.release_instance_lock()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. Watchdog Startup Race & In-Flight Crash Containment
    # --------------------------------------------------------------------------
    def test_watchdog_pre_launch_failure_prevents_child(self):
        """
        Verify that if watchdog monitor fails startup self-check,
        the supervisor aborts immediately and NEVER spawns the child process.
        """
        dummy_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        res = self.runner._execute_supervised_process(
            dummy_cmd,
            timeout_sec=5.0,
            is_test_harness=True,
            test_skip_ram=True,
            test_skip_ac=True,
            test_skip_temp=True,
            test_force_monitor_startup_failure=True
        )
        self.assertFalse(res["success"])
        self.assertIn("WATCHDOG_STARTUP_ABORT", res["error"])
        # Proof: child process was never created
        self.assertIsNone(self.runner.child_process, "Child process must NOT be spawned if watchdog fails startup")

    def test_watchdog_in_flight_crash_aborts_child(self):
        """
        Verify that if the watchdog thread crashes during execution,
        the supervisor immediately detects watchdog death and terminates the child.
        """
        # Child process that intends to sleep for 20 seconds
        dummy_cmd = [sys.executable, "-c", "import time; time.sleep(20)"]
        t_start = time.monotonic()
        res = self.runner._execute_supervised_process(
            dummy_cmd,
            timeout_sec=10.0,
            is_test_harness=True,
            test_skip_ram=True,
            test_skip_ac=True,
            test_skip_temp=True,
            test_force_monitor_in_flight_crash=True
        )
        t_elapsed = time.monotonic() - t_start

        self.assertFalse(res["success"])
        self.assertTrue(
            "WATCHDOG_THREAD_CRASH" in str(res["abort_reason"]) or
            "WATCHDOG_DIED_PREMATURELY" in str(res["abort_reason"]),
            f"Unexpected abort reason: {res['abort_reason']}"
        )
        self.assertLess(t_elapsed, 3.0, "Child process must be killed promptly upon watchdog crash")
        self.assertFalse(res["lingering_child_detected"])

    # --------------------------------------------------------------------------
    # 2. Ingestion-Time Bounded Streaming Capture & Memory DOS Protection
    # --------------------------------------------------------------------------
    def test_output_memory_limit_breach_terminates_child(self):
        """
        Verify that a child process emitting a runaway stream of stdout
        is caught at ingestion time, memory remains bounded, and process is aborted.
        """
        # Generates massive stream of data
        spam_script = "import sys, time; [(sys.stdout.write('A' * 4096), sys.stdout.flush()) for _ in range(300)]"
        dummy_cmd = [sys.executable, "-c", spam_script]

        t_start = time.monotonic()
        res = self.runner._execute_supervised_process(
            dummy_cmd,
            timeout_sec=5.0,
            is_test_harness=True,
            test_skip_ram=True,
            test_skip_ac=True,
            test_skip_temp=True
        )
        t_elapsed = time.monotonic() - t_start

        self.assertFalse(res["success"])
        self.assertIn("OUTPUT_LIMIT_EXCEEDED", str(res["abort_reason"]))
        # Verify retained buffer is strictly bounded
        self.assertLessEqual(len(res["stdout"]), self.runner.MAX_OUTPUT_BYTES + 200)
        self.assertFalse(res["lingering_child_detected"])

    # --------------------------------------------------------------------------
    # 3. Strict Monotonic Deadline Enforcement
    # --------------------------------------------------------------------------
    def test_dummy_child_process_timeout_termination(self):
        """Verify hanging dummy process is cleanly terminated within monotonic deadline."""
        dummy_cmd = [sys.executable, "-c", "import time; time.sleep(20)"]
        t_start = time.monotonic()
        res = self.runner._execute_supervised_process(
            dummy_cmd,
            timeout_sec=1.5,
            is_test_harness=True,
            test_skip_ram=True,
            test_skip_ac=True,
            test_skip_temp=True
        )
        t_elapsed = time.monotonic() - t_start

        self.assertFalse(res["success"])
        self.assertIn("TIMEOUT", res["abort_reason"])
        self.assertLess(t_elapsed, 4.0, "Hanging child must be terminated promptly")
        self.assertFalse(res["lingering_child_detected"])

    # --------------------------------------------------------------------------
    # 4. Lock Concurrency, Cross-Process Exclusion, & Tampering Protection
    # --------------------------------------------------------------------------
    def test_lock_contention_different_process(self):
        """Verify that a separate external Python process cannot acquire lock while held."""
        self.assertTrue(self.runner.acquire_instance_lock())

        # Spawn independent child process attempting to acquire the same lock
        probe_code = (
            "import sys; "
            f"sys.path.insert(0, r'{str(MODULE_PATH)}'); "
            "from supervised_inference_runner import SupervisedInferenceRunner; "
            f"r = SupervisedInferenceRunner(lock_dir=r'{str(self.test_dir)}'); "
            "sys.exit(0 if r.acquire_instance_lock() else 1)"
        )
        proc = subprocess.run([sys.executable, "-c", probe_code], capture_output=True)
        self.assertEqual(proc.returncode, 1, "External process must return exit code 1 (lock denied)")

        # Release lock on self.runner
        self.assertTrue(self.runner.release_instance_lock())

        # Probe again: now external process should succeed
        proc2 = subprocess.run([sys.executable, "-c", probe_code], capture_output=True)
        self.assertEqual(proc2.returncode, 0, "External process must succeed after release")

    def test_lock_reacquisition_immediately_after_release(self):
        """Verify clean reacquisition of lock immediately after release."""
        runner1 = SupervisedInferenceRunner(lock_dir=self.test_dir)
        runner2 = SupervisedInferenceRunner(lock_dir=self.test_dir)

        self.assertTrue(runner1.acquire_instance_lock())
        self.assertTrue(runner1.release_instance_lock())

        self.assertTrue(runner2.acquire_instance_lock())
        self.assertTrue(runner2.release_instance_lock())

    def test_lock_tampered_content_protection(self):
        """Verify release_instance_lock refuses to delete file if owner token was tampered with."""
        self.assertTrue(self.runner.acquire_instance_lock())

        # Externally tamper with the lock file
        with open(self.runner.lock_file, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "owner_token": "tampered_fake_token"}, f)

        # Release must fail and file must NOT be deleted
        released = self.runner.release_instance_lock()
        self.assertFalse(released)
        self.assertTrue(self.runner.lock_file.exists(), "Tampered lock file must NOT be deleted")

    def test_stale_lock_preservation(self):
        """Verify stale lock from previous crash is preserved and not auto-deleted."""
        stale_file = Path(self.test_dir) / "inference_single_instance.lock"
        stale_payload = {
            "pid": 999999,
            "owner_token": "stale_token_deadbeef",
            "acquired_at": "2026-11-06T00:00:00Z"
        }
        with open(stale_file, "w", encoding="utf-8") as f:
            json.dump(stale_payload, f)

        new_runner = SupervisedInferenceRunner(lock_dir=self.test_dir)
        self.assertFalse(new_runner.acquire_instance_lock())
        self.assertFalse(new_runner.release_instance_lock())
        self.assertTrue(stale_file.exists(), "Stale lock file must be preserved for audit")

    def test_inspect_and_cleanup_orphaned_lock_lifecycle(self):
        """Verify crash recovery lock auditing and guarded orphan cleanup."""
        runner = SupervisedInferenceRunner(lock_dir=self.test_dir)
        
        # 1. No lock
        audit0 = runner.inspect_instance_lock()
        self.assertEqual(audit0["status"], "NO_LOCK")

        # 2. Active lock held by running process (current process)
        self.assertTrue(runner.acquire_instance_lock())
        audit_active = runner.inspect_instance_lock()
        self.assertEqual(audit_active["status"], "ACTIVE_LOCK_HELD_BY_RUNNING_PROCESS")
        self.assertEqual(audit_active["pid"], os.getpid())

        # Refuse cleanup when held by living process even if force is True
        cleaned, reason = runner.cleanup_orphaned_lock(force_stale_cleanup=True)
        self.assertFalse(cleaned)
        self.assertIn("REFUSED_LIVING_PROCESS_HELD", reason)

        # Release normally
        self.assertTrue(runner.release_instance_lock())

        # 3. Simulate stale lock left by crashed dead PID (999999)
        stale_file = Path(self.test_dir) / "inference_single_instance.lock"
        stale_payload = {
            "pid": 999999,
            "owner_token": "deadbeef_token_1234",
            "acquired_at": "2026-11-08T00:00:00Z"
        }
        with open(stale_file, "w", encoding="utf-8") as f:
            json.dump(stale_payload, f)

        audit_stale = runner.inspect_instance_lock()
        self.assertEqual(audit_stale["status"], "STALE_ORPHANED_LOCK_DETECTED")
        self.assertEqual(audit_stale["dead_pid"], 999999)

        # Refuse cleanup without force_stale_cleanup authorization
        cleaned_no_force, reason_no_force = runner.cleanup_orphaned_lock(force_stale_cleanup=False)
        self.assertFalse(cleaned_no_force)
        self.assertIn("MANUAL_CONFIRMATION_REQUIRED", reason_no_force)
        self.assertTrue(stale_file.exists(), "Stale lock must NOT be auto-cleaned without force")

        # Clean with explicit force_stale_cleanup
        cleaned_force, reason_force = runner.cleanup_orphaned_lock(force_stale_cleanup=True)
        self.assertTrue(cleaned_force)
        self.assertIn("CLEANED_STALE_LOCK", reason_force)
        self.assertFalse(stale_file.exists(), "Stale lock must be removed after authorized cleanup")

    # --------------------------------------------------------------------------
    # 5. Production Zero-Bypass API & Unverified Sensor Blocking
    # --------------------------------------------------------------------------
    def test_production_api_blocks_when_sensor_unverified(self):
        """Verify production execution API strictly BLOCKS real LLM inference when sensor unverified."""
        mock_ram = {"total_mb": 8000.0, "avail_mb": 3500.0, "load_pct": 50}
        with patch("supervised_inference_runner.get_ram_metrics", return_value=mock_ram):
            config = SafeInferenceConfig(prompt="【架空国立北都大学】定員を教えてください。")
            res = self.runner.execute_production_inference(config)
            self.assertFalse(res["success"])
            self.assertIn("BLOCKED", res["error"])
            self.assertIn("PREFLIGHT_THERMAL_BLOCKED", res["error"])

    def test_production_api_blocks_when_ram_insufficient(self):
        """Verify production execution API strictly BLOCKS when free RAM < 2200 MB."""
        mock_ram = {"total_mb": 8000.0, "avail_mb": 1500.0, "load_pct": 80}
        with patch("supervised_inference_runner.get_ram_metrics", return_value=mock_ram):
            config = SafeInferenceConfig(prompt="【架空国立北都大学】定員を教えてください。")
            res = self.runner.execute_production_inference(config)
            self.assertFalse(res["success"])
            self.assertIn("PREFLIGHT_RAM_FAIL", res["error"])

    def test_test_harness_blocks_arbitrary_executables(self):
        """Verify test harness strictly rejects any binary other than python.exe."""
        res = self.runner._execute_supervised_process(
            cmd_args=["curl.exe", "http://example.com"],
            is_test_harness=True
        )
        self.assertFalse(res["success"])
        self.assertIn("TEST_HARNESS_SECURITY_ERROR", res["error"])

    # --------------------------------------------------------------------------
    # 6. CLI Command Builder & Validator
    # --------------------------------------------------------------------------
    def test_safe_command_builder_valid_and_bounds(self):
        """Verify safe command generator enforces exact binary, model, and numeric bounds."""
        config = SafeInferenceConfig(
            prompt="テストプロンプト",
            threads=2,
            threads_batch=2,
            ctx_size=1024,
            predict_tokens=64
        )
        cmd = build_safe_llama_command(config)
        self.assertEqual(cmd[0], str(ALLOWED_LLAMA_CLI_PATH.resolve()))
        self.assertIn("-m", cmd)
        self.assertIn("-t", cmd)
        self.assertIn("2", cmd)
        self.assertIn("-ngl", cmd)
        self.assertIn("0", cmd)

        with self.assertRaises(ValueError):
            build_safe_llama_command(SafeInferenceConfig(threads=4))
        with self.assertRaises(ValueError):
            build_safe_llama_command(SafeInferenceConfig(gpu_layers=1))
        with self.assertRaises(ValueError):
            build_safe_llama_command(SafeInferenceConfig(ctx_size=4096))

    def test_validate_cli_args_negative_cases(self):
        """Verify raw CLI validator rejects unknown, duplicate, or unsafe options."""
        base_cmd = [str(ALLOWED_LLAMA_CLI_PATH.resolve()), "-m", str(ALLOWED_MODEL_PATH.resolve())]

        # Unknown option
        ok, reason, _ = validate_cli_args(base_cmd + ["--unknown-option", "123"])
        self.assertFalse(ok)
        self.assertIn("Unknown or forbidden option", reason)

        # Duplicate option
        ok, reason, _ = validate_cli_args(base_cmd + ["-t", "2", "-t", "1"])
        self.assertFalse(ok)
        self.assertIn("Duplicate option", reason)

        # Syntax with = (e.g. --threads=4)
        ok, reason, _ = validate_cli_args(base_cmd + ["--threads=4"])
        self.assertFalse(ok)
        self.assertIn("exceeds limit", reason)

        # Threads batch > 2
        ok, reason, _ = validate_cli_args(base_cmd + ["--threads-batch=3"])
        self.assertFalse(ok)

        # GPU offload
        ok, reason, _ = validate_cli_args(base_cmd + ["-ngl", "1"])
        self.assertFalse(ok)

    # --------------------------------------------------------------------------
    # 7. Defined PII / Secret Masking & Sensor State
    # --------------------------------------------------------------------------
    def test_real_sensor_reading_and_classification(self):
        """Verify real ACPI temperature reading and unverified status metadata."""
        temp = read_acpi_temperature()
        if temp is None:
            self.skipTest("Host environment lacks ACPI thermal zone counter (expected on VM / headless / foreign host)")
        self.assertGreater(temp, 10.0)
        self.assertLess(temp, 100.0)

        meta = self.runner.THERMAL_SENSOR_METADATA
        self.assertEqual(meta["status"], "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED")

    def test_pii_and_secret_masking_defined_patterns(self):
        """Verify defined PII and secret patterns are masked with zero leak of raw secrets."""
        test_samples = [
            ("ユーザー連絡先: 080-1234-5678 です。", "[電話番号]"),
            ("問い合わせ先: user.admission@example.ac.jp へ。", "[メール]"),
            ("Authorization: Bearer secret_jwt_token_9876543210abcdef", "Authorization: Bearer [秘匿情報]"),
            ("api_key: key_live_51234567890abcdefghijklmn", "api_key: [秘匿情報]"),
            ("DB password = SuperSecurePassword_12345678", "DB password = [秘匿情報]"),
            ("token: ghp_1234567890abcdefghijklmnopqrstuvwxyz", "token: [秘匿トークン]"),
        ]
        raw_secrets = [
            "080-1234-5678",
            "user.admission@example.ac.jp",
            "secret_jwt_token_9876543210abcdef",
            "key_live_51234567890abcdefghijklmn",
            "SuperSecurePassword_12345678",
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        ]

        combined = " | ".join(s[0] for s in test_samples)
        sanitized = mask_sensitive_data(combined)
        for secret in raw_secrets:
            self.assertNotIn(secret, sanitized, f"Defined secret leaked: {secret}")

    def test_eval_set_json_schema_and_cases(self):
        """Verify sogh_admission_eval_set_v1.json syntax, version, and 6 cases."""
        eval_path = FIXTURES_PATH / "sogh_admission_eval_set_v1.json"
        with open(eval_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("version"), "2.0.0")
        cases = data.get("cases", [])
        self.assertEqual(len(cases), 6)


    def test_network_egress_attempt_triggers_failclose(self):
        """
        Verify that if a child process attempts an external network call,
        the harness intercepts/blocks the egress and fail-closes with
        NETWORK_EGRESS_DETECTED_FAILCLOSE, completely redacting outputs.
        """
        # Synthetic dummy process attempting external HTTP request
        dummy_net_cmd = [
            sys.executable,
            "-c",
            "import urllib.request; urllib.request.urlopen('http://example.com', timeout=1.0)"
        ]

        res = self.runner._execute_supervised_process(
            cmd_args=dummy_net_cmd,
            timeout_sec=5.0,
            is_test_harness=True,
            test_skip_ram=True,
            test_skip_ac=True,
            test_skip_temp=True
        )

        self.assertFalse(res["success"], "Network-attempting child must NOT succeed")
        self.assertIn("NETWORK_EGRESS_DETECTED_FAILCLOSE", str(res["abort_reason"]))
        self.assertEqual(res["stdout"], "[REDACTED_DUE_TO_NETWORK_VIOLATION]")
        self.assertEqual(res["stderr"], "[REDACTED_DUE_TO_NETWORK_VIOLATION]")

    def test_watchdog_sensor_loss_in_flight_terminates_child(self):
        """
        Verify that if the thermal sensor disconnects or becomes unavailable
        during execution, the watchdog trips EMERGENCY_THERMAL_FAILCLOSE and
        immediately force-terminates the child process.
        """
        dummy_cmd = [sys.executable, "-c", "import time; time.sleep(10)"]

        # First call is normal (green), second call loses sensor
        call_count = 0
        def dynamic_sensor_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Initial readings valid
                from thermal_sensor_reader import ThermalReading
                return ("COMPONENT_TEMP_VERIFIED_GREEN", ThermalReading(
                    sensor_name="AMD Ryzen CPU (Tctl/Tdie)",
                    hardware_id="CPU_DIE",
                    sensor_type="CPU_DIE_TCTL_TDIE",
                    is_direct_die=True,
                    temp_c=50.0,
                    timestamp_mono=time.monotonic(),
                    timestamp_iso="2026-11-08T00:00:00Z",
                    age_seconds=0.1,
                    is_fresh=True
                ), "valid")
            else:
                # Sudden sensor disconnect / unreadable failure
                return ("THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE", None, "Sensor query failed")

        with patch.object(self.runner.thermal_manager, "read_current_thermal_state", side_effect=dynamic_sensor_mock):
            res = self.runner._execute_supervised_process(
                cmd_args=dummy_cmd,
                timeout_sec=5.0,
                is_test_harness=True,
                test_skip_ram=True,
                test_skip_ac=True,
                test_skip_temp=False
            )

        self.assertFalse(res["success"], "Child must be terminated when sensor is lost")
        self.assertIn("EMERGENCY_THERMAL_FAILCLOSE", str(res["abort_reason"]))
        self.assertFalse(res["lingering_child_detected"])

    def test_watchdog_critical_overheat_in_flight_terminates_child(self):
        """
        Verify that if CPU temperature spikes to critical threshold (>= 90.0 C)
        during execution, the watchdog trips EMERGENCY_THERMAL_TRIP immediately
        and kills the child process.
        """
        dummy_cmd = [sys.executable, "-c", "import time; time.sleep(10)"]

        call_count = 0
        def dynamic_overheat_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            from thermal_sensor_reader import ThermalReading
            temp = 52.0 if call_count <= 2 else 92.5 # Spike to 92.5 C (exceeds EMERGENCY_MAX_TEMP_C of 90.0)
            return ("COMPONENT_TEMP_VERIFIED_GREEN", ThermalReading(
                sensor_name="AMD Ryzen CPU (Tctl/Tdie)",
                hardware_id="CPU_DIE",
                sensor_type="CPU_DIE_TCTL_TDIE",
                is_direct_die=True,
                temp_c=temp,
                timestamp_mono=time.monotonic(),
                timestamp_iso="2026-11-08T00:00:00Z",
                age_seconds=0.1,
                is_fresh=True
            ), "overheat test")

        with patch.object(self.runner.thermal_manager, "read_current_thermal_state", side_effect=dynamic_overheat_mock):
            res = self.runner._execute_supervised_process(
                cmd_args=dummy_cmd,
                timeout_sec=5.0,
                is_test_harness=True,
                test_skip_ram=True,
                test_skip_ac=True,
                test_skip_temp=False
            )

        self.assertFalse(res["success"], "Child must be terminated on thermal spike")
        self.assertIn("EMERGENCY_THERMAL_TRIP", str(res["abort_reason"]))
        self.assertIn("92.5 C", str(res["abort_reason"]))
        self.assertFalse(res["lingering_child_detected"])

if __name__ == "__main__":
    unittest.main()
