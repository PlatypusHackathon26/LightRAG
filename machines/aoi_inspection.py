from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class AoiInspection(BaseMachine):
    """Mô phỏng máy kiểm tra quang học 3D SMT (Model: Koh Young Zenith 3D AOI)."""

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-AOI-01",
            machine_type="AOI_INSPECTION",
            model="KOH_YOUNG_ZENITH_3D",
            location="Cell-03_SMT_Inspection",
            event_hub=event_hub,
        )

        # 1. Trạng thái điều khiển
        self.state = "RUNNING"
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
        self.last_update_time = time.time()

        # 3. Khai báo danh mục lỗi
        self.active_faults = {
            "OPTICAL_LENS_CONTAMINATION": False,  # Bụi bẩn bám lăng kính Moire
            "LED_DRIVER_DEGRADATION": False,      # Nguồn LED suy hao, giảm sáng
            "SMEMA_CONVEYOR_JAM": False,          # Kẹt bảng mạch trên băng chuyền
        }

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            current_time = time.time()
            dt = max(0.1, min(current_time - self.last_update_time, 2.5))
            self.last_update_time = current_time

            # --- BĂNG CHUYỀN ---
            if self.state == "RUNNING" and not self.active_faults["SMEMA_CONVEYOR_JAM"]:
                target_speed = self.target_conveyor_speed
            else:
                target_speed = 0.0
            self.conveyor_speed_m_min = self.ramp(self.conveyor_speed_m_min, target_speed, dt, 0.2)
            target_cycle = 4.1 if target_speed > 0 else 0.0
            self.inspection_cycle_time_sec = self.ramp(self.inspection_cycle_time_sec, target_cycle, dt, 0.7)

            # --- ĐỘ SẠCH THẤU KÍNH & CHIẾU SÁNG ---
            if self.active_faults["OPTICAL_LENS_CONTAMINATION"]:
                self.optics_cleanliness_pct = max(30.0, self.optics_cleanliness_pct - 0.5 * dt)
            else:
                self.optics_cleanliness_pct = self.ramp(
                    self.optics_cleanliness_pct, self.optics_cleanliness_target_pct,
                    dt, self.optics_recovery_rate,
                )

            if self.active_faults["LED_DRIVER_DEGRADATION"]:
                self.illumination_actual_lux = max(9000.0, self.illumination_actual_lux - 350.0 * dt)
            else:
                self.illumination_actual_lux = self.ramp(
                    self.illumination_actual_lux, self.illumination_target_lux, dt, 350.0
                )

            # --- TỶ LỆ TỪ CHỐI GIẢ (FRR %) ---
            if self.state == "RUNNING":
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
            noise_lux = random.uniform(-15.0, 15.0)
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

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        frr = telemetry.get("False_Reject_Rate_Pct", 0.0)
        clean = telemetry.get("Optics_Cleanliness_Pct", 100.0)
        lux = telemetry.get("Illumination_Intensity_Lux", 18500.0)

        if frr > 4.0:
            return "CRITICAL_HIGH_FALSE_REJECT_RATE"
        if clean < 75.0:
            return "OPTICAL_LENS_DEGRADED"
        if lux < 14000.0:
            return "ILLUMINATION_UNDER_THRESHOLD"
        if frr > 2.0:
            return "WARNING_FRR_ELEVATED"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""

            if command == "RECALIBRATE_OPTICS":
                self.clear_fault("OPTICAL_LENS_CONTAMINATION")
                self.optics_cleanliness_target_pct = 99.0
                self.optics_recovery_rate = 0.5
                detail = "Thổi khí nén tự động và hiệu chuẩn lại cân bằng trắng buồng quang học thành công."

            elif command == "REPLACE_LED_MODULE":
                self.clear_fault("LED_DRIVER_DEGRADATION")
                detail = "Đã bảo trì driver LED; cường độ sáng khôi phục mức tiêu chuẩn."

            elif command == "CLEAR_CONVEYOR_JAM":
                self.clear_fault("SMEMA_CONVEYOR_JAM")
                detail = "Đã gỡ kẹt PCB trên băng chuyền nạp."

            elif command == "PAUSE_INSPECTION_LINE":
                self.state = "LINE_PAUSED"
                detail = "Tạm dừng băng tải nạp để ngăn ngừa phế phẩm dây chuyền SMT."

            elif command == "RESUME":
                self.state = "RUNNING"
                detail = "Tiếp tục chu trình kiểm tra quang học 3D tự động."

            else:
                detail = f"Lệnh '{command}' không hợp lệ trên cầu nối AOI."

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
