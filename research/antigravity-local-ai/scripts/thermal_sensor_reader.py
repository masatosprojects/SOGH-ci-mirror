#!/usr/bin/env python3
r"""
SOGH Antigravity - CPU & Hardware Thermal Sensor Reading Module (Phase 2B)

Strict separation between direct CPU die temperature (AMD Ryzen Tctl/Tdie)
and motherboard ACPI thermal zones (\_tz.thrm).

Features:
1. Hardware sensor identification:
   - CPU (Tctl/Tdie) via HWiNFO64 Shared Memory (Global\\HWiNFO_SENS_SM2)
   - Motherboard ACPI Thermal Zone (\\Thermal Zone Information(*)\\High Precision Temperature)
2. Freshness and stickiness verification:
   - Rejects readings older than MAX_STALENESS_SEC (3.0s).
   - Detects frozen sensors (checks timestamp progression).
3. Status Classification:
   - COMPONENT_TEMP_VERIFIED_GREEN: Valid, fresh, direct CPU Tctl/Tdie from SMU.
   - THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED: ACPI zone observed, direct die unverified.
   - THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE: No sensor readable, fail-close active.
"""

import os
import sys
import time
import struct
import ctypes
import ctypes.wintypes
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

MAX_STALENESS_SEC = 3.0
MAX_PHYSICAL_TEMP_C = 115.0
MIN_PHYSICAL_TEMP_C = 5.0

# HWiNFO Shared Memory SM2 Structures
FILE_MAP_READ = 0x0004

class HWiNFO_READING_ELEMENT(ctypes.Structure):
    _fields_ = [
        ("tReadingType", ctypes.c_uint32),
        ("dwSensorIndex", ctypes.c_uint32),
        ("dwReadingID", ctypes.c_uint32),
        ("szLabelOrig", ctypes.c_char * 128),
        ("szLabelUser", ctypes.c_char * 128),
        ("szUnit", ctypes.c_char * 16),
        ("Value", ctypes.c_double),
    ]

class HWiNFO_SENSOR_ELEMENT(ctypes.Structure):
    _fields_ = [
        ("dwSensorID", ctypes.c_uint32),
        ("dwSensorInst", ctypes.c_uint32),
        ("szSensorNameOrig", ctypes.c_char * 128),
        ("szSensorNameUser", ctypes.c_char * 128),
    ]

class HWiNFO_SHARED_MEM_HEADER(ctypes.Structure):
    _fields_ = [
        ("dwSignature", ctypes.c_uint32), # 0x53695748 ("HWiS")
        ("dwVersion", ctypes.c_uint32),
        ("dwRevision", ctypes.c_uint32),
        ("poll_time", ctypes.c_int64),
        ("dwOffsetOfSensorSection", ctypes.c_uint32),
        ("dwSizeOfSensorElement", ctypes.c_uint32),
        ("dwNumSensorElements", ctypes.c_uint32),
        ("dwOffsetOfReadingSection", ctypes.c_uint32),
        ("dwSizeOfReadingElement", ctypes.c_uint32),
        ("dwNumReadingElements", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class ThermalReading:
    sensor_name: str
    hardware_id: str
    sensor_type: str        # "CPU_DIE_TCTL_TDIE" or "ACPI_THERMAL_ZONE"
    is_direct_die: bool     # True only for real CPU Tctl/Tdie
    temp_c: float
    timestamp_mono: float
    timestamp_iso: str
    age_seconds: float
    is_fresh: bool


class HWiNFOSensorReader:
    """Reads direct CPU Tctl/Tdie from HWiNFO64 Shared Memory in user mode."""
    SHARED_MEM_NAME = "Global\\HWiNFO_SENS_SM2"
    HWIS_SIGNATURE = 0x53695748

    def __init__(self):
        self.last_poll_time = None
        self.last_value = None
        self.stagnant_poll_count = 0

    def read_cpu_die_temperature(self) -> ThermalReading | None:
        """
        Attempts to open Global\\HWiNFO_SENS_SM2 and locate AMD CPU (Tctl/Tdie).
        Returns None if HWiNFO is not running, shared memory disabled, or stale.
        """
        handle = ctypes.windll.kernel32.OpenFileMappingW(
            FILE_MAP_READ, False, self.SHARED_MEM_NAME
        )
        if not handle:
            return None

        map_view = None
        try:
            map_view = ctypes.windll.kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
            if not map_view:
                return None

            header = HWiNFO_SHARED_MEM_HEADER.from_address(map_view)
            if header.dwSignature != self.HWIS_SIGNATURE:
                return None

            now_mono = time.monotonic()
            now_iso = datetime.now(timezone.utc).isoformat()
            now_epoch = time.time()
            poll_epoch = float(header.poll_time)
            age = max(0.0, now_epoch - poll_epoch)

            # Check freshness
            if age > MAX_STALENESS_SEC:
                return None

            # Detect stuck / frozen poll time
            if self.last_poll_time is not None:
                if header.poll_time < self.last_poll_time:
                    # Poll time jumped backwards -> Fail-Close
                    return None
                elif header.poll_time == self.last_poll_time:
                    # Poll time is completely stagnant (frozen sensor process)
                    self.stagnant_poll_count += 1
                    if self.stagnant_poll_count >= 2:
                        # Consecutive identical poll time -> Fail-Close
                        return None
                else:
                    self.stagnant_poll_count = 0
            self.last_poll_time = header.poll_time

            # Traverse readings
            reading_offset = header.dwOffsetOfReadingSection
            reading_size = header.dwSizeOfReadingElement
            num_readings = header.dwNumReadingElements

            sensor_offset = header.dwOffsetOfSensorSection
            sensor_size = header.dwSizeOfSensorElement
            num_sensors = header.dwNumSensorElements

            cpu_die_temp = None
            sensor_label = "CPU (Tctl/Tdie)"
            matched_sensor_index = 0
            matched_reading_id = 0

            for i in range(num_readings):
                elem_addr = map_view + reading_offset + (i * reading_size)
                elem = HWiNFO_READING_ELEMENT.from_address(elem_addr)
                # tReadingType == 1 (Temperature)
                if elem.tReadingType == 1:
                    label_orig = elem.szLabelOrig.decode("ascii", errors="ignore").strip()
                    if "Tctl/Tdie" in label_orig or ("CPU" in label_orig and "Die" in label_orig):
                        val = elem.Value
                        if MIN_PHYSICAL_TEMP_C <= val <= MAX_PHYSICAL_TEMP_C:
                            cpu_die_temp = round(val, 2)
                            sensor_label = label_orig
                            matched_sensor_index = elem.dwSensorIndex
                            matched_reading_id = elem.dwReadingID
                            break

            if cpu_die_temp is None:
                return None

            parent_sensor_name = "CPU"
            if matched_sensor_index < num_sensors and sensor_offset > 0 and sensor_size > 0:
                sensor_elem_addr = map_view + sensor_offset + (matched_sensor_index * sensor_size)
                sensor_elem = HWiNFO_SENSOR_ELEMENT.from_address(sensor_elem_addr)
                sensor_name_str = sensor_elem.szSensorNameOrig.decode("ascii", errors="ignore").strip()
                if sensor_name_str:
                    parent_sensor_name = sensor_name_str

            return ThermalReading(
                sensor_name=f"{parent_sensor_name} - {sensor_label}",
                hardware_id=f"HWINFO_SM2_SENSOR_{matched_sensor_index}_READING_{matched_reading_id}",
                sensor_type="CPU_DIE_TCTL_TDIE",
                is_direct_die=True,
                temp_c=cpu_die_temp,
                timestamp_mono=now_mono,
                timestamp_iso=now_iso,
                age_seconds=round(age, 3),
                is_fresh=(age <= MAX_STALENESS_SEC)
            )
        except Exception:
            return None
        finally:
            if map_view:
                ctypes.windll.kernel32.UnmapViewOfFile(map_view)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)


class ACPISensorReader:
    r"""Reads motherboard ACPI thermal zone counter (\_tz.thrm)."""
    COUNTER_PATH = r"\Thermal Zone Information(*)\High Precision Temperature"
    INSTANCE_NAME = r"\_tz.thrm"

    def read_acpi_temperature(self, timeout_sec: float = 4.0) -> ThermalReading | None:
        ps_cmd = (
            "$ErrorActionPreference='Stop'; "
            "$s=@((Get-Counter '\\Thermal Zone Information(*)\\High Precision Temperature').CounterSamples | "
            "Where-Object { $_.InstanceName -eq '\\_tz.thrm' -and $_.Status -eq 0 }); "
            "if($s.Count -ne 1){exit 2}; "
            "[Console]::Write(($s[0].CookedValue/10-273.15).ToString([Globalization.CultureInfo]::InvariantCulture))"
        )
        child_env = {k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"}
        t0 = time.monotonic()
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=timeout_sec, env=child_env,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            elapsed = time.monotonic() - t0
            if r.returncode != 0:
                return None
            val = float(r.stdout.strip())
            if not (MIN_PHYSICAL_TEMP_C <= val <= MAX_PHYSICAL_TEMP_C):
                return None

            now_mono = time.monotonic()
            now_iso = datetime.now(timezone.utc).isoformat()
            return ThermalReading(
                sensor_name=r"Motherboard ACPI Thermal Zone (\_tz.thrm)",
                hardware_id="ACPI_MOTHERBOARD_THERMAL_ZONE",
                sensor_type="ACPI_THERMAL_ZONE",
                is_direct_die=False,
                temp_c=round(val, 2),
                timestamp_mono=now_mono,
                timestamp_iso=now_iso,
                age_seconds=round(elapsed, 3),
                is_fresh=(elapsed <= timeout_sec)
            )
        except Exception:
            return None


class ThermalSensorManager:
    """
    Unified manager handling primary (HWiNFO SMU Tctl/Tdie) and fallback (ACPI zone).
    Strictly prevents treating ACPI readings as direct CPU die confirmation.
    """
    def __init__(self):
        self.hwinfo_reader = HWiNFOSensorReader()
        self.acpi_reader = ACPISensorReader()
        self.last_reading = None

    def read_current_thermal_state(self, acpi_timeout_sec: float = 4.0) -> tuple[str, ThermalReading | None, str]:
        """
        Attempts direct CPU die reading first, then ACPI.
        Returns (status, reading, explanation):
        - COMPONENT_TEMP_VERIFIED_GREEN: Real CPU die verified and fresh
        - THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED: Only ACPI zone available
        - THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE: Neither sensor is readable
        """
        # 1. Try Primary: Direct CPU Die (HWiNFO Shared Memory)
        direct_reading = self.hwinfo_reader.read_cpu_die_temperature()
        if direct_reading and direct_reading.is_fresh:
            self.last_reading = direct_reading
            return (
                "COMPONENT_TEMP_VERIFIED_GREEN",
                direct_reading,
                f"Direct AMD CPU Tctl/Tdie verified fresh ({direct_reading.temp_c} C, age {direct_reading.age_seconds}s)"
            )

        # 2. Try Fallback: ACPI Thermal Zone
        acpi_reading = self.acpi_reader.read_acpi_temperature(timeout_sec=acpi_timeout_sec)
        if acpi_reading:
            self.last_reading = acpi_reading
            return (
                "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED",
                acpi_reading,
                f"Motherboard ACPI thermal zone observed ({acpi_reading.temp_c} C). Direct CPU core (Tctl/Tdie) unverified."
            )

        # 3. Fail-close
        return (
            "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE",
            None,
            "No thermal sensors readable. Fail-close activated."
        )

    def evaluate_preflight_thermal_gate(self, max_temp_c: float = 76.0, acpi_timeout_sec: float = 4.0, require_direct_die: bool = True) -> tuple[bool, str, dict]:
        """
        Evaluates pre-flight thermal gate.
        When require_direct_die=True, strictly requires COMPONENT_TEMP_VERIFIED_GREEN and direct CPU die.
        When require_direct_die=False (user-authorized ACPI mode), permits observed ACPI zones below max_temp_c.
        """
        status, reading, reason = self.read_current_thermal_state(acpi_timeout_sec=acpi_timeout_sec)

        details = {
            "status": status,
            "reason": reason,
            "reading": asdict(reading) if reading else None,
            "gate_threshold_c": max_temp_c,
            "require_direct_die": require_direct_die
        }

        if status == "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE" or reading is None:
            return False, f"PREFLIGHT_THERMAL_FAIL: {reason}", details

        if reading.temp_c >= max_temp_c:
            return False, f"PREFLIGHT_THERMAL_FAIL: Temperature ({reading.temp_c} C) >= threshold ({max_temp_c} C)", details

        if require_direct_die:
            if (
                status != "COMPONENT_TEMP_VERIFIED_GREEN"
                or not getattr(reading, "is_direct_die", False)
                or getattr(reading, "sensor_type", "") != "CPU_DIE_TCTL_TDIE"
                or not getattr(reading, "is_fresh", False)
            ):
                return False, f"PREFLIGHT_THERMAL_BLOCKED: {reason} (Direct CPU die verification failed; real model execution is BLOCKED)", details

        if status in ["COMPONENT_TEMP_VERIFIED_GREEN", "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED"]:
            return True, "PREFLIGHT_THERMAL_PASSED", details

        return False, f"PREFLIGHT_THERMAL_FAIL: {reason}", details


if __name__ == "__main__":
    mgr = ThermalSensorManager()
    status, reading, reason = mgr.read_current_thermal_state()
    print("Status:", status)
    print("Reading:", reading)
    print("Reason:", reason)
