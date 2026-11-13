#!/usr/bin/env python3
"""
Unit tests for ThermalSensorManager and HWiNFO64 / ACPI sensor integration (Phase 2B).
Verifies:
1. Pure user-mode OpenFileMappingW returns None when HWiNFO is not running.
2. Direct CPU die parsing and hardware ID recording on valid HWiNFO SM2 payload.
3. Staleness detection (poll time older than 3.0s rejected).
4. Frozen / backwards timestamp rejection.
5. Real ACPI thermal zone reading on host machine.
6. Strict blocking of real LLM preflight when direct CPU die is unverified.
7. Verification pass only when direct CPU die is verified and < 76.0 C.
8. Trip fail when direct CPU die is overheated (>= 76.0 C).
9. Dynamic lifecycle adaptation (seamless promotion on HWiNFO launch, graceful ACPI fallback on exit).
"""

import sys
import time
import ctypes
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts"
if str(MODULE_PATH) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH))

from thermal_sensor_reader import (
    ThermalReading,
    HWiNFOSensorReader,
    ACPISensorReader,
    ThermalSensorManager,
    HWiNFO_SHARED_MEM_HEADER,
    HWiNFO_SENSOR_ELEMENT,
    HWiNFO_READING_ELEMENT
)

class TestThermalSensorReader(unittest.TestCase):
    def setUp(self):
        self.mgr = ThermalSensorManager()

    def test_hwinfo_reader_returns_none_when_not_running(self):
        """Verify reader gracefully returns None without exception when HWiNFO is not running."""
        reader = HWiNFOSensorReader()
        res = reader.read_cpu_die_temperature()
        # On current machine without HWiNFO running, must return None
        self.assertIsNone(res)

    def test_hwinfo_reader_parses_mock_sm2_payload_correctly(self):
        """Verify HWiNFOSensorReader parses simulated SM2 shared memory buffer accurately."""
        # Construct synthetic buffer
        header = HWiNFO_SHARED_MEM_HEADER()
        header.dwSignature = 0x53695748 # "HWiS"
        header.dwVersion = 2
        header.dwRevision = 0
        header.poll_time = int(time.time())
        header.dwOffsetOfSensorSection = ctypes.sizeof(HWiNFO_SHARED_MEM_HEADER)
        header.dwSizeOfSensorElement = ctypes.sizeof(HWiNFO_SENSOR_ELEMENT)
        header.dwNumSensorElements = 1
        header.dwOffsetOfReadingSection = header.dwOffsetOfSensorSection + header.dwSizeOfSensorElement
        header.dwSizeOfReadingElement = ctypes.sizeof(HWiNFO_READING_ELEMENT)
        header.dwNumReadingElements = 1

        reading_elem = HWiNFO_READING_ELEMENT()
        reading_elem.tReadingType = 1 # Temp
        reading_elem.dwSensorIndex = 0
        reading_elem.dwReadingID = 0
        reading_elem.szLabelOrig = b"CPU (Tctl/Tdie)"
        reading_elem.szLabelUser = b"CPU (Tctl/Tdie)"
        reading_elem.szUnit = b"\xc2\xb0C" # °C
        reading_elem.Value = 62.5

        sensor_elem = HWiNFO_SENSOR_ELEMENT()
        sensor_elem.dwSensorID = 0x1234
        sensor_elem.szSensorNameOrig = b"AMD Ryzen 5 3550H"

        buffer = bytearray(header.dwOffsetOfReadingSection + header.dwSizeOfReadingElement)
        ctypes.memmove(ctypes.addressof((ctypes.c_char * len(buffer)).from_buffer(buffer)), ctypes.byref(header), ctypes.sizeof(header))
        ctypes.memmove(ctypes.addressof((ctypes.c_char * len(buffer)).from_buffer(buffer)) + header.dwOffsetOfSensorSection, ctypes.byref(sensor_elem), ctypes.sizeof(sensor_elem))
        ctypes.memmove(ctypes.addressof((ctypes.c_char * len(buffer)).from_buffer(buffer)) + header.dwOffsetOfReadingSection, ctypes.byref(reading_elem), ctypes.sizeof(reading_elem))

        buf_addr = ctypes.addressof((ctypes.c_char * len(buffer)).from_buffer(buffer))

        reader = HWiNFOSensorReader()
        with patch("ctypes.windll.kernel32.OpenFileMappingW", return_value=123):
            with patch("ctypes.windll.kernel32.MapViewOfFile", return_value=buf_addr):
                with patch("ctypes.windll.kernel32.UnmapViewOfFile", return_value=1):
                    with patch("ctypes.windll.kernel32.CloseHandle", return_value=1):
                        res = reader.read_cpu_die_temperature()

        self.assertIsNotNone(res)
        self.assertEqual(res.sensor_type, "CPU_DIE_TCTL_TDIE")
        self.assertTrue(res.is_direct_die)
        self.assertEqual(res.temp_c, 62.5)
        self.assertTrue(res.hardware_id.startswith("HWINFO_SM2_SENSOR_"))
        self.assertIn("CPU (Tctl/Tdie)", res.sensor_name)
        self.assertTrue(res.is_fresh)

    def test_hwinfo_reader_rejects_stale_data(self):
        """Verify readings with poll_time older than MAX_STALENESS_SEC are rejected."""
        header = HWiNFO_SHARED_MEM_HEADER()
        header.dwSignature = 0x53695748
        header.poll_time = int(time.time() - 15.0) # 15 seconds stale

        buf = bytearray(ctypes.sizeof(header) + 500)
        ctypes.memmove(ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf)), ctypes.byref(header), ctypes.sizeof(header))
        buf_addr = ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf))

        reader = HWiNFOSensorReader()
        with patch("ctypes.windll.kernel32.OpenFileMappingW", return_value=123):
            with patch("ctypes.windll.kernel32.MapViewOfFile", return_value=buf_addr):
                with patch("ctypes.windll.kernel32.UnmapViewOfFile", return_value=1):
                    with patch("ctypes.windll.kernel32.CloseHandle", return_value=1):
                        res = reader.read_cpu_die_temperature()

        self.assertIsNone(res, "Stale reading must return None")

    def test_acpi_sensor_reader_on_host(self):
        """Verify real motherboard ACPI thermal reading on current host."""
        reader = ACPISensorReader()
        res = reader.read_acpi_temperature(timeout_sec=4.0)
        if res is None:
            self.skipTest("Host environment lacks ACPI thermal zone counter (expected on VM / headless / foreign host)")
        self.assertFalse(res.is_direct_die, "ACPI zone must NOT be marked as direct CPU die")
        self.assertEqual(res.sensor_type, "ACPI_THERMAL_ZONE")
        self.assertGreater(res.temp_c, 10.0)
        self.assertLess(res.temp_c, 100.0)

    def test_manager_blocks_preflight_when_only_acpi_available(self):
        """Verify manager strictly BLOCKS real inference if direct CPU die is unverified."""
        mock_acpi_reading = ThermalReading(
            sensor_name=r"Motherboard ACPI Thermal Zone (\_tz.thrm)",
            hardware_id="ACPI_MOTHERBOARD_THERMAL_ZONE",
            sensor_type="ACPI_THERMAL_ZONE",
            is_direct_die=False,
            temp_c=45.0,
            timestamp_mono=time.monotonic(),
            timestamp_iso=datetime.now().isoformat(),
            age_seconds=0.1,
            is_fresh=True
        )
        with patch.object(self.mgr.acpi_reader, "read_acpi_temperature", return_value=mock_acpi_reading):
            passed, reason, details = self.mgr.evaluate_preflight_thermal_gate(max_temp_c=76.0)
            self.assertFalse(passed)
            self.assertIn("BLOCKED", reason)
        self.assertEqual(details["status"], "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED")

    def test_manager_passes_preflight_when_direct_cpu_green(self):
        """Verify manager passes preflight when direct CPU Tctl/Tdie is fresh and < 76C."""
        mock_reading = ThermalReading(
            sensor_name="AMD Ryzen 5 3550H - CPU (Tctl/Tdie)",
            hardware_id="AMD_RYZEN_3550H_SMU_TCTL_TDIE",
            sensor_type="CPU_DIE_TCTL_TDIE",
            is_direct_die=True,
            temp_c=54.5,
            timestamp_mono=time.monotonic(),
            timestamp_iso="2026-11-07T00:00:00Z",
            age_seconds=0.1,
            is_fresh=True
        )

        with patch.object(self.mgr.hwinfo_reader, "read_cpu_die_temperature", return_value=mock_reading):
            passed, reason, details = self.mgr.evaluate_preflight_thermal_gate(max_temp_c=76.0)
            self.assertTrue(passed)
            self.assertEqual(reason, "PREFLIGHT_THERMAL_PASSED")
            self.assertEqual(details["status"], "COMPONENT_TEMP_VERIFIED_GREEN")
            self.assertEqual(details["reading"]["temp_c"], 54.5)

    def test_manager_trips_preflight_when_direct_cpu_overheated(self):
        """Verify manager trips preflight if direct CPU Tctl/Tdie >= 76C."""
        mock_reading = ThermalReading(
            sensor_name="AMD Ryzen 5 3550H - CPU (Tctl/Tdie)",
            hardware_id="AMD_RYZEN_3550H_SMU_TCTL_TDIE",
            sensor_type="CPU_DIE_TCTL_TDIE",
            is_direct_die=True,
            temp_c=79.0, # Exceeds 76.0
            timestamp_mono=time.monotonic(),
            timestamp_iso="2026-11-07T00:00:00Z",
            age_seconds=0.1,
            is_fresh=True
        )

        with patch.object(self.mgr.hwinfo_reader, "read_cpu_die_temperature", return_value=mock_reading):
            passed, reason, details = self.mgr.evaluate_preflight_thermal_gate(max_temp_c=76.0)
            self.assertFalse(passed)
            self.assertIn("PREFLIGHT_THERMAL_FAIL", reason)
            self.assertIn("79.0 C", reason)

    def test_manager_dynamic_lifecycle_adaptation(self):
        """
        Verify manager seamlessly auto-promotes to direct CPU die when HWiNFO starts,
        and degrades safely to ACPI / fail-close when HWiNFO terminates, without restart.
        """
        mock_acpi = ThermalReading(
            sensor_name=r"Motherboard ACPI Thermal Zone (\_tz.thrm)",
            hardware_id="ACPI_MOTHERBOARD_THERMAL_ZONE",
            sensor_type="ACPI_THERMAL_ZONE",
            is_direct_die=False,
            temp_c=48.0,
            timestamp_mono=time.monotonic(),
            timestamp_iso="2026-11-07T00:00:00Z",
            age_seconds=0.1,
            is_fresh=True
        )
        mock_direct = ThermalReading(
            sensor_name="AMD Ryzen 5 3550H - CPU (Tctl/Tdie)",
            hardware_id="AMD_RYZEN_3550H_SMU_TCTL_TDIE",
            sensor_type="CPU_DIE_TCTL_TDIE",
            is_direct_die=True,
            temp_c=55.0,
            timestamp_mono=time.monotonic(),
            timestamp_iso="2026-11-07T00:00:00Z",
            age_seconds=0.1,
            is_fresh=True
        )

        # Stage 1: HWiNFO not running -> ACPI fallback
        with patch.object(self.mgr.hwinfo_reader, "read_cpu_die_temperature", return_value=None), \
             patch.object(self.mgr.acpi_reader, "read_acpi_temperature", return_value=mock_acpi):
            status, reading, exp = self.mgr.read_current_thermal_state()
            self.assertEqual(status, "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED")
            self.assertFalse(reading.is_direct_die)

        # Stage 2: User launches HWiNFO -> Auto-promotes to direct CPU die
        with patch.object(self.mgr.hwinfo_reader, "read_cpu_die_temperature", return_value=mock_direct), \
             patch.object(self.mgr.acpi_reader, "read_acpi_temperature", return_value=mock_acpi):
            status, reading, exp = self.mgr.read_current_thermal_state()
            self.assertEqual(status, "COMPONENT_TEMP_VERIFIED_GREEN")
            self.assertTrue(reading.is_direct_die)
            self.assertEqual(reading.temp_c, 55.0)

        # Stage 3: HWiNFO exits -> Gracefully falls back to ACPI
        with patch.object(self.mgr.hwinfo_reader, "read_cpu_die_temperature", return_value=None), \
             patch.object(self.mgr.acpi_reader, "read_acpi_temperature", return_value=mock_acpi):
            status, reading, exp = self.mgr.read_current_thermal_state()
            self.assertEqual(status, "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED")
            self.assertFalse(reading.is_direct_die)

        # Stage 4: ACPI also fails -> Strict failclose
        with patch.object(self.mgr.hwinfo_reader, "read_cpu_die_temperature", return_value=None), \
             patch.object(self.mgr.acpi_reader, "read_acpi_temperature", return_value=None):
            status, reading, exp = self.mgr.read_current_thermal_state()
            self.assertEqual(status, "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE")
            self.assertIsNone(reading)


    def test_hwinfo_reader_rejects_stagnant_frozen_poll_time(self):
        """Verify that consecutive identical poll times (frozen process) trigger Fail-Close."""
        header = HWiNFO_SHARED_MEM_HEADER()
        header.dwSignature = 0x53695748
        header.poll_time = int(time.time())

        # Minimal valid buffer setup
        header.dwOffsetOfSensorSection = ctypes.sizeof(HWiNFO_SHARED_MEM_HEADER)
        header.dwSizeOfSensorElement = ctypes.sizeof(HWiNFO_SENSOR_ELEMENT)
        header.dwNumSensorElements = 1
        header.dwOffsetOfReadingSection = header.dwOffsetOfSensorSection + header.dwSizeOfSensorElement
        header.dwSizeOfReadingElement = ctypes.sizeof(HWiNFO_READING_ELEMENT)
        header.dwNumReadingElements = 1

        reading_elem = HWiNFO_READING_ELEMENT()
        reading_elem.tReadingType = 1
        reading_elem.szLabelOrig = b"CPU (Tctl/Tdie)"
        reading_elem.Value = 55.0

        sensor_elem = HWiNFO_SENSOR_ELEMENT()
        sensor_elem.szSensorNameOrig = b"AMD Ryzen"

        buf = bytearray(header.dwOffsetOfReadingSection + header.dwSizeOfReadingElement)
        ctypes.memmove(ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf)), ctypes.byref(header), ctypes.sizeof(header))
        ctypes.memmove(ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf)) + header.dwOffsetOfSensorSection, ctypes.byref(sensor_elem), ctypes.sizeof(sensor_elem))
        ctypes.memmove(ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf)) + header.dwOffsetOfReadingSection, ctypes.byref(reading_elem), ctypes.sizeof(reading_elem))
        buf_addr = ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf))

        reader = HWiNFOSensorReader()
        with patch("ctypes.windll.kernel32.OpenFileMappingW", return_value=123), \
             patch("ctypes.windll.kernel32.MapViewOfFile", return_value=buf_addr), \
             patch("ctypes.windll.kernel32.UnmapViewOfFile", return_value=1), \
             patch("ctypes.windll.kernel32.CloseHandle", return_value=1):

            # 1st read: accepted
            r1 = reader.read_cpu_die_temperature()
            self.assertIsNotNone(r1)

            # 2nd read with identical poll_time: flagged stagnant
            r2 = reader.read_cpu_die_temperature()
            # 3rd read still identical: strictly fails close (returns None)
            r3 = reader.read_cpu_die_temperature()
            self.assertIsNone(r3, "Frozen stagnant poll time must fail-close to None")

    def test_acpi_sensor_reader_timeout_fails_close(self):
        """Verify that subprocess timeout during ACPI read safely fail-closes to None."""
        reader = ACPISensorReader()
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=4.0)):
            res = reader.read_acpi_temperature(timeout_sec=4.0)
            self.assertIsNone(res, "Timed-out ACPI query must fail-close to None without crashing")

if __name__ == "__main__":
    unittest.main()
