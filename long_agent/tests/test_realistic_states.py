"""The machines behave like machines: stopping stops them, repairs need a locked-out machine,
fixing a part never resets a reading, and a stopped machine needs a real restart."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from iot.telemetry_receiver import TelemetryReceiver
from machines.amr_vehicle import AmrVehicle
from machines.cnc_milling import CncMilling
from machines.injection_molding import InjectionMolding
from machines.robot_arm import RobotArm
from sim_helpers import command, repair, restart, simulate


class StopTests(unittest.TestCase):
    def test_an_emergency_stop_brings_motion_and_load_to_zero_and_lets_heat_decay(
        self,
    ) -> None:
        m = CncMilling()
        m.set_active_faults(["SPINDLE_BEARING_LACK_OF_LUBE"])
        hot = simulate(m, 120)
        self.assertEqual(command(m, "E-STOP")["status"], "OK")  # an alias
        after = simulate(m, 30)
        self.assertEqual(after["Spindle_RotaryVelocity_RPM"], 0.0)
        self.assertLess(
            after["Spindle_Load_Pct"], 1.0
        )  # decays with the load signal's 5 s lag
        self.assertLess(
            after["Spindle_Temp_C"], hot["Spindle_Temp_C"]
        )  # cooling, not jumping
        self.assertGreater(after["Spindle_Temp_C"], m.ambient_temp_c)
        self.assertEqual(
            m.get_active_faults(), ["SPINDLE_BEARING_LACK_OF_LUBE"]
        )  # stopping repairs nothing

    def test_symptoms_fade_while_stopped_and_return_after_restart_if_unrepaired(
        self,
    ) -> None:
        m = RobotArm()
        m.set_active_faults(["GEARBOX_LACK_OF_GREASE"])
        self.assertGreater(simulate(m, 300)["Joint_3_Current_A"], 16.5)
        command(m, "SAFE_STOP")
        self.assertLess(simulate(m, 120)["Motor_Temp_C"], 40)
        restart(m)
        self.assertGreater(
            simulate(m, 120)["Joint_3_Current_A"], 16.5
        )  # the dry gearbox is still dry

    def test_an_emergency_stop_must_be_reset_before_anything_else(self) -> None:
        m = AmrVehicle()
        command(m, "EMERGENCY_STOP")
        simulate(m, 5)
        refused = command(m, "START")
        self.assertEqual(refused["status"], "REJECTED")
        self.assertFalse(refused["retryable"])
        self.assertEqual(command(m, "RESET_ESTOP")["status"], "OK")
        self.assertEqual(command(m, "START")["status"], "OK")


class RepairPreconditionTests(unittest.TestCase):
    def test_a_repair_is_refused_on_a_running_machine(self) -> None:
        m = CncMilling()
        m.set_active_faults(["COOLANT_PUMP_FAILURE"])
        res = command(m, "REPAIR_COOLANT_SYSTEM")
        self.assertEqual(res["status"], "REJECTED")
        self.assertEqual(m.get_active_faults(), ["COOLANT_PUMP_FAILURE"])

    def test_lockout_waits_until_the_spindle_has_stopped(self) -> None:
        m = CncMilling()
        command(m, "SAFE_STOP")
        early = command(m, "LOCKOUT")
        self.assertEqual((early["status"], early["retryable"]), ("REJECTED", True))
        simulate(m, 5)
        self.assertEqual(command(m, "LOCKOUT")["status"], "OK")

    def test_a_repair_takes_time_and_only_then_removes_the_fault(self) -> None:
        m = CncMilling()
        m.set_active_faults(["COOLANT_PUMP_FAILURE"])
        command(m, "SAFE_STOP")
        simulate(m, 5)
        command(m, "LOCKOUT")
        self.assertEqual(command(m, "REPAIR_COOLANT_SYSTEM")["status"], "OK")
        simulate(m, 30)
        self.assertEqual(
            (m.state, m.get_active_faults()), ("MAINTENANCE", ["COOLANT_PUMP_FAILURE"])
        )
        simulate(m, 31)
        self.assertEqual((m.state, m.get_active_faults()), ("LOCKED_OUT", []))

    def test_fixing_the_part_never_resets_the_readings(self) -> None:
        m = CncMilling()
        m.set_active_faults(["COOLANT_PUMP_FAILURE"])
        simulate(m, 180)
        repair(m, "REPAIR_COOLANT_SYSTEM")
        # Pump fixed but the machine is stopped: no pressure until it runs again.
        self.assertEqual(simulate(m, 1)["Coolant_Pressure_Bar"], 0.0)
        restart(m)
        first = simulate(m, 1)["Coolant_Pressure_Bar"]
        self.assertGreater(first, 0.0)
        self.assertLess(
            first, 20.0
        )  # builds up with the pump, does not jump to nominal

    def test_the_wrong_repair_leaves_the_fault_in_place(self) -> None:
        m = InjectionMolding()
        m.set_active_faults(["HYDRAULIC_PROPORTIONAL_VALVE_LEAK"])
        simulate(m, 60)
        repair(m, "SERVICE_HEATER_SSR")
        self.assertEqual(m.get_active_faults(), ["HYDRAULIC_PROPORTIONAL_VALVE_LEAK"])
        self.assertFalse(m.last_repair["fault_was_present"])
        restart(m)
        self.assertLess(simulate(m, 60)["Clamping_Pressure_Bar"], 115.0)


class RestartTests(unittest.TestCase):
    def test_start_is_blocked_while_the_spindle_is_too_hot(self) -> None:
        m = CncMilling()
        m.spindle_temp_c = 120.0
        command(m, "SAFE_STOP")
        res = command(m, "START")
        self.assertEqual((res["status"], res["retryable"]), ("REJECTED", True))
        self.assertIn("chờ nguội", res["execution_detail"])
        simulate(m, 60)
        self.assertEqual(command(m, "START")["status"], "OK")

    def test_an_injection_machine_runs_only_once_the_nozzle_is_hot(self) -> None:
        m = InjectionMolding()
        command(m, "SAFE_STOP")
        simulate(m, 5)  # clamp pressure bleeds off first
        self.assertEqual(command(m, "LOCKOUT")["status"], "OK")
        simulate(m, 300)  # heaters off: the barrel cools down
        self.assertLess(m.nozzle_temp_zone1_actual, 100)
        command(m, "UNLOCK")
        self.assertEqual(command(m, "START")["status"], "OK")
        simulate(m, 10)
        self.assertEqual(m.state, "STARTING")  # warming up
        for _ in range(400):
            if m.state == "RUNNING":
                break
            simulate(m, 1)
        self.assertEqual(m.state, "RUNNING")
        self.assertGreaterEqual(m.nozzle_temp_zone1_actual, 195)

    def test_an_amr_with_a_flat_battery_must_charge_before_it_starts(self) -> None:
        m = AmrVehicle()
        m.battery_pct = 10.0
        command(m, "SAFE_STOP")
        self.assertEqual(command(m, "START")["status"], "REJECTED")
        command(m, "RETURN_TO_CHARGER")
        simulate(m, 60)
        self.assertEqual(command(m, "RESUME")["status"], "OK")


class EdgeFilterTests(unittest.TestCase):
    def receiver_events(self, machine, receiver, seconds):
        alerts = []
        for i in range(seconds):
            tele = simulate(machine, 1)
            tele.pop("Simulated_Active_Faults")
            with patch("time.monotonic", return_value=machine.last_update_time):
                res = receiver.process(
                    {
                        "event_type": "telemetry",
                        "machine_id": machine.machine_id,
                        "machine_type": machine.machine_type,
                        "payload": tele,
                    }
                )
            if res and res.get("label") == "alert":
                alerts.append(res)
        return alerts

    def test_a_stopped_or_locked_out_machine_raises_no_low_reading_alerts(self) -> None:
        m = CncMilling()
        receiver = TelemetryReceiver(settle_sec=30)
        self.assertEqual(self.receiver_events(m, receiver, 40), [])
        command(m, "SAFE_STOP")
        self.assertEqual(
            self.receiver_events(m, receiver, 10), []
        )  # pressure at zero is what stopping means
        command(m, "LOCKOUT")
        self.assertEqual(self.receiver_events(m, receiver, 30), [])

    def test_a_restart_warm_up_is_not_an_alert_but_a_returning_fault_is(self) -> None:
        m = CncMilling()
        receiver = TelemetryReceiver(settle_sec=30)
        command(m, "SAFE_STOP")
        simulate(m, 300)  # cold
        restart(m)
        self.assertEqual(self.receiver_events(m, receiver, 200), [])
        m.set_active_faults(["COOLANT_PUMP_FAILURE"])
        alerts = self.receiver_events(m, receiver, 60)
        self.assertTrue(
            any(
                a["param"] == "Coolant_Pressure_Bar"
                for e in alerts
                for a in e["anomalies"]
            )
        )


if __name__ == "__main__":
    unittest.main()
