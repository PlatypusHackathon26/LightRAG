from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Iterable, Optional


class DashboardState:
    """Thread-safe snapshot of simulator events for the browser dashboard."""

    def __init__(self, alert_limit: int = 30, history_limit: int = 30) -> None:
        self._lock = threading.RLock()
        self._machines: Dict[str, Dict[str, Any]] = {}
        self._alerts: Deque[Dict[str, Any]] = deque(maxlen=alert_limit)
        self._history_limit = history_limit

    def register_machines(self, machines: Iterable[Any]) -> None:
        with self._lock:
            for machine in machines:
                self._machines[machine.machine_id] = {
                    "machine_id": machine.machine_id,
                    "machine_type": machine.machine_type,
                    "model": machine.model,
                    "location": machine.location,
                    "status": "starting",
                    "telemetry": {},
                    "history": {},
                    "last_updated": None,
                    "last_alert": None,
                    "last_agent_result": None,
                }

    def handle_event(self, event: Dict[str, Any]) -> None:
        machine_id = event.get("machine_id")
        if not machine_id:
            return

        timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
        event_type = event.get("event_type")
        payload = event.get("payload") or {}

        with self._lock:
            machine = self._machines.get(machine_id)
            if machine is None:
                return

            machine["last_updated"] = timestamp
            if event_type == "connection":
                machine["status"] = payload.get("status", "online")
            elif event_type == "telemetry":
                machine["status"] = "online"
                machine["telemetry"] = dict(payload)
                for key, value in payload.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        points = machine["history"].setdefault(key, deque(maxlen=self._history_limit))
                        points.append(value)
            elif event_type == "alert":
                alert = {
                    "timestamp": timestamp,
                    "machine_id": machine_id,
                    "issue": payload.get("issue", "Unknown alert"),
                    "telemetry": dict(payload.get("telemetry") or {}),
                    "agent_result": None,
                }
                machine["status"] = "alert"
                machine["last_alert"] = alert["issue"]
                machine["last_agent_result"] = None
                self._alerts.appendleft(alert)

    def record_agent_result(self, machine_id: str, result: Dict[str, Any]) -> None:
        with self._lock:
            machine = self._machines.get(machine_id)
            if machine is None:
                return
            machine["last_agent_result"] = dict(result)
            for alert in self._alerts:
                if alert["machine_id"] == machine_id and alert["agent_result"] is None:
                    alert["agent_result"] = dict(result)
                    break

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            machines = []
            for machine in self._machines.values():
                item = dict(machine)
                item["telemetry"] = dict(machine["telemetry"])
                item["history"] = {key: list(values) for key, values in machine["history"].items()}
                item["last_agent_result"] = (
                    dict(machine["last_agent_result"]) if machine["last_agent_result"] else None
                )
                machines.append(item)

            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "machines": machines,
                "alerts": [dict(alert) for alert in self._alerts],
            }
