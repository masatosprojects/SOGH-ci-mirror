"""Independent QA (Claude): research/antigravity-local-ai/scripts/standalone_production_runner.py (master 7673da3).
Probes the thermal wrapper only (no model, no process start, no real sensor): can it hand the supervised runner a reading that no sensor produced, or one labelled as something it is not?
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import standalone_production_runner as sp
from thermal_sensor_reader import ThermalReading


class NoSensor:
    """A raw manager whose every read fails (no ACPI, no HWiNFO)."""
    def read_current_thermal_state(self, acpi_timeout_sec=4.0):
        return "THERMAL_SENSOR_UNAVAILABLE_FAILCLOSE", None, "No thermal sensors readable."


class AcpiOnly:
    """Only the motherboard ACPI zone answers, as on this machine without HWiNFO."""
    def read_current_thermal_state(self, acpi_timeout_sec=4.0):
        r = ThermalReading(sensor_name="ACPI", hardware_id="ACPI_THERMAL_ZONE", sensor_type="MOTHERBOARD_ACPI", is_direct_die=False, temp_c=55.0,
                           timestamp_mono=0.0, timestamp_iso="x", age_seconds=0.0, is_fresh=True)
        return "THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED", r, "ACPI only"


class TestClaudeIndependentQAStandaloneRunner(unittest.TestCase):
    def test_S1_no_sensor_at_all_must_not_yield_a_green_reading(self):
        m = sp.AsyncCachedThermalManager(NoSensor())
        m.start()
        try:
            status, reading, _ = m.read_current_thermal_state()
        finally:
            m.stop()
        self.assertNotEqual(status, "COMPONENT_TEMP_VERIFIED_GREEN", f"a GREEN reading of {getattr(reading, 'temp_c', None)} C was produced although no sensor answered")

    def test_S2_an_acpi_zone_must_not_be_labelled_a_direct_cpu_die_reading(self):
        m = sp.AsyncCachedThermalManager(AcpiOnly())
        m.start()
        try:
            _, reading, _ = m.read_current_thermal_state()
        finally:
            m.stop()
        self.assertIsNotNone(reading)
        self.assertFalse(reading.is_direct_die and reading.sensor_type == "CPU_DIE_TCTL_TDIE", f"ACPI reading labelled {reading.sensor_type!r}, is_direct_die={reading.is_direct_die}")

    def test_S3_the_preflight_gate_refuses_when_only_acpi_answers(self):
        m = sp.AsyncCachedThermalManager(AcpiOnly())
        m.start()
        try:
            ok, msg, _ = m.evaluate_preflight_thermal_gate()
        finally:
            m.stop()
        self.assertFalse(ok, msg)       # the audited gate (thermal_sensor_reader) refuses ACPI-only; the wrapper should not be weaker


if __name__ == "__main__":
    unittest.main()
