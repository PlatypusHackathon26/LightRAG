from __future__ import annotations

import math
import random
from typing import Any, Dict, Optional

from machines import commands as cmd
from machines.base_machine import BaseMachine
from machines.commands import CommandSpec, ParamSpec


class InjectionMolding(BaseMachine):
    """Mô phỏng máy ép phun nhựa chuẩn EUROMAP 63/77 (Model: FANUC ROBOSHOT S-2000i).

    Gia nhiệt vẫn bật khi STOPPED (giữ nhựa nóng cho lần chạy sau); khoá an toàn, bảo trì
    và dừng khẩn cấp ngắt nhiệt. START chỉ thành RUNNING khi đầu phun đủ nóng."""

    MACHINE_TYPE = "INJECTION_MOLDING"
    HEATERS_OFF_STATES = frozenset({cmd.LOCKED_OUT, cmd.MAINTENANCE, cmd.E_STOP})
    MIN_PROCESS_TEMP_C = 195.0
    CRITICAL_NOZZLE_TEMP_C = 245.0

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-INJ-01",
            machine_type="INJECTION_MOLDING",
            model="FANUC_ROBOSHOT_S2000I",
            location="Cell-02",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
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

        # 3. Khai báo danh mục lỗi
        self.active_faults = {
            "HEATER_BAND_RUNAWAY": False,               # Kẹt rơ-le nhiệt, quá nhiệt đầu phun
            "HYDRAULIC_PROPORTIONAL_VALVE_LEAK": False, # Hở van thủy lực kẹp khuôn, tụt áp
            "NOZZLE_CLOGGING": False,                   # Nghẹt nhựa lạnh nòng phun
        }

    @classmethod
    def command_specs(cls) -> Dict[str, CommandSpec]:
        specs = cmd.control_commands(hold_desc="Tạm dừng chu trình ép, giữ khuôn kẹp và nhiệt")
        for spec in (
            cmd.repair("SERVICE_HEATER_SSR", "HEATER_BAND_RUNAWAY", "Thay rơ-le bán dẫn SSR vòng gia nhiệt", 40,
                       ("REPLACE_HEATER_SSR", "REPLACE_SSR", "REPAIR_HEATER")),
            cmd.repair("REPAIR_HYDRAULIC_VALVE", "HYDRAULIC_PROPORTIONAL_VALVE_LEAK",
                       "Thay phớt van tỉ lệ thủy lực kẹp khuôn", 60,
                       ("REPAIR_VALVE", "REPLACE_HYDRAULIC_SEAL", "FIX_HYDRAULIC_LEAK")),
            cmd.repair("PURGE_BARREL", "NOZZLE_CLOGGING", "Đùn xả nhựa cặn thông nòng phun (cần nòng còn nóng)", 30,
                       ("PURGE_NOZZLE", "PURGE", "XA_NHUA"),
                       allowed=frozenset({cmd.STOPPED}), return_state=cmd.STOPPED),
            CommandSpec("ADJUST_TEMPERATURE", "setpoint", "Đặt nhiệt độ đầu phun vùng 1",
                        frozenset({cmd.RUNNING, cmd.HOLD, cmd.STOPPED}), risk="LOW",
                        params={"target_temp": ParamSpec("float", 180, 245, 220.0, "°C")},
                        aliases=("SET_NOZZLE_TEMP", "SET_TEMPERATURE")),
        ):
            specs[spec.name] = spec
        return specs

    def on_command(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        if name == "ADJUST_TEMPERATURE":
            self.nozzle_temp_zone1_target = params["target_temp"]
            return f"Đã đặt nhiệt độ đầu phun {self.nozzle_temp_zone1_target:g}°C."
        return None

    def on_repaired(self, name: str) -> None:
        if name == "SERVICE_HEATER_SSR":
            self.nozzle_temp_zone1_target = 220.0

    def at_rest(self) -> bool:
        return self.clamping_pressure_bar < 5.0 and self.injection_pressure_bar < 5.0

    def start_blocker(self) -> Optional[str]:
        if self.nozzle_temp_zone1_actual > self.CRITICAL_NOZZLE_TEMP_C:
            return (f"đầu phun {self.nozzle_temp_zone1_actual:.1f}°C > {self.CRITICAL_NOZZLE_TEMP_C:.0f}°C, "
                    "chờ nguội")
        return None

    def ready_to_run(self) -> bool:
        return self.nozzle_temp_zone1_actual >= self.MIN_PROCESS_TEMP_C

    def command_precondition(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        if name == "PURGE_BARREL" and self.nozzle_temp_zone1_actual < self.MIN_PROCESS_TEMP_C:
            return (f"Nòng {self.nozzle_temp_zone1_actual:.0f}°C còn nguội: cần ≥ {self.MIN_PROCESS_TEMP_C:.0f}°C "
                    "để đùn xả nhựa.")
        return None

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            dt = self._tick()

            # Tự phục hồi nếu setpoint hoặc trạng thái nhiệt bị hỏng; nhiệt không thấp hơn môi trường.
            if (
                not math.isfinite(self.nozzle_temp_zone1_target)
                or not self.nozzle_temp_zone1_min_target <= self.nozzle_temp_zone1_target <= self.nozzle_temp_zone1_max_target
            ):
                self.nozzle_temp_zone1_target = 220.0
            if not math.isfinite(self.nozzle_temp_zone1_actual) or self.nozzle_temp_zone1_actual < self.ambient_temp_c:
                self.nozzle_temp_zone1_actual = self.nozzle_temp_zone1_target

            # --- NHIỆT ĐỘ ĐẦU PHUN ZONE 1: rơ-le kẹt chỉ đốt nóng khi vòng gia nhiệt có điện ---
            if self.state in self.HEATERS_OFF_STATES or not self.heater_bands_enabled:
                cooling = (self.nozzle_temp_zone1_actual - self.ambient_temp_c) * 0.05 * dt
                self.nozzle_temp_zone1_actual = max(self.ambient_temp_c, self.nozzle_temp_zone1_actual - cooling)
            elif self.active_faults["HEATER_BAND_RUNAWAY"]:
                self.nozzle_temp_zone1_actual = min(280.0, self.nozzle_temp_zone1_actual + 1.2 * dt)
            else:
                target = self.approach(self.nozzle_temp_zone1_actual, self.nozzle_temp_zone1_target, dt, 15.0)
                self.nozzle_temp_zone1_actual = self.ramp(self.nozzle_temp_zone1_actual, target, dt, 1.2)
            self.nozzle_temp_zone1_actual = max(self.ambient_temp_c, min(280.0, self.nozzle_temp_zone1_actual))

            # --- ÁP SUẤT KẸP KHUÔN: bơm thủy lực giữ áp khi chạy / tạm dừng ---
            if self.mold_clamp_command and self.state in (cmd.RUNNING, cmd.HOLD):
                target_p = self.clamping_pressure_target_bar
                if self.active_faults["HYDRAULIC_PROPORTIONAL_VALVE_LEAK"]:
                    target_p = 102.0  # Tụt áp kẹp do hở van
                self.clamping_pressure_bar = self.approach(self.clamping_pressure_bar, target_p, dt, 5.0)
            else:
                self.clamping_pressure_bar = max(0.0, self.clamping_pressure_bar - 40.0 * dt)

            # --- ÁP SUẤT PHUN NHỰA: chỉ khi đang ép ---
            if self.running and self.clamping_pressure_bar > 80.0:
                base_inj = 165.0 if self.active_faults["NOZZLE_CLOGGING"] else 95.0
                viscosity_offset = (220.0 - self.nozzle_temp_zone1_actual) * 0.35
                self.injection_pressure_bar = self.approach(
                    self.injection_pressure_bar, base_inj + viscosity_offset, dt, 5.0)
            else:
                self.injection_pressure_bar = self.ramp(self.injection_pressure_bar, 0.0, dt, 20.0)

            noise_temp = random.uniform(-0.12, 0.12)
            noise_clamp = random.uniform(-0.5, 0.5) if self.clamping_pressure_bar > 5.0 else 0.0
            noise_inj = random.uniform(-0.5, 0.5) if self.injection_pressure_bar > 5.0 else 0.0

            return {
                "Controller_Execution": self.state,
                "Cycle_Phase": self.cycle_phase if self.running else "IDLE",
                "Nozzle_Temp_Zone1": round(self.nozzle_temp_zone1_actual + noise_temp, 2),
                "Barrel_Temp_Zone2": round(self.barrel_temp_zone2_actual, 2),
                "Mold_Temp_C": round(self.mold_temp_c, 1),
                "Clamping_Pressure_Bar": round(max(0.0, self.clamping_pressure_bar + noise_clamp), 1),
                "Injection_Pressure_Bar": round(max(0.0, self.injection_pressure_bar + noise_inj), 1),
                "Cushion_Position_mm": round(self.screw_position_mm, 2),
                "Cycle_Time_Sec": 22.4,
                "Simulated_Active_Faults": self.get_active_faults(),
            }
