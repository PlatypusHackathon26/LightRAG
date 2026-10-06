from __future__ import annotations

from typing import Dict, List


class AgentTools:
    """Tools exposed to the mock agent for PLC, ticketing, and notifications."""

    def __init__(self) -> None:
        self.action_log: List[Dict[str, Any]] = []

    def create_ticket(self, machine_id: str, summary: str, priority: str = "medium") -> Dict[str, Any]:
        result = {
            "tool": "create_ticket",
            "machine_id": machine_id,
            "summary": summary,
            "priority": priority,
            "ticket_id": f"TKT-{machine_id}-{len(self.action_log) + 1}",
        }
        self.action_log.append(result)
        return result

    def send_notification(self, machine_id: str, message: str) -> Dict[str, Any]:
        result = {"tool": "send_notification", "machine_id": machine_id, "message": message}
        self.action_log.append(result)
        return result
