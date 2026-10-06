from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines.base_machine import BaseMachine


class AmrVehicle(BaseMachine):
    def __init__(self, event_hub: Optional[object] = None) -> None:
        super().__init__(
            machine_id="AMR-TRANS-03",
            machine_type="AMR_VEHICLE",
            model="MIR250",
            location="Logistics-Area",
            event_hub=event_hub,
        )

    def generate_telemetry(self) -> Dict[str, Any]:
        battery = 82 + random.uniform(-12, 10)
        speed = 1.2 + random.uniform(-0.4, 1.5)
        route_deviation = 0.5 + random.uniform(-0.2, 0.8)
        return {
            "Battery_SOC_pct": round(battery, 2),
            "Vehicle_Speed_m_s": round(speed, 2),
            "Route_Deviation_m": round(route_deviation, 2),
            "Docking_Alignment_mm": 8 + random.uniform(-3, 7),
        }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        if telemetry.get("Battery_SOC_pct", 0) < 20:
            return "battery low"
        if telemetry.get("Route_Deviation_m", 0) > 1.5:
            return "navigation drift"
        if telemetry.get("Docking_Alignment_mm", 0) > 12:
            return "docking alignment deviation"
        return None
