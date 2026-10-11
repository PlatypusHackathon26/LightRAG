from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines import commands as cmd
from machines.base_machine import BaseMachine
from machines.commands import CommandSpec, ParamSpec


class CncMilling(BaseMachine):
    """Mo phong may phay CNC (Model: DMG MORI NVX 5080) chuan MTConnect & OPC UA."""

    MACHINE_TYPE = "CNC_MILLING"
    CRITICAL_SPINDLE_TEMP_C = 90.0

    def __init__(
        self,
        event_hub: Optional[Any] = None,
    ) -> None:
        super().__init__(
            machine_id="MC-MILL-01",
            machine_type="CNC_MILLING",
            model="DMG_MORI_NVX_5080",
            location="Cell-01",
            event_hub=event_hub,
        )

        self.spindle_enabled = True
        self.spindle_target_rpm = 12000.0
        self.feed_override_pct = 100.0
        self.coolant_pump_command = True
        self.coolant_target_bar = 20.0

        self.spindle_actual_rpm = self.nominal("Spindle_RotaryVelocity_RPM")
        self.spindle_load_pct = self.nominal("Spindle_Load_Pct")
        self.spindle_temp_c = self.nominal("Spindle_Temp_C")
        self.vibration_rms_mm_s = self.nominal("Vibration_RMS_mm_s")
        self.coolant_pressure_bar = self.nominal("Coolant_Pressure_Bar")
        self.tool_wear_pct = self.nominal("Tool_Wear_Pct")

        self.ambient_temp_c = 26.0

        self.active_faults = {
            "SPINDLE_BEARING_LACK_OF_LUBE": False,
            "COOLANT_PUMP_FAILURE": False,
            "TOOL_CHIPPING_OR_WEAR": False,
            "GUIDEWAY_LUBRICATION_ISSUE": False,
        }

    @classmethod
    def command_specs(cls) -> Dict[str, CommandSpec]:
        specs = cmd.control_commands(
            hold_aliases=("FEED_HOLD",),
            hold_desc="Feed Hold: dừng chạy dao, trục chính vẫn quay",
        )
        live = frozenset({cmd.RUNNING, cmd.HOLD})
        for spec in (
            cmd.repair(
                "REFILL_SPINDLE_LUBRICANT",
                "SPINDLE_BEARING_LACK_OF_LUBE",
                "Bơm mỡ bôi trơn ổ bi trục chính",
                40,
                (
                    "LUBRICATE_SPINDLE",
                    "REFILL_SPINDLE_GREASE",
                    "GREASE_SPINDLE_BEARING",
                ),
            ),
            cmd.repair(
                "REPAIR_COOLANT_SYSTEM",
                "COOLANT_PUMP_FAILURE",
                "Sửa / thay bơm tưới nguội và thông đường ống",
                60,
                ("REPAIR_COOLANT_PUMP", "REPLACE_COOLANT_PUMP", "FIX_COOLANT_PUMP"),
            ),
            cmd.repair(
                "REPLACE_TOOL",
                "TOOL_CHIPPING_OR_WEAR",
                "Thay dao phay mới (độ mòn về 0%)",
                30,
                ("TOOL_CHANGE", "CHANGE_TOOL", "REPLACE_CUTTER"),
            ),
            cmd.repair(
                "LUBRICATE_GUIDEWAYS",
                "GUIDEWAY_LUBRICATION_ISSUE",
                "Bôi trơn băng trượt các trục X/Y/Z",
                30,
                ("LUBRICATE_GUIDEWAY", "OIL_GUIDEWAYS"),
            ),
            CommandSpec(
                "SET_FEED_OVERRIDE",
                "setpoint",
                "Đặt tỉ lệ tốc độ chạy dao (giảm tải, giảm nhiệt)",
                frozenset({cmd.RUNNING, cmd.HOLD, cmd.STOPPED}),
                risk="LOW",
                params={
                    "override_pct": ParamSpec(
                        "float", 0, 150, 50.0, "% tốc độ chạy dao"
                    )
                },
                aliases=("FEED_OVERRIDE", "SET_FEEDRATE"),
            ),
            CommandSpec(
                "COOLANT_BOOST",
                "setpoint",
                "Tăng áp bơm tưới nguội lên 35 Bar (biện pháp tạm, bơm phải còn tốt)",
                live,
                risk="LOW",
                aliases=("BOOST_COOLANT", "TANG_TUOI_NGUOI"),
            ),
        ):
            specs[spec.name] = spec
        return specs

    def on_command(self, name: str, params: Dict[str, Any]) -> Optional[str]:
        if name == "SET_FEED_OVERRIDE":
            self.feed_override_pct = params["override_pct"]
            return f"Đã đặt Feedrate Override {self.feed_override_pct:g}%."
        if name == "COOLANT_BOOST":
            self.coolant_target_bar = 35.0
            return "Đặt áp bơm tưới nguội 35 Bar."
        if name == "START":
            self.coolant_target_bar = 20.0
        return None

    def on_repaired(self, name: str) -> None:
        if name == "REPLACE_TOOL":
            self.tool_wear_pct = 0.0  # a new tool: the root cause itself is replaced

    def at_rest(self) -> bool:
        return self.spindle_actual_rpm < 30.0

    def start_blocker(self) -> Optional[str]:
        if self.spindle_temp_c > self.CRITICAL_SPINDLE_TEMP_C:
            return f"nhiệt trục chính {self.spindle_temp_c:.1f}°C > {self.CRITICAL_SPINDLE_TEMP_C:.0f}°C, chờ nguội"
        return None

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            dt = self._tick()

            # Spindle turns while powered (feed hold keeps it turning); otherwise it brakes.
            if self.powered and self.spindle_enabled:
                self.spindle_actual_rpm = self.approach(
                    self.spindle_actual_rpm, self.spindle_target_rpm, dt, 3.0
                )
            else:
                self.spindle_actual_rpm = max(
                    0.0, self.spindle_actual_rpm - 3500.0 * dt
                )
            spin = self.spindle_actual_rpm / 12000.0  # 1 at full speed, 0 at rest
            feed = (self.feed_override_pct / 100.0) if self.running else 0.0

            # Coolant pump: needs power and a healthy pump.
            if (
                self.coolant_pump_command
                and self.powered
                and not self.active_faults["COOLANT_PUMP_FAILURE"]
            ):
                self.coolant_pressure_bar = self.ramp(
                    self.coolant_pressure_bar, self.coolant_target_bar, dt, 3.0
                )
            else:
                self.coolant_pressure_bar = max(
                    0.0, self.coolant_pressure_bar - 8.0 * dt
                )

            # Load: cutting scales with feed, friction with spindle speed. A fault only loads the
            # spindle while the part it affects is moving.
            target_load = (
                42.0 * feed * spin + (self.tool_wear_pct / 100.0) * 25.0 * spin
            )
            if self.active_faults["TOOL_CHIPPING_OR_WEAR"]:
                target_load += 35.0 * feed * spin
            if self.active_faults["SPINDLE_BEARING_LACK_OF_LUBE"]:
                target_load += 20.0 * spin
            if self.active_faults["GUIDEWAY_LUBRICATION_ISSUE"]:
                target_load += 8.0 * feed
            self.spindle_load_pct = self.approach(
                self.spindle_load_pct, target_load, dt, 5.0
            )

            # Spindle temperature. Normal balance: 0.54 / 0.045 = 12 C over ambient -> 38 C.
            if self.spindle_actual_rpm > 500.0:
                heat_in = (self.spindle_load_pct / 100.0) * 1.2
                if self.active_faults["SPINDLE_BEARING_LACK_OF_LUBE"]:
                    heat_in += 4.5 * spin
                cool_coeff = 0.045 * max(0.3, self.coolant_pressure_bar / 20.0)
                self.spindle_temp_c = self.approach(
                    self.spindle_temp_c,
                    self.ambient_temp_c + heat_in / cool_coeff,
                    dt,
                    1.0 / cool_coeff,
                )
            else:
                cooling = (self.spindle_temp_c - self.ambient_temp_c) * 0.08 * dt
                self.spindle_temp_c = max(
                    self.ambient_temp_c, self.spindle_temp_c - cooling
                )
            self.spindle_temp_c = max(
                self.ambient_temp_c, min(140.0, self.spindle_temp_c)
            )

            # Vibration.
            if self.spindle_actual_rpm > 1000.0:
                target_vib = 1.2 * spin
                if self.active_faults["SPINDLE_BEARING_LACK_OF_LUBE"]:
                    target_vib += 3.2 * spin
                if self.active_faults["TOOL_CHIPPING_OR_WEAR"]:
                    target_vib += 4.5 * feed
                if self.active_faults["GUIDEWAY_LUBRICATION_ISSUE"]:
                    target_vib += 1.5 * feed
                target_vib += max(
                    0.0, (self.spindle_temp_c - 70.0) * 0.15
                )  # heat-driven
            else:
                target_vib = 0.05
            self.vibration_rms_mm_s = self.approach(
                self.vibration_rms_mm_s, target_vib, dt, 4.0
            )

            # Tool wear only while cutting (x7 without coolant, x3 when chipped).
            if self.running and self.spindle_actual_rpm > 1000.0:
                w_rate = (
                    0.005 if not self.active_faults["COOLANT_PUMP_FAILURE"] else 0.035
                )
                if self.active_faults["TOOL_CHIPPING_OR_WEAR"]:
                    w_rate *= 3.0
                self.tool_wear_pct = min(100.0, self.tool_wear_pct + w_rate * dt)

            noise_rpm = random.uniform(-15, 15) if self.spindle_actual_rpm > 50 else 0.0
            noise_load = random.uniform(-0.3, 0.3)
            noise_temp = random.uniform(-0.06, 0.06)
            noise_vib = random.uniform(-0.03, 0.03)
            noise_cool = (
                random.uniform(-0.2, 0.2) if self.coolant_pressure_bar > 0.5 else 0.0
            )

            return {
                "Controller_Execution": self.state,
                "Spindle_RotaryVelocity_RPM": round(
                    max(0.0, self.spindle_actual_rpm + noise_rpm), 1
                ),
                "Spindle_Load_Pct": round(
                    max(0.0, self.spindle_load_pct + noise_load), 1
                ),
                "Spindle_Temp_C": round(
                    max(self.ambient_temp_c, self.spindle_temp_c + noise_temp), 2
                ),
                "Vibration_RMS_mm_s": round(
                    max(0.05, self.vibration_rms_mm_s + noise_vib), 2
                ),
                "Coolant_Pressure_Bar": round(
                    max(0.0, self.coolant_pressure_bar + noise_cool), 1
                ),
                "Path_Feedrate_Override_Pct": self.feed_override_pct,
                "Tool_Wear_Pct": round(self.tool_wear_pct, 2),
                "Simulated_Active_Faults": self.get_active_faults(),
            }
