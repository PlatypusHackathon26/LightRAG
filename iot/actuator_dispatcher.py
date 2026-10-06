from __future__ import annotations

from typing import Any, Dict, Optional


class ActuatorDispatcher:
    """Outbound side of the edge gateway: map decisions to PLC actions."""

    def __init__(self, machine_registry: Optional[Any] = None) -> None:
        self.machine_registry = machine_registry if machine_registry is not None else {}

    def dispatch(self, machine_id: str, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        machine = self.machine_registry.get(machine_id)
        if machine is None:
            return {"status": "unknown_machine", "machine_id": machine_id, "action": action}
        command = self._map_action(action)
        result = machine.receive_plc_command(command, payload or {})
        return {
            "status": "dispatched",
            "machine_id": machine_id,
            "action": action,
            "plc_command": command,
            "result": result,
        }

    def _map_action(self, action: str) -> str:
        mapping = {
            "feed_hold": "FEED_HOLD",
            "safe_home": "SAFE_HOME",
            "reduce_speed": "REDUCE_SPEED_70",
            "quality_hold": "QUALITY_HOLD",
            "shutdown": "EMERGENCY_STOP",
            "battery_charge": "ROUTE_TO_CHARGER",
        }
        return mapping.get(action, action.upper())
