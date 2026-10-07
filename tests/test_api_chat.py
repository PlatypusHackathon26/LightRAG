from __future__ import annotations

import json
import os
import threading
import unittest
from urllib.request import Request, urlopen

from dashboard.server import UPLOAD_DIR, DashboardServer
from dashboard.state_store import DashboardState


class StateStoreTests(unittest.TestCase):
    """Kiểm tra cấu trúc hội thoại 2 nhánh (user / system_alert)."""

    def test_alert_creates_system_conversation_and_rag_reply_appends(self) -> None:
        state = DashboardState()
        state.handle_event({
            "event_type": "telemetry",
            "label": "alert",
            "machine_id": "MC-MILL-01",
            "payload": {"Spindle_Temp_C": 91.5},
            "anomalies": [
                {"param": "Spindle_Temp_C", "value": 91.5,
                 "reason": "Vượt ngưỡng trần 85.0"},
            ],
        })
        state.handle_event({
            "event_type": "chat_notification",
            "machine_id": "MC-MILL-01",
            "text": "Khuyến nghị bật làm mát và giảm tải.",
            "source": "AI_RAG",
        })

        snap = state.get_snapshot()
        convs = snap["conversations"]
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["category"], "system_alert")
        self.assertEqual(convs[0]["machine_id"], "MC-MILL-01")
        self.assertEqual(len(convs[0]["messages"]), 2)
        self.assertEqual(convs[0]["messages"][0]["role"], "system")
        self.assertEqual(convs[0]["messages"][1]["role"], "assistant")
        self.assertIn("Spindle_Temp_C", convs[0]["messages"][0]["text"])

    def test_user_session_and_snapshot_keys(self) -> None:
        state = DashboardState()
        sid = state.create_user_session("Kiểm tra mã lỗi E8150")
        self.assertTrue(state.add_message(sid, "user", "Kiểm tra mã lỗi E8150"))
        self.assertTrue(state.add_message(sid, "assistant", "Đây là lỗi quá dòng J3."))

        snap = state.get_snapshot()
        for key in ("server_time", "machines", "conversations",
                    "pending_approvals", "alerts", "uploads"):
            self.assertIn(key, snap)
        conv = snap["conversations"][0]
        self.assertEqual(conv["category"], "user")
        self.assertEqual(conv["title"], "Kiểm tra mã lỗi E8150")
        self.assertEqual(len(conv["messages"]), 2)

    def test_add_message_unknown_session_returns_false(self) -> None:
        state = DashboardState()
        self.assertFalse(state.add_message("nope", "user", "x"))

class ApiEndpointTests(unittest.TestCase):
    """Chạy HTTP server thật trên cổng ngẫu nhiên để test chat/upload."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = DashboardState()
        cls.server = DashboardServer(
            ("127.0.0.1", 0),
            cls.state,
            None,
            on_decision=None,
            on_chat=lambda text: f"Phản hồi RAG cho: {text}",
        )
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path: str, body: bytes, ctype: str) -> tuple[int, dict]:
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers={"Content-Type": ctype},
            method="POST",
        )
        with urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def test_chat_endpoint_creates_user_thread_and_replies(self) -> None:
        payload = json.dumps({"session_id": "", "text": "Cách xử lý rung CNC?"}).encode()
        status, data = self._post("/api/chat", payload, "application/json")
        self.assertEqual(status, 200)
        self.assertTrue(data["session_id"])
        self.assertIn("Phản hồi RAG", data["reply"])

        snap = self.state.get_snapshot()
        conv = next(c for c in snap["conversations"]
                    if c["session_id"] == data["session_id"])
        self.assertEqual(conv["category"], "user")
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant"])

        # Gửi tiếp vào cùng thread
        payload2 = json.dumps(
            {"session_id": data["session_id"], "text": "Giảm còn 50%?"}
        ).encode()
        _, data2 = self._post("/api/chat", payload2, "application/json")
        self.assertEqual(data2["session_id"], data["session_id"])
        conv2 = next(c for c in self.state.get_snapshot()["conversations"]
                     if c["session_id"] == data["session_id"])
        self.assertEqual(len(conv2["messages"]), 4)

    def test_chat_empty_text_rejected(self) -> None:
        from urllib.error import HTTPError
        payload = json.dumps({"text": "   "}).encode()
        with self.assertRaises(HTTPError) as ctx:
            self._post("/api/chat", payload, "application/json")
        self.assertEqual(ctx.exception.code, 400)

    def test_upload_multipart_saves_file_and_registers(self) -> None:
        filename = "_test_rag_upload.txt"
        content = "quy trình bảo trì CNC test"
        boundary = "----densoTestBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        status, data = self._post(
            "/api/upload", body, f"multipart/form-data; boundary={boundary}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "OK")
        self.assertEqual(data["files"][0]["filename"], filename)

        saved_path = os.path.join(UPLOAD_DIR, filename)
        self.assertTrue(os.path.exists(saved_path))
        with open(saved_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), content)

        self.assertTrue(any(u["filename"] == filename
                            for u in self.state.get_snapshot()["uploads"]))
        os.remove(saved_path)

    def test_state_endpoint_includes_conversations(self) -> None:
        with urlopen(f"http://127.0.0.1:{self.port}/api/state", timeout=5) as res:
            snap = json.loads(res.read().decode("utf-8"))
        self.assertIn("conversations", snap)
        self.assertIn("uploads", snap)


if __name__ == "__main__":
    unittest.main()

