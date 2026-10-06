from __future__ import annotations

from typing import Any, Dict, List, Optional


class TelemetryReceiver:
    """Inbound side of the edge gateway: collect, filter, and forward alerts."""

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        self.event_hub = event_hub
        self.alerts: List[Dict[str, Any]] = []
        self.filtered_events: List[Dict[str, Any]] = []

    def process(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not event:
            return None
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        if event_type == "telemetry":
            if self._is_threshold_violation(payload):
                filtered = {**event, "priority": "high"}
                self.filtered_events.append(filtered)
                self.alerts.append(filtered)
                if self.event_hub is not None:
                    self.event_hub.publish(filtered)
                return filtered
        return None

    def _is_threshold_violation(self, payload: Dict[str, Any]) -> bool:
        for key, value in payload.items():
            key_name = key.lower()
            if isinstance(value, (int, float)):
                if "temp" in key_name and value > 85:
                    return True
                if "vibration" in key_name and value > 7:
                    return True
                if "pressure" in key_name and (value < 80 or value > 140):
                    return True
                if "current" in key_name and value > 40:
                    return True
                if "false_reject" in key_name and value > 4:
                    return True
                if "battery" in key_name and value < 20:
                    return True
        return False
