from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

from machines.base_machine import BaseMachine

logger = logging.getLogger("ActuatorDispatcher")


class ActuatorDispatcher:
    """Bộ định tuyến và chấp hành lệnh PLC xuống các thiết bị máy móc.

    Đặc tính:
    - Quản lý danh bạ máy móc động theo machine_id.
    - Định tuyến và gọi trực tiếp receive_plc_command(command, payload) của máy.
    - Lưu vết lịch sử thực thi (Execution Audit Trail) phục vụ giám sát.
    - Bắn bản tin phản hồi (command_response) ngược lại EventBus để Dashboard và Agent theo dõi.
    """

    def __init__(self, event_bus: Optional[Any] = None) -> None:
        self.event_bus = event_bus
        # Danh bạ máy: {machine_id: BaseMachine}
        self._machines: Dict[str, BaseMachine] = {}
        # Sổ nhật ký thực thi: lưu tối đa 200 lệnh gần nhất
        self._history: List[Dict[str, Any]] = []
        self._lock = Lock()

    def register_machine(self, machine: BaseMachine) -> None:
        """Đăng ký một thiết bị vào trạm điều khiển."""
        with self._lock:
            self._machines[machine.machine_id] = machine
            logger.info(
                f"[Dispatcher] Đã kết nối thiết bị: {machine.machine_id} "
                f"({getattr(machine, 'machine_type', 'UNKNOWN')})"
            )

    def register_machines(self, machines: List[BaseMachine]) -> None:
        """Đăng ký hàng loạt máy cùng lúc."""
        for m in machines:
            self.register_machine(m)

    def execute(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Tiếp nhận event lệnh và thực thi xuống máy đích.

        Hỗ trợ cả 2 định dạng phổ biến:
        1. {"machine_id": "MC-MILL-01", "command": "FEED_OVERRIDE", "params": {"override_pct": 70}}
        2. {"machine_id": "MC-MILL-01", "action": "FEED_OVERRIDE", "payload": {"override_pct": 70}}
        """
        machine_id = event.get("machine_id")
        command = event.get("command") or event.get("action")
        payload = event.get("params") or event.get("payload") or {}
        reason = event.get("reason", "N/A")
        now_str = datetime.now().isoformat()

        # 1. Kiểm tra tính hợp lệ của tham số đầu vào
        if not machine_id or not command:
            err_msg = f"Gói tin lệnh thiếu 'machine_id' hoặc 'command': {event}"
            logger.error(f"[Dispatcher] {err_msg}")
            return self._record_and_publish(
                machine_id=machine_id or "UNKNOWN",
                command=command or "UNKNOWN",
                status="REJECTED",
                error=err_msg,
                reason=reason,
                timestamp=now_str,
            )

        # 2. Tra cứu cỗ máy trong danh bạ
        machine = self._machines.get(machine_id)
        if not machine:
            err_msg = f"Không tìm thấy thiết bị '{machine_id}' trong danh bạ đã đăng ký"
            logger.error(f"[Dispatcher] {err_msg}")
            return self._record_and_publish(
                machine_id=machine_id,
                command=command,
                status="NOT_FOUND",
                error=err_msg,
                reason=reason,
                timestamp=now_str,
            )

        # 3. Chuyển lệnh xuống cỗ máy mục tiêu
        logger.info(
            f"[Dispatcher] Đang phát lệnh '{command}' xuống máy '{machine_id}' "
            f"kèm tham số: {payload} | Lý do: {reason}"
        )
        try:
            # Gọi trực tiếp hàm tiếp nhận chuẩn hóa của BaseMachine
            machine_result_event = machine.receive_plc_command(command=command, payload=payload)[cite: 1]
            exec_payload = machine_result_event.get("payload", {})
            status = "SUCCESS" if "rejected" not in str(exec_payload.get("execution_detail", "")).lower() else "REJECTED"

            return self._record_and_publish(
                machine_id=machine_id,
                command=command,
                status=status,
                details=exec_payload,
                reason=reason,
                timestamp=now_str,
            )

        except Exception as exc:
            err_msg = f"Lỗi ngoại lệ khi máy {machine_id} thực thi lệnh {command}: {exc}"
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
        """Ghi nhật ký và bắn kết quả ngược lại EventBus để khép kín vòng lặp."""
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

        # Lưu lịch sử xoay vòng (tối đa 200 bản ghi)
        with self._lock:
            self._history.append(result_packet)
            if len(self._history) > 200:
                self._history.pop(0)

        # Bắn kết quả lên EventBus
        if self.event_bus is not None:
            self.event_bus.publish(result_packet)

        return result_packet

    def get_history(self, machine_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Truy vấn lịch sử thực thi lệnh (dùng cho Dashboard hoặc Agent kiểm tra lại)."""
        with self._lock:
            if machine_id:
                return [rec for rec in self._history if rec["machine_id"] == machine_id]
            return list(self._history)