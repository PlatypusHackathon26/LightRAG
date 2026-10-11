from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

from machines.base_machine import BaseMachine

logger = logging.getLogger("ActuatorDispatcher")


class ActuatorDispatcher:
    """Bộ định tuyến và chấp hành lệnh PLC xuống các thiết bị máy móc trong xưởng, có lưu vết Audit Trail.

    Liên động và trạng thái cho phép do chính máy kiểm tra (machines/commands.py)."""

    def machine(self, machine_id: str) -> Optional[BaseMachine]:
        with self._lock:
            return self._machines.get(machine_id)

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

        # 3. Gửi lệnh xuống máy. Máy tự kiểm tra lệnh có tồn tại, tham số, trạng thái cho phép và
        # liên động (machines/commands.py), và trả kết quả có cấu trúc: không đoán qua câu chữ.
        logger.info(
            f"[Dispatcher] Gửi lệnh '{command}' xuống máy '{machine_id}' "
            f"| Params: {payload} | Lý do: {reason}"
        )
        try:
            machine_result_event = machine.receive_plc_command(command=command, payload=payload)
            exec_payload = machine_result_event.get("payload", {})
            status = "SUCCESS" if exec_payload.get("status") == "OK" else "REJECTED"
            if status == "REJECTED":
                logger.warning(f"[Dispatcher] {machine_id} từ chối '{command}': {exec_payload.get('execution_detail')}")

            return self._record_and_publish(
                machine_id=machine_id,
                command=exec_payload.get("command") or command,
                status=status,
                details=exec_payload,
                error="" if status == "SUCCESS" else str(exec_payload.get("execution_detail", "")),
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

    def dispatch(self, machine_id: str, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Alias kiểu cũ cho execute() — test_hitl dùng dispatch(machine_id, action, payload)."""
        result = self.execute({
            "machine_id": machine_id,
            "command": action,
            "action": action,
            "payload": payload or {},
            "params": payload or {},
        })
        return {
            "status": "dispatched" if result.get("status") == "SUCCESS" else result.get("status"),
            "machine_id": machine_id,
            "action": action,
            "plc_command": action.upper() if isinstance(action, str) else action,
            "detail": result,
        }

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