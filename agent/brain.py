from __future__ import annotations

from typing import Any, Dict, List

from .knowledge_base import KnowledgeBase


class AgentBrain:
    """Rule-based reasoning layer (mock LLM / mock RAG logic)."""

    def __init__(self, tools: Any | None = None, knowledge_base: KnowledgeBase | None = None) -> None:
        self.tools = tools
        self.knowledge_base = knowledge_base or KnowledgeBase()

    def handle_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        machine_id = alert.get("machine_id", "unknown")
        issue = alert.get("payload", {}).get("issue", "unknown")
        telemetry = alert.get("payload", {}).get("telemetry", {})

        diagnosis = self.knowledge_base.query(issue)
        recommendations = self._recommend_actions(issue, telemetry)

        if self.tools is not None:
            self.tools.create_ticket(machine_id, f"Maintenance alert: {issue}", priority="high")
            self.tools.send_notification(machine_id, diagnosis)

        return {
            "machine_id": machine_id,
            "issue": issue,
            "diagnosis": diagnosis,
            "recommendations": recommendations,
        }

    def _recommend_actions(self, issue: str, telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
        normalized = issue.lower()
        if "thermal" in normalized or "temperature" in normalized:
            return [{"action": "feed_hold", "payload": {"reason": issue, "temp": telemetry.get("Spindle_Temp_C") or telemetry.get("Barrel_Zone_Temp_C")}}]
        if "vibration" in normalized or "overload" in normalized:
            return [{"action": "safe_home", "payload": {"reason": issue, "vibration": telemetry.get("Vibration_RMS_mm_s") or telemetry.get("Motor_Current_A")}}]
        if "pressure" in normalized:
            return [{"action": "quality_hold", "payload": {"reason": issue, "pressure": telemetry.get("Injection_Peak_Pressure_MPa")}}]
        if "battery" in normalized:
            return [{"action": "battery_charge", "payload": {"reason": issue, "battery": telemetry.get("Battery_SOC_pct")}}]
        return [{"action": "reduce_speed", "payload": {"reason": issue, "telemetry": telemetry}}]
