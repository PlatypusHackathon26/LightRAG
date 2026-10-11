"""Repair procedures: planned from the machine's state graph, run after approval, then verified."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import patch

from agent.procedures import PlanningError, plan_repair, plan_restart
from iot.action_approval import ActionApproval
from iot.actuator_dispatcher import ActuatorDispatcher
from iot.procedure_runner import ProcedureRunner
from iot.telemetry_receiver import TelemetryReceiver
from machines.amr_vehicle import AmrVehicle
from machines.cnc_milling import CncMilling
from machines.injection_molding import InjectionMolding
from sim_helpers import command, simulate


def names(steps: List[Dict[str, Any]]) -> List[str]:
    return [s["command"] for s in steps]


class PlanTests(unittest.TestCase):
    def test_a_repair_is_wrapped_in_stop_lockout_and_unlock_from_any_state(
        self,
    ) -> None:
        specs = CncMilling.command_specs()
        self.assertEqual(
            names(plan_repair(specs, "RUNNING", "REPAIR_COOLANT_SYSTEM")),
            ["SAFE_STOP", "LOCKOUT", "REPAIR_COOLANT_SYSTEM", "UNLOCK"],
        )
        self.assertEqual(
            names(plan_repair(specs, "HOLD", "REPLACE_TOOL")),
            ["SAFE_STOP", "LOCKOUT", "REPLACE_TOOL", "UNLOCK"],
        )
        self.assertEqual(
            names(plan_repair(specs, "E_STOP", "REPLACE_TOOL")),
            ["RESET_ESTOP", "LOCKOUT", "REPLACE_TOOL", "UNLOCK"],
        )
        self.assertEqual(
            names(plan_repair(specs, "LOCKED_OUT", "REPLACE_TOOL")),
            ["REPLACE_TOOL", "UNLOCK"],
        )

    def test_purging_runs_on_a_stopped_hot_barrel_without_lockout(self) -> None:
        self.assertEqual(
            names(
                plan_repair(InjectionMolding.command_specs(), "RUNNING", "PURGE_BARREL")
            ),
            ["SAFE_STOP", "PURGE_BARREL"],
        )

    def test_restart_paths(self) -> None:
        specs = AmrVehicle.command_specs()
        self.assertEqual(names(plan_restart(specs, "STOPPED")), ["START"])
        self.assertEqual(names(plan_restart(specs, "E_STOP")), ["RESET_ESTOP", "START"])
        self.assertEqual(names(plan_restart(specs, "LOCKED_OUT")), ["UNLOCK", "START"])

    def test_only_declared_repairs_can_be_planned(self) -> None:
        specs = CncMilling.command_specs()
        for bad in ("SAFE_STOP", "TOGGLE_COOLANT", "REPAIR_HYDRAULIC_VALVE"):
            with self.subTest(command=bad), self.assertRaises(PlanningError):
                plan_repair(specs, "RUNNING", bad)
        with self.assertRaises(PlanningError):
            plan_repair(specs, "MAINTENANCE", "REPLACE_TOOL")


class Plant:
    """One CNC, the dispatcher, approvals and the runner on a shared fake clock."""

    def __init__(self, fault: str) -> None:
        self.machine = CncMilling()
        self.machine.set_active_faults([fault])
        self.dispatcher = ActuatorDispatcher()
        self.dispatcher.register_machine(self.machine)
        self.events: List[Dict[str, Any]] = []
        bus = type("Bus", (), {"publish": lambda _self, e: self.events.append(e)})()
        self.runner = ProcedureRunner(
            self.dispatcher,
            event_bus=bus,
            verify_s=90,
            sleep=self.sleep,
            clock=lambda: self.machine.last_update_time,
            background=False,
        )
        self.approval = ActionApproval(
            dispatcher=self.dispatcher,
            procedure_runner=self.runner,
            event_bus=bus,
            require_approval_for_all=True,
        )
        self.restarts: List[Dict[str, Any]] = []
        self.runner.request_restart = lambda mid, steps, rec: self.restarts.append(
            self.approval.process_action_request(
                {
                    "machine_id": mid,
                    "kind": "restart",
                    "command": "START",
                    "steps": steps,
                }
            )
        )
        self.receiver = TelemetryReceiver(settle_sec=30)
        self.mono = 0.0

    def sleep(self, seconds: float) -> None:
        self.run(seconds)

    def run(self, seconds: float) -> Dict[str, Any]:
        """Advance the plant: machine physics, edge filter, and alerts to the runner."""
        tele: Dict[str, Any] = {}
        for _ in range(int(seconds)):
            tele = simulate(self.machine, 1)
            self.mono += 1
            payload = {k: v for k, v in tele.items() if k != "Simulated_Active_Faults"}
            with patch("time.monotonic", return_value=self.mono):
                alert = self.receiver.process(
                    {
                        "event_type": "telemetry",
                        "machine_id": self.machine.machine_id,
                        "machine_type": self.machine.machine_type,
                        "payload": payload,
                    }
                )
            if alert and alert.get("label") == "alert":
                self.runner.on_alert(alert)
            self.runner.check_verification(self.machine.machine_id)
        return tele

    def approve_repair(self, repair: str) -> None:
        steps = plan_repair(self.machine.commands, self.machine.state, repair)
        ticket = self.approval.process_action_request(
            {
                "machine_id": self.machine.machine_id,
                "kind": "repair",
                "command": repair,
                "steps": steps,
            }
        )
        with patch("time.time", side_effect=lambda: self.machine.last_update_time):
            self.approval.approve(ticket["approval_id"])

    def approve_restart(self) -> None:
        with patch("time.time", side_effect=lambda: self.machine.last_update_time):
            self.approval.approve(self.restarts[-1]["approval_id"])

    def verification(self) -> List[str]:
        return [
            e["status"] for e in self.events if e.get("event_type") == "verification"
        ]


class ClosedLoopTests(unittest.TestCase):
    def test_the_right_repair_is_run_restarted_and_verified(self) -> None:
        plant = Plant("COOLANT_PUMP_FAILURE")
        plant.run(180)
        plant.approve_repair("REPAIR_COOLANT_SYSTEM")
        m = plant.machine
        self.assertEqual((m.state, m.get_active_faults()), ("STOPPED", []))
        stopped = m.generate_telemetry()
        self.assertEqual(
            stopped["Spindle_RotaryVelocity_RPM"], 0.0
        )  # repaired, still stopped
        self.assertEqual(
            stopped["Coolant_Pressure_Bar"], 0.0
        )  # pump repaired but not running yet
        self.assertEqual(
            len(plant.restarts), 1
        )  # the second ticket waits for an engineer
        self.assertEqual(names(plant.restarts[0]["steps"]), ["START"])
        plant.approve_restart()
        self.assertEqual(m.state, "RUNNING")
        self.assertEqual(plant.runner.phase(m.machine_id), "verifying")
        tele = plant.run(100)
        self.assertGreater(tele["Coolant_Pressure_Bar"], 18)
        self.assertEqual(plant.verification(), ["started", "verified"])
        self.assertEqual(plant.runner.attempts(m.machine_id), [])
        events = [h["event"] for h in plant.approval.get_history()]
        self.assertEqual(events, ["approved", "approved"])

    def test_a_wrong_repair_leaves_the_fault_and_fails_verification(self) -> None:
        plant = Plant("COOLANT_PUMP_FAILURE")
        plant.run(180)
        plant.approve_repair("REFILL_SPINDLE_LUBRICANT")
        self.assertEqual(
            plant.machine.get_active_faults(), ["COOLANT_PUMP_FAILURE"]
        )  # wrong part: still broken
        steps = [
            e
            for e in plant.events
            if e.get("event_type") == "procedure_step" and e["status"] == "done"
        ]
        self.assertIn(
            "không có lỗi", steps[-2]["detail"]
        )  # the repair step says the part was fine
        plant.approve_restart()
        plant.run(100)
        self.assertEqual(plant.verification(), ["started", "failed"])
        self.assertEqual(
            plant.runner.attempts("MC-MILL-01"),
            [
                {
                    "repair": "REFILL_SPINDLE_LUBRICANT",
                    "outcome": "failed",
                    "at": plant.runner.attempts("MC-MILL-01")[0]["at"],
                }
            ],
        )

    def test_a_machine_runs_one_procedure_at_a_time(self) -> None:
        plant = Plant("COOLANT_PUMP_FAILURE")
        plant.runner._busy["MC-MILL-01"] = "repair"
        self.assertTrue(plant.runner.is_busy("MC-MILL-01"))
        ticket = plant.approval.process_action_request(
            {
                "machine_id": "MC-MILL-01",
                "kind": "repair",
                "command": "REPAIR_COOLANT_SYSTEM",
                "steps": [{"command": "SAFE_STOP"}],
            }
        )
        from iot.action_approval import ActionDispatchError

        with self.assertRaises(ActionDispatchError):
            plant.approval.approve(ticket["approval_id"])

    def test_a_step_the_machine_refuses_for_good_stops_the_procedure_safely(
        self,
    ) -> None:
        plant = Plant("COOLANT_PUMP_FAILURE")
        command(plant.machine, "EMERGENCY_STOP")
        stale = [
            "SAFE_STOP",
            "LOCKOUT",
            "REPAIR_COOLANT_SYSTEM",
            "UNLOCK",
        ]  # planned before the E-stop
        ticket = plant.approval.process_action_request(
            {
                "machine_id": "MC-MILL-01",
                "kind": "repair",
                "command": "REPAIR_COOLANT_SYSTEM",
                "steps": [{"command": n, "kind": "control"} for n in stale],
            }
        )
        with patch("time.time", side_effect=lambda: plant.machine.last_update_time):
            plant.approval.approve(ticket["approval_id"])
        done = [e for e in plant.events if e.get("event_type") == "procedure_done"]
        self.assertEqual(
            (done[-1]["ok"], done[-1]["failed_step"]), (False, "SAFE_STOP")
        )
        self.assertEqual(plant.machine.state, "E_STOP")
        self.assertEqual(plant.restarts, [])
        self.assertFalse(plant.runner.is_busy("MC-MILL-01"))


if __name__ == "__main__":
    unittest.main()
