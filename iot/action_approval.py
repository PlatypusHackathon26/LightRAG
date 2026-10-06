# iot/action_approval.py
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("ActionApproval")


class ActionApproval:
    """Chốt chặn an toàn (Human-in-the-Loop) phân loại rủi ro và quản lý phê duyệt lệnh."""

    def __init__(
        self,
        dispatcher: Optional[Any] = None,
        dispatcher_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self.event_bus = event_bus
        # Hỗ trợ cả 2 cách truyền: truyền object dispatcher hoặc truyền trực tiếp callback execute
        if dispatcher_callback is not None:
            self.dispatcher_callback = dispatcher_callback
        elif dispatcher is not None and hasattr(dispatcher, "execute"):
            self.dispatcher_callback = dispatcher.execute
        else:
            self.dispatcher_callback = None

        # Danh sách lệnh chờ phê duyệt: {approval_id: command_event}
        self.pending_actions: Dict[str, Dict[str, Any]] = {}

    def process_action_request(self, command: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Phân loại mức độ rủi ro của lệnh do Agent đề xuất."""
        risk_level = str(command.get("risk_level", "LOW")).upper()
        machine_id = command.get("machine_id", "UNKNOWN")
        cmd_name = command.get("command") or command.get("action", "UNKNOWN")

        # 1. RỦI RO THẤP (LOW): Chuyển xuống Dispatcher thực thi ngay lập tức
        if risk_level == "LOW":
            logger.info(f"[Approval] Lệnh an toàn ({cmd_name} trên {machine_id}) -> Cho phép thực thi ngay.")
            if self.dispatcher_callback:
                return self.dispatcher_callback(command)
            return None

        # 2. RỦI RO CAO (HIGH): Treo lại, tạo mã ticket chờ người bấm duyệt
        approval_id = str(uuid.uuid4())[:8]
        command_record = {
            **command,
            "approval_id": approval_id,
            "action_id": approval_id,  # Khớp với UI dashboard
            "created_at": time.strftime("%H:%M:%S"),
        }
        self.pending_actions[approval_id] = command_record

        logger.warning(
            f"[Approval] LỆNH NGUY HIỂM ({cmd_name} trên {machine_id})! "
            f"Chờ kỹ sư phê duyệt [ID: {approval_id}]"
        )

        # Phát thông báo lên EventBus để Dashboard bắt được và hiển thị nút duyệt
        if self.event_bus:
            self.event_bus.publish({
                "event_type": "approval_required",
                "approval_id": approval_id,
                "command": command_record,
            })

        return command_record

    def approve(self, action_id: str) -> bool:
        """Kỹ sư bấm [Duyệt Thực Thi] trên giao diện Web UI."""
        command = self.pending_actions.pop(action_id, None)
        if command and self.dispatcher_callback:
            logger.info(f"[Approval] Lệnh {action_id} ĐÃ ĐƯỢC DUYỆT -> Chuyển sang Dispatcher thi hành.")
            self.dispatcher_callback(command)
            return True
        return False

    def reject(self, action_id: str) -> bool:
        """Kỹ sư bấm [Từ Chối] trên giao diện Web UI."""
        if action_id in self.pending_actions:
            del self.pending_actions[action_id]
            logger.info(f"[Approval] Đã từ chối lệnh {action_id}")
            return True
        return False

    def decide(self, action_id: str, decision: str) -> Dict[str, Any]:
        """Tương thích ngược với DashboardServer cũ."""
        decision_upper = decision.strip().upper()
        if decision_upper in ("APPROVE", "APPROVED", "YES"):
            success = self.approve(action_id)
            return {"action_id": action_id, "status": "approved" if success else "not_found"}
        else:
            success = self.reject(action_id)
            return {"action_id": action_id, "status": "rejected" if success else "not_found"}