from __future__ import annotations

import random
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class RobotArm(BaseMachine):
    """Mô phỏng cánh tay Robot công nghiệp 6 bậc chuẩn OPC UA Robotics (Model: DENSO VS-068).

    Mô phỏng dòng điện servo khớp (Joint Currents), tải trọng cổ tay (Wrist Payload),
    va chạm và nhiệt độ cuộn cảm stator.
    """

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-ROBOT-01",
            machine_type="ROBOT_ARM",
            model="DENSO_VS_068",
            location="Cell-01_Handling",
            event_hub=event_hub,
        )

        # Trạng thái điều khiển servo
        self.state = "RUNNING"  # RUNNING, PAUSED, COLLISION_STOP, E_STOP
        self.speed_override_pct = 100.0  # Tốc độ quỹ đạo vận hành
        self.payload_kg = 3.2  # Tải gắp phôi hiện tại (Max 7.0 kg)

        # Động học khớp 3 (Joint 3 - Khớp chịu mô-men uốn và gia tốc lớn nhất)
        self.joint_3_current_a = 9.5  # Dòng điện pha động cơ định danh (Amps)
        self.joint_3_temp_c = 48.0  # Nhiệt độ cuộn dây servo (°C)
        self.joint_1_current_a = 6.2
        self.ambient_temp_c = 28.0

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            if self.state == "RUNNING":
                # 1. Dòng điện Joint 3 = f(Speed Override, Payload, Gravity Torque)
                speed_ratio = self.speed_override_pct / 100.0
                dynamic_load = (self.payload_kg / 7.0) * 5.0
                base_current = 7.0 * speed_ratio + dynamic_load
                self.joint_3_current_a = base_current + random.uniform(-0.8, 1.2)

                # 2. Nhiệt độ động cơ khớp = Hiệu ứng Joule (I^2 * R)
                heat_generated = ((self.joint_3_current_a / 12.0) ** 2) * 1.1
                heat_dissipated = 0.55
                self.joint_3_temp_c += (heat_generated - heat_dissipated) + random.uniform(-0.1, 0.15)
                self.joint_3_temp_c = max(self.ambient_temp_c, min(105.0, self.joint_3_temp_c))

                self.joint_1_current_a = 5.0 * speed_ratio + random.uniform(-0.4, 0.4)
            else:
                self.joint_3_current_a = 0.6 + random.uniform(-0.1, 0.1)  # Dòng giữ phanh servo
                self.joint_1_current_a = 0.4
                self.joint_3_temp_c = max(self.ambient_temp_c, self.joint_3_temp_c - 0.4)

            return {
                "Controller_Execution": self.state,
                "Joint_3_Current_A": round(max(0.0, self.joint_3_current_a), 2),
                "Joint_1_Current_A": round(max(0.0, self.joint_1_current_a), 2),
                "Motor_Temp_C": round(self.joint_3_temp_c, 2),
                "Payload_Kg": round(self.payload_kg, 2),
                "Speed_Override_Pct": self.speed_override_pct,
                "Safety_Guard_Interlock": True,
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        j3_amp = telemetry.get("Joint_3_Current_A", 0)
        motor_t = telemetry.get("Motor_Temp_C", 0)
        if j3_amp > 18.0:
            return "joint 3 servo overcurrent (mechanical resistance/collision)"
        if motor_t > 75.0:
            return "servo motor thermal overload"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""
            if command == "PAUSE_MOTION":
                self.state = "PAUSED"
                self.speed_override_pct = 0.0
                detail = "Robot trajectory motion suspended. Servo position locks engaged."

            elif command == "ADJUST_JOINT_SPEED":
                factor = float(payload.get("speed_factor", 0.5))
                self.speed_override_pct = factor * 100.0
                detail = f"Trajectory velocity scaled down to {self.speed_override_pct}%."

            elif command == "RESET_TRAJECTORY":
                self.state = "RUNNING"
                self.speed_override_pct = 50.0
                self.payload_kg = 0.0  # Nhả kẹp phôi
                detail = "Manipulator homed to safe origin position; gripper released."

            elif command == "EMERGENCY_STOP":
                self.state = "COLLISION_STOP"
                self.speed_override_pct = 0.0
                self.joint_3_current_a = 0.0
                detail = "Category 0 E-Stop activated: Dynamic braking engaged and 24V servo bus dropped."

            elif command == "RESUME":
                self.state = "RUNNING"
                self.speed_override_pct = 100.0
                detail = "Robot resumed automated handling cycle at normal velocity."

            else:
                detail = f"Command {command} rejected by Denso RC8A controller."

            return self._build_event(
                "plc_command_executed",
                {
                    "machine_id": self.machine_id,
                    "command": command,
                    "execution_detail": detail,
                    "current_state": self.state,
                },
                priority="info",
            )