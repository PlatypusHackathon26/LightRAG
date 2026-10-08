# tests/test_fault_interval.py
"""Test luồng điều chỉnh tần suất sinh lỗi từ Web UI."""
from __future__ import annotations

import time
import unittest

from fastapi.testclient import TestClient

from dashboard.server import create_app
from dashboard.state_store import StateStore
from machines.cnc_milling import CncMilling


class FaultIntervalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = CncMilling()
        self.state_store = StateStore()
        # Giả lập snapshot đã có dữ liệu (như vòng lặp IoT đã chạy)
        self.state_store.update_machine_telemetry(
            machine_id=self.machine.machine_id,
            machine_type=self.machine.machine_type,
            payload={"Spindle_Temp_C": 40.0},
        )
        self.app = create_app(
            state_store=self.state_store,
            machines_dict={self.machine.machine_id: self.machine},
        )
        self.client = TestClient(self.app)

    def test_set_interval_updates_machine_and_snapshot(self) -> None:
        response = self.client.post("/api/fault/interval", params={"seconds": 5})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["interval_sec"], 5)

        # Máy thật đã đổi tần suất
        self.assertEqual(self.machine.fault_interval_sec, 5.0)
        # Snapshot (được stream về Web qua SSE) cũng chứa giá trị mới
        snapshot = self.state_store.get_all_machines()
        self.assertEqual(
            snapshot[self.machine.machine_id]["fault_interval_sec"], 5.0
        )

    def test_interval_is_clamped_to_at_least_one_second(self) -> None:
        response = self.client.post("/api/fault/interval", params={"seconds": 0.5})
        self.assertEqual(response.json()["success"], True)
        self.assertEqual(self.machine.fault_interval_sec, 1.0)

    def test_changing_interval_resets_countdown(self) -> None:
        # Giả lập máy đã chạy lâu: mốc lỗi cũ cách đây 100s
        self.machine.last_fault_time = time.time() - 100
        self.client.post("/api/fault/interval", params={"seconds": 30})
        elapsed = time.time() - self.machine.last_fault_time
        self.assertLess(elapsed, 1.0, "Đổi tần suất phải reset bộ đếm")

    def test_fault_triggers_with_new_interval(self) -> None:
        self.client.post("/api/fault/interval", params={"seconds": 1})
        self.machine.last_fault_time = time.time() - 2  # Đã qua hạn với interval=1s
        self.machine.generate_telemetry()
        self.assertTrue(self.machine.has_any_fault(), "Lỗi phải tự sinh ngay")


if __name__ == "__main__":
    unittest.main()