# iot/action_approval.py
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ActionApproval")

# Các lệnh rủi ro cao mặc định bắt buộc qua Human-in-the-Loop
HIGH_RISK_COMMANDS = {
    "EMERGENCY_STOP",
    "REPLACE_TOOL",
    "REFILL_SPINDLE_LUBRICANT",
    "REPAIR_COOLANT_SYSTEM",
    "SERVICE_HEATER_SSR",
    "REPAIR_HYDRAULIC_VALVE",
    "PURGE_BARREL",
    "RESET_COLLISION_ALARM",
    "REFILL_GEARBOX_GREASE",
}

# Các lệnh an toàn, cho phép Agent tự động can thiệp ngay để dập nguy cơ
LOW_RISK_COMMANDS = {
    "FEED_HOLD",
    "SET_FEED_OVERRIDE",
    "COOLANT_BOOST",
    "PAUSE_MOTION",
    "SET_SPEED_OVERRIDE",
    "PAUSE_INSPECTION_LINE",
    "ADJUST_TEMPERATURE",
    "RESUME",
}


class ActionApproval:
    """Chốt chặn an toàn (Human-in-the-Loop) phân loại rủi ro, quản lý phê duyệt và bảo vệ vận hành."""

    def __init__(
        self,
        dispatcher: Optional[Any] = None,
        dispatcher_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        event_bus: Optional[Any] = None,
        default_ttl_sec: float = 300.0,  # Lệnh chờ duyệt quá 5 phút sẽ tự hết hạn (Expired)
    ) -> None:
        self.event_bus = event_bus
        self.default_ttl_sec = default_ttl_sec
        self._lock = Lock()

        if dispatcher_callback is not None:
            self.dispatcher_callback = dispatcher_callback
        elif dispatcher is not None and hasattr(dispatcher, "execute"):
            self.dispatcher_callback = dispatcher.execute
        else:
            self.dispatcher_callback = None

        # Danh sách chờ: {approval_id: command_record}
        self.pending_actions: Dict[str, Dict[str, Any]] = {}

    def _assess_risk_level(self, cmd_name: str, requested_level: Optional[str]) -> str:
        """Đánh giá rủi ro hai lớp: nếu thuộc danh mục nguy hiểm thì ép buộc HIGH."""
        cmd_upper = cmd_name.strip().upper()
        if cmd_upper in HIGH_RISK_COMMANDS:
            return "HIGH"
        if requested_level:
            return requested_level.strip().upper()
        if cmd_upper in LOW_RISK_COMMANDS:
            return "LOW"
        return "HIGH"  # An toàn là trên hết: lệnh lạ chưa phân loại mặc định là HIGH

    def _cleanup_expired(self) -> None:
        """Dọn dẹp các ticket đã hết hạn."""
        now = time.time()
        expired_ids = [
            aid
            for aid, rec in self.pending_actions.items()
            if now > rec.get("expires_at", float("inf"))
        ]
        for aid in expired_ids:
            rec = self.pending_actions.pop(aid, None)
            logger.warning(f"[Approval] Ticket {aid} ({rec.get('command')}) ĐÃ HẾT HẠN (Expired TTL).")
            if self.event_bus:
                self.event_bus.publish({
                    "event_type": "approval_expired",
                    "approval_id": aid,
                    "command": rec,
                })

    def process_action_request(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Phân loại mức độ rủi ro và xử lý luồng thực thi / chờ phê duyệt."""
        with self._lock:
            self._cleanup_expired()

            machine_id = command.get("machine_id", "UNKNOWN")
            cmd_name = str(command.get("command") or command.get("action") or "UNKNOWN")
            user_risk = command.get("risk_level")
            final_risk = self._assess_risk_level(cmd_name, user_risk)

            # 1. RỦI RO THẤP (LOW): Chuyển xuống Dispatcher thực thi tức thì
            if final_risk == "LOW":
                logger.info(
                    f"[Approval] Lệnh AN TOÀN [{cmd_name}] trên [{machine_id}] "
                    f"-> Tự động phê duyệt thi hành ngay."
                )
                if self.dispatcher_callback:
                    return self.dispatcher_callback(command)
                return {"status": "NO_DISPATCHER_ATTACHED", "command": command}

            # 2. RỦI RO CAO (HIGH): Sinh mã phê duyệt & giữ lại chờ kỹ sư
            approval_id = f"APP-{str(uuid.uuid4())[:8].upper()}"
            now_ts = time.time()
            command_record = {
                **command,
                "approval_id": approval_id,
                "action_id": approval_id,
                "risk_level": "HIGH",
                "status": "PENDING_APPROVAL",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "expires_at": now_ts + self.default_ttl_sec,
            }
            self.pending_actions[approval_id] = command_record

            logger.warning(
                f"[Approval] LỆNH NGUY HIỂM / BẢO TRÌ [{cmd_name}] trên [{machine_id}]! "
                f"Yêu cầu xác nhận từ kỹ sư. [Mã Ticket: {approval_id}]"
            )

            # Bắn event thông báo lên EventBus cho Dashboard / Webhook
            if self.event_bus:
                self.event_bus.publish({
                    "event_type": "approval_required",
                    "approval_id": approval_id,
                    "command": command_record,
                })

            return command_record

    def approve(self, action_id: str) -> Dict[str, Any]:
        """Kỹ sư bấm [Duyệt Thực Thi] trên giao diện."""
        with self._lock:
            self._cleanup_expired()
            command = self.pending_actions.pop(action_id, None)

        if not command:
            logger.warning(f"[Approval] Không thể duyệt: Ticket {action_id} không tồn tại hoặc đã hết hạn.")
            return {"status": "REJECTED_OR_EXPIRED", "action_id": action_id}

        logger.info(f"[Approval] Kỹ sư ĐÃ DUYỆT lệnh {action_id} ({command.get('command')}) -> Chuyển thi hành.")
        if self.dispatcher_callback:
            exec_res = self.dispatcher_callback(command)
            return {"status": "EXECUTED", "action_id": action_id, "execution_result": exec_res}
        return {"status": "DISPATCHER_UNAVAILABLE", "action_id": action_id}

    def reject(self, action_id: str, reason: str = "Rejected by operator") -> Dict[str, Any]:
        """Kỹ sư bấm [Từ Chối] trên giao diện."""
        with self._lock:
            command = self.pending_actions.pop(action_id, None)

        if command:
            logger.info(f"[Approval] Đã TỪ CHỐI lệnh {action_id}. Lý do: {reason}")
            if self.event_bus:
                self.event_bus.publish({
                    "event_type": "approval_rejected",
                    "approval_id": action_id,
                    "command": command,
                    "reason": reason,
                })
            return {"status": "REJECTED", "action_id": action_id}
        return {"status": "NOT_FOUND", "action_id": action_id}

    def decide(self, action_id: str, decision: str) -> Dict[str, Any]:
        """Endpoint đa năng phục vụ REST API Dashboard."""
        dec = decision.strip().upper()
        if dec in ("APPROVE", "APPROVED", "YES", "CONFIRM"):
            return self.approve(action_id)
        return self.reject(action_id)

    def get_pending_actions(self) -> List[Dict[str, Any]]:
        """Lấy danh sách các lệnh đang chờ duyệt trên Dashboard."""
        with self._lock:
            self._cleanup_expired()
            return list(self.pending_actions.values())