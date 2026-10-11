"""The tester dashboard's state and HTTP routes."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dashboard.server import create_app
from dashboard.state_store import StateStore


class DashboardStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = StateStore()
        self.state.register_machines([SimpleNamespace(machine_id="MC-MILL-01", machine_type="CNC_MILLING",
                                                      model="TestMill", location="Cell-01")])

    def test_an_alert_reading_opens_the_machines_alert_thread(self) -> None:
        self.state.handle_event({
            "event_type": "telemetry", "machine_id": "MC-MILL-01", "label": "alert",
            "payload": {"Spindle_Temp_C": 81.5},
            "anomalies": [{"param": "Spindle_Temp_C", "value": 81.5, "reason": "Vượt ngưỡng trần (81.5 > 75)"}],
        })
        self.state.record_agent_result("MC-MILL-01", {"diagnosis": "Kiểm tra làm mát trục chính."})

        machine = self.state.snapshot()["machines"][0]
        self.assertEqual(machine["status"], "alert")
        self.assertEqual(machine["telemetry"]["Spindle_Temp_C"], 81.5)
        self.assertEqual(machine["history"]["Spindle_Temp_C"], [81.5])
        self.assertEqual(machine["last_agent_result"]["diagnosis"], "Kiểm tra làm mát trục chính.")

        snap = self.state.get_snapshot()
        (conv,) = snap["conversations"]
        self.assertEqual((conv["category"], conv["machine_id"]), ("system_alert", "MC-MILL-01"))
        self.assertIn("Spindle_Temp_C=81.5", conv["messages"][0]["text"])
        self.assertEqual(snap["alerts"][0]["anomalies"][0]["param"], "Spindle_Temp_C")

    def test_a_normal_reading_does_not_open_a_thread(self) -> None:
        self.state.handle_event({"event_type": "telemetry", "machine_id": "MC-MILL-01", "label": "normal",
                                 "payload": {"Spindle_Temp_C": 38.0}})
        self.assertEqual(self.state.get_snapshot()["conversations"], [])
        self.assertEqual(self.state.snapshot()["machines"][0]["status"], "normal")


class DashboardHttpTests(unittest.TestCase):
    def test_the_page_and_the_state_are_served(self) -> None:
        state = StateStore()
        state.update_machine_telemetry("MC-MILL-01", "CNC_MILLING", {"Spindle_Temp_C": 38.0})
        client = TestClient(create_app(state))

        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("GIÁM SÁT NHÀ MÁY THÔNG MINH", page.text)

        machines = client.get("/api/machines").json()
        self.assertEqual(machines["MC-MILL-01"]["telemetry"]["Spindle_Temp_C"], 38.0)
        self.assertTrue(any(m["key"] == "Spindle_Temp_C" for m in machines["MC-MILL-01"]["metrics"]))
        self.assertIn("MC-MILL-01", client.get("/api/state").json()["machines"])


if __name__ == "__main__":
    unittest.main()
