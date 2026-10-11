"""Verify the sensor contract and actual time trajectories, including recovery."""
import unittest
import re
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from agent.brain import AgentBrain
from agent.tools import AgentTools
from dashboard.server import create_app
from dashboard.state_store import StateStore
from machines.specifications import MACHINE_METRICS
from machines.cnc_milling import CncMilling
from machines.robot_arm import RobotArm
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.injection_molding import InjectionMolding
from iot.telemetry_receiver import MACHINE_THRESHOLDS


FACTORIES = (CncMilling, RobotArm, AmrVehicle, AoiInspection, InjectionMolding)
CASES = (
    (CncMilling, 'SPINDLE_BEARING_LACK_OF_LUBE', 'Spindle_Load_Pct', 45, 65),
    (CncMilling, 'COOLANT_PUMP_FAILURE', 'Coolant_Pressure_Bar', 20, 0),
    (CncMilling, 'TOOL_CHIPPING_OR_WEAR', 'Vibration_RMS_mm_s', 1.2, 5.7),
    (CncMilling, 'GUIDEWAY_LUBRICATION_ISSUE', 'Spindle_Load_Pct', 45, 53),
    (RobotArm, 'GEARBOX_LACK_OF_GREASE', 'Joint_3_Current_A', 9.25, 17.75),
    (RobotArm, 'GRIPPER_PNEUMATIC_LEAK', 'Gripper_Pressure_Bar', 6, .8),
    (RobotArm, 'PAYLOAD_OVERLOAD', 'Joint_3_Current_A', 9.25, 14.75),
    (AmrVehicle, 'BATTERY_CELL_DEGRADATION', 'Battery_Temp_C', 33.6, 56.37),
    (AmrVehicle, 'LIDAR_OPTICAL_DIRT', 'Lidar_Confidence_Pct', 99.5, 40),
    (AmrVehicle, 'WHEEL_MOTOR_RESISTANCE', 'Current_Velocity_m_s', 1.2, .6),
    (AoiInspection, 'OPTICAL_LENS_CONTAMINATION', 'Optics_Cleanliness_Pct', 99, 30),
    (AoiInspection, 'LED_DRIVER_DEGRADATION', 'Illumination_Intensity_Lux', 18500, 9000),
    (AoiInspection, 'SMEMA_CONVEYOR_JAM', 'Conveyor_Speed_m_min', 1.2, 0),
    (InjectionMolding, 'HEATER_BAND_RUNAWAY', 'Nozzle_Temp_Zone1', 220, 280),
    (InjectionMolding, 'HYDRAULIC_PROPORTIONAL_VALVE_LEAK', 'Clamping_Pressure_Bar', 140, 102),
    (InjectionMolding, 'NOZZLE_CLOGGING', 'Injection_Pressure_Bar', 95, 165),
)


class SmoothTelemetryTests(unittest.TestCase):
    def tick(self, machine, dt=1):
        with patch('random.uniform', return_value=0), patch('time.time', return_value=machine.last_update_time + dt):
            return machine.generate_telemetry()

    def test_every_nominal_dashboard_value_matches_specification(self):
        for factory in FACTORIES:
            machine = factory()
            telemetry = self.tick(machine)
            for metric in MACHINE_METRICS[machine.machine_type]:
                with self.subTest(machine=machine.machine_id, key=metric['key']):
                    self.assertIn(metric['key'], telemetry)
                    # Battery and tool wear are explicitly accumulating quantities.
                    allowance = .06 if metric.get('drift') else 10 ** (-metric['digits'])
                    self.assertAlmostEqual(telemetry[metric['key']], metric['nominal'], delta=allowance)

    def test_documented_nominals_and_noise_match_shared_contract(self):
        document = (Path(__file__).parents[1] / 'machines_description.md').read_text(encoding='utf-8')
        for metrics in MACHINE_METRICS.values():
            for metric in metrics:
                if metric['key'] == 'Path_Feedrate_Override_Pct':
                    continue
                row = re.search(r'^\| `' + re.escape(metric['key']) + r'` \| ([^|]+)\| ([^|]+)\|', document, re.MULTILINE)
                self.assertIsNotNone(row, metric['key'])
                nominal = float(re.search(r'\d+(?:\.\d+)?', row[1])[0])
                noise_match = re.search(r'±(\d+(?:\.\d+)?)', row[2])
                noise = float(noise_match[1]) if noise_match else 0
                self.assertEqual(nominal, metric['nominal'], metric['key'])
                self.assertEqual(noise, metric['noise'], metric['key'])

    def test_all_16_faults_move_gradually_and_recover_without_resets(self):
        for factory, fault, key, initial, target in CASES:
            with self.subTest(fault=fault):
                machine = factory()
                machine.set_active_faults([fault])
                first = self.tick(machine)[key]
                self.assertGreater(first, min(initial, target))
                self.assertLess(first, max(initial, target))
                trace = [first]
                for _ in range(179):
                    trace.append(self.tick(machine)[key])
                for previous, current in zip(trace, trace[1:]):
                    if target > initial:
                        self.assertGreaterEqual(current, previous)
                    else:
                        self.assertLessEqual(current, previous)
                self.assertAlmostEqual(trace[-1], target, delta=.25)
                machine.set_active_faults([])
                next_value = self.tick(machine)[key]
                self.assertGreater(next_value, min(initial, trace[-1]))
                self.assertLess(next_value, max(initial, trace[-1]))
                recovered = next_value
                for _ in range(899):
                    recovered = self.tick(machine)[key]
                # Accumulated wear raises CNC load slowly even after its fault is cleared.
                self.assertAlmostEqual(recovered, initial, delta=1.5 if key == 'Spindle_Load_Pct' else .15)

    def test_fast_responses_are_smooth_for_every_supported_sampling_interval(self):
        for dt in (.1, .5, 1, 2.5):
            for factory, fault, key, initial, target in CASES:
                if key in ('Coolant_Pressure_Bar', 'Gripper_Pressure_Bar'):
                    continue  # Defined linear leaks can reach their floor during a long sample.
                machine = factory()
                machine.set_active_faults([fault])
                value = self.tick(machine, dt)[key]
                with self.subTest(dt=dt, fault=fault):
                    self.assertGreater(value, min(initial, target))
                    self.assertLess(value, max(initial, target))

    def test_noisy_readings_stay_within_documented_output_noise(self):
        # Two identical simulations with different random output streams must differ
        # only by the declared sensor noise, never by physical state.
        for factory in FACTORIES:
            quiet, noisy = factory(), factory()
            now = quiet.last_update_time
            quiet.last_update_time = noisy.last_update_time = now
            with patch('random.uniform', return_value=0), patch('time.time', return_value=now + 1):
                reference = quiet.generate_telemetry()
            with patch('time.time', return_value=now + 1):
                actual = noisy.generate_telemetry()
            for metric in MACHINE_METRICS[quiet.machine_type]:
                tolerance = metric['noise'] + 10 ** (-metric['digits'])
                self.assertAlmostEqual(actual[metric['key']], reference[metric['key']], delta=tolerance)

    def test_aoi_repairs_do_not_teleport_sensor_values(self):
        machine = AoiInspection()
        machine.set_active_faults(['OPTICAL_LENS_CONTAMINATION', 'LED_DRIVER_DEGRADATION'])
        for _ in range(180):
            self.tick(machine)
        before = (machine.optics_cleanliness_pct, machine.illumination_actual_lux, machine.false_reject_rate_pct)
        machine.receive_plc_command('RECALIBRATE_OPTICS')
        machine.receive_plc_command('REPLACE_LED_MODULE')
        self.assertEqual(before, (machine.optics_cleanliness_pct, machine.illumination_actual_lux, machine.false_reject_rate_pct))
        after = self.tick(machine)
        self.assertGreater(after['Optics_Cleanliness_Pct'], before[0])
        self.assertLess(after['Optics_Cleanliness_Pct'], 99.2)
        self.assertGreater(after['Illumination_Intensity_Lux'], before[1])
        self.assertLess(after['Illumination_Intensity_Lux'], 18500)

    def test_api_supplies_same_metric_contract_used_by_models(self):
        store = StateStore()
        for factory in FACTORIES:
            machine = factory()
            telemetry = self.tick(machine)
            telemetry.pop('Simulated_Active_Faults')
            store.update_machine_telemetry(machine.machine_id, machine.machine_type, telemetry)
        client = TestClient(create_app(store))
        data = client.get('/api/machines').json()
        for machine in data.values():
            self.assertEqual(machine['metrics'], MACHINE_METRICS[machine['machine_type']])
            for metric in machine['metrics']:
                self.assertIsInstance(machine['telemetry'][metric['key']], (int, float))

    def test_edge_static_thresholds_match_dashboard_and_specification(self):
        for machine_type, metrics in MACHINE_METRICS.items():
            for metric in metrics:
                for bound in ('min', 'max'):
                    expected = metric.get(bound, metric.get('critical_' + bound))
                    if expected is not None:
                        self.assertEqual(MACHINE_THRESHOLDS[machine_type][metric['key']][bound], expected)

    def test_tester_agent_proposes_actions_without_modifying_machines(self):
        bus, rag = Mock(), Mock()
        rag.query.return_value = 'Hạ nhiệt nòng phun về 215°C (ADJUST_TEMPERATURE)'
        brain = AgentBrain(rag, AgentTools(), bus, execute_actions=False)
        brain.handle_alert({'machine_id': 'MC-INJ-01', 'machine_type': 'INJECTION_MOLDING', 'payload': {}})
        events = [call.args[0] for call in bus.publish.call_args_list]
        self.assertTrue(any(event['event_type'] == 'action_proposed' for event in events))
        self.assertFalse(any(event['event_type'] == 'action_command' for event in events))

    def test_temperature_parser_does_not_read_a_machine_code_as_celsius(self):
        actions = AgentTools().translate_advice_to_actions(
            'MC-INJ-01', 'INJECTION_MOLDING', 'MC-INJ-01 cần giảm nhiệt đầu phun về 215°C'
        )
        temperature = next(a for a in actions if a['command'] == 'ADJUST_TEMPERATURE')
        self.assertEqual(temperature['params']['target_temp'], 215)


if __name__ == '__main__':
    unittest.main()
