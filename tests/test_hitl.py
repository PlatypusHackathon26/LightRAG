from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent.brain import AgentBrain
from agent.tools import AgentTools
from dashboard.server import DashboardServer
from dashboard.state_store import DashboardState
from iot.action_approval import ActionApproval, ActionDispatchError
from iot.actuator_dispatcher import ActuatorDispatcher


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def dispatch(self, machine_id: str, action: str, payload: dict) -> dict:
        self.calls.append((machine_id, action, payload))
        return {"status": "dispatched", "machine_id": machine_id, "action": action}


class HitlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = FakeDispatcher()
        self.approvals = ActionApproval(self.dispatcher)

    def test_agent_proposes_action_without_dispatching_but_creates_ticket_and_notification(self) -> None:
        tools = AgentTools()
        brain = AgentBrain(tools=tools)
        result = brain.handle_alert(
            {
                "machine_id": "MC-MILL-01",
                "payload": {
                    "issue": "spindle thermal overload",
                    "telemetry": {"Spindle_Temp_C": 91},
                },
            }
        )

        self.assertEqual(len(result["recommendations"]), 1)
        self.assertEqual(self.dispatcher.calls, [])
        self.assertEqual([item["tool"] for item in tools.action_log], ["create_ticket", "send_notification"])

    def test_dispatcher_observes_machines_added_after_construction(self) -> None:
        class Machine:
            def receive_plc_command(self, command: str, payload: dict) -> dict:
                return {"event_type": "plc_command", "command": command, "payload": payload}

        registry = {}
        dispatcher = ActuatorDispatcher(machine_registry=registry)
        registry["MC-MILL-01"] = Machine()

        result = dispatcher.dispatch("MC-MILL-01", "feed_hold", {"reason": "hot"})
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(result["plc_command"], "FEED_HOLD")

    def test_pending_and_rejected_actions_never_dispatch(self) -> None:
        proposal = self.approvals.propose("MC-MILL-01", "feed_hold", {"reason": "temperature"})
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(self.dispatcher.calls, [])

        rejected = self.approvals.decide(proposal["action_id"], "reject")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self.dispatcher.calls, [])
        with self.assertRaises(RuntimeError):
            self.approvals.decide(proposal["action_id"], "approve")

    def test_approved_action_dispatches_once(self) -> None:
        proposal = self.approvals.propose("RB-ASSY-01", "safe_home", {"reason": "overload"})
        approved = self.approvals.decide(proposal["action_id"], "approve")

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.dispatcher.calls, [("RB-ASSY-01", "safe_home", {"reason": "overload"})])
        self.assertEqual(approved["dispatch_result"]["status"], "dispatched")
        with self.assertRaises(RuntimeError):
            self.approvals.decide(proposal["action_id"], "approve")
        self.assertEqual(len(self.dispatcher.calls), 1)

    def test_dispatch_failure_is_not_reported_as_approved(self) -> None:
        class UnavailableDispatcher:
            def dispatch(self, machine_id: str, action: str, payload: dict) -> dict:
                return {"status": "unknown_machine", "machine_id": machine_id}

        approvals = ActionApproval(UnavailableDispatcher())
        proposal = approvals.propose("MISSING", "feed_hold")
        with self.assertRaises(ActionDispatchError):
            approvals.decide(proposal["action_id"], "approve")
        self.assertEqual(approvals.snapshot()[0]["status"], "dispatch_failed")

    def test_unknown_action_and_invalid_decision_are_rejected(self) -> None:
        with self.assertRaises(KeyError):
            self.approvals.decide("missing-id", "approve")
        with self.assertRaises(ValueError):
            self.approvals.decide("missing-id", "execute")

    def test_pending_proposals_are_not_expired_or_evicted(self) -> None:
        proposals = [
            self.approvals.propose("MC-MILL-01", f"action-{index}")
            for index in range(105)
        ]
        snapshot = self.approvals.snapshot()
        self.assertEqual(len(snapshot), 105)
        self.assertEqual(snapshot[-1]["action_id"], proposals[0]["action_id"])
        self.assertEqual(self.dispatcher.calls, [])

    def test_http_approval_endpoint_dispatches_only_after_approval(self) -> None:
        state = DashboardState()
        proposal = self.approvals.propose("MC-MILL-01", "feed_hold", {"reason": "thermal"})
        server = DashboardServer(("127.0.0.1", 0), state, self.approvals)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/state", timeout=2) as response:
                snapshot = json.loads(response.read().decode("utf-8"))
                self.assertEqual(snapshot["actions"][0]["status"], "pending")

            cross_origin_request = Request(
                f"{base_url}/api/actions/{proposal['action_id']}/approve",
                method="POST",
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(cross_origin_request, timeout=2)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            self.assertEqual(self.dispatcher.calls, [])

            request = Request(
                f"{base_url}/api/actions/{proposal['action_id']}/approve",
                method="POST",
                headers={"Origin": base_url},
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["action"]["status"], "approved")

            self.assertEqual(len(self.dispatcher.calls), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
