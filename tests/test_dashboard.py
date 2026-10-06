from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from urllib.request import urlopen

from dashboard.server import DashboardServer
from dashboard.state_store import DashboardState


class ApprovalStub:
    def snapshot(self) -> list[dict]:
        return []


class DashboardStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = DashboardState()
        machine = SimpleNamespace(
            machine_id="MC-MILL-01",
            machine_type="CNC_MILLING",
            model="TestMill",
            location="Cell-01",
        )
        self.state.register_machines([machine])

    def test_tracks_telemetry_and_agent_diagnosis(self) -> None:
        self.state.handle_event(
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "event_type": "telemetry",
                "machine_id": "MC-MILL-01",
                "payload": {"Spindle_Temp_C": 81.5},
            }
        )
        self.state.handle_event(
            {
                "timestamp": "2026-01-01T00:00:01+00:00",
                "event_type": "alert",
                "machine_id": "MC-MILL-01",
                "payload": {"issue": "spindle thermal overload", "telemetry": {"Spindle_Temp_C": 91}},
            }
        )
        result = {"issue": "spindle thermal overload", "diagnosis": "Check spindle cooling."}
        self.state.record_agent_result("MC-MILL-01", result)

        snapshot = self.state.snapshot()
        machine = snapshot["machines"][0]
        self.assertEqual(machine["status"], "alert")
        self.assertEqual(machine["telemetry"]["Spindle_Temp_C"], 81.5)
        self.assertEqual(machine["history"]["Spindle_Temp_C"], [81.5])
        self.assertEqual(machine["last_agent_result"], result)
        self.assertEqual(snapshot["alerts"][0]["agent_result"], result)

    def test_http_server_serves_dashboard_and_state_json(self) -> None:
        server = DashboardServer(("127.0.0.1", 0), self.state, ApprovalStub())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(base_url, timeout=2) as response:
                html = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("Trạng thái dây chuyền", html)

            with urlopen(f"{base_url}/api/state", timeout=2) as response:
                snapshot = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(snapshot["machines"][0]["machine_id"], "MC-MILL-01")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
