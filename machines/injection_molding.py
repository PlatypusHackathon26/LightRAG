from __future__ import annotations

import random
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class InjectionMolding(BaseMachine):
    """Mô phỏng máy ép phun nhựa chuẩn EUROMAP 63/77 (Model: FANUC ROBOSHOT S-2000i).

    Mô phỏng chu trình ép 4 thì (Clamping -> Injection -> Packing/Cooling -> Mold Open),
    cân bằng nhiệt nòng phun và áp suất thủy lực/servo.
    """

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-INJ-01",
            machine_type="INJECTION_MOLDING",
            model="FANUC_ROBOSHOT_S2000I",
            location="Cell-02",
            event_hub=event_hub,
        )

        # Trạng thái chu trình
        self.state = "RUNNING"  # RUNNING, MOLD_MAINTENANCE, PURGING, EMERGENCY_STOP
        self.cycle_phase = "INJECTION"  # CLAMP, INJECTION, PACKING, COOLING, OPEN
        self.heater_bands_active = True
        self.mold_clamped = True

        # Động học và nhiệt độ các vùng nòng phun (Heater Zones)
        self.nozzle_temp_zone1_target = 220.0  # Vùng đầu phun (°C)
        self.nozzle_temp_zone1_actual = 220.0
        self.barrel_temp_zone2_actual = 210.0
        self.mold_temp_c = 45.0  # Nhiệt độ nước giải nhiệt khuôn (°C)

        # Áp suất & vị trí trục vít ép
        self.clamping_pressure_bar = 140.0  # Áp lực kẹp khuôn định danh (120-160 Bar)
        self.injection_pressure_bar = 95.0  # Áp suất phun nhựa
        self.screw_position_mm = 35.0  # Vị trí trục vít (Cushion position)
        self.ambient_temp_c = 28.0

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            if self.state == "RUNNING":
                # 1. Động học nhiệt độ Zone 1: Dao động theo công suất gia nhiệt và đối lưu nhựa
                if self.heater_bands_active:
                    # Rủi ro: Cảm biến trôi nhiệt hoặc cháy thermistor
                    self.nozzle_temp_zone1_actual += random.uniform(-0.35, 0.45)
                    self.nozzle_temp_zone1_actual = max(self.ambient_temp_c, min(270.0, self.nozzle_temp_zone1_actual))
                else:
                    self.nozzle_temp_zone1_actual = max(self.ambient_temp_c, self.nozzle_temp_zone1_actual - 0.7)

                # 2. Nhiệt độ khuôn phụ thuộc nhiệt nhựa nóng và lưu lượng chiller
                self.mold_temp_c += random.uniform(-0.15, 0.2)

                # 3. Áp suất kẹp khuôn (Tương quan thủy lực/servo clamp)
                if self.mold_clamped:
                    self.clamping_pressure_bar = 140.0 + random.uniform(-2.5, 3.0)
                else:
                    self.clamping_pressure_bar = 0.0

                # 4. Áp suất phun nhựa thực tế
                viscosity_factor = max(0.8, 1.0 + (220.0 - self.nozzle_temp_zone1_actual) * 0.02)
                self.injection_pressure_bar = (90.0 * viscosity_factor) + random.uniform(-1.5, 2.0)
            else:
                self.clamping_pressure_bar = 0.0
                self.injection_pressure_bar = 0.0
                self.nozzle_temp_zone1_actual = max(self.ambient_temp_c, self.nozzle_temp_zone1_actual - 0.5)

            return {
                "Controller_Execution": self.state,
                "Cycle_Phase": self.cycle_phase,
                "Nozzle_Temp_Zone1": round(self.nozzle_temp_zone1_actual, 2),
                "Barrel_Temp_Zone2": round(self.barrel_temp_zone2_actual, 2),
                "Mold_Temp_C": round(self.mold_temp_c, 1),
                "Clamping_Pressure_Bar": round(max(0.0, self.clamping_pressure_bar), 1),
                "Injection_Pressure_Bar": round(max(0.0, self.injection_pressure_bar), 1),
                "Cushion_Position_mm": round(self.screw_position_mm + random.uniform(-0.2, 0.2), 2),
                "Cycle_Time_Sec": 22.4,
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        zone1 = telemetry.get("Nozzle_Temp_Zone1", 0)
        clamp_p = telemetry.get("Clamping_Pressure_Bar", 0)
        if zone1 > 240.0:
            return "nozzle thermal runaway (burn hazard)"
        if zone1 < 200.0 and self.state == "RUNNING":
            return "nozzle freezing (cold slug hazard)"
        if (clamp_p < 120.0 or clamp_p > 165.0) and self.mold_clamped:
            return "clamping tonnage deviation"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""
            if command == "ADJUST_TEMPERATURE":
                target = float(payload.get("target_temp", 215.0))
                self.nozzle_temp_zone1_target = target
                # Hiệu chỉnh giảm nhiệt nòng phun
                self.nozzle_temp_zone1_actual = target
                detail = f"PID loop setpoint adjusted to {target}°C."

            elif command == "SET_CLAMP_PRESSURE":
                target_p = float(payload.get("pressure_bar", 135.0))
                self.clamping_pressure_bar = target_p
                detail = f"Proportional valve calibrated clamping pressure to {target_p} Bar."

            elif command == "PURGE_BARREL":
                self.state = "PURGING"
                self.screw_position_mm = 5.0
                detail = "Auto-purge cycle initialized to flush degraded resin."

            elif command == "SAFE_STOP":
                self.state = "MOLD_MAINTENANCE"
                self.mold_clamped = False
                self.clamping_pressure_bar = 0.0
                detail = "Cycle terminated gracefully. Mold parted to safe clearance position."

            elif command == "EMERGENCY_STOP":
                self.state = "EMERGENCY_STOP"
                self.heater_bands_active = False
                self.mold_clamped = False
                detail = "Safety door interlock / E-Stop tripped: Heaters killed, hydraulic dump valve opened."

            elif command == "RESUME":
                self.state = "RUNNING"
                self.heater_bands_active = True
                self.mold_clamped = True
                detail = "Automatic injection molding cycle restarted."

            else:
                detail = f"Command {command} unmapped in Euromap registers."

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