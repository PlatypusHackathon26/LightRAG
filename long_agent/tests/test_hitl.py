"""Human-in-the-loop: what runs at once, what waits for an engineer, and what never runs."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from agent.brain import AgentBrain
from dashboard.server import create_app
from dashboard.state_store import StateStore
from iot.action_approval import ActionApproval, ActionDispatchError
from iot.actuator_dispatcher import ActuatorDispatcher
from machines.cnc_milling import CncMilling


def cnc_spec(machine_id: str, command: str):
    return CncMilling.command_specs().get(command)


class FakeDispatcher:
    def __init__(self, status: str = "SUCCESS") -> None:
        self.status = status
        self.calls: list[dict] = []

    def execute(self, command: dict) -> dict:
        self.calls.append(command)
        return {"status": self.status, "machine_id": command.get("machine_id")}


class HitlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = FakeDispatcher()
        self.approvals = ActionApproval(
            dispatcher=self.dispatcher, spec_lookup=cnc_spec
        )

    def test_a_command_the_machine_declares_low_risk_runs_at_once_when_allowed(
        self,
    ) -> None:
        result = self.approvals.process_action_request(
            {"machine_id": "MC-MILL-01", "command": "HOLD"}
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual([c["command"] for c in self.dispatcher.calls], ["HOLD"])
        self.assertEqual(self.approvals.get_history()[-1]["event"], "executed")

    def test_a_request_cannot_lower_the_declared_risk(self) -> None:
        ticket = self.approvals.process_action_request(
            {"machine_id": "MC-MILL-01", "command": "REPLACE_TOOL", "risk_level": "LOW"}
        )
        self.assertEqual(ticket["status"], "PENDING_APPROVAL")
        self.assertEqual(self.dispatcher.calls, [])

    def test_a_high_risk_command_waits_and_runs_once_after_approval(self) -> None:
        ticket = self.approvals.process_action_request(
            {"machine_id": "MC-MILL-01", "command": "REPLACE_TOOL"}
        )
        self.assertEqual(ticket["status"], "PENDING_APPROVAL")
        self.assertEqual(self.dispatcher.calls, [])
        approved = self.approvals.decide(ticket["approval_id"], "approve")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(len(self.dispatcher.calls), 1)
        with self.assertRaises(KeyError):  # a ticket is consumed by its decision
            self.approvals.decide(ticket["approval_id"], "approve")
        self.assertEqual(len(self.dispatcher.calls), 1)

    def test_an_unknown_command_is_treated_as_high_risk(self) -> None:
        ticket = self.approvals.process_action_request(
            {"machine_id": "MC-MILL-01", "command": "SELF_DESTRUCT"}
        )
        self.assertEqual(ticket["status"], "PENDING_APPROVAL")

    def test_a_rejected_command_never_runs(self) -> None:
        ticket = self.approvals.propose(
            "MC-MILL-01", "REPLACE_TOOL", {"reason": "mòn dao"}
        )
        self.assertEqual(
            self.approvals.decide(ticket["action_id"], "reject")["status"], "rejected"
        )
        with self.assertRaises(KeyError):
            self.approvals.decide(ticket["action_id"], "approve")
        self.assertEqual(self.dispatcher.calls, [])

    def test_a_failed_dispatch_is_not_reported_as_approved(self) -> None:
        approvals = ActionApproval(dispatcher=FakeDispatcher(status="REJECTED"))
        ticket = approvals.propose("MISSING", "REPLACE_TOOL")
        with self.assertRaises(ActionDispatchError):
            approvals.decide(ticket["action_id"], "approve")
        self.assertEqual(approvals.get_history()[-1]["event"], "failed")

    def test_unknown_tickets_and_decisions_are_refused(self) -> None:
        with self.assertRaises(KeyError):
            self.approvals.decide("missing-id", "approve")
        with self.assertRaises(ValueError):
            self.approvals.decide("missing-id", "execute")

    def test_a_ticket_left_undecided_expires(self) -> None:
        approvals = ActionApproval(dispatcher=self.dispatcher, default_ttl_sec=0.05)
        approvals.propose("MC-MILL-01", "REPLACE_TOOL")
        self.assertEqual(len(approvals.get_pending_actions()), 1)
        time.sleep(0.1)
        self.assertEqual(approvals.get_pending_actions(), [])
        self.assertEqual(self.dispatcher.calls, [])
        self.assertEqual(
            approvals.get_history()[-1]["event"], "expired"
        )  # recorded, not silently dropped

    def test_the_dispatcher_reports_what_the_machine_answered(self) -> None:
        machine = CncMilling()
        dispatcher = ActuatorDispatcher()
        dispatcher.register_machine(machine)
        ok = dispatcher.execute({"machine_id": "MC-MILL-01", "command": "feed hold"})
        self.assertEqual(
            (ok["status"], ok["command"], machine.state), ("SUCCESS", "HOLD", "HOLD")
        )
        refused = dispatcher.execute(
            {"machine_id": "MC-MILL-01", "command": "REPLACE_TOOL"}
        )
        self.assertEqual(refused["status"], "REJECTED")
        self.assertIn("LOCKED_OUT", refused["error"])
        unknown = dispatcher.execute(
            {"machine_id": "MC-MILL-01", "command": "TOGGLE_COOLANT"}
        )
        self.assertEqual(unknown["status"], "REJECTED")  # never reported as success
        self.assertEqual(
            dispatcher.execute({"machine_id": "MC-NONE", "command": "HOLD"})["status"],
            "NOT_FOUND",
        )

    def test_with_proposals_off_the_brain_only_announces_them(self) -> None:
        bus = MagicMock()
        rag = MagicMock()
        rag.query_with_schema.return_value = {
            "diagnosis": "Quá nhiệt trục chính",
            "actions": [
                {
                    "command": "HOLD",
                    "params": {},
                    "risk_level": "LOW",
                    "reason": "giảm nhiệt",
                }
            ],
        }
        AgentBrain(rag_engine=rag, event_bus=bus, execute_actions=False).handle_alert(
            {
                "machine_id": "MC-MILL-01",
                "machine_type": "CNC_MILLING",
                "payload": {"Spindle_Temp_C": 91},
            }
        )
        types = [call.args[0]["event_type"] for call in bus.publish.call_args_list]
        self.assertEqual(
            types, ["chat_notification", "action_proposed"]
        )  # never "action_command"


class ApprovalEndpointTests(unittest.TestCase):
    def test_the_approve_endpoint_refuses_other_origins(self) -> None:
        dispatcher = FakeDispatcher()
        approvals = ActionApproval(dispatcher=dispatcher)
        ticket = approvals.propose("MC-MILL-01", "REPLACE_TOOL")
        client = TestClient(create_app(StateStore(), approval=approvals))

        state = client.get("/api/state").json()
        self.assertEqual(
            [a["action_id"] for a in state["actions"]], [ticket["action_id"]]
        )

        refused = client.post(
            f"/api/actions/{ticket['action_id']}/approve",
            headers={"Origin": "http://evil.example"},
        )
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(dispatcher.calls, [])

        ok = client.post(
            f"/api/actions/{ticket['action_id']}/approve",
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["action"]["status"], "approved")
        self.assertEqual(len(dispatcher.calls), 1)


if __name__ == "__main__":
    unittest.main()
