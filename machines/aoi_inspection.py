from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines.base_machine import BaseMachine


class AoiInspection(BaseMachine):
    def __init__(self, event_hub: Optional[object] = None) -> None:
        super().__init__(
            machine_id="AOI-INSPECT-02",
            machine_type="AOI_INSPECTION",
            model="KOH_YOUNG_ZENITH_ALPHA",
            location="Cell-04",
            event_hub=event_hub,
        )

    def generate_telemetry(self) -> Dict[str, Any]:
        false_reject = 1.3 + random.uniform(-0.5, 2.5)
        light_current = 65 + random.uniform(-10, 16)
        inspection_duration = 1300 + random.uniform(-120, 420)
        return {
            "False_Reject_Ratio_pct": round(false_reject, 2),
            "Camera_Light_Current_mA": round(light_current, 2),
            "Inspection_Duration_ms": round(inspection_duration, 2),
            "Defect_Missing_Rate_pct": 1.4 + random.uniform(-0.2, 1.6),
        }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        if telemetry.get("False_Reject_Ratio_pct", 0) > 4:
            return "false reject spike"
        if telemetry.get("Camera_Light_Current_mA", 0) > 78:
            return "lighting overcurrent"
        return None
