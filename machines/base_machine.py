from __future__ import annotations

import json
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class BaseMachine:
    """Lớp cơ sở chuẩn hóa cho các thiết bị cạnh trong mô phỏng nhà máy thông minh."""

    def __init__(
        self,
        machine_id: str,
        machine_type: str,
        model: str,
        location: str,
        event_hub: Optional[Any] = None,
        fault_interval_sec: float = 30.0,  # <-- Cấu hình tần suất sinh lỗi (mặc định 30 giây)
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

        # --- QUẢN LÝ LỖI VÀ TẦN SUẤT THEO THỜI GIAN THỰC ---
        self.active_faults: Dict[str, bool] = {}
        self.fault_interval_sec: float = fault_interval_sec  # Chu kỳ giãn cách giữa các lỗi
        self.last_fault_time: float = time.time()  # Mốc thời gian lỗi trước đó phát sinh
        self.fault_auto_enabled: bool = True  # Cho phép bật/tắt chế độ tự sinh lỗi

    def set_fault_interval(self, seconds: float) -> None:
        """Cho phép can thiệp thay đổi tần suất sinh lỗi lúc runtime."""
        with self._lock:
            self.fault_interval_sec = max(1.0, float(seconds))
            self.last_fault_time = time.time()  # Đếm lại chu kỳ ngay từ lúc đổi tần suất
            print(f"⏱️ [{self.machine_id}] Đã chỉnh chu kỳ sinh lỗi thành: {self.fault_interval_sec} giây")

    def maybe_trigger_random_fault(self) -> Optional[str]:
        """Tự động phát sinh 1 sự cố ngẫu nhiên đúng theo chu kỳ fault_interval_sec."""
        if not self.fault_auto_enabled or not self.active_faults:
            return None

        now = time.time()
        elapsed = now - self.last_fault_time

        # Chỉ sinh lỗi nếu:
        # 1. Đã đủ thời gian giãn cách (ví dụ 30 giây kể từ lần lỗi trước)
        # 2. Máy hiện tại chưa bị dính lỗi nào chưa sửa
        if elapsed >= self.fault_interval_sec and not self.has_any_fault():
            chosen_fault = random.choice(list(self.active_faults.keys()))
            self.active_faults[chosen_fault] = True
            self.last_fault_time = now  # Reset mốc thời gian đếm tiếp
            print(f"💥 [TỰ PHÁT SINH LỖI] Máy {self.machine_id} vừa gặp: {chosen_fault} (sau {round(elapsed, 1)}s)!")
            return chosen_fault

        return None

    def inject_fault(self, fault_name: str) -> bool:
        """Kích hoạt thủ công 1 lỗi."""
        with self._lock:
            if fault_name in self.active_faults:
                self.active_faults[fault_name] = True
                self.last_fault_time = time.time()
                print(f"🔥 [{self.machine_id}] Đã kích hoạt lỗi: {fault_name}")
                return True
            return False

    def clear_fault(self, fault_name: str) -> bool:
        """Tắt cờ lỗi (khi kỹ sư hoặc PLC sửa xong) và đặt lại mốc thời gian đếm chu kỳ tiếp theo."""
        with self._lock:
            if fault_name in self.active_faults:
                self.active_faults[fault_name] = False
                self.last_fault_time = time.time()  # Bắt đầu đếm lại 30s sau khi lỗi cũ được sửa
                print(f"🔧 [{self.machine_id}] Đã sửa xong {fault_name}. Bộ đếm chu kỳ được đặt lại.")
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