# dashboard/state_store.py
from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, List


class DashboardState:
    """Kho lưu trữ trạng thái tập trung phục vụ hiển thị Dashboard."""

    def __init__(self) -> None:
        self._lock = Lock()
        # Trạng thái 5 máy: {machine_id: {...}}
        self.machines: Dict[str, Dict[str, Any]] = {}
        # Lịch sử chat AI/RAG
        self.chat_history: List[Dict[str, Any]] = []
        # Danh sách lệnh chờ phê duyệt: {approval_id: {...}}
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}
        # Lịch sử cảnh báo
        self.alerts: List[Dict[str, Any]] = []

    def register_machines(self, machines: List[Any]) -> None:
        """Đăng ký danh mục máy ban đầu."""
        with self._lock:
            for m in machines:
                self.machines[m.machine_id] = {
                    "machine_id": m.machine_id,
                    "machine_type": getattr(m, "machine_type", "UNKNOWN"),
                    "model": getattr(m, "model", "N/A"),
                    "location": getattr(m, "location", "Shopfloor"),
                    "status": "ONLINE",
                    "label": "normal",
                    "telemetry": {},
                    "last_updated": time.time(),
                }

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Lắng nghe tất cả các sự kiện trên EventBus."""
        event_type = event.get("event_type")
        label = event.get("label")
        machine_id = event.get("machine_id")

        with self._lock:
            # 1. Cập nhật Telemetry máy
            if event_type == "telemetry" or label in ("normal", "alert"):
                if machine_id in self.machines:
                    m = self.machines[machine_id]
                    m["last_updated"] = time.time()
                    if "payload" in event:
                        m["telemetry"] = event["payload"]
                    if label:
                        m["label"] = label
                        m["status"] = "ALERT" if label == "alert" else "ONLINE"

                if label == "alert":
                    self.alerts.append({
                        "timestamp": event.get("timestamp", time.time()),
                        "machine_id": machine_id,
                        "anomalies": event.get("anomalies", []),
                    })
                    if len(self.alerts) > 50:
                        self.alerts.pop(0)

            # 2. Cập nhật thông điệp Chatbot từ RAG/Agent
            elif event_type == "chat_notification":
                self.chat_history.append({
                    "timestamp": time.strftime("%H:%M:%S"),
                    "machine_id": machine_id,
                    "text": event.get("text", ""),
                    "source": event.get("source", "AI_AGENT"),
                })
                if len(self.chat_history) > 100:
                    self.chat_history.pop(0)

            # 3. Cập nhật yêu cầu phê duyệt an toàn
            elif event_type == "approval_required":
                app_id = event.get("approval_id")
                cmd = event.get("command", {})
                if app_id:
                    self.pending_approvals[app_id] = {
                        "approval_id": app_id,
                        "machine_id": cmd.get("machine_id"),
                        "command": cmd.get("command"),
                        "params": cmd.get("params", {}),
                        "reason": cmd.get("reason", ""),
                        "created_at": time.strftime("%H:%M:%S"),
                    }

            # 4. Khi lệnh đã được thực thi hoặc hủy
            elif event_type in ("command_response", "command_result"):
                # Dọn các lệnh đã xử lý xong ra khỏi danh sách chờ
                pass

    def get_snapshot(self) -> Dict[str, Any]:
        """Lấy toàn bộ dữ liệu snapshot để trả về cho giao diện Web."""
        with self._lock:
            return {
                "server_time": time.strftime("%H:%M:%S"),
                "machines": list(self.machines.values()),
                "chat_history": list(self.chat_history[-20:]),  # 20 tin gần nhất
                "pending_approvals": list(self.pending_approvals.values()),
                "alerts": list(self.alerts[-10:]),
            }

    def remove_approval(self, approval_id: str) -> None:
        """Xóa lệnh chờ khi đã được bấm duyệt trên web."""
        with self._lock:
            self.pending_approvals.pop(approval_id, None)