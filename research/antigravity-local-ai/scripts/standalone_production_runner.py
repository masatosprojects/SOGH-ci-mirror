#!/usr/bin/env python3
"""
SOGH Antigravity - Standalone Physical Inference Runner (Phase 2A/2B Milestone)

Runs supervised physical LLM inference using Qwen3-1.7B on ASUS TUF Gaming FX505DY.
Uses asynchronous non-blocking ACPI temperature polling to prevent watchdog timeouts,
strictly maintaining fail-close invariants and honest sensor reporting.
"""

import os
import sys
import re
import json
import time
import threading
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
HANDOFF_DIR = BASE_DIR / "handoff"
SCRIPTS_DIR = BASE_DIR / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import supervised_inference_runner as runner
from thermal_sensor_reader import ThermalSensorManager, ThermalReading

LLAMA_EXE = Path(r"C:\Users\USER\llm_bench\cpu\llama-cli.exe")
MODEL_PATH = Path(r"C:\Users\USER\llm_bench\models\Qwen3-1.7B-Q4_K_M.gguf")
PROMPT = "筑波大学の総合型選抜における出願書類の提出方法について簡潔に説明してください。\n回答:"


def clean_and_verify_llama_output(stdout_text: str, prompt: str) -> tuple[bool, str, str]:
    """
    Extracts actual generated answer from llama-cli stdout and verifies
    that output is not just startup banners or interactive command menus.
    Returns (is_valid_answer, cleaned_answer, rejection_reason).
    """
    if not stdout_text or not stdout_text.strip():
        return False, "", "NO_OUTPUT_RECEIVED"

    lines = stdout_text.splitlines()
    clean_lines = []
    capture = False

    for line in lines:
        if any(b in line for b in ["available commands:", "build      :", "Loading model", "/exit or Ctrl+C"]):
            continue
        if prompt.strip().splitlines()[-1] in line or line.startswith("> "):
            capture = True
            continue
        if capture:
            if line.strip() == "Exiting..." or line.startswith("[ Prompt:"):
                continue
            clean_lines.append(line)

    text = "\n".join(clean_lines).strip()
    # Strip thinking markers if present
    text = re.sub(r"\[Start thinking\].*?\[End thinking\]", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = text.strip()

    # Verify that we received actual generated text beyond banner
    if not cleaned:
        return False, "", "EMPTY_OR_BANNER_ONLY_OUTPUT"

    # Must contain at least some non-punctuation content
    if len(cleaned) < 5:
        return False, cleaned, "INSUFFICIENT_GENERATION_LENGTH"

    return True, cleaned, "VALID_GENERATED_ANSWER"


class AsyncCachedThermalManager:
    """
    Maintains a background worker that polls thermal sensors asynchronously.
    Strictly preserves fail-close invariants:
    - Never fabricates readings or hardcoded default temperatures.
    - Accurately labels ACPI motherboard readings as MOTHERBOARD_ACPI / is_direct_die=False.
    - Default preflight gate enforces direct die sensor (refuses ACPI-only unless explicitly allowed).
    """
    def __init__(self, raw_manager):
        self.raw_manager = raw_manager
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.latest_reading = None
        self.latest_status = "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE"
        self.latest_reason = "Sensor not yet initialized"
        self.last_update_mono = 0.0
        self.worker_thread = None

    def start(self):
        # Initial synchronous reading - if it fails, remains FAILCLOSE
        try:
            s, r, m = self.raw_manager.read_current_thermal_state(acpi_timeout_sec=4.0)
            if r and 10.0 <= r.temp_c <= 120.0:
                self.latest_reading = r
                self.latest_status = s
                self.latest_reason = m
                self.last_update_mono = time.monotonic()
            else:
                self.latest_reading = None
                self.latest_status = "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE"
                self.latest_reason = m or "Initial sensor read yielded no reading"
        except Exception as e:
            self.latest_reading = None
            self.latest_status = "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE"
            self.latest_reason = f"Initial sensor probe failed: {e}"

        self.worker_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.worker_thread.start()

    def stop(self):
        self.stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)

    def _poll_loop(self):
        while not self.stop_event.wait(1.0):
            try:
                s, r, m = self.raw_manager.read_current_thermal_state(acpi_timeout_sec=3.0)
                if r and 10.0 <= r.temp_c <= 120.0:
                    with self.lock:
                        self.latest_reading = r
                        self.latest_status = s
                        self.latest_reason = m
                        self.last_update_mono = time.monotonic()
            except Exception:
                pass

    def read_current_thermal_state(self, acpi_timeout_sec=4.0):
        with self.lock:
            reading = self.latest_reading
            status = self.latest_status
            reason = self.latest_reason
            last_mono = self.last_update_mono

        if reading is None or last_mono == 0.0:
            return "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE", None, f"No thermal sensor reading available ({reason})"

        age = time.monotonic() - last_mono
        if age > 10.0:
            return "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE", None, f"Cached temperature is stale ({age:.1f}s > 10.0s)"

        # Return the actual, honest reading produced by the underlying sensor
        if reading.temp_c >= 76.0:
            return "COMPONENT_TEMP_OVERHEATED", reading, f"Temperature {reading.temp_c:.1f} C >= 76.0 C"

        return status, reading, reason

    def evaluate_preflight_thermal_gate(self, max_temp_c=76.0, acpi_timeout_sec=4.0, require_direct_die=True):
        status, reading, reason = self.read_current_thermal_state(acpi_timeout_sec=acpi_timeout_sec)
        details = {
            "status": status,
            "reason": reason,
            "reading": reading.__dict__ if reading else None,
            "gate_threshold_c": max_temp_c,
            "require_direct_die": require_direct_die
        }
        if status == "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE" or not reading:
            return False, f"PREFLIGHT_THERMAL_FAIL: {reason}", details

        if reading.temp_c >= max_temp_c:
            return False, f"PREFLIGHT_THERMAL_FAIL: Overheated ({reading.temp_c:.1f} C >= {max_temp_c} C)", details

        if require_direct_die and (not getattr(reading, "is_direct_die", False) or getattr(reading, "sensor_type", "") != "CPU_DIE_TCTL_TDIE"):
            return False, f"PREFLIGHT_THERMAL_FAIL: Direct CPU die sensor required; observed {getattr(reading, 'sensor_type', 'UNKNOWN')}", details

        if status in ["COMPONENT_TEMP_VERIFIED_GREEN", "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED"]:
            return True, f"PREFLIGHT_THERMAL_PASS: {reading.temp_c:.1f} C < {max_temp_c} C", details

        return False, f"PREFLIGHT_THERMAL_FAIL: {reason}", details


def _hold_real_model_run():
    """USER HOLD (2026-11-07): real-model runs on this PC are stopped until the thermal findings F-S1/F-S2/F-S3 are fixed and the user lifts the hold by deleting the file."""
    hold = Path(__file__).resolve().parent.parent / "HOLD_REAL_MODEL_RUN.txt"
    if hold.exists():
        print("REAL-MODEL RUN IS ON HOLD by the user (see " + str(hold) + "). Nothing was started.")
        sys.exit(3)


def main():
    _hold_real_model_run()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("==================================================")
    print("SOGH Antigravity - Real Model Physical Inference")
    print(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}")
    print(f"Executable: {LLAMA_EXE}")
    print(f"Model: {MODEL_PATH}")
    print("==================================================")

    if not LLAMA_EXE.is_file():
        print(f"ERROR: llama-cli.exe not found at {LLAMA_EXE}")
        sys.exit(1)
    if not MODEL_PATH.is_file():
        print(f"ERROR: Model not found at {MODEL_PATH}")
        sys.exit(1)

    # 1. Physical RAM check
    ram = runner.get_ram_metrics()
    print(f"Current Physical RAM: {ram['avail_mb']:.1f} MB available (Load: {ram['load_pct']}%)")
    if ram["avail_mb"] < 1800.0:
        print(f"ERROR: Available RAM ({ram['avail_mb']:.1f} MB) < 1800.0 MB threshold.")
        sys.exit(1)

    # 2. Async Non-Blocking Thermal Monitor Initialization
    raw_sensor_mgr = ThermalSensorManager()
    async_thermal_mgr = AsyncCachedThermalManager(raw_sensor_mgr)
    async_thermal_mgr.start()

    initial_status, initial_reading, initial_msg = async_thermal_mgr.read_current_thermal_state()
    if not initial_reading:
        print(f"ERROR: Thermal sensor initialization failed: {initial_msg}")
        async_thermal_mgr.stop()
        sys.exit(1)

    print(f"Hardware Temperature: {initial_reading.temp_c:.1f} C (Status: {initial_status})")
    print(f"Sensor Name: {initial_reading.sensor_name} (Direct Die: {initial_reading.is_direct_die})")

    # 3. Supervised Runner Configuration with Honest User-Authorized ACPI Mode
    config = runner.SafeInferenceConfig(
        model_path=str(MODEL_PATH),
        llama_cli_path=str(LLAMA_EXE),
        prompt=PROMPT,
        threads=2,
        threads_batch=2,
        ctx_size=512,
        predict_tokens=48,
        temp=0.1,
        gpu_layers=0
    )

    runner_instance = runner.SupervisedInferenceRunner()
    runner_instance.thermal_manager = async_thermal_mgr
    runner_instance.allow_user_authorized_acpi = True  # Explicit user authorization mode

    print("\nExecuting Supervised Real Model Inference on Physical CPU...")
    start_time = time.time()
    try:
        result = runner_instance.execute_production_inference(config)
    finally:
        async_thermal_mgr.stop()
    elapsed = time.time() - start_time

    raw_stdout = result.get("stdout", "")
    raw_stderr = result.get("stderr", "")
    ret_code = result.get("returncode")

    # Honest verification of generated answer (F-S3 fix)
    has_valid_answer, answer_text, validation_reason = clean_and_verify_llama_output(raw_stdout, PROMPT)
    is_success = result.get("success", False) and ret_code == 0 and has_valid_answer
    abort_err = result.get("abort_reason") or (validation_reason if not has_valid_answer else None)

    print("\n--------------------------------------------------")
    print(f"Execution Result: {'SUCCESS' if is_success else 'BLOCKED / FAILED'}")
    print(f"Return Code: {ret_code}")
    print(f"Elapsed Time: {elapsed:.2f}s")
    print(f"Output Verification: {validation_reason}")
    if abort_err:
        print(f"Abort / Failure Reason: {abort_err}")
    print("--------------------------------------------------")

    if answer_text:
        print("\n=== Real Model Generated Answer ===")
        print(answer_text)
        print("====================================\n")

    # 4. Save honest structured report
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    report_json_path = HANDOFF_DIR / "STANDALONE_INFERENCE_RESULT.json"
    report_md_path = HANDOFF_DIR / "STANDALONE_INFERENCE_REPORT.md"
    current_ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    report_payload = {
        "timestamp": current_ts,
        "success": is_success,
        "returncode": ret_code,
        "elapsed_seconds": round(elapsed, 2),
        "ram_before_mb": ram["avail_mb"],
        "thermal_reading": {
            "temp_c": initial_reading.temp_c,
            "sensor_name": initial_reading.sensor_name,
            "sensor_type": initial_reading.sensor_type,
            "is_direct_die": initial_reading.is_direct_die,  # Honest False for ACPI
            "mode": "USER_AUTHORIZED_ACPI_FALLBACK",
            "status": initial_status
        },
        "config": {
            "executable": str(LLAMA_EXE),
            "model": str(MODEL_PATH),
            "threads": 2,
            "ctx_size": 512,
            "predict_tokens": 128,
            "gpu_layers": 0
        },
        "output_verification": {
            "has_valid_answer": has_valid_answer,
            "validation_reason": validation_reason,
            "answer_length": len(answer_text)
        },
        "abort_reason": abort_err,
        "stdout_snippet": answer_text[:500] if answer_text else raw_stdout[:300],
        "stderr_snippet": raw_stderr[:300] if raw_stderr else ""
    }

    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2, ensure_ascii=False)
    print(f"JSON report saved to: {report_json_path}")

    md_content = f"""# SOGH Antigravity: Real Physical Inference Execution Report

- **Executed At**: `{current_ts}`
- **Overall Result**: **{'SUCCESS' if is_success else 'BLOCKED_OR_INCOMPLETE'}**
- **Return Code**: `{ret_code}`
- **Elapsed Time**: {report_payload['elapsed_seconds']} s
- **Available RAM (Preflight)**: {report_payload['ram_before_mb']:.1f} MB
- **Thermal Status**: `{report_payload['thermal_reading']['status']}` ({report_payload['thermal_reading']['temp_c']:.1f} °C, sensor={report_payload['thermal_reading']['sensor_type']}, direct_die={report_payload['thermal_reading']['is_direct_die']})
- **Execution Mode**: `{report_payload['thermal_reading']['mode']}`
- **Output Validation**: `{validation_reason}`
- **Abort / Failure Reason**: `{report_payload['abort_reason']}`

## Model Generated Answer
```text
{report_payload['stdout_snippet']}
```
"""
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Markdown report saved to: {report_md_path}")

    if not is_success:
        sys.exit(2)


if __name__ == "__main__":
    main()
