# dashboard/state_store.py
from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, List, Optional


class DashboardState:
    """Kho lưu trữ trạng thái tập trung cho Dashboard kiểu Chat-GPT.

    Hội thoại chia làm 2 nhánh:
    - category="user":         user chủ động mở chat với Agent.
    - category="system_alert": hệ thống tự tạo khi máy phát sinh cảnh báo.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # Trạng thái 5 máy: {machine_id: {...}}
        self.machines: Dict[str, Dict[str, Any]] = {}
        # Danh sách hội thoại (chat threads)
        self.conversations: List[Dict[str, Any]] = []
        # Danh sách lệnh chờ phê duyệt: {approval_id: {...}}
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}
        # Lịch sử cảnh báo
        self.alerts: List[Dict[str, Any]] = []
        # Kho file đã upload lên RAG
        self.uploads: List[Dict[str, Any]] = []
        # Bản đồ máy -> thread cảnh báo: {machine_id: session_id}
        self._system_sessions: Dict[str, str] = {}
        self._session_seq = 0

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
                    self._record_alert_conversation(event)

            # 2. Cập nhật hội thoại chat (RAG / Agent phản hồi)
            elif event_type == "chat_notification":
                self._append_chat_notification(event)

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

    # ==========================================================================
    # Quản lý hội thoại (conversations)
    # ==========================================================================
    def _next_session_id(self) -> str:
        self._session_seq += 1
        return f"s{self._session_seq:04d}"

    def _create_session(
        self,
        category: str,
        title: str,
        machine_id: Optional[str] = None,
    ) -> str:
        """Tạo thread chat mới (phải gọi trong lúc đang giữ lock)."""
        session_id = self._next_session_id()
        now = time.strftime("%H:%M:%S")
        self.conversations.append({
            "session_id": session_id,
            "category": category,          # "user" | "system_alert"
            "title": (title or "Cuộc trò chuyện").strip().replace("\n", " ")[:60],
            "machine_id": machine_id,
            "created_at": now,
            "updated_at": now,
            "messages": [],                # [{role, text, source, time}]
        })
        return session_id

    def _find_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        for conv in self.conversations:
            if conv["session_id"] == session_id:
                return conv
        return None

    def add_message(
        self,
        session_id: str,
        role: str,
        text: str,
        source: str = "",
    ) -> bool:
        """Thêm 1 tin nhắn vào thread. Trả về False nếu thread không tồn tại."""
        with self._lock:
            conv = self._find_session(session_id)
            if conv is None:
                return False
            conv["messages"].append({
                "role": role,               # "user" | "assistant" | "system"
                "text": text,
                "source": source,
                "time": time.strftime("%H:%M:%S"),
            })
            conv["updated_at"] = time.strftime("%H:%M:%S")
            return True

    def create_user_session(self, first_message: str) -> str:
        """User chủ động mở 1 thread chat mới (tiêu đề lấy từ tin nhắn đầu)."""
        with self._lock:
            title = first_message.strip() or "Cuộc trò chuyện mới"
            return self._create_session("user", title)

    def _get_or_create_system_session(self, machine_id: str, title: str) -> str:
        """Lấy (hoặc tạo) thread cảnh báo của 1 máy. Đang giữ lock."""
        existing = self._system_sessions.get(machine_id)
        if existing:
            conv = self._find_session(existing)
            if conv is not None:
                return existing
        session_id = self._create_session("system_alert", title, machine_id=machine_id)
        self._system_sessions[machine_id] = session_id
        return session_id

    def _record_alert_conversation(self, event: Dict[str, Any]) -> None:
        """Máy phát cảnh báo -> tạo/mở rộng thread hệ thống kèm tóm tắt bất thường."""
        machine_id = event.get("machine_id", "UNKNOWN")
        anomalies = event.get("anomalies", [])

        summary_lines = []
        for anom in anomalies:
            param = anom.get("param", "?")
            value = anom.get("value", "?")
            reason = anom.get("reason", "")
            summary_lines.append(f"• {param} = {value} — {reason}")
        summary = "\n".join(summary_lines) if summary_lines else "Phát hiện bất thường ngoài ngưỡng."

        first_param = anomalies[0].get("param", "Anomaly") if anomalies else "Anomaly"
        title = f"{machine_id} · {first_param}"

        session_id = self._get_or_create_system_session(machine_id, title)
        conv = self._find_session(session_id)
        if conv is not None:
            conv["messages"].append({
                "role": "system",
                "text": f"⚠️ CẢNH BÁO THIẾT BỊ {machine_id}\n{summary}",
                "source": "IIOT_GATEWAY",
                "time": time.strftime("%H:%M:%S"),
            })
            conv["updated_at"] = time.strftime("%H:%M:%S")

    def _append_chat_notification(self, event: Dict[str, Any]) -> None:
        """Phản hồi RAG/Agent -> nối vào thread cảnh báo của máy (hoặc thread chỉ định)."""
        machine_id = event.get("machine_id")
        session_id = event.get("session_id")
        text = event.get("text", "")
        source = event.get("source", "AI_AGENT")

        target: Optional[Dict[str, Any]] = None
        if session_id:
            target = self._find_session(session_id)
        elif machine_id and machine_id in self._system_sessions:
            target = self._find_session(self._system_sessions[machine_id])

        if target is None and machine_id:
            # RAG trả lời trước khi thread được tạo (race) -> tạo bù
            new_id = self._get_or_create_system_session(
                machine_id, f"{machine_id} · Cảnh báo"
            )
            target = self._find_session(new_id)

        if target is None:
            # Không gắn được vào máy nào -> tạo 1 thread chung
            new_id = self._create_session("user", "Phản hồi từ AI Agent")
            target = self._find_session(new_id)

        if target is not None:
            target["messages"].append({
                "role": "assistant",
                "text": text,
                "source": source,
                "time": time.strftime("%H:%M:%S"),
            })
            target["updated_at"] = time.strftime("%H:%M:%S")

    # ==========================================================================
    # Upload kho tri thức RAG
    # ==========================================================================
    def record_upload(self, filename: str, size: int, status: str = "OK") -> None:
        with self._lock:
            self.uploads.append({
                "filename": filename,
                "size": size,
                "time": time.strftime("%H:%M:%S"),
                "status": status,
            })

    def get_snapshot(self) -> Dict[str, Any]:
        """Lấy toàn bộ dữ liệu snapshot để trả về cho giao diện Web."""
        with self._lock:
            # Sắp xếp thread theo thời điểm hoạt động gần nhất
            conv_sorted = sorted(
                self.conversations,
                key=lambda c: c.get("updated_at", ""),
                reverse=True,
            )
            return {
                "server_time": time.strftime("%H:%M:%S"),
                "machines": list(self.machines.values()),
                "conversations": [
                    {**c, "messages": list(c["messages"])} for c in conv_sorted
                ],
                "pending_approvals": list(self.pending_approvals.values()),
                "alerts": list(self.alerts[-10:]),
                "uploads": list(self.uploads),
            }

    def remove_approval(self, approval_id: str) -> None:
        """Xóa lệnh chờ khi đã được bấm duyệt trên web."""
        with self._lock:
            self.pending_approvals.pop(approval_id, None)