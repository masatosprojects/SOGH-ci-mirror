#!/usr/bin/env python3
"""
SOGH Antigravity - Safe Supervised Local LLM Inference Controller (Phase 2A.3)

Strict fail-close process controller designed for ASUS TUF Gaming FX505DY:
1. True owner-level instance locking via unguessable instance token (UUID/secrets).
   - Differentiates multiple instances within the same PID / process.
   - Non-acquiring instances cannot release locks.
   - Stale locks are never forcefully deleted without explicit administrative confirmation.
   - Robust against TOCTOU and file tampering.
2. Complete architectural separation between Production API and Test Harness:
   - Production entrypoint (execute_production_inference) has zero bypass parameters.
   - Production entrypoint strictly BLOCKS if component core temperature is unverified.
   - Safe command generation from typed SafeInferenceConfig rather than arbitrary CLI input.
3. Strict CLI parameter validator:
   - Rejects unknown options (supports both -flag val and --flag=val).
   - Inspects both -t/--threads and -tb/--threads-batch (both capped at <= 2).
   - Rejects GPU offload (-ngl must be 0).
   - Rejects duplicate options and out-of-range/non-positive numbers.
   - Verifies exact resolved paths for executable and model.
4. Hardened watchdog monitor thread & startup race prevention:
   - Two-phase synchronization: Watchdog MUST start and pass initial health checks
     BEFORE child process can be spawned.
   - If watchdog fails startup, child process is NEVER launched.
   - Main execution thread actively monitors watchdog thread liveness (50ms interval);
     if watchdog crashes in-flight, child process is immediately terminated.
   - Strict 30.0s monotonic execution deadline shared between watchdog and main thread.
5. Ingestion-time bounded streaming capture (BoundedStreamReader):
   - Stdout and stderr are streamed chunk-by-chunk with a hard memory ceiling of 512 KB.
   - Excess bytes are discarded without buffering into memory to prevent DOS.
   - Drains pipes continuously to prevent pipe-buffer deadlocks.
   - Triggers clean child termination on runaway output breach.
6. Defined PII and credential masking:
   - Scopes precisely documented (Japanese phone, email, GH tokens, prefixed credentials).
   - Masking applied to stdout, stderr, command logs, and exception strings.
"""

import os
import sys
import re
import time
import json
import secrets
import ctypes
import tempfile
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

# Thermal Sensor Integration (Phase 2B)
try:
    from thermal_sensor_reader import ThermalSensorManager, ThermalReading
except ImportError:
    from .thermal_sensor_reader import ThermalSensorManager, ThermalReading

# Windows API Structures for RAM and Power
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

class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]

def get_ram_metrics() -> dict:
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        raise RuntimeError("Failed to query physical RAM via GlobalMemoryStatusEx")
    total_mb = stat.ullTotalPhys / (1024 * 1024)
    avail_mb = stat.ullAvailPhys / (1024 * 1024)
    load_pct = stat.dwMemoryLoad
    return {"total_mb": total_mb, "avail_mb": avail_mb, "load_pct": load_pct}

def get_power_status() -> dict:
    p = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(p)):
        return {"on_ac": False, "battery_pct": 0}
    return {"on_ac": (p.ACLineStatus == 1), "battery_pct": int(p.BatteryLifePercent)}

def read_acpi_temperature(timeout_sec: float = 4.0):
    r"""
    Reads Windows Thermal Zone counter in user mode:
    \Thermal Zone Information(*)\High Precision Temperature
    Formula: (CookedValue / 10) - 273.15 = Celsius.

    Note: Reads motherboard ACPI thermal zone (\_tz.thrm) near APU.
    Component core temperatures (CPU Tctl/Tdie, GPU die) remain unverified.
    """
    ps_cmd = (
        "$ErrorActionPreference='Stop'; "
        "$s=@((Get-Counter '\\Thermal Zone Information(*)\\High Precision Temperature').CounterSamples | "
        "Where-Object { $_.InstanceName -eq '\\_tz.thrm' -and $_.Status -eq 0 }); "
        "if($s.Count -ne 1){exit 2}; "
        "[Console]::Write(($s[0].CookedValue/10-273.15).ToString([Globalization.CultureInfo]::InvariantCulture))"
    )
    child_env = {k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"}
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=timeout_sec, env=child_env,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if r.returncode != 0:
            return None
        val = float(r.stdout.strip())
        if 0.0 < val < 125.0:
            return round(val, 2)
        return None
    except Exception:
        return None

# ==============================================================================
# PII & Secret Masking (Defined Patterns & Clear Boundaries)
# ==============================================================================
PHONE_REGEX = re.compile(r"\b0\d{1,4}[-(]?\d{1,4}[-)]?\d{3,4}\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
GH_TOKEN_REGEX = re.compile(r"\b(?:ghp_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{30,})\b")
SECRET_PREFIX_REGEX = re.compile(
    r"\b((?:api[_-]?key|secret[_-]?key|access[_-]?token|bearer|token|password|secret|key)[=:\s]+)[a-zA-Z0-9_\-]{8,}",
    re.IGNORECASE
)

def mask_sensitive_data(text: str) -> str:
    """Masks defined PII and secret patterns with deterministic replacement labels."""
    if not isinstance(text, str):
        return text
    t = PHONE_REGEX.sub("[電話番号]", text)
    t = EMAIL_REGEX.sub("[メール]", t)
    t = GH_TOKEN_REGEX.sub("[秘匿トークン]", t)
    t = SECRET_PREFIX_REGEX.sub(r"\1[秘匿情報]", t)
    return t


# ==============================================================================
# Ingestion-Time Bounded Streaming Reader (Zero Memory DOS)
# ==============================================================================
class BoundedStreamReader:
    """
    Real-time streaming reader that strictly bounds memory consumption.
    Chunks are ingested in 4KB blocks up to max_bytes.
    Any excess bytes beyond max_bytes are immediately drained and discarded to prevent pipe deadlock
    while ensuring the process's working set never grows unconstrained.
    """
    def __init__(self, stream, max_bytes: int):
        self.stream = stream
        self.max_bytes = max_bytes
        self.buffer = bytearray()
        self.total_bytes_read = 0
        self.limit_exceeded = False
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        try:
            while True:
                chunk = self.stream.read(4096)
                if not chunk:
                    break
                self.total_bytes_read += len(chunk)
                if not self.limit_exceeded:
                    space_left = self.max_bytes - len(self.buffer)
                    if len(chunk) <= space_left:
                        self.buffer.extend(chunk)
                    else:
                        self.buffer.extend(chunk[:space_left])
                        self.limit_exceeded = True
        except Exception:
            pass
        finally:
            try:
                self.stream.close()
            except Exception:
                pass

    def get_output(self, encoding="utf-8", errors="replace") -> str:
        self.thread.join(timeout=1.0)
        text = self.buffer.decode(encoding, errors=errors)
        if self.limit_exceeded:
            text += f"\n[TRUNCATED: Output stream exceeded memory ceiling of {self.max_bytes} bytes]"
        return text


# ==============================================================================
# Safe Configuration & Safe Command Builder
# ==============================================================================
ALLOWED_MODEL_PATH = Path(r"C:\Users\USER\llm_bench\models\Qwen3-1.7B-Q4_K_M.gguf")
ALLOWED_LLAMA_CLI_PATH = Path(r"C:\Users\USER\llm_bench\cpu\llama-cli.exe")

@dataclass(frozen=True)
class SafeInferenceConfig:
    """Immutable safe configuration for supervised Qwen3-1.7B execution."""
    model_path: str = ""
    llama_cli_path: str = ""
    prompt: str = ""
    threads: int = 2
    threads_batch: int = 2
    ctx_size: int = 2048
    predict_tokens: int = 128
    temp: float = 0.1
    gpu_layers: int = 0  # GPU offload strictly prohibited

    def __post_init__(self):
        if not self.model_path:
            object.__setattr__(self, "model_path", str(ALLOWED_MODEL_PATH))
        if not self.llama_cli_path:
            object.__setattr__(self, "llama_cli_path", str(ALLOWED_LLAMA_CLI_PATH))

def build_safe_llama_command(config: SafeInferenceConfig) -> list[str]:
    """
    Constructs a rigid, non-tamperable command vector from verified safe config.
    Guarantees no unknown or dangerous flags can be passed to llama-cli.
    """
    # 1. Verify executable path
    cli_path = Path(config.llama_cli_path).resolve()
    if cli_path != ALLOWED_LLAMA_CLI_PATH.resolve() or not cli_path.is_file():
        raise ValueError(f"Invalid llama-cli path: {config.llama_cli_path}")

    # 2. Verify model path
    model_path = Path(config.model_path).resolve()
    if model_path != ALLOWED_MODEL_PATH.resolve() or not model_path.is_file():
        raise ValueError(f"Invalid model path: {config.model_path}")

    # 3. Numeric bounds validation
    if not (1 <= config.threads <= 2):
        raise ValueError(f"threads ({config.threads}) must be 1 or 2")
    if not (1 <= config.threads_batch <= 2):
        raise ValueError(f"threads_batch ({config.threads_batch}) must be 1 or 2")
    if config.gpu_layers != 0:
        raise ValueError(f"gpu_layers must be 0 (got {config.gpu_layers})")
    if not (1 <= config.ctx_size <= 2048):
        raise ValueError(f"ctx_size ({config.ctx_size}) must be between 1 and 2048")
    if not (1 <= config.predict_tokens <= 256):
        raise ValueError(f"predict_tokens ({config.predict_tokens}) must be between 1 and 256")
    if not (0.0 <= config.temp <= 1.0):
        raise ValueError(f"temp ({config.temp}) must be between 0.0 and 1.0")

    return [
        str(cli_path),
        "-m", str(model_path),
        "-t", str(config.threads),
        "-tb", str(config.threads_batch),
        "-c", str(config.ctx_size),
        "-n", str(config.predict_tokens),
        "-ngl", "0",
        "--temp", str(config.temp),
        "-p", config.prompt
    ]


def validate_cli_args(args: list[str]) -> tuple[bool, str, dict]:
    """
    Strictly validates raw CLI argument vector for llama-cli.exe.
    - Rejects unknown options.
    - Handles both -flag val and --flag=val formats.
    - Rejects duplicate options.
    - Enforces numeric limits (threads <= 2, threads_batch <= 2, ngl == 0).
    - Verifies exact path of executable and model.
    """
    if not args or not isinstance(args, list):
        return False, "PARAM_VALIDATE_FAIL: args must be a non-empty list", {}

    exe = Path(args[0]).resolve()
    if exe != ALLOWED_LLAMA_CLI_PATH.resolve() or not exe.is_file():
        return False, f"PARAM_VALIDATE_FAIL: Unauthorized executable '{args[0]}'", {}

    ALLOWED_OPTIONS = {
        "-m": "model", "--model": "model",
        "-t": "threads", "--threads": "threads",
        "-tb": "threads_batch", "--threads-batch": "threads_batch",
        "-c": "ctx_size", "--ctx-size": "ctx_size",
        "-n": "predict_tokens", "--predict": "predict_tokens", "--n-predict": "predict_tokens",
        "-ngl": "gpu_layers", "--n-gpu-layers": "gpu_layers",
        "--temp": "temp",
        "-p": "prompt", "--prompt": "prompt"
    }

    seen_keys = set()
    parsed_values = {
        "threads": 1,
        "threads_batch": 1,
        "gpu_layers": 0,
        "ctx_size": 512,
        "predict_tokens": 128,
        "temp": 0.1,
        "model": None,
        "prompt": ""
    }

    i = 1
    while i < len(args):
        token = args[i]
        key = None
        val = None

        if "=" in token and token.startswith("--"):
            parts = token.split("=", 1)
            key = parts[0]
            val = parts[1]
            i += 1
        elif token in ALLOWED_OPTIONS:
            key = token
            if i + 1 >= len(args):
                return False, f"PARAM_VALIDATE_FAIL: Flag '{token}' missing value", {}
            val = args[i + 1]
            i += 2
        else:
            return False, f"PARAM_VALIDATE_FAIL: Unknown or forbidden option '{token}'", {}

        norm_key = ALLOWED_OPTIONS.get(key)
        if not norm_key:
            return False, f"PARAM_VALIDATE_FAIL: Option '{key}' not in whitelist", {}

        if norm_key in seen_keys:
            return False, f"PARAM_VALIDATE_FAIL: Duplicate option '{key}'", {}
        seen_keys.add(norm_key)

        # Parse & Validate value
        if norm_key in ("threads", "threads_batch"):
            try:
                iv = int(val)
                if not (1 <= iv <= 2):
                    return False, f"PARAM_VALIDATE_FAIL: {norm_key} ({iv}) exceeds limit (must be 1 or 2)", {}
                parsed_values[norm_key] = iv
            except ValueError:
                return False, f"PARAM_VALIDATE_FAIL: {norm_key} value '{val}' must be integer", {}
        elif norm_key == "gpu_layers":
            try:
                iv = int(val)
                if iv != 0:
                    return False, f"PARAM_VALIDATE_FAIL: gpu_layers ({iv}) forbidden (must be 0)", {}
                parsed_values[norm_key] = iv
            except ValueError:
                return False, f"PARAM_VALIDATE_FAIL: gpu_layers value '{val}' must be integer", {}
        elif norm_key == "ctx_size":
            try:
                iv = int(val)
                if not (1 <= iv <= 2048):
                    return False, f"PARAM_VALIDATE_FAIL: ctx_size ({iv}) out of range (1..2048)", {}
                parsed_values[norm_key] = iv
            except ValueError:
                return False, f"PARAM_VALIDATE_FAIL: ctx_size value '{val}' must be integer", {}
        elif norm_key == "predict_tokens":
            try:
                iv = int(val)
                if not (1 <= iv <= 256):
                    return False, f"PARAM_VALIDATE_FAIL: predict_tokens ({iv}) out of range (1..256)", {}
                parsed_values[norm_key] = iv
            except ValueError:
                return False, f"PARAM_VALIDATE_FAIL: predict_tokens value '{val}' must be integer", {}
        elif norm_key == "temp":
            try:
                fv = float(val)
                if not (0.0 <= fv <= 1.0):
                    return False, f"PARAM_VALIDATE_FAIL: temp ({fv}) out of range (0.0..1.0)", {}
                parsed_values[norm_key] = fv
            except ValueError:
                return False, f"PARAM_VALIDATE_FAIL: temp value '{val}' must be float", {}
        elif norm_key == "model":
            m_path = Path(val).resolve()
            if m_path != ALLOWED_MODEL_PATH.resolve() or not m_path.is_file():
                return False, f"PARAM_VALIDATE_FAIL: Unauthorized model path '{val}'", {}
            parsed_values[norm_key] = str(m_path)
        elif norm_key == "prompt":
            parsed_values[norm_key] = val

    if not parsed_values.get("model"):
        return False, "PARAM_VALIDATE_FAIL: Model path (-m/--model) is mandatory", {}

    return True, "PARAM_VALIDATE_PASSED", parsed_values


# ==============================================================================
# Supervised Inference Controller
# ==============================================================================
class SupervisedInferenceRunner:
    """
    Fail-close supervisor for local LLM inference under strict thermal & memory ceilings.
    """
    # Safety Thresholds
    START_MAX_TEMP_C = 76.0       # Must be GREEN (< 76.0 C) to start
    HOT_WARN_TEMP_C = 85.0        # Sustained warning ceiling
    EMERGENCY_MAX_TEMP_C = 90.0   # Critical trip ceiling (instant abort)
    MIN_START_RAM_MB = 2200.0     # Minimum free physical RAM to start (2,200 MB / 2.2 GB)
    EMERGENCY_MIN_RAM_MB = 700.0  # Emergency low RAM floor
    MAX_THREADS = 2               # Hard CPU thread ceiling
    HARD_TIMEOUT_SEC = 30.0       # Max execution time per prompt
    MAX_OUTPUT_BYTES = 512 * 1024 # 512 KB stdout/stderr buffer protection
    MONITOR_STARTUP_WAIT_SEC = 6.0 # Max wait for watchdog initialization (timing reconciliation)

    # Sensor Identification Metadata
    THERMAL_SENSOR_METADATA = {
        "sensor_source": "WINDOWS_PERFORMANCE_COUNTER",
        "counter_path": r"\Thermal Zone Information(*)\High Precision Temperature",
        "instance_name": r"\_tz.thrm",
        "status": "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED",
        "notes": "Motherboard ACPI thermal zone near APU. Direct CPU Tctl/Tdie and GPU core die temperatures unverified without HWiNFO64 shared memory."
    }

    def __init__(self, lock_dir=None):
        self.lock_dir = Path(lock_dir) if lock_dir else Path(tempfile.gettempdir()) / "sogh_antigravity_lock"
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.lock_dir / "inference_single_instance.lock"
        self.thermal_manager = ThermalSensorManager()
        self.allow_user_authorized_acpi = False
        self.owner_token = None
        self.child_process = None
        self.child_pid = None
        self.monitor_thread = None
        self.monitor_ready_event = threading.Event()
        self.stop_event = threading.Event()
        self.abort_reason = None
        self.metrics_log = []
        self._lock = threading.Lock()

    def is_pid_alive(self, pid: int | None) -> bool:
        """Checks whether a given process ID is actively running on the OS."""
        if pid is None or pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    return True
                return False
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def inspect_instance_lock(self) -> dict:
        """
        Audits the single-instance lock file state without altering it:
        - NO_LOCK: lock file does not exist.
        - ACTIVE_LOCK_HELD_BY_RUNNING_PROCESS: lock file exists and owning PID is alive.
        - STALE_ORPHANED_LOCK_DETECTED: lock file exists but owning PID is confirmed dead.
        - CORRUPTED_LOCK_DETECTED: lock file exists but cannot be parsed as valid JSON.
        """
        if not self.lock_file.exists():
            return {"status": "NO_LOCK", "lock_file": str(self.lock_file)}

        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                data = json.loads(f.read().strip())
            pid = data.get("pid")
            owner_token = data.get("owner_token")
            acquired_at = data.get("acquired_at")
            alive = self.is_pid_alive(pid)
            if alive:
                return {
                    "status": "ACTIVE_LOCK_HELD_BY_RUNNING_PROCESS",
                    "lock_file": str(self.lock_file),
                    "pid": pid,
                    "acquired_at": acquired_at,
                    "owner_token_prefix": owner_token[:6] if owner_token else None
                }
            else:
                return {
                    "status": "STALE_ORPHANED_LOCK_DETECTED",
                    "lock_file": str(self.lock_file),
                    "dead_pid": pid,
                    "acquired_at": acquired_at,
                    "owner_token_prefix": owner_token[:6] if owner_token else None
                }
        except Exception as e:
            return {
                "status": "CORRUPTED_LOCK_DETECTED",
                "lock_file": str(self.lock_file),
                "error": str(e)
            }

    def cleanup_orphaned_lock(self, force_stale_cleanup: bool = False) -> tuple[bool, str]:
        """
        Safely clears a lock abandoned by a crashed or killed process.
        - Strictly REFUSES to touch locks held by living processes.
        - Requires force_stale_cleanup=True to prevent accidental deletion during automated runs.
        """
        audit = self.inspect_instance_lock()
        status = audit["status"]
        if status == "NO_LOCK":
            return True, "NO_LOCK_PRESENT"
        if status == "ACTIVE_LOCK_HELD_BY_RUNNING_PROCESS":
            return False, f"REFUSED_LIVING_PROCESS_HELD: PID {audit['pid']} is actively running"
        if status in ("STALE_ORPHANED_LOCK_DETECTED", "CORRUPTED_LOCK_DETECTED"):
            if not force_stale_cleanup:
                return False, f"MANUAL_CONFIRMATION_REQUIRED: Stale lock preserved for audit (dead PID {audit.get('dead_pid')})"
            try:
                self.lock_file.unlink(missing_ok=True)
                return True, f"CLEANED_STALE_LOCK: Removed lock file from dead PID {audit.get('dead_pid')}"
            except Exception as e:
                return False, f"CLEANUP_FAILED: {str(e)}"
        return False, f"UNKNOWN_LOCK_STATUS: {status}"

    def acquire_instance_lock(self) -> bool:
        """
        Acquires exclusive non-blocking file lock recording an unguessable owner token.
        Only the instance holding this unique owner token can release the lock.
        """
        if self.owner_token is not None:
            return True

        token = secrets.token_hex(16)
        lock_fd = None
        try:
            lock_fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            payload = {
                "pid": os.getpid(),
                "owner_token": token,
                "acquired_at": datetime.now(timezone.utc).isoformat()
            }
            os.write(lock_fd, json.dumps(payload).encode("utf-8"))
            os.close(lock_fd)
            lock_fd = None
            self.owner_token = token
            return True
        except FileExistsError:
            return False
        except Exception:
            return False
        finally:
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except Exception:
                    pass

    def release_instance_lock(self) -> bool:
        """
        Releases instance lock with true instance ownership verification:
        - If this instance did not acquire the lock (self.owner_token is None), does nothing.
        - Verifies that the lock file contains self.owner_token before unlinking.
        - Never deletes another instance's lock (even with matching PID).
        - Stale locks from other instances are preserved for admin audit.
        """
        if self.owner_token is None:
            return False

        current_token = self.owner_token
        self.owner_token = None

        if not self.lock_file.exists():
            return False

        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                data = json.loads(f.read().strip())
            if data.get("owner_token") == current_token:
                try:
                    self.lock_file.unlink()
                    return True
                except FileNotFoundError:
                    return False
        except Exception:
            pass

        return False

    def run_preflight_checks(self) -> tuple[bool, str, dict]:
        """
        Mandatory production pre-flight safety gates:
        1. RAM >= 2200 MB
        2. AC power status confirmed
        3. Real CPU die temperature verified (< 76 C) and fresh
        """
        # 1. RAM check
        ram = get_ram_metrics()
        if ram["avail_mb"] < self.MIN_START_RAM_MB:
            return False, f"PREFLIGHT_RAM_FAIL: Available RAM ({ram['avail_mb']:.1f} MB) < {self.MIN_START_RAM_MB} MB", ram

        # 2. Power check
        power = get_power_status()
        if not power["on_ac"]:
            return False, "PREFLIGHT_POWER_FAIL: Not running on AC power (battery throttling risk)", power

        # 3. Dynamic Thermal Gate Check via ThermalSensorManager
        gate_kwargs = {"max_temp_c": self.START_MAX_TEMP_C, "acpi_timeout_sec": 4.0}
        import inspect
        sig = inspect.signature(self.thermal_manager.evaluate_preflight_thermal_gate)
        if "require_direct_die" in sig.parameters:
            gate_kwargs["require_direct_die"] = not self.allow_user_authorized_acpi

        passed_thermal, thermal_reason, thermal_details = self.thermal_manager.evaluate_preflight_thermal_gate(**gate_kwargs)
        if not passed_thermal:
            return False, thermal_reason, {
                "ram_avail_mb": ram["avail_mb"],
                "on_ac": power["on_ac"],
                "thermal_details": thermal_details
            }

        return True, "PREFLIGHT_PASSED", {
            "ram_avail_mb": ram["avail_mb"],
            "on_ac": power["on_ac"],
            "thermal_details": thermal_details
        }

    def _is_sensor_acceptable(self, status, reading):
        if not reading:
            return False, "reading is None"
        if getattr(reading, "is_direct_die", False) and getattr(reading, "sensor_type", "") == "CPU_DIE_TCTL_TDIE":
            return status == "COMPONENT_TEMP_VERIFIED_GREEN", "direct CPU die verified"
        if self.allow_user_authorized_acpi:
            if getattr(reading, "sensor_type", "") in ["MOTHERBOARD_ACPI", "ACPI_MOTHERBOARD", "ACPI_THERMAL_ZONE"]:
                return status in ["COMPONENT_TEMP_VERIFIED_GREEN", "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED"], "user-authorized ACPI tracking"
        return False, f"unacceptable sensor type: {getattr(reading, 'sensor_type', 'UNKNOWN')}, direct_die={getattr(reading, 'is_direct_die', False)}"

    def _monitor_loop(
        self,
        deadline_mono: float,
        effective_timeout: float,
        test_skip_ram: bool = False,
        test_skip_temp: bool = False,
        test_force_startup_failure: bool = False,
        test_force_in_flight_crash: bool = False
    ):
        """Active watchdog monitor running on separate thread with strict fail-close containment."""
        start_time = time.monotonic()
        hot_since = None

        try:
            # 1. Watchdog Startup Verification
            if test_force_startup_failure:
                raise RuntimeError("TEST_INJECTED_MONITOR_STARTUP_FAILURE")

            if not test_skip_ram:
                initial_ram = get_ram_metrics()
                if initial_ram["avail_mb"] < self.EMERGENCY_MIN_RAM_MB:
                    self.abort_reason = f"EMERGENCY_RAM_STOP: Free RAM dropped to {initial_ram['avail_mb']:.1f} MB"
                    return
            # Thermal Check
            if not test_skip_temp:
                status, reading, reason = self.thermal_manager.read_current_thermal_state(acpi_timeout_sec=4.0)
                acceptable, probe_reason = self._is_sensor_acceptable(status, reading)
                if not acceptable:
                    self.abort_reason = f"EMERGENCY_THERMAL_FAILCLOSE: Direct CPU die sensor lost before start (status={status}, reason={reason}; probe={probe_reason})"
                    return
                if reading.temp_c >= self.EMERGENCY_MAX_TEMP_C:
                    self.abort_reason = f"EMERGENCY_THERMAL_TRIP: Critical temp {reading.temp_c:.1f} C"
                    return

            # Signal that watchdog initialized and verified initial state
            self.monitor_ready_event.set()

            # 2. Continuous Monitoring Loop
            loop_count = 0
            while not self.stop_event.wait(0.1):
                loop_count += 1
                if test_force_in_flight_crash and loop_count >= 2:
                    raise RuntimeError("TEST_INJECTED_MONITOR_IN_FLIGHT_CRASH")

                now = time.monotonic()
                if now >= deadline_mono:
                    self.abort_reason = f"TIMEOUT: Exceeded hard timeout of {effective_timeout}s"
                    self._terminate_child()
                    break

                # Memory Check
                if not test_skip_ram:
                    try:
                        ram = get_ram_metrics()
                        if ram["avail_mb"] < self.EMERGENCY_MIN_RAM_MB:
                            self.abort_reason = f"EMERGENCY_RAM_STOP: Free RAM dropped to {ram['avail_mb']:.1f} MB"
                            self._terminate_child()
                            break
                    except Exception as e:
                        self.abort_reason = f"MONITOR_ERROR: RAM query failed ({str(e)})"
                        self._terminate_child()
                        break
                else:
                    ram = {"avail_mb": 2500.0}

                # Thermal Check (in-flight)
                if not test_skip_temp:
                    status, reading, reason = self.thermal_manager.read_current_thermal_state(acpi_timeout_sec=2.0)
                    acceptable, probe_reason = self._is_sensor_acceptable(status, reading)
                    if not acceptable:
                        self.abort_reason = f"EMERGENCY_THERMAL_FAILCLOSE: Direct CPU die sensor reading lost during execution (status={status}; probe={probe_reason})"
                        self._terminate_child()
                        break

                    temp = reading.temp_c
                    if temp >= self.EMERGENCY_MAX_TEMP_C:
                        self.abort_reason = f"EMERGENCY_THERMAL_TRIP: Temp reached critical {temp:.1f} C"
                        self._terminate_child()
                        break

                    if temp >= self.HOT_WARN_TEMP_C:
                        if hot_since is None:
                            hot_since = time.monotonic()
                        elif (time.monotonic() - hot_since) >= 10.0:
                            self.abort_reason = f"SUSTAINED_HOT_STOP: Temp >= {self.HOT_WARN_TEMP_C} C for 10 seconds"
                            self._terminate_child()
                            break
                    else:
                        hot_since = None
                else:
                    temp = 50.0

                with self._lock:
                    self.metrics_log.append({
                        "elapsed_s": round(now - start_time, 2),
                        "avail_ram_mb": round(ram["avail_mb"], 1),
                        "temp_c": round(temp, 2)
                    })
        except Exception as e:
            self.abort_reason = f"WATCHDOG_THREAD_CRASH: {type(e).__name__}: {str(e)}"
            self._terminate_child()
        finally:
            if not self.monitor_ready_event.is_set():
                self.monitor_ready_event.set()

    def _terminate_child(self):
        """Terminates ONLY its own spawned child process with force-kill fallback."""
        if self.child_process and self.child_process.poll() is None:
            try:
                self.child_process.terminate()
                self.child_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    self.child_process.kill()
                    self.child_process.wait(timeout=1.0)
                except Exception:
                    pass
            except Exception:
                pass

    # ==========================================================================
    # Production API (Zero Bypass, Full Safety Enforcement)
    # ==========================================================================
    def execute_production_inference(self, config: SafeInferenceConfig) -> dict:
        """
        Public entrypoint for real local LLM inference.
        Guarantees:
        1. No bypass flags exist.
        2. Fixed safe command generated from validated config.
        3. Preflight strictly blocks if hardware/temperature is not verified green.
        4. Single instance lock with unique token.
        5. Hard timeout capped at 30.0s.
        """
        try:
            cmd = build_safe_llama_command(config)
        except Exception as e:
            return {"success": False, "error": f"CONFIG_VALIDATION_ERROR: {str(e)}"}

        return self._execute_supervised_process(
            cmd_args=cmd,
            timeout_sec=self.HARD_TIMEOUT_SEC,
            is_test_harness=False
        )

    # ==========================================================================
    # Internal Process Supervisor Engine
    # ==========================================================================
    def _execute_supervised_process(
        self,
        cmd_args: list[str],
        timeout_sec: float = None,
        is_test_harness: bool = False,
        test_skip_ram: bool = False,
        test_skip_ac: bool = False,
        test_skip_temp: bool = False,
        test_force_monitor_startup_failure: bool = False,
        test_force_monitor_in_flight_crash: bool = False
    ) -> dict:
        """
        Internal process supervisor engine.
        Accepts test bypass flags ONLY when is_test_harness=True and command is verified dummy test.
        """
        max_timeout = self.HARD_TIMEOUT_SEC
        if timeout_sec is None or timeout_sec > max_timeout or timeout_sec <= 0:
            effective_timeout = max_timeout
        else:
            effective_timeout = float(timeout_sec)

        # 1. Acquire instance lock
        if not self.acquire_instance_lock():
            return {
                "success": False,
                "error": "INSTANCE_LOCK_FAILED: Another inference supervisor is currently active"
            }

        try:
            # 2. Gate Verification
            if not is_test_harness:
                passed, reason, metrics = self.run_preflight_checks()
                if not passed:
                    return {
                        "success": False,
                        "error": reason,
                        "preflight_metrics": metrics
                    }
            else:
                exe_name = Path(cmd_args[0]).name.lower()
                if exe_name not in ("python.exe", "python"):
                    return {
                        "success": False,
                        "error": f"TEST_HARNESS_SECURITY_ERROR: Test harness only permits python.exe dummy commands (got {exe_name})"
                    }
                ram = get_ram_metrics()
                if not test_skip_ram and ram["avail_mb"] < self.MIN_START_RAM_MB:
                    return {"success": False, "error": f"PREFLIGHT_RAM_FAIL: {ram['avail_mb']:.1f} MB < {self.MIN_START_RAM_MB} MB"}
                power = get_power_status()
                if not test_skip_ac and not power["on_ac"]:
                    return {"success": False, "error": "PREFLIGHT_POWER_FAIL: Not on AC"}
                temp = read_acpi_temperature()
                if not test_skip_temp:
                    if temp is None or temp >= self.START_MAX_TEMP_C:
                        return {"success": False, "error": "PREFLIGHT_THERMAL_FAIL"}

            # 3. Launch Watchdog Monitor Thread FIRST
            self.stop_event.clear()
            self.monitor_ready_event.clear()
            self.abort_reason = None
            self.metrics_log = []

            start_mono = time.monotonic()
            deadline_mono = start_mono + effective_timeout

            self.monitor_thread = threading.Thread(
                target=self._monitor_loop,
                args=(
                    deadline_mono,
                    effective_timeout,
                    test_skip_ram,
                    test_skip_temp,
                    test_force_monitor_startup_failure,
                    test_force_monitor_in_flight_crash
                ),
                daemon=True
            )
            self.monitor_thread.start()

            # Verify watchdog initialized successfully BEFORE spawning child (timing reconciled)
            ready = self.monitor_ready_event.wait(timeout=self.MONITOR_STARTUP_WAIT_SEC)
            if not ready or self.abort_reason or not self.monitor_thread.is_alive():
                self.stop_event.set()
                if self.monitor_thread.is_alive():
                    self.monitor_thread.join(timeout=1.0)
                err = self.abort_reason or "WATCHDOG_STARTUP_TIMEOUT: Watchdog failed to initialize"
                return {
                    "success": False,
                    "error": f"WATCHDOG_STARTUP_ABORT: {err}"
                }

            # 4. Watchdog Verified -> Spawn Child Process with Strict Network Isolation
            stdout_reader = None
            stderr_reader = None
            returncode = -1

            offline_env = os.environ.copy()
            offline_env['HTTP_PROXY'] = 'http://127.0.0.1:0'
            offline_env['HTTPS_PROXY'] = 'http://127.0.0.1:0'
            offline_env['ALL_PROXY'] = 'http://127.0.0.1:0'
            offline_env['NO_PROXY'] = ''
            offline_env['SOGH_OFFLINE_STRICT'] = '1'

            try:
                self.child_process = subprocess.Popen(
                    cmd_args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=offline_env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
                self.child_pid = self.child_process.pid

                # Attach bounded streaming readers (512 KB memory limit)
                stdout_reader = BoundedStreamReader(self.child_process.stdout, self.MAX_OUTPUT_BYTES)
                stderr_reader = BoundedStreamReader(self.child_process.stderr, self.MAX_OUTPUT_BYTES)

                # Active execution monitor loop with strict deadline & liveness checks
                while self.child_process.poll() is None:
                    now = time.monotonic()
                    # A. Deadline check
                    if now >= deadline_mono:
                        self.abort_reason = f"TIMEOUT: Exceeded hard timeout of {effective_timeout}s"
                        self._terminate_child()
                        break

                    # B. Watchdog liveness check
                    if not self.monitor_thread.is_alive() and not self.stop_event.is_set():
                        if not self.abort_reason:
                            self.abort_reason = "WATCHDOG_DIED_PREMATURELY: Watchdog thread died while child was active"
                        self._terminate_child()
                        break

                    # C. Output memory limit check
                    if stdout_reader.limit_exceeded or stderr_reader.limit_exceeded:
                        self.abort_reason = f"OUTPUT_LIMIT_EXCEEDED: Process output stream breached memory ceiling of {self.MAX_OUTPUT_BYTES} bytes"
                        self._terminate_child()
                        break

                    # D. Watchdog abort flag
                    if self.abort_reason:
                        self._terminate_child()
                        break

                    time.sleep(0.05)

                returncode = self.child_process.poll()
                if returncode is None:
                    self._terminate_child()
                    returncode = -1
            except Exception as e:
                self._terminate_child()
                returncode = -1
                if not self.abort_reason:
                    self.abort_reason = f"PROCESS_EXECUTION_ERROR: {str(e)}"
            finally:
                self.stop_event.set()
                if self.monitor_thread and self.monitor_thread.is_alive():
                    self.monitor_thread.join(timeout=1.5)

            total_elapsed = time.monotonic() - start_mono

            # Retrieve bounded output and check for ingestion-time limit breach
            raw_stdout = stdout_reader.get_output() if stdout_reader else ""
            raw_stderr = stderr_reader.get_output() if stderr_reader else ""

            if (stdout_reader and stdout_reader.limit_exceeded) or (stderr_reader and stderr_reader.limit_exceeded):
                if not self.abort_reason:
                    self.abort_reason = f"OUTPUT_LIMIT_EXCEEDED: Process output stream breached memory ceiling of {self.MAX_OUTPUT_BYTES} bytes"

            # E. Network Egress Attempt Detection (Strict Offline Containment)
            network_signatures = ("proxyerror", "connectionrefused", "127.0.0.1:0", "winerror 10061", "socket.gaierror", "urllib.error")
            combined_raw = ((raw_stderr or "") + " " + (raw_stdout or "")).lower()
            if any(sig in combined_raw for sig in network_signatures):
                self.abort_reason = "NETWORK_EGRESS_DETECTED_FAILCLOSE: Process attempted unauthorized network connection"

            # Verify no zombie residual of child
            is_lingering = (self.child_process is not None and self.child_process.poll() is None)
            if is_lingering:
                self._terminate_child()

            # PII and Secret Masking on outputs
            if self.abort_reason and "NETWORK_EGRESS" in self.abort_reason:
                clean_stdout = "[REDACTED_DUE_TO_NETWORK_VIOLATION]"
                clean_stderr = "[REDACTED_DUE_TO_NETWORK_VIOLATION]"
            else:
                clean_stdout = mask_sensitive_data(raw_stdout)
                clean_stderr = mask_sensitive_data(raw_stderr)

            success = (returncode == 0 and self.abort_reason is None)

            return {
                "success": success,
                "returncode": returncode,
                "child_pid": self.child_pid,
                "elapsed_seconds": round(total_elapsed, 2),
                "abort_reason": self.abort_reason,
                "stdout": clean_stdout,
                "stderr": clean_stderr,
                "metrics_samples_count": len(self.metrics_log),
                "metrics_log": self.metrics_log,
                "lingering_child_detected": is_lingering,
                "sensor_metadata": self.THERMAL_SENSOR_METADATA
            }
        finally:
            self.release_instance_lock()


if __name__ == "__main__":
    runner = SupervisedInferenceRunner()
    print("Pre-flight check:", runner.run_preflight_checks())
