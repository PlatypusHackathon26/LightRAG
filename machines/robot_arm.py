from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class RobotArm(BaseMachine):
    """Mô phỏng cánh tay Robot công nghiệp 6 trục (Model: DENSO VS-068)."""

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-ROBOT-01",
            machine_type="ROBOT_ARM",
            model="DENSO_VS_068",
            location="Cell-01_Handling",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
        self.state = "RUNNING"
        self.speed_override_pct = 100.0
        self.servo_power_enabled = True
        self.gripper_command = "CLAMP"
        self.payload_kg = 3.5

        # 2. Trạng thái vật lý
        self.joint_3_current_a = self.nominal("Joint_3_Current_A")
        self.joint_3_temp_c = self.nominal("Motor_Temp_C")
        self.actual_gripper_pressure_bar = self.nominal("Gripper_Pressure_Bar")
        self.ambient_temp_c = 26.0
        # Exact nominal equilibrium: I=9.25 A, T=40 C.
        self.motor_cooling_coeff = ((9.25 / 10.0) ** 2) * 1.5 / (40.0 - 26.0)
        self.last_update_time = time.time()

        # 3. Khai báo danh mục lỗi
        self.active_faults = {
            "GEARBOX_LACK_OF_GREASE": False,  # Khô mỡ hộp số giảm tốc khớp 3
            "GRIPPER_PNEUMATIC_LEAK": False,  # Xì khí nén kẹp phôi
            "PAYLOAD_OVERLOAD": False,        # Quá tải trọng gắp
        }

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            current_time = time.time()
            dt = max(0.1, min(current_time - self.last_update_time, 2.5))
            self.last_update_time = current_time

            # --- DÒNG ĐIỆN SERVO KHỚP 3 ---
            if self.state == "RUNNING" and self.servo_power_enabled:
                base_target_j3 = 5.0 * (self.speed_override_pct / 100.0) + (self.payload_kg / 7.0) * 4.5 + 2.0
                if self.active_faults["GEARBOX_LACK_OF_GREASE"]:
                    base_target_j3 += 8.5  # Ma sát khô bánh răng làm động cơ kéo dòng lớn
                if self.active_faults["PAYLOAD_OVERLOAD"]:
                    base_target_j3 += 5.5
                target_j3 = base_target_j3
            elif self.state == "PAUSED":
                target_j3 = 2.0
            else:
                target_j3 = 0.0

            self.joint_3_current_a = self.approach(self.joint_3_current_a, target_j3, dt, 4.0)

            # --- CÂN BẰNG NHIỆT KHỚP (JOULE THERMAL DYNAMICS) ---
            if self.joint_3_current_a > 1.0:
                heat_in = ((self.joint_3_current_a / 10.0) ** 2) * 1.5
                if self.active_faults["GEARBOX_LACK_OF_GREASE"]:
                    heat_in += 4.0
                if self.active_faults["PAYLOAD_OVERLOAD"]:
                    heat_in += 1.5  # Động cơ quá tải sinh nhiệt ngoài mô hình I²R
                # Hệ số danh nghĩa giữ nhiệt cân bằng ở 40°C khi dòng điện 9.25 A.
                self.joint_3_temp_c = self.approach(
                    self.joint_3_temp_c, self.ambient_temp_c + heat_in / self.motor_cooling_coeff,
                    dt, 1.0 / self.motor_cooling_coeff,
                )
            else:
                cooling = (self.joint_3_temp_c - self.ambient_temp_c) * 0.08 * dt
                self.joint_3_temp_c = max(self.ambient_temp_c, self.joint_3_temp_c - cooling)

            self.joint_3_temp_c = max(self.ambient_temp_c, min(140.0, self.joint_3_temp_c))

            # --- ÁP SUẤT TAY GẮP KHÍ NÉN ---
            if self.gripper_command == "CLAMP":
                if self.active_faults["GRIPPER_PNEUMATIC_LEAK"]:
                    self.actual_gripper_pressure_bar = max(0.8, self.actual_gripper_pressure_bar - 1.2 * dt)
                else:
                    self.actual_gripper_pressure_bar = self.ramp(
                        self.actual_gripper_pressure_bar, 6.0, dt, 1.2
                    )
            else:
                self.actual_gripper_pressure_bar = max(0.0, self.actual_gripper_pressure_bar - 8.0 * dt)

            noise_j3 = random.uniform(-0.05, 0.05)
            noise_temp = random.uniform(-0.04, 0.04)
            noise_grip = random.uniform(-0.08, 0.08)

            return {
                "Controller_Execution": self.state,
                "Joint_3_Current_A": round(max(0.0, self.joint_3_current_a + noise_j3), 2),
                "Motor_Temp_C": round(max(self.ambient_temp_c, self.joint_3_temp_c + noise_temp), 2),
                "Gripper_Pressure_Bar": round(max(0.0, self.actual_gripper_pressure_bar + noise_grip), 2),
                "Payload_Kg": round(self.payload_kg, 2),
                "Speed_Override_Pct": self.speed_override_pct,
                "Simulated_Active_Faults": self.get_active_faults(),
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        j3 = telemetry.get("Joint_3_Current_A", 0)
        temp = telemetry.get("Motor_Temp_C", 0)
        pressure = telemetry.get("Gripper_Pressure_Bar", 0)

        if j3 > 16.5:
            return "CRITICAL_SERVO_OVERCURRENT"
        if temp > 80.0:
            return "CRITICAL_SERVO_OVERHEAT"
        if self.gripper_command == "CLAMP" and pressure < 3.5 and self.state == "RUNNING":
            return "CRITICAL_GRIPPER_PRESSURE_LOSS"
        if temp > 65.0:
            return "WARNING_SERVO_ELEVATED_TEMPERATURE"
        if j3 > 12.5:
            return "WARNING_JOINT_HIGH_LOAD"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""

            if command == "REFILL_GEARBOX_GREASE":
                self.clear_fault("GEARBOX_LACK_OF_GREASE")
                detail = "Đã bơm mỡ bôi trơn chuyên dụng cho hộp số giảm tốc Khớp 3."

            elif command == "REPAIR_PNEUMATIC_SYSTEM":
                self.clear_fault("GRIPPER_PNEUMATIC_LEAK")
                detail = "Đã thay gioăng ống dẫn khí kẹp gắp, áp suất phục hồi 6 Bar."

            elif command == "RESET_PAYLOAD":
                self.clear_fault("PAYLOAD_OVERLOAD")
                self.payload_kg = 3.5
                detail = "Đã đưa tải trọng phôi về định mức danh nghĩa 3.5 kg."

            elif command == "PAUSE_MOTION":
                self.state = "PAUSED"
                self.speed_override_pct = 0.0
                detail = "Đã dừng quỹ đạo di chuyển robot. Động cơ giữ phanh tại vị trí an toàn."

            elif command == "SET_SPEED_OVERRIDE":
                target_pct = float(payload.get("speed_pct", 50.0))
                self.speed_override_pct = max(0.0, min(100.0, target_pct))
                detail = f"Đã hạ tốc độ di chuyển cánh tay robot xuống {self.speed_override_pct}%."

            elif command == "RESUME":
                self.state = "RUNNING"
                self.servo_power_enabled = True
                self.speed_override_pct = 100.0
                detail = "Khôi phục chu trình gắp đặt tự động bình thường."

            elif command == "EMERGENCY_STOP":
                self.state = "COLLISION_STOP"
                self.speed_override_pct = 0.0
                self.servo_power_enabled = False
                detail = "NGẮT KHẨN CẤP: Ngắt nguồn driver servo, khóa chốt phanh cơ học."

            else:
                detail = f"Lệnh '{command}' không được hỗ trợ bởi bộ điều khiển Denso RC8A."

            return self._build_event(
                "plc_command_executed",
                {
                    "machine_id": self.machine_id,
                    "command": command,
                    "execution_detail": detail,
                    "current_state": self.state,
                    "active_faults": self.get_active_faults(),
                },
                priority="info",
            )
