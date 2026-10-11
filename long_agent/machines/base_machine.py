from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from machines import commands as cmd
from machines.commands import CommandSpec
from machines.specifications import MACHINE_METRICS


class BaseMachine:
    """Lớp cơ sở chuẩn hóa cho các thiết bị cạnh trong mô phỏng nhà máy thông minh.

    Rules for subclasses:
    - declare MACHINE_TYPE and command_specs(); a command exists only if it is declared there;
    - call self._tick() at the start of generate_telemetry() for dt (it also finishes repairs and starts);
    - drive physics from self.state and the actuators, never from fault flags alone: a fault's symptoms
      appear only while the part it affects operates;
    - a repair (on_repaired) may change the root cause (a new tool, a new battery module) but never a
      symptom (temperature, pressure, vibration): those recover through the physics after START.
    """

    MACHINE_TYPE = ""
    start_duration_s = 5.0

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
        self.state = cmd.RUNNING
        self.connected = False
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._last_telemetry: Dict[str, Any] = {}

        self.active_faults: Dict[str, bool] = {}
        self.commands: Dict[str, CommandSpec] = self.command_specs()
        self.last_update_time = time.time()
        self._maintenance: Optional[Tuple[str, float]] = (
            None  # (repair command, finishes at)
        )
        self._starting_since = 0.0
        self.last_repair: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ commands
    @classmethod
    def command_specs(cls) -> Dict[str, CommandSpec]:
        return cmd.control_commands()

    def on_command(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        """Actuator side effects of a control or setpoint command. Returns a detail line."""
        return None

    def on_repaired(self, name: str) -> None:
        """Root-cause changes when a repair finishes (the fault flag is cleared by the base)."""

    def at_rest(self) -> bool:
        """True once moving parts have stopped; LOCKOUT is refused before."""
        return True

    def start_blocker(self) -> Optional[str]:
        """A reason START must be refused (an interlock), or None."""
        return None

    def ready_to_run(self) -> bool:
        """STARTING becomes RUNNING once this holds and start_duration_s has passed."""
        return True

    def command_precondition(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        """A machine-specific reason to refuse a command in its allowed state, or None."""
        return None

    @property
    def powered(self) -> bool:
        return self.state in cmd.POWERED

    @property
    def running(self) -> bool:
        return self.state == cmd.RUNNING

    def _tick(self) -> float:
        """Advance the clock: returns dt and completes a finished repair or start-up."""
        now = time.time()
        dt = max(0.1, min(now - self.last_update_time, 2.5))
        self.last_update_time = now
        self._advance(now)
        return dt

    def _advance(self, now: float) -> None:
        if (
            self.state == cmd.MAINTENANCE
            and self._maintenance
            and now >= self._maintenance[1]
        ):
            name = self._maintenance[0]
            spec = self.commands[name]
            fixed = bool(spec.fixes and self.active_faults.get(spec.fixes))
            if spec.fixes:
                self.active_faults[spec.fixes] = False
            self.on_repaired(name)
            self._maintenance = None
            self.state = spec.return_state
            self.last_repair = {
                "command": name,
                "fault": spec.fixes,
                "fault_was_present": fixed,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        if (
            self.state == cmd.STARTING
            and now - self._starting_since >= self.start_duration_s
            and self.ready_to_run()
        ):
            self.state = cmd.RUNNING

    def maintenance_remaining_s(self) -> float:
        if self.state != cmd.MAINTENANCE or not self._maintenance:
            return 0.0
        return max(0.0, self._maintenance[1] - time.time())

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run a declared command if the machine's state allows it. Never raises for a bad request:
        the result says REJECTED and why."""
        with self._lock:
            now = time.time()
            self._advance(now)
            name = cmd.normalize_command(command, self.commands)
            if name is None:
                return self._command_result(
                    str(command),
                    "REJECTED",
                    f"Máy {self.machine_id} không có lệnh '{command}'.",
                )
            spec = self.commands[name]
            try:
                params = cmd.validate_params(spec, payload)
            except ValueError as exc:
                return self._command_result(name, "REJECTED", str(exc))
            if self.state not in spec.allowed_states:
                return self._command_result(
                    name,
                    "REJECTED",
                    f"{name} chỉ chạy khi máy ở {', '.join(sorted(spec.allowed_states))}; hiện tại {self.state}.",
                )
            blocker = self._precondition(name, params)
            if blocker:  # a condition that time can change (still moving, still hot): worth retrying
                return self._command_result(name, "REJECTED", blocker, retryable=True)

            if spec.kind == "repair":
                self._maintenance = (name, now + spec.duration_s)
                self.state = cmd.MAINTENANCE
                return self._command_result(
                    name,
                    "OK",
                    f"Bắt đầu: {spec.desc_vi} (khoảng {spec.duration_s:.0f} s).",
                )
            detail = self.on_command(name, params)
            if spec.next_state:
                self.state = spec.next_state
            if name == "START":
                self._starting_since = now
            return self._command_result(name, "OK", detail or spec.desc_vi)

    def _precondition(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        if name == "LOCKOUT" and not self.at_rest():
            return "Máy chưa dừng hẳn; chờ các bộ phận chuyển động đứng yên rồi mới khoá an toàn."
        if name == "START":
            blocker = self.start_blocker()
            if blocker:
                return f"Liên động khởi động: {blocker}"
        return self.command_precondition(name, params)

    def _command_result(
        self, command: str, status: str, detail: str, retryable: bool = False
    ) -> Dict[str, Any]:
        return self._build_event(
            "plc_command_executed",
            {
                "machine_id": self.machine_id,
                "command": command,
                "status": status,
                "retryable": retryable,
                "execution_detail": detail,
                "current_state": self.state,
                "maintenance_remaining_s": round(self.maintenance_remaining_s(), 1),
                "active_faults": self.get_active_faults(),
            },
        )

    def nominal(self, key: str) -> float:
        return next(
            m["nominal"] for m in MACHINE_METRICS[self.machine_type] if m["key"] == key
        )

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
        """Tester control: replace the fault selection atomically; preserve physical state for recovery.
        Removing a fault here is the simulator's reset, not a repair - repairs go through commands."""
        with self._lock:
            if not isinstance(faults, list) or any(
                not isinstance(f, str) for f in faults
            ):
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

    def _build_event(
        self, event_type: str, payload: Dict[str, Any], priority: str = "info"
    ) -> Dict[str, Any]:
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

    def emit_event(
        self, event_type: str, payload: Dict[str, Any], priority: str = "info"
    ) -> Dict[str, Any]:
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
        return (
            f"{self.__class__.__name__}(id={self.machine_id}, type={self.machine_type})"
        )
