from __future__ import annotations

import random
from typing import Any, Dict, Optional
from machines.base_machine import BaseMachine


class AoiInspection(BaseMachine):
    """Mô phỏng máy kiểm tra quang học 3D (Model: Koh Young Zenith 3D AOI).

    Mô phỏng tỷ lệ phát hiện lỗi sai (False Reject Rate - FRR), độ bẩn thấu kính,
    độ rọi chiếu sáng Moire (Lighting Lux) và tốc độ băng chuyền kiểm tra PCB.
    """

    def __init__(self, event_hub: Optional[Any] = None) -> None:
        super().__init__(
            machine_id="MC-AOI-01",
            machine_type="AOI_INSPECTION",
            model="KOH_YOUNG_ZENITH_3D",
            location="Cell-03_SMT_Inspection",
            event_hub=event_hub,
        )

        # Trạng thái buồng kiểm quang
        self.state = "RUNNING"  # RUNNING, CALIBRATING, LINE_PAUSED, MAINTENANCE
        self.conveyor_speed_m_min = 1.2  # Vận tốc băng chuyền (m/phút)
        self.optics_cleanliness_pct = 98.0  # Độ sạch cụm camera & lăng kính Moire

        # Chỉ số đo lường chất lượng
        self.false_reject_rate_pct = 0.8  # Tỷ lệ từ chối giả (% FRR chuẩn < 1.5%)
        self.illumination_intensity_lux = 18500.0  # Cường độ đèn LED đa hướng
        self.boards_inspected_total = 1420
        self.boards_flagged_defect = 24

    def generate_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            if self.state == "RUNNING":
                # 1. Bám bụi quang học theo thời gian vận hành
                self.optics_cleanliness_pct = max(30.0, self.optics_cleanliness_pct - 0.02)

                # 2. FRR tăng phi tuyến khi quang học bị mờ hoặc đèn chiếu bị lệch
                dirt_penalty = max(0.0, (85.0 - self.optics_cleanliness_pct) * 0.12)
                self.false_reject_rate_pct = 0.6 + dirt_penalty + random.uniform(-0.1, 0.25)

                # 3. Cường độ nguồn sáng LED
                self.illumination_intensity_lux += random.uniform(-40.0, 45.0)
                self.boards_inspected_total += 1
                if random.random() < (self.false_reject_rate_pct / 100.0):
                    self.boards_flagged_defect += 1
            else:
                self.conveyor_speed_m_min = 0.0

            return {
                "Controller_Execution": self.state,
                "False_Reject_Rate_Pct": round(max(0.0, self.false_reject_rate_pct), 2),
                "Optics_Cleanliness_Pct": round(self.optics_cleanliness_pct, 1),
                "Illumination_Intensity_Lux": round(self.illumination_intensity_lux, 0),
                "Conveyor_Speed_m_min": self.conveyor_speed_m_min,
                "Inspection_Cycle_Time_Sec": 4.1,
                "Total_Defect_Count": self.boards_flagged_defect,
            }

    def detect_anomaly(self, telemetry: Dict[str, Any]) -> Optional[str]:
        frr = telemetry.get("False_Reject_Rate_Pct", 0)
        clean = telemetry.get("Optics_Cleanliness_Pct", 100)
        if frr > 4.0:
            return "high false reject rate (threshold drift/optics degraded)"
        if clean < 75.0:
            return "optical lens dirty (requires air blast purge)"
        return None

    def receive_plc_command(
        self, command: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            detail = ""
            if command == "RECALIBRATE_OPTICS":
                # Quy trình tự làm sạch bằng khí nén & hiệu chuẩn bù sáng
                self.state = "CALIBRATING"
                self.optics_cleanliness_pct = 99.5
                self.false_reject_rate_pct = 0.5
                self.state = "RUNNING"
                detail = "Dual pneumatic purge performed; white-balance calibration completed."

            elif command == "PAUSE_INSPECTION_LINE":
                self.state = "LINE_PAUSED"
                self.conveyor_speed_m_min = 0.0
                detail = "Infeed SMEMA conveyor paused to prevent defect batch accumulation."

            elif command == "ADJUST_EXPOSURE":
                exp_offset = float(payload.get("offset_lux", 500.0))
                self.illumination_intensity_lux += exp_offset
                detail = f"LED driver current adjusted; illuminance corrected by {exp_offset} Lux."

            elif command == "RESUME":
                self.state = "RUNNING"
                self.conveyor_speed_m_min = 1.2
                detail = "3D AOI inline inspection resumed."

            else:
                detail = f"Command {command} rejected by AOI software bridge."

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