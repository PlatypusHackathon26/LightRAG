from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines import commands as cmd
from machines.base_machine import BaseMachine
from machines.commands import CommandSpec, ParamSpec


class AmrVehicle(BaseMachine):
    """Mô phỏng xe tự hành nhà kho AMR chuẩn VDA 5050 (Model: OMRON LD-90 / MiR250).

    RUNNING là đang chạy lộ trình; CHARGING là đang nằm trên đế sạc."""

    MACHINE_TYPE = "AMR_VEHICLE"
    MIN_START_BATTERY_PCT = 15.0
    CRITICAL_BATTERY_TEMP_C = 55.0

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-AMR-01",
            machine_type="AMR_VEHICLE",
            model="OMRON_LD90_VDA5050",
            location="Floor_Transit_Zone",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
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

        # 3. Khai báo lỗi
        self.active_faults = {
            "BATTERY_CELL_DEGRADATION": False,  # Chai pin, nội trở cao
            "LIDAR_OPTICAL_DIRT": False,  # Bụi bẩn che lăng kính LiDAR
            "WHEEL_MOTOR_RESISTANCE": False,  # Kẹt cơ cấu bánh xe
        }

    @classmethod
    def command_specs(cls) -> Dict[str, CommandSpec]:
        specs = cmd.control_commands(
            hold_desc="Dừng xe tại chỗ, giữ lộ trình",
            resume_from=frozenset({cmd.HOLD, cmd.CHARGING}),
        )
        for spec in (
            cmd.repair(
                "REPLACE_BATTERY_MODULE",
                "BATTERY_CELL_DEGRADATION",
                "Thay cụm cell pin LiFePO4 mới (module mới sạc sẵn 95%)",
                60,
                ("REPLACE_BATTERY", "CHANGE_BATTERY", "THAY_PIN"),
            ),
            cmd.repair(
                "CLEAN_LIDAR_OPTICS",
                "LIDAR_OPTICAL_DIRT",
                "Lau sạch ống kính LiDAR",
                20,
                ("CLEAN_LIDAR", "CLEAN_LIDAR_LENS"),
            ),
            cmd.repair(
                "SERVICE_DRIVE_MOTOR",
                "WHEEL_MOTOR_RESISTANCE",
                "Kiểm tra, bôi trơn cụm động cơ bánh xe",
                45,
                ("REPAIR_DRIVE_MOTOR", "SERVICE_WHEEL_MOTOR", "LUBRICATE_WHEEL"),
            ),
            CommandSpec(
                "RETURN_TO_CHARGER",
                "control",
                "Về đế sạc để nạp pin (chỉ bù pin cạn do vận hành; không sửa được pin chai)",
                frozenset({cmd.RUNNING, cmd.HOLD, cmd.STOPPED}),
                cmd.CHARGING,
                risk="LOW",
                aliases=("GO_CHARGE", "CHARGE", "VE_SAC"),
            ),
            CommandSpec(
                "NAVIGATE_TO",
                "setpoint",
                "Chạy tới trạm chỉ định",
                frozenset({cmd.RUNNING, cmd.HOLD, cmd.CHARGING}),
                cmd.RUNNING,
                risk="LOW",
                params={
                    "station": ParamSpec(
                        "str", default="BUFFER_STATION", desc_vi="mã trạm"
                    ),
                    "speed_m_s": ParamSpec("float", 0, 1.4, 1.2, "tốc độ m/s"),
                },
                aliases=("GOTO", "GO_TO_STATION"),
            ),
        ):
            specs[spec.name] = spec
        return specs

    def on_command(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        if name == "RETURN_TO_CHARGER":
            self.target_station = "CHARGING_STATION"
            return "Xe về và kết nối đế sạc tự động."
        if name == "NAVIGATE_TO":
            self.target_station = params["station"]
            self.target_speed_m_s = params["speed_m_s"]
            return f"Chấp thuận lộ trình VDA 5050 tới trạm {self.target_station}."
        if name in ("RESUME", "START"):
            self.target_speed_m_s = self.target_speed_m_s or 1.2
        return None

    def on_repaired(self, name: str) -> None:
        if name == "REPLACE_BATTERY_MODULE":
            self.battery_pct = (
                95.0  # the new module's own charge, not a reset of the old one
            )

    def at_rest(self) -> bool:
        return self.current_velocity_m_s < 0.05

    def start_blocker(self) -> Optional[str]:
        if self.battery_pct < self.MIN_START_BATTERY_PCT:
            return f"pin {self.battery_pct:.1f}% < {self.MIN_START_BATTERY_PCT:.0f}%, cần sạc"
        if self.battery_temp_c > self.CRITICAL_BATTERY_TEMP_C:
            return f"nhiệt pin {self.battery_temp_c:.1f}°C > {self.CRITICAL_BATTERY_TEMP_C:.0f}°C, chờ nguội"
        return None

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            dt = self._tick()

            # --- VẬN TỐC XE: chỉ chạy khi RUNNING; còn lại phanh (dừng khẩn cấp phanh gấp đôi) ---
            if self.running:
                desired = self.target_speed_m_s
                if self.active_faults["WHEEL_MOTOR_RESISTANCE"]:
                    desired *= 0.5  # Kẹt bánh làm tốc độ tụt mạnh
                self.current_velocity_m_s = self.approach(
                    self.current_velocity_m_s, desired, dt, 4.0
                )
            else:
                decel = 5.0 if self.state == cmd.E_STOP else 2.5
                self.current_velocity_m_s = max(
                    0.0, self.current_velocity_m_s - decel * dt
                )

            # --- TIÊU HAO & NHIỆT ĐỘ PIN ---
            if self.running:
                drain = 0.04 + (self.payload_weight_kg / 90.0) * 0.02
                if self.active_faults["BATTERY_CELL_DEGRADATION"]:
                    drain *= 4.0  # Tụt pin gấp 4 lần
                if self.active_faults["WHEEL_MOTOR_RESISTANCE"]:
                    drain *= 1.8
                self.battery_pct = max(0.0, self.battery_pct - drain * dt)
                heat_gen = drain * 5.0
                self.battery_temp_c = self.approach(
                    self.battery_temp_c,
                    self.ambient_temp_c + heat_gen / 0.03,
                    dt,
                    1 / 0.03,
                )
            elif self.state == cmd.CHARGING:
                self.battery_pct = min(100.0, self.battery_pct + 0.4 * dt)
                cooling = (self.battery_temp_c - self.ambient_temp_c) * 0.08 * dt
                self.battery_temp_c = max(
                    self.ambient_temp_c, self.battery_temp_c - cooling
                )
            else:
                self.battery_pct = max(0.0, self.battery_pct - 0.001 * dt)
                cooling = (self.battery_temp_c - self.ambient_temp_c) * 0.05 * dt
                self.battery_temp_c = max(
                    self.ambient_temp_c, self.battery_temp_c - cooling
                )

            # --- ĐỘ TIN CẬY LIDAR SLAM ---
            if self.active_faults["LIDAR_OPTICAL_DIRT"]:
                self.lidar_confidence_pct = max(
                    40.0, self.lidar_confidence_pct - 2.0 * dt
                )
            else:
                self.lidar_confidence_pct = min(
                    99.5, self.lidar_confidence_pct + 2.0 * dt
                )

            noise_v = (
                random.uniform(-0.02, 0.02) if self.current_velocity_m_s > 0.05 else 0.0
            )
            noise_lidar = random.uniform(-0.2, 0.2)
            noise_bat = random.uniform(-0.05, 0.05)
            noise_btemp = random.uniform(-0.1, 0.1)

            return {
                "Controller_Execution": self.state,
                "Battery_Pct": round(
                    max(0.0, min(100.0, self.battery_pct + noise_bat)), 2
                ),
                "Battery_Temp_C": round(self.battery_temp_c + noise_btemp, 1),
                "Current_Velocity_m_s": round(
                    max(0.0, self.current_velocity_m_s + noise_v), 2
                ),
                "Payload_Weight_Kg": round(self.payload_weight_kg, 1),
                "Current_Station": self.current_station,
                "Target_Station": self.target_station,
                "Lidar_Confidence_Pct": round(
                    max(0.0, min(100.0, self.lidar_confidence_pct + noise_lidar)), 1
                ),
                "Simulated_Active_Faults": self.get_active_faults(),
            }
