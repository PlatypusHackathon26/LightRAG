from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines.base_machine import BaseMachine


class CncMilling(BaseMachine):
    def __init__(self, event_hub: Optional[object] = None) -> None:
        super().__init__(
            machine_id="MC-MILL-01",
            machine_type="CNC_MILLING",
            model="DMG_MORI_NVX_5080",
            location="Cell-01",
            event_hub=event_hub,
        )

    def generate_telemetry(self) -> Dict[str, Any]:
        spindle_temp = 72 + random.uniform(-6, 12)
        vibration = 3.5 + random.uniform(-0.8, 2.2)
        coolant_pressure = 18 + random.uniform(-6, 9)
        return {
            "Spindle_Temp_C": round(spindle_temp, 2),
            "Vibration_RMS_mm_s": round(vibration, 2),
            "Coolant_Pressure_Bar": round(coolant_pressure, 2),
            "Tool_Life_Remaining_Minutes": max(0, 120 - random.uniform(0, 22)),
        }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        if telemetry.get("Spindle_Temp_C", 0) > 88:
            return "spindle thermal overload"
        if telemetry.get("Vibration_RMS_mm_s", 0) > 7.5:
            return "vibration anomaly"
        if telemetry.get("Coolant_Pressure_Bar", 0) < 8:
            return "coolant pressure deviation"
        return None
