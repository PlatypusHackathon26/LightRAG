from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines.base_machine import BaseMachine


class InjectionMolding(BaseMachine):
    def __init__(self, event_hub: Optional[object] = None) -> None:
        super().__init__(
            machine_id="IM-PRESS-04",
            machine_type="INJECTION_MOLDING",
            model="FANUC_ROBOSHOT_S100IA",
            location="Cell-03",
            event_hub=event_hub,
        )

    def generate_telemetry(self) -> Dict[str, Any]:
        barrel_temp = 200 + random.uniform(-14, 18)
        injection_pressure = 120 + random.uniform(-16, 30)
        mold_temp = 62 + random.uniform(-10, 12)
        return {
            "Barrel_Zone_Temp_C": round(barrel_temp, 2),
            "Injection_Peak_Pressure_MPa": round(injection_pressure, 2),
            "Mold_Temp_C": round(mold_temp, 2),
            "Clamping_Force_kN": 450 + random.uniform(-32, 55),
        }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        if telemetry.get("Injection_Peak_Pressure_MPa", 0) > 140 or telemetry.get("Injection_Peak_Pressure_MPa", 0) < 80:
            return "pressure deviation"
        if telemetry.get("Barrel_Zone_Temp_C", 0) < 170 or telemetry.get("Barrel_Zone_Temp_C", 0) > 230:
            return "thermal instability"
        return None
