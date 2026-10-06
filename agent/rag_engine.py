from __future__ import annotations

from typing import Any, Dict, Optional


class RagEngine:
    """Lightweight knowledge retrieval mock. Real RAG would integrate a vector store."""

    def __init__(self, knowledge_base: Optional[Dict[str, str]] = None) -> None:
        self.knowledge_base = knowledge_base or {
            "thermal overload": "Check cooling system, review lubricant flow, and inspect spindle bearings for heat accumulation.",
            "vibration anomaly": "Compare vibration RMS against baseline values and inspect tool wear or mechanical imbalance.",
            "pressure deviation": "Review injection pressure stability, verify barrel temperature consistency, and inspect mold sealing.",
            "robot overload": "Inspect servo current, verify joint alignment, and check for mechanical friction or unexpected payload.",
        }

    def query(self, issue: str, telemetry: Optional[Dict[str, Any]] = None) -> Optional[str]:
        normalized = issue.lower()
        for keyword, knowledge in self.knowledge_base.items():
            if keyword in normalized:
                return knowledge
        if telemetry:
            for key, value in telemetry.items():
                if "temp" in key.lower() and isinstance(value, (int, float)) and value > 85:
                    return "Temperature is elevated above normal operating conditions. Inspect cooling and lubrication before resuming production."
                if "vibration" in key.lower() and isinstance(value, (int, float)) and value > 8:
                    return "Vibration exceeds the machine safety threshold. Validate tool wear and mechanical balance immediately."
        return None
