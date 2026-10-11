"""The command declarations: name normalisation, parameter checks, and the documents kept in step."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from agent.rag_engine import _machine_classes
from machines.commands import normalize_command, validate_params

ROOT = Path(__file__).resolve().parent.parent
ALL_SPECS = {t: cls.command_specs() for t, cls in _machine_classes().items()}


class NormalizeTests(unittest.TestCase):
    def test_case_spaces_dashes_accents_and_aliases_resolve_to_one_name(self) -> None:
        cnc = ALL_SPECS["CNC_MILLING"]
        for raw, expected in (("emergency stop", "EMERGENCY_STOP"), ("E-STOP", "EMERGENCY_STOP"),
                              ("dừng khẩn cấp", "EMERGENCY_STOP"), ("Feed Hold", "HOLD"),
                              ("loto", "LOCKOUT"), ("replace-coolant-pump", "REPAIR_COOLANT_SYSTEM"),
                              ("  REPLACE_TOOL  ", "REPLACE_TOOL")):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_command(raw, cnc), expected)

    def test_anything_undeclared_is_not_a_command(self) -> None:
        cnc = ALL_SPECS["CNC_MILLING"]
        for raw in ("TOGGLE_COOLANT", "REPAIR_COOLANT", "REPLACE_BATTERY_MODULE", "", None, 42):
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_command(raw, cnc))

    def test_aliases_never_collide_within_a_machine(self) -> None:
        from machines.commands import _canon
        for machine_type, specs in ALL_SPECS.items():
            names = [s.name for s in specs.values()] + [_canon(a) for s in specs.values() for a in s.aliases]
            with self.subTest(machine_type=machine_type):
                self.assertEqual(len(names), len(set(names)))


class ParamTests(unittest.TestCase):
    def test_params_are_coerced_checked_and_defaulted(self) -> None:
        spec = ALL_SPECS["CNC_MILLING"]["SET_FEED_OVERRIDE"]
        self.assertEqual(validate_params(spec, {"override_pct": "40", "junk": 1}), {"override_pct": 40.0})
        self.assertEqual(validate_params(spec, None), {"override_pct": 50.0})
        for bad in ({"override_pct": 151}, {"override_pct": "fast"}, {"override_pct": float("nan")}, ["x"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_params(spec, bad)

    def test_a_station_name_is_a_plain_code(self) -> None:
        spec = ALL_SPECS["AMR_VEHICLE"]["NAVIGATE_TO"]
        self.assertEqual(validate_params(spec, {"station": "dock_3"})["station"], "DOCK_3")
        with self.assertRaises(ValueError):
            validate_params(spec, {"station": "../etc"})


class DocumentTests(unittest.TestCase):
    def test_every_fault_has_exactly_one_repair_and_the_sop_covers_it(self) -> None:
        sop = (ROOT / "docs" / "maintenance_sop.md").read_text(encoding="utf-8")
        for machine_type, cls in _machine_classes().items():
            faults = set(cls().active_faults)
            repairs = {s.fixes: s.name for s in ALL_SPECS[machine_type].values() if s.kind == "repair"}
            with self.subTest(machine_type=machine_type):
                self.assertEqual(set(repairs), faults)
                for fault, repair in repairs.items():
                    section = next((b for b in sop.split("### ") if f"({fault})" in b), "")
                    self.assertIn(f"`{repair}`", section, f"SOP section for {fault} must name {repair}")

    def test_every_command_the_sop_names_exists(self) -> None:
        sop = (ROOT / "docs" / "maintenance_sop.md").read_text(encoding="utf-8")
        declared = {name for specs in ALL_SPECS.values() for name in specs}
        named = set(re.findall(r"`([A-Z][A-Z_]{2,})`", sop))
        self.assertEqual(named - declared, set())

    def test_the_machine_description_repair_column_matches_the_specs(self) -> None:
        text = (ROOT / "machines_description.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| `([A-Z_]+)` — .*\| `([A-Z_]+)`", text, re.MULTILINE)
        self.assertEqual(len(rows), 16)
        fixes = {s.fixes: s.name for specs in ALL_SPECS.values() for s in specs.values() if s.kind == "repair"}
        for fault, repair in rows:
            with self.subTest(fault=fault):
                self.assertEqual(fixes[fault], repair)


if __name__ == "__main__":
    unittest.main()
