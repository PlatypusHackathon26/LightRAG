from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

from machines.base_machine import BaseMachine

logger = logging.getLogger("ActuatorDispatcher")


class ActuatorDispatcher:
    """Bộ định tuyến và chấp hành lệnh PLC xuống các thiết bị máy móc trong xưởng.
    
    Tích hợp kiểm tra an toàn liên động (Interlock Verification) và lưu vết Audit Trail.
    """

    def __init__(self, event_bus: Optional[Any] = None) -> None:
        self.event_bus = event_bus
        self._machines: Dict[str, BaseMachine] = {}
        self._history: List[Dict[str, Any]] = []
        self._lock = Lock()

    def register_machine(self, machine: BaseMachine) -> None:
        """Đăng ký một thiết bị vào trạm điều khiển."""
        with self._lock:
            self._machines[machine.machine_id] = machine
            m_type = getattr(machine, "machine_type", "UNKNOWN")
            logger.info(f"[Dispatcher] Đã liên kết thiết bị: {machine.machine_id} [{m_type}]")

    def register_machines(self, machines: List[BaseMachine]) -> None:
        """Đăng ký hàng loạt máy cùng lúc."""
        for m in machines:
            self.register_machine(m)

    def execute(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Tiếp nhận event lệnh, kiểm tra an toàn và thực thi xuống máy đích."""
        machine_id = event.get("machine_id")
        command = event.get("command") or event.get("action")
        # Chuẩn hóa payload nhận từ Agent: arguments / params / payload
        payload = event.get("arguments") or event.get("params") or event.get("payload") or {}
        reason = event.get("reason", "Action initiated by AI Agent / Controller")
        now_str = datetime.now().isoformat()

        # 1. Kiểm tra tham số cơ bản
        if not machine_id or not command:
            err_msg = f"Gói tin lệnh không hợp lệ, thiếu 'machine_id' hoặc 'command': {event}"
            logger.error(f"[Dispatcher] {err_msg}")
            return self._record_and_publish(
                machine_id=machine_id or "UNKNOWN",
                command=command or "UNKNOWN",
                status="REJECTED",
                error=err_msg,
                reason=reason,
                timestamp=now_str,
            )

        # 2. Tra cứu máy trong danh bạ
        machine = self._machines.get(machine_id)
        if not machine:
            err_msg = f"Không tìm thấy thiết bị '{machine_id}' trong danh bạ đã liên kết."
            logger.error(f"[Dispatcher] {err_msg}")
            return self._record_and_publish(
                machine_id=machine_id,
                command=command,
                status="NOT_FOUND",
                error=err_msg,
                reason=reason,
                timestamp=now_str,
            )

        # 3. Kiểm tra khóa liên động an toàn (Interlock Safety Rules)
        current_state = getattr(machine, "state", "UNKNOWN")
        if current_state in ("EMERGENCY_STOP", "COLLISION_STOP") and command not in (
            "RESET_COLLISION_ALARM",
            "RESUME",
            "SERVICE_HEATER_SSR",
        ):
            err_msg = (
                f"LỆNH BỊ CHẶN AN TOÀN: Máy {machine_id} đang ở trạng thái {current_state}. "
                f"Không thể thi hành '{command}' trước khi reset cờ lỗi phần cứng."
            )
            logger.warning(f"[Dispatcher] {err_msg}")
            return self._record_and_publish(
                machine_id=machine_id,
                command=command,
                status="INTERLOCK_BLOCKED",
                error=err_msg,
                reason=reason,
                timestamp=now_str,
            )

        # 4. Gửi lệnh xuống hàm tiếp nhận PLC của máy
        logger.info(
            f"[Dispatcher] Gửi lệnh '{command}' xuống máy '{machine_id}' "
            f"| Params: {payload} | Lý do: {reason}"
        )
        try:
            machine_result_event = machine.receive_plc_command(command=command, payload=payload)
            exec_payload = machine_result_event.get("payload", {})
            detail = str(exec_payload.get("execution_detail", ""))

            # Phân loại kết quả thực thi
            if "rejected" in detail.lower() or "không hợp lệ" in detail.lower():
                status = "REJECTED"
            else:
                status = "SUCCESS"

            return self._record_and_publish(
                machine_id=machine_id,
                command=command,
                status=status,
                details=exec_payload,
                reason=reason,
                timestamp=now_str,
            )

        except Exception as exc:
            err_msg = f"Ngoại lệ khi thực thi lệnh '{command}' trên máy '{machine_id}': {exc}"
            logger.error(f"[Dispatcher] {err_msg}", exc_info=True)
            return self._record_and_publish(
                machine_id=machine_id,
                command=command,
                status="FAILED",
                error=str(exc),
                reason=reason,
                timestamp=now_str,
            )

    def _record_and_publish(
        self,
        machine_id: str,
        command: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        error: str = "",
        reason: str = "",
        timestamp: str = "",
    ) -> Dict[str, Any]:
        """Ghi nhận vào Audit Trail và bắn bản tin phản hồi (command_response) lên EventBus."""
        result_packet = {
            "event_type": "command_response",
            "timestamp": timestamp,
            "machine_id": machine_id,
            "command": command,
            "status": status,
            "reason": reason,
            "details": details or {},
            "error": error,
        }

        # Lưu lịch sử xoay vòng có khóa Thread Lock
        with self._lock:
            self._history.append(result_packet)
            if len(self._history) > 200:
                self._history.pop(0)

        # Bắn kết quả phản hồi lên EventBus để Agent và Dashboard cập nhật vòng lặp
        if self.event_bus is not None:
            self.event_bus.publish(result_packet)

        return result_packet

    def get_history(self, machine_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Truy xuất nhật ký thực thi lệnh."""
        with self._lock:
            if machine_id:
                return [rec for rec in self._history if rec.get("machine_id") == machine_id]
            return list(self._history)