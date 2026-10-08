from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from machines.specifications import MACHINE_METRICS


class BaseMachine:
    """Lớp cơ sở chuẩn hóa cho các thiết bị cạnh trong mô phỏng nhà máy thông minh."""

    def __init__(
        self,
        machine_id: str,
        machine_type: str,
        model: str,
        location: str,
        event_hub: Optional[Any] = None,
    ) -> None:
        self.machine_id = machine_id
        self.machine_type = machine_type
        self.model = model
        self.location = location
        self.event_hub = event_hub
        self.state = "RUNNING"
        self.connected = False
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._last_telemetry: Dict[str, Any] = {}

        self.active_faults: Dict[str, bool] = {}

    def nominal(self, key: str) -> float:
        return next(m["nominal"] for m in MACHINE_METRICS[self.machine_type] if m["key"] == key)

    @staticmethod
    def approach(current: float, target: float, dt: float, tau: float) -> float:
        """Exact first-order response; never jump or overshoot for a large dt."""
        return target + (current - target) * math.exp(-dt / tau)

    @staticmethod
    def ramp(current: float, target: float, dt: float, rate: float) -> float:
        step = rate * dt
        value = current + max(-step, min(step, target - current))
        return target if math.isclose(value, target, abs_tol=1e-10) else value

    def inject_fault(self, fault_name: str) -> bool:
        """Kích hoạt thủ công 1 lỗi."""
        with self._lock:
            if fault_name in self.active_faults:
                self.active_faults[fault_name] = True
                return True
            return False

    def get_fault_config(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "machine_id": self.machine_id,
                "available_faults": list(self.active_faults),
                "active_faults": self.get_active_faults(),
            }

    def set_active_faults(self, faults: List[str]) -> Dict[str, Any]:
        """Replace the fault selection atomically; preserve physical state for recovery."""
        with self._lock:
            if not isinstance(faults, list) or any(not isinstance(f, str) for f in faults):
                raise ValueError("faults must be a list of fault codes")
            unknown = set(faults) - self.active_faults.keys()
            if unknown:
                raise ValueError("Unknown faults: " + ", ".join(sorted(unknown)))
            selected = set(faults)
            for fault in self.active_faults:
                self.active_faults[fault] = fault in selected
            return self.get_fault_config()

    def clear_fault(self, fault_name: str) -> bool:
        """Tắt cờ lỗi khi kỹ sư hoặc PLC sửa xong."""
        with self._lock:
            if fault_name in self.active_faults:
                self.active_faults[fault_name] = False
                return True
            return False

    def get_active_faults(self) -> List[str]:
        with self._lock:
            return [f for f, on in self.active_faults.items() if on]

    def has_any_fault(self) -> bool:
        with self._lock:
            return any(self.active_faults.values())

    def connect(self) -> Dict[str, Any]:
        with self._lock:
            self.connected = True
            self.state = "RUNNING"
            return self._build_event("connection", {"status": "connected"})

    def disconnect(self) -> Dict[str, Any]:
        with self._lock:
            self.connected = False
            self.state = "offline"
            self._stop_event.set()
            return self._build_event("connection", {"status": "disconnected"})

    def receive_plc_command(self, command: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            self.state = "command_received"
            return self._build_event(
                "plc_command",
                {"command": command, "payload": payload or {}, "result": "accepted"},
                priority="info",
            )

    def _build_event(self, event_type: str, payload: Dict[str, Any], priority: str = "info") -> Dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "machine_id": self.machine_id,
            "machine_type": self.machine_type,
            "model": self.model,
            "location": self.location,
            "priority": priority,
            "payload": payload,
        }

    def emit_event(self, event_type: str, payload: Dict[str, Any], priority: str = "info") -> Dict[str, Any]:
        event = self._build_event(event_type, payload, priority)
        if self.event_hub is not None:
            self.event_hub.publish(event)
        return event

    def generate_telemetry(self) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses must implement generate_telemetry().")

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        return None

    def stop(self) -> None:
        self._stop_event.set()
        self.disconnect()

    def as_json(self, data: Dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.machine_id}, type={self.machine_type})"
