from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class AmrVehicle(BaseMachine):
    """Mô phỏng xe tự hành nhà kho AMR chuẩn VDA 5050 (Model: OMRON LD-90 / MiR250)."""

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-AMR-01",
            machine_type="AMR_VEHICLE",
            model="OMRON_LD90_VDA5050",
            location="Floor_Transit_Zone",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
        self.state = "NAVIGATING"  # Mặc định xe chạy vận chuyển linh kiện
        self.target_station = "STATION_DOCK_2"
        self.current_station = "STATION_DOCK_1"
        self.target_speed_m_s = 1.2
        self.max_configured_speed = 1.4

        # 2. Trạng thái vật lý
        self.current_velocity_m_s = self.nominal("Current_Velocity_m_s")
        self.battery_pct = self.nominal("Battery_Pct")
        self.battery_temp_c = self.nominal("Battery_Temp_C")
        self.payload_weight_kg = 25.0
        self.lidar_confidence_pct = self.nominal("Lidar_Confidence_Pct")
        self.ambient_temp_c = 26.0
        self.last_update_time = time.time()

        # 3. Khai báo lỗi
        self.active_faults = {
            "BATTERY_CELL_DEGRADATION": False,  # Chai pin, nội trở cao
            "LIDAR_OPTICAL_DIRT": False,        # Bụi bẩn che lăng kính LiDAR
            "WHEEL_MOTOR_RESISTANCE": False,    # Kẹt cơ cấu bánh xe
        }

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            current_time = time.time()
            dt = max(0.1, min(current_time - self.last_update_time, 2.5))
            self.last_update_time = current_time

            # --- VẬN TỐC XE ---
            if self.state == "NAVIGATING":
                desired = self.target_speed_m_s
                if self.active_faults["WHEEL_MOTOR_RESISTANCE"]:
                    desired *= 0.5  # Kẹt bánh làm tốc độ tụt mạnh
                self.current_velocity_m_s = self.approach(self.current_velocity_m_s, desired, dt, 4.0)
            else:
                self.current_velocity_m_s = max(0.0, self.current_velocity_m_s - 2.5 * dt)

            # --- TIÊU HAO & NHIỆT ĐỘ PIN ---
            if self.state == "NAVIGATING":
                drain = 0.04 + (self.payload_weight_kg / 90.0) * 0.02
                if self.active_faults["BATTERY_CELL_DEGRADATION"]:
                    drain *= 4.0  # Tụt pin gấp 4 lần
                if self.active_faults["WHEEL_MOTOR_RESISTANCE"]:
                    drain *= 1.8
                self.battery_pct = max(0.0, self.battery_pct - drain * dt)

                heat_gen = drain * 5.0
                self.battery_temp_c = self.approach(
                    self.battery_temp_c, self.ambient_temp_c + heat_gen / 0.03, dt, 1 / 0.03
                )
            elif self.state == "CHARGING":
                self.battery_pct = min(100.0, self.battery_pct + 0.4 * dt)
                cooling = (self.battery_temp_c - self.ambient_temp_c) * 0.08 * dt
                self.battery_temp_c = max(self.ambient_temp_c, self.battery_temp_c - cooling)
            else:
                self.battery_pct = max(0.0, self.battery_pct - 0.001 * dt)
                cooling = (self.battery_temp_c - self.ambient_temp_c) * 0.05 * dt
                self.battery_temp_c = max(self.ambient_temp_c, self.battery_temp_c - cooling)

            # --- ĐỘ TIN CẬY LIDAR SLAM ---
            if self.active_faults["LIDAR_OPTICAL_DIRT"]:
                self.lidar_confidence_pct = max(40.0, self.lidar_confidence_pct - 2.0 * dt)
            else:
                self.lidar_confidence_pct = min(99.5, self.lidar_confidence_pct + 2.0 * dt)

            noise_v = random.uniform(-0.02, 0.02) if self.current_velocity_m_s > 0.05 else 0.0
            noise_lidar = random.uniform(-0.2, 0.2)
            noise_bat = random.uniform(-0.05, 0.05)
            noise_btemp = random.uniform(-0.1, 0.1)

            return {
                "Controller_Execution": self.state,
                "Battery_Pct": round(max(0.0, min(100.0, self.battery_pct + noise_bat)), 2),
                "Battery_Temp_C": round(self.battery_temp_c + noise_btemp, 1),
                "Current_Velocity_m_s": round(max(0.0, self.current_velocity_m_s + noise_v), 2),
                "Payload_Weight_Kg": round(self.payload_weight_kg, 1),
                "Current_Station": self.current_station,
                "Target_Station": self.target_station,
                "Lidar_Confidence_Pct": round(max(0.0, min(100.0, self.lidar_confidence_pct + noise_lidar)), 1),
                "Simulated_Active_Faults": self.get_active_faults(),
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        bat = telemetry.get("Battery_Pct", 100.0)
        temp = telemetry.get("Battery_Temp_C", 30.0)
        lidar = telemetry.get("Lidar_Confidence_Pct", 100.0)

        if bat < 15.0 and self.state != "CHARGING":
            return "CRITICAL_BATTERY_EXHAUSTED"
        if temp > 55.0:
            return "CRITICAL_BATTERY_OVERHEAT"
        if lidar < 65.0:
            return "LOCALIZATION_CONFIDENCE_LOST"
        if bat < 25.0 and self.state != "CHARGING":
            return "WARNING_LOW_BATTERY"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""

            if command == "CLEAN_LIDAR_OPTICS":
                self.clear_fault("LIDAR_OPTICAL_DIRT")
                detail = "Đã làm sạch ống kính quang học LiDAR bằng khí nén; SLAM phục hồi."

            elif command == "SERVICE_DRIVE_MOTOR":
                self.clear_fault("WHEEL_MOTOR_RESISTANCE")
                detail = "Đã kiểm tra và bôi trơn trục động cơ di chuyển."

            elif command == "REPLACE_BATTERY_MODULE":
                self.clear_fault("BATTERY_CELL_DEGRADATION")
                self.battery_pct = 95.0
                detail = "Đã thay cụm cell pin LiFePO4 mới."

            elif command == "RETURN_TO_CHARGER":
                self.target_station = "CHARGING_STATION"
                self.state = "CHARGING"
                self.target_speed_m_s = 0.0
                self.payload_weight_kg = 0.0
                detail = "Xe đã kết nối đế sạc tiếp xúc tự động."

            elif command == "NAVIGATE_TO":
                station = payload.get("station", "BUFFER_STATION")
                self.target_station = station
                self.state = "NAVIGATING"
                self.target_speed_m_s = max(
                    0.0,
                    min(self.max_configured_speed, float(payload.get("speed_m_s", 1.2))),
                )
                detail = f"Chấp thuận lệnh lộ trình VDA 5050 tới trạm {station}."

            elif command == "RESUME":
                self.state = "NAVIGATING"
                self.target_speed_m_s = 1.2
                detail = "Tiếp tục lộ trình vận chuyển tự hành."

            elif command == "EMERGENCY_STOP":
                self.state = "E_STOP"
                self.target_speed_m_s = 0.0
                self.current_velocity_m_s = 0.0
                detail = "Phanh điện từ kích hoạt, dừng xe khẩn cấp."

            else:
                detail = f"Lệnh '{command}' không được hỗ trợ trong giao thức VDA 5050."

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
