from __future__ import annotations

import random
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class AmrVehicle(BaseMachine):
    """Mô phỏng xe tự hành nhà kho AMR chuẩn VDA 5050 (Model: OMRON LD-90 / MiR250).

    Mô phỏng trạng thái pin LiFePO4, nhiệt độ cell, tải kéo, định vị LiDAR SLAM
    và điều phối các chặng di chuyển trong xưởng.
    """

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-AMR-01",
            machine_type="AMR_VEHICLE",
            model="OMRON_LD90_VDA5050",
            location="Floor_Transit_Zone",
            event_hub=event_hub,
        )

        # Trạng thái di chuyển
        self.state = "IDLE"  # IDLE, NAVIGATING, CHARGING, BLOCKED_OBSTACLE, E_STOP
        self.current_station = "STATION_DOCK_1"
        self.target_station = "STATION_DOCK_1"
        self.current_speed_m_s = 0.0
        self.max_speed_m_s = 1.4

        # Năng lượng & cơ khí
        self.battery_pct = 82.0  # Dung lượng pin (%)
        self.battery_temp_c = 31.0
        self.payload_weight_kg = 0.0  # Tải trọng chuyên chở (Max 90 kg)
        self.lidar_confidence_pct = 99.2  # Độ tin cậy định vị hạt SLAM

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            # 1. Động học tiêu hao pin
            if self.state == "NAVIGATING":
                self.current_speed_m_s = self.max_speed_m_s + random.uniform(-0.1, 0.1)
                # Xả pin = Tải kéo + vận tốc
                drain_rate = 0.08 + (self.payload_weight_kg / 90.0) * 0.05
                self.battery_pct = max(0.0, self.battery_pct - drain_rate)
                self.battery_temp_c += random.uniform(0.01, 0.05)
            elif self.state == "CHARGING":
                self.current_speed_m_s = 0.0
                self.battery_pct = min(100.0, self.battery_pct + 0.45)
                self.battery_temp_c = max(28.0, self.battery_temp_c - 0.08)
            else:
                self.current_speed_m_s = 0.0
                self.battery_pct = max(0.0, self.battery_pct - 0.005)

            # 2. Nhiễu LiDAR từ bụi sàn / người đi lại
            self.lidar_confidence_pct = max(50.0, min(100.0, 99.0 + random.uniform(-1.5, 0.8)))

            return {
                "Controller_Execution": self.state,
                "Battery_Pct": round(self.battery_pct, 1),
                "Battery_Temp_C": round(self.battery_temp_c, 1),
                "Current_Velocity_m_s": round(self.current_speed_m_s, 2),
                "Payload_Weight_Kg": round(self.payload_weight_kg, 1),
                "Current_Station": self.current_station,
                "Target_Station": self.target_station,
                "Lidar_Confidence_Pct": round(self.lidar_confidence_pct, 1),
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        bat = telemetry.get("Battery_Pct", 100)
        lidar = telemetry.get("Lidar_Confidence_Pct", 100)
        if bat < 20.0 and self.state != "CHARGING":
            return "critically low battery (depletion risk)"
        if lidar < 65.0:
            return "localization lost (lidar obscured/corridor symmetric slip)"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""
            if command == "NAVIGATE_TO":
                station = payload.get("station", "BUFFER_STATION")
                self.target_station = station
                self.state = "NAVIGATING"
                self.payload_weight_kg = float(payload.get("load_weight_kg", 25.0))
                detail = f"VDA 5050 instant action accepted: Path calculated to {station}."

            elif command == "RETURN_TO_CHARGER":
                self.target_station = "CHARGING_STATION"
                self.state = "CHARGING"
                self.payload_weight_kg = 0.0
                detail = "Vehicle docked to fast-charge contact plate."

            elif command == "EMERGENCY_STOP":
                self.state = "E_STOP"
                self.current_speed_m_s = 0.0
                detail = "Safety LiDAR safety field breached: Dynamic electro-magnetic braking clamped."

            elif command == "RESUME":
                self.state = "IDLE"
                self.current_speed_m_s = 0.0
                detail = "Obstacle cleared; AMR safety circuit reset to IDLE."

            else:
                detail = f"VDA 5050 command {command} rejected by fleet manager."

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