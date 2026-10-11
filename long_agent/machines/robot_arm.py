from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines import commands as cmd
from machines.base_machine import BaseMachine
from machines.commands import CommandSpec, ParamSpec


class RobotArm(BaseMachine):
    """Mô phỏng cánh tay Robot công nghiệp 6 trục (Model: DENSO VS-068)."""

    MACHINE_TYPE = "ROBOT_ARM"
    CRITICAL_MOTOR_TEMP_C = 80.0

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-ROBOT-01",
            machine_type="ROBOT_ARM",
            model="DENSO_VS_068",
            location="Cell-01_Handling",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
        self.speed_override_pct = 100.0
        self.payload_kg = self.nominal("Payload_Kg")
        self.overload_payload_kg = 12.0   # Phôi quá tải: khối lượng gắp vượt định mức
        self.overload_gripper_bar = 8.0   # Tăng lực kẹp để giữ phôi nặng

        # 2. Trạng thái vật lý
        self.joint_3_current_a = self.nominal("Joint_3_Current_A")
        self.joint_3_temp_c = self.nominal("Motor_Temp_C")
        self.actual_gripper_pressure_bar = self.nominal("Gripper_Pressure_Bar")
        self.ambient_temp_c = 26.0
        # Exact nominal equilibrium: I=9.25 A, T=40 C.
        self.motor_cooling_coeff = ((9.25 / 10.0) ** 2) * 1.5 / (40.0 - 26.0)

        # 3. Khai báo danh mục lỗi
        self.active_faults = {
            "GEARBOX_LACK_OF_GREASE": False,  # Khô mỡ hộp số giảm tốc khớp 3
            "GRIPPER_PNEUMATIC_LEAK": False,  # Xì khí nén kẹp phôi
            "PAYLOAD_OVERLOAD": False,        # Quá tải trọng gắp
        }

    @classmethod
    def command_specs(cls) -> Dict[str, CommandSpec]:
        specs = cmd.control_commands(hold_aliases=("PAUSE_MOTION",),
                                     hold_desc="Dừng quỹ đạo, servo giữ phanh tại chỗ")
        for spec in (
            cmd.repair("REFILL_GEARBOX_GREASE", "GEARBOX_LACK_OF_GREASE", "Bơm mỡ hộp số giảm tốc khớp 3", 40,
                       ("GREASE_GEARBOX", "LUBRICATE_GEARBOX", "REFILL_JOINT_GREASE")),
            cmd.repair("REPAIR_PNEUMATIC_SYSTEM", "GRIPPER_PNEUMATIC_LEAK", "Thay gioăng / ống khí nén tay gắp", 30,
                       ("REPAIR_GRIPPER_LEAK", "FIX_PNEUMATIC_LEAK", "REPLACE_PNEUMATIC_SEAL")),
            cmd.repair("RESET_PAYLOAD", "PAYLOAD_OVERLOAD", "Gỡ phôi quá tải, nạp lại phôi đúng định mức 3.5 kg", 20,
                       ("REMOVE_OVERLOAD", "CLEAR_PAYLOAD_OVERLOAD")),
            CommandSpec("SET_SPEED_OVERRIDE", "setpoint", "Đặt tỉ lệ tốc độ di chuyển cánh tay",
                        frozenset({cmd.RUNNING, cmd.HOLD, cmd.STOPPED}), risk="LOW",
                        params={"speed_pct": ParamSpec("float", 0, 100, 50.0, "% tốc độ")},
                        aliases=("SPEED_OVERRIDE",)),
        ):
            specs[spec.name] = spec
        return specs

    def on_command(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        if name == "SET_SPEED_OVERRIDE":
            self.speed_override_pct = params["speed_pct"]
            return f"Đã đặt tốc độ cánh tay {self.speed_override_pct:g}%."
        return None

    def at_rest(self) -> bool:
        return self.joint_3_current_a < 1.0

    def start_blocker(self) -> Optional[str]:
        if self.joint_3_temp_c > self.CRITICAL_MOTOR_TEMP_C:
            return f"nhiệt động cơ khớp {self.joint_3_temp_c:.1f}°C > {self.CRITICAL_MOTOR_TEMP_C:.0f}°C, chờ nguội"
        return None

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            dt = self._tick()
            moving = self.running
            speed = self.speed_override_pct / 100.0

            # --- TẢI TRỌNG GẮP: khối lượng thật của phôi; số đo cân (payload_kg) hội tụ dần ---
            part_mass_kg = (
                self.overload_payload_kg if self.active_faults["PAYLOAD_OVERLOAD"] else self.nominal("Payload_Kg")
            )
            self.payload_kg = self.ramp(self.payload_kg, part_mass_kg, dt, 2.0)

            # --- DÒNG ĐIỆN SERVO KHỚP 3: chỉ kéo tải khi chuyển động; tạm dừng/khởi động giữ phanh 2 A ---
            if moving:
                target_j3 = 5.0 * speed + (part_mass_kg / 7.0) * 4.5 + 2.0   # the motor feels the real mass
                if self.active_faults["GEARBOX_LACK_OF_GREASE"]:
                    target_j3 += 8.5 * speed   # ma sát khô bánh răng tỉ lệ với chuyển động
            elif self.state in (cmd.HOLD, cmd.STARTING):
                target_j3 = 2.0
            else:
                target_j3 = 0.0
            self.joint_3_current_a = self.approach(self.joint_3_current_a, target_j3, dt, 4.0)

            # --- CÂN BẰNG NHIỆT KHỚP (JOULE) ---
            if self.joint_3_current_a > 1.0:
                heat_in = ((self.joint_3_current_a / 10.0) ** 2) * 1.5
                if moving and self.active_faults["GEARBOX_LACK_OF_GREASE"]:
                    heat_in += 4.0 * speed
                if moving and self.active_faults["PAYLOAD_OVERLOAD"]:
                    heat_in += 1.5
                self.joint_3_temp_c = self.approach(
                    self.joint_3_temp_c, self.ambient_temp_c + heat_in / self.motor_cooling_coeff,
                    dt, 1.0 / self.motor_cooling_coeff,
                )
            else:
                cooling = (self.joint_3_temp_c - self.ambient_temp_c) * 0.08 * dt
                self.joint_3_temp_c = max(self.ambient_temp_c, self.joint_3_temp_c - cooling)
            self.joint_3_temp_c = max(self.ambient_temp_c, min(140.0, self.joint_3_temp_c))

            # --- ÁP SUẤT TAY GẮP: cấp khí khi máy có nguồn; dừng/khoá an toàn thì xả khí ---
            if self.powered:
                if self.active_faults["GRIPPER_PNEUMATIC_LEAK"]:
                    self.actual_gripper_pressure_bar = max(0.8, self.actual_gripper_pressure_bar - 1.2 * dt)
                else:
                    grip_target = self.overload_gripper_bar if self.active_faults["PAYLOAD_OVERLOAD"] else 6.0
                    self.actual_gripper_pressure_bar = self.ramp(self.actual_gripper_pressure_bar, grip_target, dt, 1.2)
            else:
                self.actual_gripper_pressure_bar = max(0.0, self.actual_gripper_pressure_bar - 1.2 * dt)

            noise_j3 = random.uniform(-0.05, 0.05) if self.joint_3_current_a > 0.2 else 0.0
            noise_temp = random.uniform(-0.04, 0.04)
            noise_grip = random.uniform(-0.08, 0.08) if self.actual_gripper_pressure_bar > 0.2 else 0.0

            return {
                "Controller_Execution": self.state,
                "Joint_3_Current_A": round(max(0.0, self.joint_3_current_a + noise_j3), 2),
                "Motor_Temp_C": round(max(self.ambient_temp_c, self.joint_3_temp_c + noise_temp), 2),
                "Gripper_Pressure_Bar": round(max(0.0, self.actual_gripper_pressure_bar + noise_grip), 2),
                "Payload_Kg": round(self.payload_kg, 2),
                "Speed_Override_Pct": self.speed_override_pct,
                "Simulated_Active_Faults": self.get_active_faults(),
            }
