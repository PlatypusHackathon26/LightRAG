"""Per-fault verification for every simulated machine.

Each documented fault in machines_description.md is checked for two things:
* code contract - the fault drives exactly the documented metric, gradually,
  to the documented target, and the documented PLC repair clears it;
* machine realism - secondary couplings (extra heat, faster tool wear, lost
  pressure, reduced throughput, higher discharge) match what a real machine
  would show, and unrelated metrics stay essentially untouched.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from machines.cnc_milling import CncMilling
from machines.robot_arm import RobotArm
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.injection_molding import InjectionMolding


FACTORIES = (CncMilling, RobotArm, AmrVehicle, AoiInspection, InjectionMolding)

DOCUMENTED_FAULTS = {
    CncMilling: {
        "SPINDLE_BEARING_LACK_OF_LUBE",
        "COOLANT_PUMP_FAILURE",
        "TOOL_CHIPPING_OR_WEAR",
        "GUIDEWAY_LUBRICATION_ISSUE",
    },
    RobotArm: {
        "GEARBOX_LACK_OF_GREASE",
        "GRIPPER_PNEUMATIC_LEAK",
        "PAYLOAD_OVERLOAD",
    },
    AmrVehicle: {
        "BATTERY_CELL_DEGRADATION",
        "LIDAR_OPTICAL_DIRT",
        "WHEEL_MOTOR_RESISTANCE",
    },
    AoiInspection: {
        "OPTICAL_LENS_CONTAMINATION",
        "LED_DRIVER_DEGRADATION",
        "SMEMA_CONVEYOR_JAM",
    },
    InjectionMolding: {
        "HEATER_BAND_RUNAWAY",
        "HYDRAULIC_PROPORTIONAL_VALVE_LEAK",
        "NOZZLE_CLOGGING",
    },
}

DOCUMENTED_REPAIRS = {
    (CncMilling, "SPINDLE_BEARING_LACK_OF_LUBE"): "REFILL_SPINDLE_LUBRICANT",
    (CncMilling, "COOLANT_PUMP_FAILURE"): "REPAIR_COOLANT_SYSTEM",
    (CncMilling, "TOOL_CHIPPING_OR_WEAR"): "REPLACE_TOOL",
    (CncMilling, "GUIDEWAY_LUBRICATION_ISSUE"): "LUBRICATE_GUIDEWAYS",
    (RobotArm, "GEARBOX_LACK_OF_GREASE"): "REFILL_GEARBOX_GREASE",
    (RobotArm, "GRIPPER_PNEUMATIC_LEAK"): "REPAIR_PNEUMATIC_SYSTEM",
    (RobotArm, "PAYLOAD_OVERLOAD"): "RESET_PAYLOAD",
    (AmrVehicle, "BATTERY_CELL_DEGRADATION"): "REPLACE_BATTERY_MODULE",
    (AmrVehicle, "LIDAR_OPTICAL_DIRT"): "CLEAN_LIDAR_OPTICS",
    (AmrVehicle, "WHEEL_MOTOR_RESISTANCE"): "SERVICE_DRIVE_MOTOR",
    (AoiInspection, "OPTICAL_LENS_CONTAMINATION"): "RECALIBRATE_OPTICS",
    (AoiInspection, "LED_DRIVER_DEGRADATION"): "REPLACE_LED_MODULE",
    (AoiInspection, "SMEMA_CONVEYOR_JAM"): "CLEAR_CONVEYOR_JAM",
    (InjectionMolding, "HEATER_BAND_RUNAWAY"): "SERVICE_HEATER_SSR",
    (InjectionMolding, "HYDRAULIC_PROPORTIONAL_VALVE_LEAK"): "REPAIR_HYDRAULIC_VALVE",
    (InjectionMolding, "NOZZLE_CLOGGING"): "PURGE_BARREL",
}


def simulate(machine, seconds, step=1.0):
    """Advance a machine with output noise removed and return the last sample."""
    now = machine.last_update_time
    telemetry = {}
    with patch("random.uniform", return_value=0.0):
        for _ in range(round(seconds / step)):
            now += step
            with patch("time.time", return_value=now):
                telemetry = machine.generate_telemetry()
    return telemetry


class FaultCatalogTests(unittest.TestCase):
    def test_machines_start_clean_with_the_documented_catalog(self):
        for factory, faults in DOCUMENTED_FAULTS.items():
            with self.subTest(machine=factory.__name__):
                machine = factory()
                self.assertFalse(machine.has_any_fault())
                self.assertEqual(set(machine.active_faults), faults)
                self.assertEqual(machine.get_active_faults(), [])

    def test_every_documented_fault_declares_a_documented_repair(self):
        for factory, faults in DOCUMENTED_FAULTS.items():
            for fault in faults:
                with self.subTest(machine=factory.__name__, fault=fault):
                    self.assertIn((factory, fault), DOCUMENTED_REPAIRS)

    def test_documented_repair_clears_only_its_own_fault(self):
        # A repair fixes one failed part; it must not silently clear unrelated
        # faults the operator is still diagnosing.
        for (factory, fault), command in DOCUMENTED_REPAIRS.items():
            with self.subTest(machine=factory.__name__, fault=fault):
                machine = factory()
                peers = [f for f in machine.active_faults if f != fault]
                machine.set_active_faults([fault] + peers)
                machine.receive_plc_command(command)
                self.assertNotIn(fault, machine.get_active_faults())
                self.assertEqual(sorted(machine.get_active_faults()), sorted(peers))

    def test_enabling_faults_never_forces_a_control_state_change(self):
        # A sensor/mechanical fault is a condition, not an operator command, so
        # it must not stop, pause or e-stop the machine by itself.
        expected_state = {CncMilling: "RUNNING", RobotArm: "RUNNING",
                          AmrVehicle: "NAVIGATING", AoiInspection: "RUNNING",
                          InjectionMolding: "RUNNING"}
        for factory, faults in DOCUMENTED_FAULTS.items():
            with self.subTest(machine=factory.__name__):
                machine = factory()
                machine.set_active_faults(sorted(faults))
                simulate(machine, 30)
                self.assertEqual(machine.state, expected_state[factory])

class CncFaultTests(unittest.TestCase):
    def test_bearing_lack_of_lube_raises_load_heat_and_vibration(self):
        machine = CncMilling()
        machine.set_active_faults(["SPINDLE_BEARING_LACK_OF_LUBE"])
        telemetry = simulate(machine, 180)
        # Dry spindle bearings add friction (load ~65%), extra heat saturates at
        # the 140 C cap, and that heat pushes ISO-10816 vibration past critical.
        self.assertAlmostEqual(telemetry["Spindle_Load_Pct"], 65, delta=3)
        self.assertGreater(telemetry["Spindle_Temp_C"], 120)
        self.assertGreater(telemetry["Vibration_RMS_mm_s"], 7.1)
        machine.receive_plc_command("REFILL_SPINDLE_LUBRICANT")
        self.assertNotIn("SPINDLE_BEARING_LACK_OF_LUBE", machine.get_active_faults())
        recovered = simulate(machine, 300)
        self.assertLess(recovered["Spindle_Temp_C"], 45)
        self.assertLess(recovered["Vibration_RMS_mm_s"], 2.0)

    def test_coolant_pump_failure_starves_cooling_and_accelerates_wear(self):
        machine = CncMilling()
        machine.set_active_faults(["COOLANT_PUMP_FAILURE"])
        telemetry = simulate(machine, 180)
        # No coolant: pressure collapses, heat rejection drops so the spindle
        # runs hotter, and the absence of flushing multiplies tool wear x7.
        self.assertLess(telemetry["Coolant_Pressure_Bar"], 0.5)
        self.assertGreater(telemetry["Spindle_Temp_C"], 55)
        self.assertLess(telemetry["Spindle_Temp_C"], 80)
        self.assertGreater(machine.tool_wear_pct, 16.0)
        machine.receive_plc_command("REPAIR_COOLANT_SYSTEM")
        recovered = simulate(machine, 60)
        self.assertGreater(recovered["Coolant_Pressure_Bar"], 18.0)
        self.assertLess(recovered["Spindle_Temp_C"], 45)

    def test_tool_chipping_raises_cutting_force_and_vibration(self):
        machine = CncMilling()
        machine.set_active_faults(["TOOL_CHIPPING_OR_WEAR"])
        telemetry = simulate(machine, 180)
        # A chipped/worn edge needs more force (load ~80%) and shakes the
        # spindle above the 4.5 mm/s warning band but below 7.1 mm/s.
        self.assertGreater(telemetry["Spindle_Load_Pct"], 75)
        self.assertLess(telemetry["Spindle_Load_Pct"], 90)
        self.assertGreater(telemetry["Vibration_RMS_mm_s"], 4.5)
        self.assertLess(telemetry["Vibration_RMS_mm_s"], 7.1)
        self.assertGreater(machine.tool_wear_pct, 13.5)
        machine.receive_plc_command("REPLACE_TOOL")
        self.assertEqual(machine.tool_wear_pct, 0.0)
        recovered = simulate(machine, 60)
        self.assertLess(recovered["Spindle_Load_Pct"], 48)

    def test_guideway_lubrication_issue_is_a_mild_load_and_vibration_bump(self):
        machine = CncMilling()
        machine.set_active_faults(["GUIDEWAY_LUBRICATION_ISSUE"])
        telemetry = simulate(machine, 180)
        # Stiction on the guideways adds a small load and a mild rumble only.
        self.assertGreater(telemetry["Spindle_Load_Pct"], 50)
        self.assertLess(telemetry["Spindle_Load_Pct"], 58)
        self.assertLess(telemetry["Vibration_RMS_mm_s"], 4.5)

    def test_coolant_and_tool_faults_multiply_wear(self):
        machine = CncMilling()
        machine.set_active_faults(["COOLANT_PUMP_FAILURE", "TOOL_CHIPPING_OR_WEAR"])
        simulate(machine, 10)
        # documented: wear rate = 0.005 x7 (coolant) x3 (chipping) = 0.105 %/s.
        self.assertAlmostEqual(machine.tool_wear_pct, 12 + 0.005 * 7 * 3 * 10, places=6)


class RobotFaultTests(unittest.TestCase):
    def test_gearbox_lack_of_grease_overloads_servo_and_heats_motor(self):
        machine = RobotArm()
        machine.set_active_faults(["GEARBOX_LACK_OF_GREASE"])
        telemetry = simulate(machine, 300)
        # Dry gearbox friction demands more torque (current ~17.75 A) and the
        # combined friction + Joule heat drives the motor to ~121 C.
        self.assertGreater(telemetry["Joint_3_Current_A"], 16.5)
        self.assertAlmostEqual(telemetry["Joint_3_Current_A"], 17.75, delta=0.2)
        self.assertGreater(telemetry["Motor_Temp_C"], 80)
        machine.receive_plc_command("REFILL_GEARBOX_GREASE")
        recovered = simulate(machine, 300)
        self.assertLess(recovered["Joint_3_Current_A"], 10)
        self.assertLess(recovered["Motor_Temp_C"], 50)

    def test_gripper_leak_only_bleeds_pneumatic_pressure(self):
        machine = RobotArm()
        machine.set_active_faults(["GRIPPER_PNEUMATIC_LEAK"])
        telemetry = simulate(machine, 60)
        # The gripper circuit is pneumatic and independent of the servo loop,
        # so only clamp pressure falls (to the 0.8 Bar floor).
        self.assertAlmostEqual(telemetry["Gripper_Pressure_Bar"], 0.8, delta=0.15)
        self.assertAlmostEqual(telemetry["Joint_3_Current_A"], 9.25, delta=0.1)
        self.assertAlmostEqual(telemetry["Motor_Temp_C"], 40.0, delta=1.0)
        machine.receive_plc_command("REPAIR_PNEUMATIC_SYSTEM")
        recovered = simulate(machine, 30)
        self.assertGreater(recovered["Gripper_Pressure_Bar"], 5.5)

    def test_payload_overload_raises_current_heat_weight_and_grip(self):
        machine = RobotArm()
        machine.set_active_faults(['PAYLOAD_OVERLOAD'])
        telemetry = simulate(machine, 300)
        # A heavier payload needs more holding torque (current ~14.75 A) and the
        # motor heats to roughly 78 C, between the 65 and 80 C thresholds.
        self.assertGreater(telemetry['Joint_3_Current_A'], 12.5)
        self.assertAlmostEqual(telemetry['Joint_3_Current_A'], 14.75, delta=0.2)
        self.assertGreater(telemetry['Motor_Temp_C'], 65)
        # The measured load and the gripper clamp force must rise as well: the
        # scale reads the overweight part and the gripper squeezes harder.
        self.assertGreater(telemetry['Payload_Kg'], 3.5)
        self.assertAlmostEqual(telemetry['Payload_Kg'], 12.0, delta=0.2)
        self.assertGreater(telemetry['Gripper_Pressure_Bar'], 6.0)
        self.assertAlmostEqual(telemetry['Gripper_Pressure_Bar'], 8.0, delta=0.2)
        machine.receive_plc_command('RESET_PAYLOAD')
        self.assertEqual(machine.payload_kg, 3.5)
        self.assertNotIn('PAYLOAD_OVERLOAD', machine.get_active_faults())
        recovered = simulate(machine, 60)
        self.assertAlmostEqual(recovered['Payload_Kg'], 3.5, delta=0.1)
        self.assertAlmostEqual(recovered['Gripper_Pressure_Bar'], 6.0, delta=0.2)

class AmrFaultTests(unittest.TestCase):
    NOMINAL_DRAIN = 0.04 + 25.0 / 90.0 * 0.02

    def test_battery_degradation_discharges_faster_and_overheats(self):
        machine = AmrVehicle()
        machine.set_active_faults(["BATTERY_CELL_DEGRADATION"])
        telemetry = simulate(machine, 120)
        # High internal resistance both drains the pack ~4x faster and turns
        # more energy into heat; the pack climbs past the 55 C limit.
        self.assertAlmostEqual(machine.battery_pct, 85 - self.NOMINAL_DRAIN * 4 * 120, delta=0.1)
        self.assertGreater(telemetry["Battery_Temp_C"], 55)
        machine.receive_plc_command("REPLACE_BATTERY_MODULE")
        self.assertEqual(machine.battery_pct, 95.0)
        self.assertNotIn("BATTERY_CELL_DEGRADATION", machine.get_active_faults())

    def test_lidar_dirt_lowers_localization_only(self):
        machine = AmrVehicle()
        machine.set_active_faults(["LIDAR_OPTICAL_DIRT"])
        telemetry = simulate(machine, 120)
        # Dirty optics degrade SLAM confidence to the 40% floor while the
        # drivetrain is untouched - speed and pack temperature stay nominal.
        self.assertAlmostEqual(telemetry["Lidar_Confidence_Pct"], 40.0, delta=0.3)
        self.assertAlmostEqual(telemetry["Current_Velocity_m_s"], 1.2, delta=0.05)
        self.assertAlmostEqual(telemetry["Battery_Temp_C"], 33.6, delta=0.3)
        machine.receive_plc_command("CLEAN_LIDAR_OPTICS")
        recovered = simulate(machine, 120)
        self.assertGreater(recovered["Lidar_Confidence_Pct"], 95.0)

    def test_wheel_resistance_slows_and_drains_the_pack(self):
        machine = AmrVehicle()
        machine.set_active_faults(["WHEEL_MOTOR_RESISTANCE"])
        telemetry = simulate(machine, 120)
        # A dragging drivetrain halves ground speed and needs more torque, so
        # the pack discharges 1.8x faster.
        self.assertAlmostEqual(telemetry["Current_Velocity_m_s"], 0.6, delta=0.05)
        self.assertAlmostEqual(machine.battery_pct, 85 - self.NOMINAL_DRAIN * 1.8 * 120, delta=0.1)
        machine.receive_plc_command("SERVICE_DRIVE_MOTOR")
        recovered = simulate(machine, 60)
        self.assertAlmostEqual(recovered["Current_Velocity_m_s"], 1.2, delta=0.05)


class AoiFaultTests(unittest.TestCase):
    def test_lens_contamination_soils_optics_and_raises_false_rejects(self):
        machine = AoiInspection()
        machine.set_active_faults(["OPTICAL_LENS_CONTAMINATION"])
        telemetry = simulate(machine, 180)
        # Contamination sits at the 30% cleanliness floor and the resulting bad
        # images push the false reject rate well past the 4% critical bound.
        self.assertAlmostEqual(telemetry["Optics_Cleanliness_Pct"], 30.0, delta=0.3)
        self.assertGreater(telemetry["False_Reject_Rate_Pct"], 6.0)
        machine.receive_plc_command("RECALIBRATE_OPTICS")
        recovered = simulate(machine, 200)
        self.assertGreater(recovered["Optics_Cleanliness_Pct"], 95.0)
        self.assertLess(recovered["False_Reject_Rate_Pct"], 2.0)

    def test_led_degradation_dims_illumination_and_raises_false_rejects(self):
        machine = AoiInspection()
        machine.set_active_faults(["LED_DRIVER_DEGRADATION"])
        telemetry = simulate(machine, 180)
        # The dimmer light box bottoms out near 9000 Lux (below the 14000 Lux
        # bound) and low contrast drives false rejects to ~8%.
        self.assertAlmostEqual(telemetry["Illumination_Intensity_Lux"], 9000.0, delta=50.0)
        self.assertGreater(telemetry["False_Reject_Rate_Pct"], 6.0)
        machine.receive_plc_command("REPLACE_LED_MODULE")
        recovered = simulate(machine, 60)
        self.assertGreater(recovered["Illumination_Intensity_Lux"], 18000.0)

    def test_conveyor_jam_stops_throughput_without_touching_optics(self):
        machine = AoiInspection()
        simulate(machine, 10)
        inspected, flagged = machine.boards_inspected_total, machine.boards_flagged_defect
        machine.set_active_faults(["SMEMA_CONVEYOR_JAM"])
        telemetry = simulate(machine, 60)
        # A jammed conveyor stops boards: speed goes to zero and the counters
        # freeze, while optics cleanliness and lighting are unaffected.
        self.assertEqual(telemetry["Conveyor_Speed_m_min"], 0.0)
        self.assertEqual(machine.boards_inspected_total, inspected)
        self.assertEqual(machine.boards_flagged_defect, flagged)
        self.assertAlmostEqual(telemetry["Optics_Cleanliness_Pct"], 99.0, delta=1.0)
        machine.receive_plc_command("CLEAR_CONVEYOR_JAM")
        recovered = simulate(machine, 20)
        self.assertAlmostEqual(recovered["Conveyor_Speed_m_min"], 1.2, delta=0.05)


class InjectionFaultTests(unittest.TestCase):
    def test_heater_runaway_overheats_melt_and_lowers_injection_pressure(self):
        machine = InjectionMolding()
        machine.set_active_faults(["HEATER_BAND_RUNAWAY"])
        telemetry = simulate(machine, 60)
        # A stuck SSR band runs the nozzle away to the 280 C safety cap, and the
        # thinner melt needs less injection pressure (below the 95 Bar nominal).
        self.assertGreater(telemetry["Nozzle_Temp_Zone1"], 245.0)
        self.assertAlmostEqual(telemetry["Nozzle_Temp_Zone1"], 280.0, delta=1.0)
        self.assertLess(telemetry["Injection_Pressure_Bar"], 85.0)
        machine.receive_plc_command("SERVICE_HEATER_SSR")
        recovered = simulate(machine, 120)
        self.assertLess(recovered["Nozzle_Temp_Zone1"], 230.0)

    def test_hydraulic_valve_leak_drops_clamping_pressure_only(self):
        machine = InjectionMolding()
        machine.set_active_faults(["HYDRAULIC_PROPORTIONAL_VALVE_LEAK"])
        telemetry = simulate(machine, 60)
        # A leaking proportional valve can only hold ~102 Bar, below the 115 Bar
        # clamp-force limit, while melt temperature and injection stay nominal.
        self.assertAlmostEqual(telemetry["Clamping_Pressure_Bar"], 102.0, delta=2.0)
        self.assertLess(telemetry["Clamping_Pressure_Bar"], 115.0)
        self.assertAlmostEqual(telemetry["Injection_Pressure_Bar"], 95.0, delta=3.0)
        machine.receive_plc_command("REPAIR_HYDRAULIC_VALVE")
        recovered = simulate(machine, 60)
        self.assertGreater(recovered["Clamping_Pressure_Bar"], 135.0)

    def test_nozzle_clogging_raises_injection_pressure_and_needs_purge(self):
        machine = InjectionMolding()
        machine.set_active_faults(["NOZZLE_CLOGGING"])
        telemetry = simulate(machine, 60)
        # A restriction in the barrel needs far more pressure (165 Bar, past the
        # 145 Bar limit) to fill the mould.
        self.assertGreater(telemetry["Injection_Pressure_Bar"], 145.0)
        self.assertAlmostEqual(telemetry["Injection_Pressure_Bar"], 165.0, delta=3.0)
        result = machine.receive_plc_command("PURGE_BARREL")
        self.assertEqual(result["payload"]["current_state"], "PURGING")
        self.assertNotIn("NOZZLE_CLOGGING", machine.get_active_faults())
        machine.receive_plc_command("RESUME")
        self.assertEqual(machine.state, "RUNNING")


if __name__ == "__main__":
    unittest.main()
