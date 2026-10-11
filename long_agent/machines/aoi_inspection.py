from __future__ import annotations

import random
from typing import Any, Dict, Optional

from machines import commands as cmd
from machines.base_machine import BaseMachine
from machines.commands import CommandSpec


class AoiInspection(BaseMachine):
    """Mô phỏng máy kiểm tra quang học 3D SMT (Model: Koh Young Zenith 3D AOI)."""

    MACHINE_TYPE = "AOI_INSPECTION"
    LIGHTS_OFF_STATES = frozenset({cmd.LOCKED_OUT, cmd.MAINTENANCE, cmd.E_STOP})

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-AOI-01",
            machine_type="AOI_INSPECTION",
            model="KOH_YOUNG_ZENITH_3D",
            location="Cell-03_SMT_Inspection",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
        self.target_conveyor_speed = 1.2
        self.illumination_target_lux = 18500.0

        # 2. Trạng thái vật lý
        self.conveyor_speed_m_min = self.nominal("Conveyor_Speed_m_min")
        self.optics_cleanliness_pct = self.nominal("Optics_Cleanliness_Pct")
        self.optics_cleanliness_target_pct = 99.0
        self.optics_recovery_rate = 0.1
        self.illumination_actual_lux = self.nominal("Illumination_Intensity_Lux")
        self.false_reject_rate_pct = self.nominal("False_Reject_Rate_Pct")
        self.inspection_cycle_time_sec = 4.1
        self._inspection_progress = 0.0
        self.boards_inspected_total = 1500
        self.boards_flagged_defect = 25

        # 3. Khai báo danh mục lỗi
        self.active_faults = {
            "OPTICAL_LENS_CONTAMINATION": False,  # Bụi bẩn bám lăng kính Moire
            "LED_DRIVER_DEGRADATION": False,      # Nguồn LED suy hao, giảm sáng
            "SMEMA_CONVEYOR_JAM": False,          # Kẹt bảng mạch trên băng chuyền
        }

    @classmethod
    def command_specs(cls) -> Dict[str, CommandSpec]:
        specs = cmd.control_commands(hold_aliases=("PAUSE_INSPECTION_LINE", "PAUSE_LINE"),
                                     hold_desc="Tạm dừng băng tải nạp, giữ buồng quang học sẵn sàng")
        for spec in (
            cmd.repair("RECALIBRATE_OPTICS", "OPTICAL_LENS_CONTAMINATION",
                       "Vệ sinh lăng kính và hiệu chuẩn lại buồng quang học", 30,
                       ("CLEAN_OPTICS", "CLEAN_LENS", "CALIBRATE_OPTICS")),
            cmd.repair("REPLACE_LED_MODULE", "LED_DRIVER_DEGRADATION", "Thay module / driver đèn LED", 40,
                       ("REPLACE_LED", "REPLACE_LED_DRIVER")),
            cmd.repair("CLEAR_CONVEYOR_JAM", "SMEMA_CONVEYOR_JAM", "Gỡ bảng mạch kẹt trên băng chuyền", 20,
                       ("CLEAR_JAM", "UNJAM_CONVEYOR", "GO_KET_BANG_TAI")),
        ):
            specs[spec.name] = spec
        return specs

    def on_repaired(self, name: str) -> None:
        if name == "RECALIBRATE_OPTICS":
            self.optics_recovery_rate = 0.5   # the next inspections re-measure a clean lens quickly

    def at_rest(self) -> bool:
        return self.conveyor_speed_m_min < 0.05

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            dt = self._tick()

            # --- BĂNG CHUYỀN ---
            target_speed = (self.target_conveyor_speed
                            if self.running and not self.active_faults["SMEMA_CONVEYOR_JAM"] else 0.0)
            self.conveyor_speed_m_min = self.ramp(self.conveyor_speed_m_min, target_speed, dt, 0.2)
            target_cycle = 4.1 if target_speed > 0 else 0.0
            self.inspection_cycle_time_sec = self.ramp(self.inspection_cycle_time_sec, target_cycle, dt, 0.7)

            # --- ĐỘ SẠCH THẤU KÍNH ---
            if self.active_faults["OPTICAL_LENS_CONTAMINATION"]:
                self.optics_recovery_rate = 0.1
                self.optics_cleanliness_pct = max(30.0, self.optics_cleanliness_pct - 0.5 * dt)
            else:
                self.optics_cleanliness_pct = self.ramp(
                    self.optics_cleanliness_pct, self.optics_cleanliness_target_pct, dt, self.optics_recovery_rate,
                )

            # --- CHIẾU SÁNG: tắt khi khoá an toàn / bảo trì / dừng khẩn cấp ---
            if self.state in self.LIGHTS_OFF_STATES:
                self.illumination_actual_lux = max(0.0, self.illumination_actual_lux - 3000.0 * dt)
            else:
                # A degraded LED driver only reaches 9000 Lux.
                target_lux = 9000.0 if self.active_faults["LED_DRIVER_DEGRADATION"] else self.illumination_target_lux
                self.illumination_actual_lux = self.ramp(self.illumination_actual_lux, target_lux, dt, 350.0)

            # --- TỶ LỆ TỪ CHỐI GIẢ (FRR %): chỉ đo khi đang kiểm tra ---
            if self.running:
                dirt_penalty = max(0.0, (88.0 - self.optics_cleanliness_pct) * 0.18)
                lux_penalty = max(0.0, abs(18500.0 - self.illumination_actual_lux) / 500.0 * 0.4)
                target_frr = 0.6 + dirt_penalty + lux_penalty
                self.false_reject_rate_pct = self.approach(self.false_reject_rate_pct, target_frr, dt, 4.0)

                # Nominal throughput is one board per second; no boards move during a jam.
                if target_speed > 0.0 and self.conveyor_speed_m_min > 0.0:
                    self._inspection_progress += dt * self.conveyor_speed_m_min / 1.2
                    completed = int(self._inspection_progress)
                    self._inspection_progress -= completed
                    self.boards_inspected_total += completed
                    for _ in range(completed):
                        if random.random() < (self.false_reject_rate_pct / 100.0):
                            self.boards_flagged_defect += 1

            noise_frr = random.uniform(-0.04, 0.04)
            noise_lux = random.uniform(-15.0, 15.0) if self.illumination_actual_lux > 100.0 else 0.0
            noise_clean = random.uniform(-0.1, 0.1)
            noise_conv = random.uniform(-0.02, 0.02) if self.conveyor_speed_m_min > 0.0 else 0.0

            return {
                "Controller_Execution": self.state,
                "False_Reject_Rate_Pct": round(max(0.0, self.false_reject_rate_pct + noise_frr), 2),
                "Optics_Cleanliness_Pct": round(max(0.0, self.optics_cleanliness_pct + noise_clean), 2),
                "Illumination_Intensity_Lux": round(max(0.0, self.illumination_actual_lux + noise_lux), 0),
                "Conveyor_Speed_m_min": round(max(0.0, self.conveyor_speed_m_min + noise_conv), 2),
                "Inspection_Cycle_Time_Sec": round(self.inspection_cycle_time_sec, 2),
                "Total_Inspected_Count": self.boards_inspected_total,
                "Total_Defect_Count": self.boards_flagged_defect,
                "Simulated_Active_Faults": self.get_active_faults(),
            }
