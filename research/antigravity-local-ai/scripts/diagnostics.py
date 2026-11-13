#!/usr/bin/env python3
r"""
SOGH Antigravity - Comprehensive Hardware & Safety Diagnostics (v0.4.1)

Capabilities:
1. Physical RAM measurement via Win32 API (GlobalMemoryStatusEx) with low-RAM halt.
2. Inference process running state detection (safe process inspection).
3. Thermal sensor evaluation with rigorous corner-case handling (evaluate_thermal_trip).
4. Synthetic Inference Controller Mock (MockInferenceRunner) to verify fail-close
   contract without killing real OS processes.
5. Unified preflight hardware audit (run_comprehensive_diagnostics):
   - Physical RAM floor (>= 2,200 MB threshold verification).
   - AC Power line status (battery throttling prevention).
   - Hybrid Thermal Sensor inspection (HWiNFO SM2 CPU die vs ACPI motherboard).
   - Real-Model User Hold status (HOLD_REAL_MODEL_RUN.txt detection).
   - Binaries and model assets integrity.
"""

import os
import sys
import platform
import shutil
import json
import math
import time
import ctypes
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Win32 Memory Status Structure
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

def get_ram_metrics():
    """Retrieve physical RAM metrics via Windows kernel32."""
    if platform.system() != "Windows":
        return {"status": "UNKNOWN", "error": "Non-Windows platform"}
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total_gb = round(stat.ullTotalPhys / (1024**3), 2)
            avail_gb = round(stat.ullAvailPhys / (1024**3), 2)
            used_gb = round(total_gb - avail_gb, 2)
            return {
                "status": "AVAILABLE",
                "total_physical_ram_gb": total_gb,
                "used_physical_ram_gb": used_gb,
                "available_physical_ram_gb": avail_gb,
                "memory_load_percent": stat.dwMemoryLoad,
                "low_ram_warning": avail_gb < 1.0,
                "critical_low_ram": avail_gb < 0.5
            }
        else:
            return {"status": "UNKNOWN", "error": "GlobalMemoryStatusEx call failed"}
    except Exception as e:
        return {"status": "UNKNOWN", "error": str(e)}

def get_running_inference_processes():
    """Check if any known local LLM processes are currently active."""
    known_inference_bins = ["llama-server.exe", "ollama.exe", "llama-bench.exe", "main.exe", "llama-cli.exe"]
    active = []
    try:
        import subprocess
        output = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="ignore")
        for line in output.splitlines():
            for bin_name in known_inference_bins:
                if bin_name.lower() in line.lower():
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        active.append({"name": parts[0], "pid": parts[1]})
        return {
            "status": "AVAILABLE",
            "active_inference_processes": active,
            "inference_running": len(active) > 0
        }
    except Exception as e:
        return {
            "status": "UNKNOWN",
            "active_inference_processes": [],
            "inference_running": "UNKNOWN",
            "error": str(e)
        }

def evaluate_thermal_trip(reading_celsius):
    """
    Evaluates temperature reading against fail-close safety boundaries.
    """
    if reading_celsius is None:
        return {
            "mode": "YELLOW_ASSUMED_UNSAFE",
            "allow_inference": False,
            "action": "HALT_DUE_TO_UNKNOWN_TEMPERATURE",
            "reason": "Reading is None (sensor unavailable)"
        }
    if isinstance(reading_celsius, str):
        return {
            "mode": "YELLOW_ASSUMED_UNSAFE",
            "allow_inference": False,
            "action": "HALT_DUE_TO_INVALID_TYPE",
            "reason": f"Reading is string: '{reading_celsius}'"
        }
    if isinstance(reading_celsius, bool):
        return {
            "mode": "YELLOW_ASSUMED_UNSAFE",
            "allow_inference": False,
            "action": "HALT_DUE_TO_INVALID_TYPE",
            "reason": "Reading is boolean"
        }
    try:
        temp = float(reading_celsius)
    except (TypeError, ValueError):
        return {
            "mode": "YELLOW_ASSUMED_UNSAFE",
            "allow_inference": False,
            "action": "HALT_DUE_TO_NON_NUMERIC_READING",
            "reason": "Non-numeric temperature value"
        }

    if math.isnan(temp) or math.isinf(temp):
        return {
            "mode": "YELLOW_ASSUMED_UNSAFE",
            "allow_inference": False,
            "action": "HALT_DUE_TO_INVALID_FLOAT",
            "reason": "Temperature is NaN or Inf"
        }

    if temp < 0.0 or temp > 150.0:
        return {
            "mode": "YELLOW_ASSUMED_UNSAFE",
            "allow_inference": False,
            "action": "HALT_DUE_TO_PHYSICAL_ANOMALY",
            "reason": f"Temperature {temp}C outside plausible operating envelope (0 - 150C)"
        }

    if temp >= 90.0:
        return {
            "mode": "RED_CRITICAL",
            "allow_inference": False,
            "action": "EMERGENCY_ABORT",
            "reason": f"Temperature {temp}C meets or exceeds critical ceiling (90.0C)"
        }
    elif temp >= 76.0:
        return {
            "mode": "YELLOW_WARNING",
            "allow_inference": True,
            "cooldown_needed": True,
            "action": "THROTTLE",
            "reason": f"Temperature {temp}C in warning zone (76.0 - 89.9C)"
        }
    else:
        return {
            "mode": "GREEN_NORMAL",
            "allow_inference": True,
            "cooldown_needed": False,
            "action": "PROCEED",
            "reason": f"Temperature {temp}C within normal zone (<76.0C)"
        }

class MockInferenceRunner:
    """
    A simulated inference controller to test fail-close emergency aborts
    via contracts without killing actual OS processes.
    """
    def __init__(self):
        self.state = "IDLE"
        self.abort_reason = None

    def execute_mock_task(self, temperature_readings: list) -> dict:
        self.state = "RUNNING"
        processed_steps = 0
        for reading in temperature_readings:
            decision = evaluate_thermal_trip(reading)
            if not decision.get("allow_inference", False):
                self.state = "ABORTED"
                self.abort_reason = decision.get("reason")
                return {
                    "final_state": self.state,
                    "processed_steps": processed_steps,
                    "abort_action": decision.get("action"),
                    "reason": self.abort_reason
                }
            processed_steps += 1

        self.state = "COMPLETED"
        return {
            "final_state": self.state,
            "processed_steps": processed_steps,
            "abort_action": None,
            "reason": None
        }

def run_diagnostics():
    report = {
        "timestamp": datetime.now().isoformat(),
        "platform": {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
        },
        "python": {
            "version": sys.version,
            "executable": sys.executable,
        },
        "memory": get_ram_metrics(),
        "inference_runtime": get_running_inference_processes(),
        "storage": {},
        "models": {
            "directory": r"C:\Users\USER\llm_bench\models",
            "found_models": []
        }
    }
    total, used, free = shutil.disk_usage("C:\\")
    report["storage"]["c_drive"] = {
        "total_gb": round(total / (1024**3), 2),
        "used_gb": round(used / (1024**3), 2),
        "free_gb": round(free / (1024**3), 2),
        "free_ratio_percent": round((free / total) * 100, 1)
    }
    model_dir = report["models"]["directory"]
    if os.path.exists(model_dir):
        for f in os.listdir(model_dir):
            if f.endswith(".gguf"):
                fp = os.path.join(model_dir, f)
                report["models"]["found_models"].append({
                    "name": f,
                    "size_mb": round(os.path.getsize(fp) / (1024**2), 2)
                })
    return report

# ==============================================================================
# v0.4.1 Unified Comprehensive Diagnostics Entrypoint
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    import supervised_inference_runner as runner
    from thermal_sensor_reader import ThermalSensorManager
except ImportError:
    runner = None
    ThermalSensorManager = None

LLAMA_EXE = Path(r"C:\Users\USER\llm_bench\cpu\llama-cli.exe")
MODEL_PATH = Path(r"C:\Users\USER\llm_bench\models\Qwen3-1.7B-Q4_K_M.gguf")
HOLD_FILE = BASE_DIR / "HOLD_REAL_MODEL_RUN.txt"

def run_comprehensive_diagnostics() -> Dict[str, Any]:
    timestamp_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    
    # 1. RAM Check
    if runner:
        ram = runner.get_ram_metrics()
        ram_ok = ram["avail_mb"] >= 2200.0
        ram_status = {
            "avail_mb": round(ram["avail_mb"], 1),
            "total_mb": round(ram["total_mb"], 1),
            "load_pct": ram["load_pct"],
            "threshold_mb": 2200.0,
            "passed": ram_ok,
            "status_code": "RAM_GREEN" if ram_ok else "RAM_INSUFFICIENT_FAILCLOSE"
        }
    else:
        ram_status = {"passed": False, "status_code": "RUNNER_UNAVAILABLE"}
        ram_ok = False

    # 2. Power Check
    if runner:
        power = runner.get_power_status()
        power_ok = power["on_ac"]
        power_status = {
            "on_ac": power_ok,
            "battery_pct": power["battery_pct"],
            "passed": power_ok,
            "status_code": "POWER_AC_CONNECTED" if power_ok else "POWER_BATTERY_FAILCLOSE"
        }
    else:
        power_status = {"passed": False, "status_code": "RUNNER_UNAVAILABLE"}
        power_ok = False

    # 3. Thermal Sensor Check
    if ThermalSensorManager:
        thermal_mgr = ThermalSensorManager()
        therm_status, reading, therm_msg = thermal_mgr.read_current_thermal_state()
        is_direct_die = getattr(reading, "is_direct_die", False) if reading else False
        temp_c = getattr(reading, "temp_c", None) if reading else None
        temp_ok = (temp_c is not None) and (temp_c < 76.0)
        thermal_summary = {
            "status": therm_status,
            "temp_c": temp_c,
            "sensor_name": getattr(reading, "sensor_name", "NONE") if reading else "NONE",
            "sensor_type": getattr(reading, "sensor_type", "NONE") if reading else "NONE",
            "is_direct_die": is_direct_die,
            "threshold_c": 76.0,
            "within_safe_temperature": temp_ok,
            "message": therm_msg
        }
    else:
        thermal_summary = {"within_safe_temperature": False, "status": "MANAGER_UNAVAILABLE"}
        temp_ok = False

    # 4. User Hold Check
    hold_active = HOLD_FILE.is_file()
    hold_summary = {
        "hold_active": hold_active,
        "hold_file_path": str(HOLD_FILE),
        "status_code": "HOLD_ACTIVE_EXECUTION_BLOCKED" if hold_active else "HOLD_INACTIVE"
    }

    # 5. Assets Check
    assets_summary = {
        "llama_cli_found": LLAMA_EXE.is_file(),
        "llama_cli_path": str(LLAMA_EXE),
        "model_found": MODEL_PATH.is_file(),
        "model_path": str(MODEL_PATH)
    }

    # 6. Instance Lock Check
    if runner:
        try:
            r_inst = runner.SupervisedInferenceRunner()
            lock_summary = r_inst.inspect_instance_lock()
        except Exception as e:
            lock_summary = {"status": "INSPECTION_ERROR", "error": str(e)}
    else:
        lock_summary = {"status": "RUNNER_UNAVAILABLE"}

    overall_hardware_green = ram_ok and power_ok and temp_ok
    can_execute_real_model = overall_hardware_green and not hold_active and assets_summary["llama_cli_found"] and assets_summary["model_found"] and (lock_summary.get("status") == "NO_LOCK")

    return {
        "timestamp": timestamp_iso,
        "overall_hardware_green": overall_hardware_green,
        "can_execute_real_model": can_execute_real_model,
        "ram": ram_status,
        "power": power_status,
        "thermal": thermal_summary,
        "user_hold": hold_summary,
        "assets": assets_summary,
        "instance_lock": lock_summary
    }

def print_diagnostics_report(report: Dict[str, Any]):
    print("================================================================================")
    print(" SOGH Antigravity - Comprehensive Safety & Hardware Diagnostics (v0.4.1)")
    print(f" Timestamp: {report['timestamp']}")
    print("================================================================================")
    ram = report["ram"]
    print(f"[RAM]     Available: {ram.get('avail_mb', 'N/A')} MB / {ram.get('total_mb', 'N/A')} MB (Load: {ram.get('load_pct', 'N/A')}%) -> [{'PASS' if ram.get('passed') else 'FAIL'}]")
    pwr = report["power"]
    print(f"[POWER]   AC Line Status: {'Connected (AC)' if pwr.get('on_ac') else 'Disconnected (Battery)'} ({pwr.get('battery_pct', 'N/A')}%) -> [{'PASS' if pwr.get('passed') else 'FAIL'}]")
    therm = report["thermal"]
    temp_str = f"{therm.get('temp_c')} °C" if therm.get('temp_c') is not None else "N/A"
    print(f"[THERMAL] Sensor: {therm.get('sensor_name')} ({therm.get('sensor_type')})")
    print(f"          Temperature: {temp_str} (Direct Die: {therm.get('is_direct_die')}) -> Status: {therm.get('status')}")
    print(f"          Detail: {therm.get('message')}")
    hold = report["user_hold"]
    print(f"[HOLD]    User Real-Model Hold: {'ACTIVE (Blocked by user instruction)' if hold.get('hold_active') else 'INACTIVE'}")
    assets = report["assets"]
    print(f"[ASSETS]  llama-cli: {'FOUND' if assets.get('llama_cli_found') else 'NOT FOUND'} | Model: {'FOUND' if assets.get('model_found') else 'NOT FOUND'}")
    lock = report.get("instance_lock", {})
    print(f"[LOCK]    Instance Lock Status: {lock.get('status', 'UNKNOWN')} ({lock.get('lock_file', '')})")
    print("--------------------------------------------------------------------------------")
    print(f" Overall Hardware Safe: [{'YES' if report['overall_hardware_green'] else 'NO'}]")
    print(f" Ready for Real Model Execution: [{'READY' if report['can_execute_real_model'] else 'BLOCKED'}]")
    if not report['can_execute_real_model']:
        reasons = []
        if not ram.get('passed'): reasons.append("Insufficient RAM (<2200MB)")
        if not pwr.get('passed'): reasons.append("Not on AC power")
        if not therm.get('within_safe_temperature'): reasons.append("Thermal threshold breach or sensor offline")
        if hold.get('hold_active'): reasons.append("User safety hold file present (HOLD_REAL_MODEL_RUN.txt)")
        if not assets.get('llama_cli_found'): reasons.append("llama-cli.exe missing")
        if not assets.get('model_found'): reasons.append("Model GGUF missing")
        if lock.get('status') != 'NO_LOCK': reasons.append(f"Instance lock busy/stale: {lock.get('status')}")
        print(f" Blocking Reasons: {', '.join(reasons)}")
    print("================================================================================")

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = run_comprehensive_diagnostics()
    print_diagnostics_report(report)

if __name__ == "__main__":
    main()
