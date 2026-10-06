from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines.base_machine import BaseMachine


class RobotArm(BaseMachine):
    def __init__(self, event_hub: Optional[object] = None) -> None:
        super().__init__(
            machine_id="RB-ASSY-01",
            machine_type="ROBOT_ARM",
            model="DENSO_ROBODK",
            location="Cell-02",
            event_hub=event_hub,
        )

    def generate_telemetry(self) -> Dict[str, Any]:
        joint_temp = 50 + random.uniform(-8, 20)
        current_draw = 28 + random.uniform(-8, 18)
        pos_error = 0.8 + random.uniform(-0.2, 1.2)
        return {
            "Joint_Temp_J3_C": round(joint_temp, 2),
            "Motor_Current_A": round(current_draw, 2),
            "Pos_Error_mm": round(pos_error, 2),
            "Gripper_Vacuum_kPa": 90 + random.uniform(-10, 12),
        }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        if telemetry.get("Joint_Temp_J3_C", 0) > 82:
            return "robot overload"
        if telemetry.get("Pos_Error_mm", 0) > 2.5:
            return "position drift"
        if telemetry.get("Motor_Current_A", 0) > 40:
            return "motor overload"
        return None
