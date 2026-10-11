import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from dashboard.server import create_app
from dashboard.state_store import StateStore
from machines.cnc_milling import CncMilling
from machines.robot_arm import RobotArm
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.injection_molding import InjectionMolding


class ManualFaultTests(unittest.TestCase):
    def setUp(self):
        self.machines = [CncMilling(), RobotArm(), AmrVehicle(), AoiInspection(), InjectionMolding()]
        self.cnc = self.machines[0]
        self.client = TestClient(create_app(StateStore(), {m.machine_id: m for m in self.machines}))
        self.url = '/api/machines/MC-MILL-01/faults'

    def test_fault_catalog_for_each_machine(self):
        for machine in self.machines:
            response = self.client.get(f'/api/machines/{machine.machine_id}/faults')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['available_faults'], list(machine.active_faults))
            self.assertEqual(response.json()['active_faults'], [])

    def test_apply_multiple_remove_one_and_clear_all(self):
        faults = list(self.cnc.active_faults)[:2]
        response = self.client.post(self.url, json={'active_faults': faults})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['active_faults'], faults)
        self.assertEqual(self.cnc.get_active_faults(), faults)
        self.assertFalse(self.machines[1].has_any_fault())
        self.client.post(self.url, json={'active_faults': faults[1:]})
        self.assertEqual(self.cnc.get_active_faults(), faults[1:])
        self.client.post(self.url, json={'active_faults': []})
        self.assertFalse(self.cnc.has_any_fault())

    def test_invalid_selection_is_atomic(self):
        fault = list(self.cnc.active_faults)[0]
        self.cnc.set_active_faults([fault])
        for selection in ([fault, 'INVALID'], ['GEARBOX_LACK_OF_GREASE'], [None], 'INVALID', {}, None):
            with self.subTest(selection=selection):
                response = self.client.post(self.url, json={'active_faults': selection})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.cnc.get_active_faults(), [fault])
        for body in ({}, [], 'bad'):
            self.assertEqual(self.client.post(self.url, json=body).status_code, 400)
        self.assertEqual(self.client.post(self.url, content='{').status_code, 400)

    def test_unknown_machine_and_removed_interval_route(self):
        url = '/api/machines/UNKNOWN/faults'
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, json={'active_faults': []}).status_code, 404)
        self.assertEqual(self.client.post('/api/fault/interval?seconds=1').status_code, 404)

    def test_multiple_faults_combine_and_cancellation_preserves_physics(self):
        self.cnc.set_active_faults(['COOLANT_PUMP_FAILURE', 'TOOL_CHIPPING_OR_WEAR'])
        now = self.cnc.last_update_time
        with patch('random.uniform', return_value=0):
            for tick in range(1, 11):
                with patch('time.time', return_value=now + tick):
                    telemetry = self.cnc.generate_telemetry()
        self.assertEqual(telemetry['Coolant_Pressure_Bar'], 0)
        self.assertGreater(telemetry['Vibration_RMS_mm_s'], 4.5)
        self.assertAlmostEqual(self.cnc.tool_wear_pct, 12 + .005 * 7 * 3 * 10)
        temperature = self.cnc.spindle_temp_c
        wear = self.cnc.tool_wear_pct
        self.cnc.set_active_faults([])
        self.assertEqual(self.cnc.spindle_temp_c, temperature)
        self.assertEqual(self.cnc.tool_wear_pct, wear)
        with patch('time.time', return_value=now + 11):
            self.cnc.generate_telemetry()
        self.assertGreater(self.cnc.coolant_pressure_bar, 0)
        self.assertLess(self.cnc.coolant_pressure_bar, 20)

    def test_no_automatic_faults_after_long_operation(self):
        for machine in self.machines:
            now = machine.last_update_time
            for tick in range(1, 601):
                with patch('time.time', return_value=now + tick):
                    machine.generate_telemetry()
            self.assertEqual(machine.get_active_faults(), [])


if __name__ == '__main__':
    unittest.main()
