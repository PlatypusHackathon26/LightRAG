# dashboard/state_store.py
from __future__ import annotations
from threading import Lock
from typing import Any, Dict, List, Optional


class StateStore:
    """Kho lưu trữ snapshot trạng thái máy thời gian thực trong bộ nhớ RAM."""

    def __init__(self) -> None:
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def update_machine_telemetry(
        self,
        machine_id: str,
        machine_type: str,
        payload: Dict[str, Any],
        label: str = "normal",
        active_faults: Optional[List[str]] = None,
        fault_interval_sec: float = 30.0,
    ) -> None:
        with self._lock:
            self._states[machine_id] = {
                "machine_id": machine_id,
                "machine_type": machine_type,
                "label": label,
                "telemetry": payload,
                "active_faults": active_faults or [],
                "fault_interval_sec": fault_interval_sec,
            }

    def set_fault_interval(self, seconds: float) -> None:
        """Cập nhật tần suất sinh lỗi trong snapshot để Web thấy ngay lập tức."""
        with self._lock:
            for state in self._states.values():
                state["fault_interval_sec"] = seconds

    def get_all_machines(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._states)