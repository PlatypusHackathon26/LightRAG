import unittest
from unittest.mock import patch

from machines.cnc_milling import CncMilling
from machines.robot_arm import RobotArm
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.injection_molding import InjectionMolding
from iot.telemetry_receiver import TelemetryReceiver


class MachineDynamicsTests(unittest.TestCase):
    def simulate(self, machine, seconds, step=1.0):
        now = machine.last_update_time
        with patch('random.uniform', return_value=0):
            for _ in range(round(seconds / step)):
                now += step
                with patch('time.time', return_value=now):
                    telemetry = machine.generate_telemetry()
        return telemetry

    def test_nominal_temperatures(self):
        for factory, key, expected, tolerance in (
            (CncMilling, 'Spindle_Temp_C', 38, 0.1),
            (RobotArm, 'Motor_Temp_C', 40, 0.01),
            (AmrVehicle, 'Battery_Temp_C', 33.6, 0.1),
            (InjectionMolding, 'Nozzle_Temp_Zone1', 220, 0.01),
        ):
            with self.subTest(machine=factory.__name__):
                self.assertAlmostEqual(self.simulate(factory(), 60)[key], expected, delta=tolerance)

    def test_injection_temperature_rejects_invalid_setpoints_and_self_repairs(self):
        machine = InjectionMolding()
        for invalid in (0, 179, 246, "bad", None, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                result = machine.receive_plc_command(
                    "ADJUST_TEMPERATURE", {"target_temp": invalid}
                )
                self.assertIn("REJECTED", result["payload"]["execution_detail"])
                self.assertEqual(machine.nozzle_temp_zone1_target, 220)

        accepted = machine.receive_plc_command(
            "ADJUST_TEMPERATURE", {"target_temp": 215}
        )
        self.assertNotIn("REJECTED", accepted["payload"]["execution_detail"])
        self.assertEqual(machine.nozzle_temp_zone1_target, 215)

        machine.nozzle_temp_zone1_target = 0
        machine.nozzle_temp_zone1_actual = 1
        telemetry = self.simulate(machine, 1)
        self.assertEqual(machine.nozzle_temp_zone1_target, 220)
        self.assertAlmostEqual(telemetry["Nozzle_Temp_Zone1"], 220, delta=.12)

    def test_cnc_vibration_noise_does_not_trigger_roc_alert(self):
        receiver = TelemetryReceiver()
        payload = {
            "Controller_Execution": "RUNNING",
            "Spindle_Temp_C": 38.0,
            "Vibration_RMS_mm_s": 1.17,
            "Spindle_Load_Pct": 45.0,
            "Coolant_Pressure_Bar": 20.0,
        }
        self.assertEqual(
            receiver._detect_anomalies("MC-MILL-01", "CNC_MILLING", payload, 0),
            [],
        )
        payload["Vibration_RMS_mm_s"] = 1.23
        self.assertEqual(
            receiver._detect_anomalies("MC-MILL-01", "CNC_MILLING", payload, 2),
            [],
        )
        self.assertEqual(
            receiver._detect_anomalies("MC-MILL-01", "CNC_MILLING", payload, 4),
            [],
        )

        payload["Vibration_RMS_mm_s"] = 4.4
        anomalies = receiver._detect_anomalies(
            "MC-MILL-01", "CNC_MILLING", payload, 5
        )
        self.assertTrue(any(a["param"] == "Vibration_RMS_mm_s" for a in anomalies))

    def test_cnc_wear_rates_and_tool_replacement(self):
        for fault, rate in ((None, .005), ('COOLANT_PUMP_FAILURE', .035), ('TOOL_CHIPPING_OR_WEAR', .015)):
            machine = CncMilling()
            if fault:
                machine.active_faults[fault] = True
            self.simulate(machine, 60)
            self.assertAlmostEqual(machine.tool_wear_pct, 12 + rate * 60)
            machine.receive_plc_command('REPLACE_TOOL')
            self.assertEqual(machine.tool_wear_pct, 0)
        machine = CncMilling()
        machine.receive_plc_command('EMERGENCY_STOP')
        self.simulate(machine, 60)
        self.assertEqual(machine.tool_wear_pct, 12)

    def test_all_faults_change_expected_metric_and_clear(self):
        cases = (
            (CncMilling, 'SPINDLE_BEARING_LACK_OF_LUBE', 'Spindle_Temp_C', 90, True, 'REFILL_SPINDLE_LUBRICANT'),
            (CncMilling, 'COOLANT_PUMP_FAILURE', 'Coolant_Pressure_Bar', 5, False, 'REPAIR_COOLANT_SYSTEM'),
            (CncMilling, 'TOOL_CHIPPING_OR_WEAR', 'Vibration_RMS_mm_s', 4.5, True, 'REPLACE_TOOL'),
            (CncMilling, 'GUIDEWAY_LUBRICATION_ISSUE', 'Spindle_Load_Pct', 50, True, 'LUBRICATE_GUIDEWAYS'),
            (RobotArm, 'GEARBOX_LACK_OF_GREASE', 'Motor_Temp_C', 120, True, 'REFILL_GEARBOX_GREASE'),
            (RobotArm, 'GRIPPER_PNEUMATIC_LEAK', 'Gripper_Pressure_Bar', 3.5, False, 'REPAIR_PNEUMATIC_SYSTEM'),
            (RobotArm, 'PAYLOAD_OVERLOAD', 'Joint_3_Current_A', 12.5, True, 'RESET_PAYLOAD'),
            (AmrVehicle, 'BATTERY_CELL_DEGRADATION', 'Battery_Temp_C', 55, True, 'REPLACE_BATTERY_MODULE'),
            (AmrVehicle, 'LIDAR_OPTICAL_DIRT', 'Lidar_Confidence_Pct', 65, False, 'CLEAN_LIDAR_OPTICS'),
            (AmrVehicle, 'WHEEL_MOTOR_RESISTANCE', 'Current_Velocity_m_s', .7, False, 'SERVICE_DRIVE_MOTOR'),
            (AoiInspection, 'OPTICAL_LENS_CONTAMINATION', 'False_Reject_Rate_Pct', 4, True, 'RECALIBRATE_OPTICS'),
            (AoiInspection, 'LED_DRIVER_DEGRADATION', 'Illumination_Intensity_Lux', 14000, False, 'REPLACE_LED_MODULE'),
            (AoiInspection, 'SMEMA_CONVEYOR_JAM', 'Conveyor_Speed_m_min', .1, False, 'CLEAR_CONVEYOR_JAM'),
            (InjectionMolding, 'HEATER_BAND_RUNAWAY', 'Nozzle_Temp_Zone1', 245, True, 'SERVICE_HEATER_SSR'),
            (InjectionMolding, 'HYDRAULIC_PROPORTIONAL_VALVE_LEAK', 'Clamping_Pressure_Bar', 115, False, 'REPAIR_HYDRAULIC_VALVE'),
            (InjectionMolding, 'NOZZLE_CLOGGING', 'Injection_Pressure_Bar', 145, True, 'PURGE_BARREL'),
        )
        for factory, fault, key, boundary, rises, command in cases:
            with self.subTest(fault=fault):
                machine = factory()
                machine.active_faults[fault] = True
                value = self.simulate(machine, 180)[key]
                (self.assertGreater if rises else self.assertLess)(value, boundary)
                machine.receive_plc_command(command)
                self.assertFalse(machine.active_faults[fault])
                if machine.state == 'PURGING':
                    machine.receive_plc_command('RESUME')
                recovered = self.simulate(machine, 300)[key]
                (self.assertLess if rises else self.assertGreater)(recovered, boundary)

    def test_aoi_counts_elapsed_time_and_stops_during_jam(self):
        for step in (.5, 1, 2):
            machine = AoiInspection()
            before = machine.boards_inspected_total
            self.simulate(machine, 60, step)
            self.assertEqual(machine.boards_inspected_total - before, 60)
            machine.active_faults['SMEMA_CONVEYOR_JAM'] = True
            before = machine.boards_inspected_total
            defects = machine.boards_flagged_defect
            self.assertEqual(self.simulate(machine, 60, step)['Conveyor_Speed_m_min'], 0)
            self.assertEqual(machine.boards_inspected_total, before)
            self.assertEqual(machine.boards_flagged_defect, defects)

    def test_amr_battery_drain_multipliers(self):
        nominal_drain = .04 + 25 / 90 * .02
        for fault, multiplier in ((None, 1), ('BATTERY_CELL_DEGRADATION', 4), ('WHEEL_MOTOR_RESISTANCE', 1.8)):
            machine = AmrVehicle()
            if fault:
                machine.active_faults[fault] = True
            self.simulate(machine, 60)
            self.assertAlmostEqual(machine.battery_pct, 85 - nominal_drain * multiplier * 60)


if __name__ == '__main__':
    unittest.main()
