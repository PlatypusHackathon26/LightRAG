from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines.base_machine import BaseMachine


class CncMilling(BaseMachine):
    """Mô phỏng máy phay CNC chuẩn hóa dựa trên chuẩn MTConnect & OPC UA (Model: DMG MORI NVX 5080).

    Tích hợp mô hình phản hồi cơ - nhiệt (Thermal-Mechanical Feedback) và phản
    ứng với lệnh PLC.
    """

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-MILL-01",
            machine_type="CNC_MILLING",
            model="DMG_MORI_NVX_5080",
            location="Cell-01",
            event_hub=event_hub,
        )

        # Trạng thái điều khiển (Operating State)
        self.state = "RUNNING"  # RUNNING, FEED_HOLD, EMERGENCY_STOP, TOOL_CHANGE
        self.spindle_running = True
        self.spindle_rpm_target = 12000.0  # Tốc độ thiết lập chương trình (RPM)
        self.spindle_rpm_actual = 12000.0  # Tốc độ đọc thực tế
        self.feed_override_pct = 100.0  # Núm Feed Override (0 - 150%)
        self.coolant_active = True  # Hệ thống tưới nguội trục chính (TSC)

        # Trạng thái vật lý nội tại (Physical & Mechanical Degradation)
        self.spindle_temp_c = 42.0  # Nhiệt độ vòng bi trục chính (°C)
        self.tool_wear_pct = 12.0  # Độ mòn dao (%)
        self.coolant_pressure_bar = (
            20.0  # Áp suất dung dịch làm mát định danh (Bar)
        )
        self.ambient_temp_c = 28.0  # Nhiệt độ môi trường xưởng (°C)

    def generate_telemetry(self) -> Dict[str, Any]:
        """Tính toán telemetry dựa trên động học và tương quan nhiệt - cơ.

        - Tải cắt (Load %) = f(Feed Override, Tool Wear) - Nhiệt độ = f(Load %,
        Coolant State) - Rung chấn (ISO 10816) = f(Tool Wear, Nhiệt giãn nở
        trục)
        """
        with self._lock:
            # 1. Tích lũy độ mòn dao khi đang phôi cắt
            if self.state == "RUNNING" and self.spindle_running:
                # Dao mòn dần theo chu trình cắt
                wear_increment = 0.04 * (self.feed_override_pct / 100.0)
                self.tool_wear_pct = min(100.0, self.tool_wear_pct + wear_increment)

            # 2. Spindle Load (% dòng định mức động cơ)
            if self.spindle_running and self.state == "RUNNING":
                base_load = 45.0 * (self.feed_override_pct / 100.0)
                wear_resistance_load = (self.tool_wear_pct / 100.0) * 35.0
                spindle_load = base_load + wear_resistance_load + random.uniform(-1.2, 1.8)
                self.spindle_rpm_actual = self.spindle_rpm_target + random.uniform(-15, 15)
            else:
                spindle_load = 3.5 + random.uniform(-0.5, 0.5)  # Dòng không tải
                self.spindle_rpm_actual = (
                    0.0 if not self.spindle_running else self.spindle_rpm_actual
                )

            # 3. Spindle Temperature (°C) - Mô hình cân bằng nhiệt
            if self.spindle_running:
                # Nhiệt sinh ra từ ma sát và tải cắt
                heat_in = (spindle_load / 100.0) * 1.35
                # Tản nhiệt qua dung dịch tưới nguội
                heat_out = 0.95 if self.coolant_active else 0.15
                self.spindle_temp_c += (heat_in - heat_out) + random.uniform(-0.15, 0.25)
                self.spindle_temp_c = max(self.ambient_temp_c, min(125.0, self.spindle_temp_c))
            else:
                # Làm mát tự nhiên về nhiệt độ phòng khi dừng
                cooling_rate = 0.8
                self.spindle_temp_c = max(self.ambient_temp_c, self.spindle_temp_c - cooling_rate)

            # 4. Vibration RMS (mm/s) - Tiêu chuẩn ISO 10816-3
            # Rung chấn tăng theo hàm phi tuyến khi dao mòn > 70% và trục giãn nở nhiệt
            if self.spindle_running:
                base_vibration = 1.6
                wear_vibration = ((self.tool_wear_pct / 100.0) ** 2.2) * 6.8
                thermal_expansion_vibration = max(0.0, (self.spindle_temp_c - 82.0) * 0.15)
                vibration_rms = (
                    base_vibration
                    + wear_vibration
                    + thermal_expansion_vibration
                    + random.uniform(-0.15, 0.2)
                )
            else:
                vibration_rms = 0.05 + random.uniform(0.0, 0.05)

            # 5. Coolant Pressure (Bar)
            if self.coolant_active:
                actual_coolant_pressure = self.coolant_pressure_bar + random.uniform(-0.3, 0.3)
            else:
                actual_coolant_pressure = 0.0

            return {
                "Controller_Execution": self.state,
                "Spindle_RotaryVelocity_RPM": round(self.spindle_rpm_actual, 1),
                "Spindle_Load_Pct": round(max(0.0, spindle_load), 1),
                "Spindle_Temp_C": round(self.spindle_temp_c, 2),
                "Vibration_RMS_mm_s": round(max(0.0, vibration_rms), 2),
                "Coolant_Pressure_Bar": round(max(0.0, actual_coolant_pressure), 2),
                "Path_Feedrate_Override_Pct": self.feed_override_pct,
                "Tool_Wear_Pct": round(self.tool_wear_pct, 1),
                "Tool_Life_Remaining_Minutes": max(
                    0, int((100.0 - self.tool_wear_pct) * 2.5)
                ),
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        """Edge Detection: Phát hiện sớm dựa trên ngưỡng kỹ thuật cẩm nang."""
        if telemetry.get("Spindle_Temp_C", 0) > 85.0:
            return "spindle thermal overload"
        if telemetry.get("Vibration_RMS_mm_s", 0) > 7.1:
            return "vibration anomaly"
        if telemetry.get("Spindle_Load_Pct", 0) > 115.0:
            return "spindle mechanical overload"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Tiếp nhận và thực thi các tín hiệu PLC tiêu chuẩn công nghiệp CNC."""
        payload = payload or {}
        with self._lock:
            detail = ""

            if command == "FEED_HOLD":
                # Tạm dừng di chuyển trục, giữ nguyên trục chính quay
                self.state = "FEED_HOLD"
                self.feed_override_pct = 0.0
                detail = "Feed hold engaged. Spindle maintained, linear axes motion suspended."

            elif command in ("REDUCE_SPEED_70", "FEED_OVERRIDE"):
                target_pct = float(payload.get("override_pct", 70.0))
                self.feed_override_pct = target_pct
                detail = f"Feedrate override adjusted to {target_pct}% to alleviate thermal load."

            elif command == "EMERGENCY_STOP":
                self.state = "EMERGENCY_STOP"
                self.spindle_running = False
                self.spindle_rpm_actual = 0.0
                self.feed_override_pct = 0.0
                detail = "Emergency stop circuit broken: Spindle drive powered down and mechanical brake locked."

            elif command == "COOLANT_BOOST":
                self.coolant_active = True
                self.coolant_pressure_bar = 35.0  # Tăng lên mức làm mát tăng áp
                detail = "High-pressure through-spindle coolant engaged (35 Bar)."

            elif command == "TOOL_CHANGE":
                self.tool_wear_pct = 0.0
                self.state = "RUNNING"
                detail = "Automatic tool change completed. Tool wear counter initialized to 0%."

            elif command == "RESUME":
                self.state = "RUNNING"
                self.feed_override_pct = 100.0
                self.spindle_running = True
                self.spindle_rpm_actual = self.spindle_rpm_target
                detail = "Program cycle resumed at 100% feedrate."

            else:
                detail = f"Command {command} rejected or unmapped in PLC registers."

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