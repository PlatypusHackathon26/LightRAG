from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

from machines.base_machine import BaseMachine


class CncMilling(BaseMachine):
    """Mo phong may phay CNC (Model: DMG MORI NVX 5080) chuan MTConnect & OPC UA."""

    def __init__(
        self,
        event_hub: Optional[Any] = None,
        fault_interval_sec: float = 30.0,
    ) -> None:
        super().__init__(
            machine_id="MC-MILL-01",
            machine_type="CNC_MILLING",
            model="DMG_MORI_NVX_5080",
            location="Cell-01",
            event_hub=event_hub,
            fault_interval_sec=fault_interval_sec,
        )

        self.state = "RUNNING"
        self.spindle_enabled = True
        self.spindle_target_rpm = 12000.0
        self.feed_override_pct = 100.0
        self.coolant_pump_command = True
        self.coolant_target_bar = 20.0

        self.spindle_actual_rpm = 12000.0
        self.spindle_load_pct = 45.0
        self.spindle_temp_c = 38.0
        self.vibration_rms_mm_s = 1.3
        self.coolant_pressure_bar = 20.0
        self.tool_wear_pct = 12.0

        self.ambient_temp_c = 26.0
        self.last_update_time = time.time()

        self.active_faults = {
            "SPINDLE_BEARING_LACK_OF_LUBE": False,
            "COOLANT_PUMP_FAILURE": False,
            "TOOL_CHIPPING_OR_WEAR": False,
            "GUIDEWAY_LUBRICATION_ISSUE": False,
        }

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            current_time = time.time()
            dt = max(0.1, min(current_time - self.last_update_time, 2.5))
            self.last_update_time = current_time

            if self.state == "RUNNING":
                self.maybe_trigger_random_fault()

            if self.state in ("EMERGENCY_STOP", "MAINTENANCE") or not self.spindle_enabled:
                self.spindle_actual_rpm = max(0.0, self.spindle_actual_rpm - 3500.0 * dt)
            else:
                diff = self.spindle_target_rpm - self.spindle_actual_rpm
                self.spindle_actual_rpm += diff * min(1.0, 3.0 * dt)

            if self.coolant_pump_command and not self.active_faults["COOLANT_PUMP_FAILURE"]:
                diff_p = self.coolant_target_bar - self.coolant_pressure_bar
                self.coolant_pressure_bar += diff_p * min(1.0, 3.0 * dt)
            else:
                self.coolant_pressure_bar = max(0.0, self.coolant_pressure_bar - 8.0 * dt)

            # --- TIN HIEU TAI (target_load) ---
            # base_load = 42% o feed=100% (khong tinh mon dao) => ~45% luc ban dau
            # +20/35/8 khi co loi tuong ung.
            base_load = 42.0 * (self.feed_override_pct / 100.0) + (self.tool_wear_pct / 100.0) * 25.0
            target_load = base_load
            if self.active_faults["TOOL_CHIPPING_OR_WEAR"]:
                target_load += 35.0
            if self.active_faults["SPINDLE_BEARING_LACK_OF_LUBE"]:
                target_load += 20.0
            if self.active_faults["GUIDEWAY_LUBRICATION_ISSUE"]:
                target_load += 8.0

            self.spindle_load_pct += (target_load - self.spindle_load_pct) * min(1.0, 2.5 * dt)

            # --- NHIET DO TRUC CHINH ---
            if self.spindle_actual_rpm > 500.0:
                heat_in = (self.spindle_load_pct / 100.0) * 1.2
                if self.active_faults["SPINDLE_BEARING_LACK_OF_LUBE"]:
                    heat_in += 4.5

                # Toa nhiet ti le chenh lech voi moi truong; tuoi nguoi yeu -> toa cham lai.
                # Can bang binh thuong: 0.54 / 0.045 = 12C -> 38C (bang gia tri khoi tao).
                cool_coeff = 0.045 * max(0.3, self.coolant_pressure_bar / 20.0)
                cooling = (self.spindle_temp_c - self.ambient_temp_c) * cool_coeff
                self.spindle_temp_c += (heat_in - cooling) * dt
            else:
                cooling = (self.spindle_temp_c - self.ambient_temp_c) * 0.08 * dt
                self.spindle_temp_c = max(self.ambient_temp_c, self.spindle_temp_c - cooling)

            self.spindle_temp_c = max(self.ambient_temp_c, min(140.0, self.spindle_temp_c))

            # --- RUNG DONG (vibration) ---
            if self.spindle_actual_rpm > 1000.0:
                base_vib = 1.2 * (self.spindle_actual_rpm / 12000.0)
                fault_vib = 0.0
                if self.active_faults["SPINDLE_BEARING_LACK_OF_LUBE"]:
                    fault_vib += 3.2
                if self.active_faults["TOOL_CHIPPING_OR_WEAR"]:
                    fault_vib += 4.5
                if self.active_faults["GUIDEWAY_LUBRICATION_ISSUE"]:
                    fault_vib += 1.5

                # Nhiet tich tu lam rung tang (tren 70C)
                thermal_vib = max(0.0, (self.spindle_temp_c - 70.0) * 0.15)
                target_vib = base_vib + fault_vib + thermal_vib
            else:
                target_vib = 0.05

            self.vibration_rms_mm_s += (target_vib - self.vibration_rms_mm_s) * min(1.0, 3.0 * dt)

            noise_rpm = random.uniform(-15, 15)
            noise_load = random.uniform(-0.3, 0.3)
            noise_temp = random.uniform(-0.06, 0.06)
            noise_vib = random.uniform(-0.03, 0.03)
            noise_cool = random.uniform(-0.2, 0.2)

            return {
                "Controller_Execution": self.state,
                "Spindle_RotaryVelocity_RPM": round(max(0.0, self.spindle_actual_rpm + noise_rpm), 1),
                "Spindle_Load_Pct": round(max(0.0, self.spindle_load_pct + noise_load), 1),
                "Spindle_Temp_C": round(max(self.ambient_temp_c, self.spindle_temp_c + noise_temp), 2),
                "Vibration_RMS_mm_s": round(max(0.05, self.vibration_rms_mm_s + noise_vib), 2),
                "Coolant_Pressure_Bar": round(max(0.0, self.coolant_pressure_bar + noise_cool), 1),
                "Path_Feedrate_Override_Pct": self.feed_override_pct,
                "Tool_Wear_Pct": round(self.tool_wear_pct, 1),
                "Simulated_Active_Faults": self.get_active_faults(),
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        temp = telemetry.get("Spindle_Temp_C", 0)
        vib = telemetry.get("Vibration_RMS_mm_s", 0)
        load = telemetry.get("Spindle_Load_Pct", 0)
        pressure = telemetry.get("Coolant_Pressure_Bar", 0)

        if temp > 90.0:
            return "CRITICAL_SPINDLE_OVERHEAT"
        if vib > 7.1:
            return "CRITICAL_VIBRATION_SEVERITY"
        if load > 120.0:
            return "SPINDLE_MOTOR_OVERLOAD"
        if self.coolant_pump_command and pressure < 5.0 and self.state == "RUNNING":
            return "COOLANT_PRESSURE_LOSS"
        if temp > 75.0:
            return "WARNING_ELEVATED_TEMPERATURE"
        if vib > 4.5:
            return "WARNING_HIGH_VIBRATION"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""

            if command == "REFILL_SPINDLE_LUBRICANT":
                self.clear_fault("SPINDLE_BEARING_LACK_OF_LUBE")
                detail = "Da bom dau boi tron truc chinh. Giam ma sat o bi ve muc binh thuong."

            elif command == "REPAIR_COOLANT_SYSTEM":
                self.clear_fault("COOLANT_PUMP_FAILURE")
                self.coolant_pump_command = True
                self.coolant_target_bar = 20.0
                detail = "He thong lam mat da duoc sua chua va thong ong, ap suat phuc hoi."

            elif command == "REPLACE_TOOL":
                self.clear_fault("TOOL_CHIPPING_OR_WEAR")
                self.tool_wear_pct = 0.0
                detail = "Da thay cum dao phay moi (ATC Tool Change). Bo dem mon dao reset ve 0%."

            elif command == "LUBRICATE_GUIDEWAYS":
                self.clear_fault("GUIDEWAY_LUBRICATION_ISSUE")
                detail = "Da boi tron bang truot cac truc X/Y/Z."

            elif command == "SET_FEED_OVERRIDE":
                target_pct = float(payload.get("override_pct", 50.0))
                self.feed_override_pct = max(0.0, min(150.0, target_pct))
                detail = f"Da dieu chinh Feedrate Override thanh {self.feed_override_pct}%."

            elif command == "FEED_HOLD":
                self.state = "FEED_HOLD"
                self.feed_override_pct = 0.0
                detail = "Tam dung tinh tien ban may (Feed Hold). Truc chinh van duy tri quay."

            elif command == "COOLANT_BOOST":
                self.coolant_pump_command = True
                self.coolant_target_bar = 35.0
                detail = "Kich hoat bom tuoi nguoi ap suat cao (35 Bar)."

            elif command == "EMERGENCY_STOP":
                self.state = "EMERGENCY_STOP"
                self.spindle_enabled = False
                self.feed_override_pct = 0.0
                detail = "NGAT KHAN CAP: Phanh truc chinh kich hoat, khoa toan bo truc co khi."

            elif command == "RESUME":
                self.state = "RUNNING"
                self.spindle_enabled = True
                self.feed_override_pct = 100.0
                self.coolant_pump_command = True
                self.coolant_target_bar = 20.0
                detail = "Khoi phuc chu trinh gia cong dinh muc 100%."

            else:
                detail = f"Lenh '{command}' khong hop le hoac chua duoc ho tro."

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

            # --- MON DAO (loi mon dao x3 khi chipping; hong bom x7) ---
            if self.state == "RUNNING" and self.spindle_actual_rpm > 1000.0:
                w_rate = 0.005 if not self.active_faults["COOLANT_PUMP_FAILURE"] else 0.035
                if self.active_faults["TOOL_CHIPPING_OR_WEAR"]:
                    w_rate *= 3.0
                self.tool_wear_pct = min(100.0, self.tool_wear_pct + w_rate * dt)
