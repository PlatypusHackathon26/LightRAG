from __future__ import annotations

import random
import math
import time
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class InjectionMolding(BaseMachine):
    """Mô phỏng máy ép phun nhựa chuẩn EUROMAP 63/77 (Model: FANUC ROBOSHOT S-2000i)."""

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-INJ-01",
            machine_type="INJECTION_MOLDING",
            model="FANUC_ROBOSHOT_S2000I",
            location="Cell-02",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
        self.state = "RUNNING"
        self.cycle_phase = "INJECTION"
        self.heater_bands_enabled = True
        self.mold_clamp_command = True
        self.nozzle_temp_zone1_target = 220.0
        self.nozzle_temp_zone1_min_target = 180.0
        self.nozzle_temp_zone1_max_target = 245.0
        self.clamping_pressure_target_bar = 140.0

        # 2. Trạng thái vật lý
        self.nozzle_temp_zone1_actual = self.nominal("Nozzle_Temp_Zone1")
        self.barrel_temp_zone2_actual = 210.0
        self.mold_temp_c = 45.0
        self.clamping_pressure_bar = self.nominal("Clamping_Pressure_Bar")
        self.injection_pressure_bar = self.nominal("Injection_Pressure_Bar")
        self.screw_position_mm = 35.0
        self.ambient_temp_c = 28.0
        self.last_update_time = time.time()

        # 3. Khai báo danh mục lỗi
        self.active_faults = {
            "HEATER_BAND_RUNAWAY": False,               # Kẹt rơ-le nhiệt, quá nhiệt đầu phun
            "HYDRAULIC_PROPORTIONAL_VALVE_LEAK": False, # Hở van thủy lực kẹp khuôn, tụt áp
            "NOZZLE_CLOGGING": False,                   # Nghẹt nhựa lạnh nòng phun
        }

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            current_time = time.time()
            dt = max(0.1, min(current_time - self.last_update_time, 2.5))
            self.last_update_time = current_time

            # --- NHIỆT ĐỘ ĐẦU PHUN ZONE 1 ---
            # Tự phục hồi nếu một lệnh cũ/không hợp lệ đã làm hỏng setpoint hoặc
            # trạng thái nhiệt. Nhiệt đầu phun không thể thấp hơn môi trường.
            if (
                not math.isfinite(self.nozzle_temp_zone1_target)
                or not self.nozzle_temp_zone1_min_target
                <= self.nozzle_temp_zone1_target
                <= self.nozzle_temp_zone1_max_target
            ):
                self.nozzle_temp_zone1_target = 220.0
            if (
                not math.isfinite(self.nozzle_temp_zone1_actual)
                or self.nozzle_temp_zone1_actual < self.ambient_temp_c
            ):
                self.nozzle_temp_zone1_actual = self.nozzle_temp_zone1_target

            if self.state in ("EMERGENCY_STOP", "MOLD_MAINTENANCE") or not self.heater_bands_enabled:
                cooling = (self.nozzle_temp_zone1_actual - self.ambient_temp_c) * 0.05 * dt
                self.nozzle_temp_zone1_actual = max(self.ambient_temp_c, self.nozzle_temp_zone1_actual - cooling)
            else:
                if self.active_faults["HEATER_BAND_RUNAWAY"]:
                    self.nozzle_temp_zone1_actual = min(280.0, self.nozzle_temp_zone1_actual + 1.2 * dt)
                else:
                    target = self.approach(
                        self.nozzle_temp_zone1_actual, self.nozzle_temp_zone1_target, dt, 15.0
                    )
                    self.nozzle_temp_zone1_actual = self.ramp(
                        self.nozzle_temp_zone1_actual, target, dt, 1.2
                    )
            self.nozzle_temp_zone1_actual = max(
                self.ambient_temp_c, min(280.0, self.nozzle_temp_zone1_actual)
            )

            # --- ÁP SUẤT KẸP KHUÔN (CLAMPING BAR) ---
            if self.mold_clamp_command and self.state == "RUNNING":
                target_p = self.clamping_pressure_target_bar
                if self.active_faults["HYDRAULIC_PROPORTIONAL_VALVE_LEAK"]:
                    target_p = 102.0  # Tụt áp kẹp do hở van
                self.clamping_pressure_bar = self.approach(self.clamping_pressure_bar, target_p, dt, 5.0)
            else:
                self.clamping_pressure_bar = max(0.0, self.clamping_pressure_bar - 40.0 * dt)

            # --- ÁP SUẤT PHUN NHỰA ---
            if self.state == "RUNNING" and self.clamping_pressure_bar > 80.0:
                base_inj = 95.0
                if self.active_faults["NOZZLE_CLOGGING"]:
                    base_inj = 165.0
                viscosity_offset = (220.0 - self.nozzle_temp_zone1_actual) * 0.35
                target_inj = base_inj + viscosity_offset
                self.injection_pressure_bar = self.approach(self.injection_pressure_bar, target_inj, dt, 5.0)
            else:
                self.injection_pressure_bar = self.ramp(self.injection_pressure_bar, 0.0, dt, 20.0)

            noise_temp = random.uniform(-0.12, 0.12)
            noise_clamp = random.uniform(-0.5, 0.5) if self.clamping_pressure_bar > 5.0 else 0.0
            noise_inj = random.uniform(-0.5, 0.5) if self.injection_pressure_bar > 5.0 else 0.0

            return {
                "Controller_Execution": self.state,
                "Cycle_Phase": self.cycle_phase,
                "Nozzle_Temp_Zone1": round(self.nozzle_temp_zone1_actual + noise_temp, 2),
                "Barrel_Temp_Zone2": round(self.barrel_temp_zone2_actual, 2),
                "Mold_Temp_C": round(self.mold_temp_c, 1),
                "Clamping_Pressure_Bar": round(max(0.0, self.clamping_pressure_bar + noise_clamp), 1),
                "Injection_Pressure_Bar": round(max(0.0, self.injection_pressure_bar + noise_inj), 1),
                "Cushion_Position_mm": round(self.screw_position_mm, 2),
                "Cycle_Time_Sec": 22.4,
                "Simulated_Active_Faults": self.get_active_faults(),
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        temp = telemetry.get("Nozzle_Temp_Zone1", 0.0)
        clamp_p = telemetry.get("Clamping_Pressure_Bar", 0.0)
        inj_p = telemetry.get("Injection_Pressure_Bar", 0.0)

        if temp > 245.0:
            return "CRITICAL_NOZZLE_THERMAL_RUNAWAY"
        if self.mold_clamp_command and clamp_p < 115.0 and self.state == "RUNNING":
            return "CRITICAL_CLAMPING_PRESSURE_LOSS"
        if inj_p > 145.0:
            return "CRITICAL_INJECTION_OVERPRESSURE"
        if temp < 195.0 and self.state == "RUNNING":
            return "WARNING_NOZZLE_COLD_SLUG"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""

            if command == "SERVICE_HEATER_SSR":
                self.clear_fault("HEATER_BAND_RUNAWAY")
                self.nozzle_temp_zone1_target = 220.0
                detail = "Đã ngắt điện cưỡng bức và thay rơ-le bán dẫn SSR vòng nhiệt."

            elif command == "REPAIR_HYDRAULIC_VALVE":
                self.clear_fault("HYDRAULIC_PROPORTIONAL_VALVE_LEAK")
                detail = "Đã thay gioăng phớt van tỉ lệ thủy lực kẹp khuôn, áp suất phục hồi."

            elif command == "PURGE_BARREL":
                self.clear_fault("NOZZLE_CLOGGING")
                self.state = "PURGING"
                detail = "Đã thực hiện chu trình đùn xả nhựa cặn thông nòng phun."

            elif command == "ADJUST_TEMPERATURE":
                try:
                    target = float(payload.get("target_temp", 220.0))
                except (TypeError, ValueError):
                    target = float("nan")
                if (
                    not math.isfinite(target)
                    or not self.nozzle_temp_zone1_min_target
                    <= target
                    <= self.nozzle_temp_zone1_max_target
                ):
                    detail = (
                        "REJECTED: Nhiệt độ đặt đầu phun phải nằm trong "
                        f"{self.nozzle_temp_zone1_min_target:.0f}–"
                        f"{self.nozzle_temp_zone1_max_target:.0f}°C."
                    )
                else:
                    self.nozzle_temp_zone1_target = target
                    detail = f"Đã cập nhật nhiệt độ đặt vùng đầu phun thành {target}°C."

            elif command == "SAFE_STOP":
                self.state = "MOLD_MAINTENANCE"
                self.mold_clamp_command = False
                detail = "Dừng chu trình an toàn; tách khuôn về vị trí xả áp."

            elif command == "EMERGENCY_STOP":
                self.state = "EMERGENCY_STOP"
                self.heater_bands_enabled = False
                self.mold_clamp_command = False
                detail = "NGẮT KHẨN CẤP: Van xả dầu hạ áp tức thời, ngắt nguồn nhiệt."

            elif command == "RESUME":
                self.state = "RUNNING"
                self.heater_bands_enabled = True
                self.mold_clamp_command = True
                detail = "Khôi phục chu trình ép tự động."

            else:
                detail = f"Lệnh '{command}' không có trong tập thanh ghi Euromap 63/77."

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
