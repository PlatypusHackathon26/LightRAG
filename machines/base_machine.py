from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class BaseMachine:
    """Base class for manufacturing devices in the edge simulator."""

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
        self.state = "idle"
        self.connected = False
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._last_telemetry: Dict[str, Any] = {}

    def connect(self) -> Dict[str, Any]:
        with self._lock:
            self.connected = True
            self.state = "online"
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

    def run(self, interval: float = 1.0, iterations: Optional[int] = None) -> None:
        self.connect()
        count = 0
        while not self._stop_event.is_set():
            telemetry = self.generate_telemetry()
            self._last_telemetry = telemetry
            self.emit_event("telemetry", telemetry, priority="info")
            anomaly = self.detect_anomaly(telemetry)
            if anomaly:
                self.state = "alert"
                self.emit_event("alert", {"issue": anomaly, "telemetry": telemetry}, priority="warning")
            count += 1
            if iterations is not None and count >= iterations:
                break
            time.sleep(interval)

    def stop(self) -> None:
        self._stop_event.set()
        self.disconnect()

    def as_json(self, data: Dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.machine_id}, type={self.machine_type})"
