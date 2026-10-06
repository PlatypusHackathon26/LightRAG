from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

MACHINE_THRESHOLDS: Dict[str, Dict[str, Dict[str, float]]] = {
    "CNC_MILLING": {
        "Spindle_Temp_C": {"max": 85.0, "window_sec": 60.0, "max_roc_per_min": 2.5},
        "Vibration_RMS_mm_s": {"max": 7.1, "window_sec": 5.0, "max_roc_per_min": 1.2},
        "Spindle_Load_Pct": {"max": 115.0, "window_sec": 10.0, "max_roc_per_min": 25.0},
        "Coolant_Pressure_Bar": {"min": 10.0, "max": 40.0},
    },
    "INJECTION_MOLDING": {
        "Nozzle_Temp_Zone1": {"min": 200.0, "max": 240.0, "window_sec": 60.0, "max_roc_per_min": 5.0},
        "Clamping_Pressure_Bar": {"min": 120.0, "max": 160.0},
    },
    "ROBOT_ARM": {
        "Joint_3_Current_A": {"max": 18.0, "window_sec": 5.0, "max_roc_per_min": 4.0},
        "Motor_Temp_C": {"max": 75.0, "window_sec": 60.0, "max_roc_per_min": 2.0},
    },
    "AOI_INSPECTION": {
        "False_Reject_Rate_Pct": {"max": 4.0, "window_sec": 30.0, "max_roc_per_min": 1.5},
    },
    "AMR_VEHICLE": {
        "Battery_Pct": {"min": 20.0},
    },
}


class TelemetryReceiver:
    def __init__(
        self,
        event_hub: Optional[Any] = None,
        heartbeat_interval_sec: float = 10.0,
        alert_cooldown_sec: float = 60.0,
    ) -> None:
        self.event_hub = event_hub
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.alert_cooldown_sec = alert_cooldown_sec

        # Lưu lịch sử mẫu: {machine_id: {param_name: deque([(timestamp, value), ...])}}
        self._history: Dict[str, Dict[str, Deque[Tuple[datetime, float]]]] = {}

        # Mốc thời gian gửi bản tin gần nhất (bất kể alert hay normal): {machine_id: datetime}
        self._last_sent: Dict[str, datetime] = {}

        # Sổ ghi cooldown theo từng thông số: {machine_id: {param_name: datetime}}
        self._last_alert_time: Dict[str, Dict[str, datetime]] = {}

    def process(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not event or event.get("event_type") != "telemetry":
            return None

        machine_id = event.get("machine_id", "UNKNOWN")
        machine_type = event.get("machine_type", "")
        payload = event.get("payload", {})
        now = datetime.now()

        # 1. Phát hiện toàn bộ bất thường thô
        raw_anomalies = self._detect_anomalies(machine_id, machine_type, payload)

        # 2. Bộ lọc chống spam (Cooldown): chỉ giữ lại bất thường chưa cảnh báo gần đây
        active_anomalies: List[Dict[str, Any]] = []
        if machine_id not in self._last_alert_time:
            self._last_alert_time[machine_id] = {}

        for anom in raw_anomalies:
            param = anom["param"]
            last_alert = self._last_alert_time[machine_id].get(param)

            # Được báo nếu: chưa từng báo trước đó HOẶC đã trôi qua thời gian cooldown
            if last_alert is None or (now - last_alert).total_seconds() >= self.alert_cooldown_sec:
                active_anomalies.append(anom)
                self._last_alert_time[machine_id][param] = now

        # TRƯỜNG HỢP A: Có bất thường hợp lệ (không bị chặn cooldown) -> Bắn nhãn ALERT ngay
        if active_anomalies:
            alert_event = {
                **event,
                "label": "alert",
                "anomalies": active_anomalies,
                "timestamp": now.isoformat(),
            }
            self._last_sent[machine_id] = now

            if self.event_hub is not None:
                self.event_hub.publish(alert_event)
            return alert_event

        # TRƯỜNG HỢP B: Thông số bình thường (hoặc đang trong cooldown) -> Gửi nhãn NORMAL định kỳ 10s
        last_time = self._last_sent.get(machine_id)
        if last_time is None or (now - last_time).total_seconds() >= self.heartbeat_interval_sec:
            normal_event = {
                **event,
                "label": "normal",
                "timestamp": now.isoformat(),
            }
            self._last_sent[machine_id] = now

            if self.event_hub is not None:
                self.event_hub.publish(normal_event)
            return normal_event

        return None

    def _detect_anomalies(
        self, machine_id: str, machine_type: str, payload: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        threshold_config = MACHINE_THRESHOLDS.get(machine_type, {})
        if not threshold_config:
            return []

        now = datetime.now()
        anomalies: List[Dict[str, Any]] = []

        if machine_id not in self._history:
            self._history[machine_id] = {}

        for param, limits in threshold_config.items():
            if param not in payload:
                continue

            val = payload[param]
            if not isinstance(val, (int, float)):
                continue

            current_val = float(val)

            # 1. So khớp ngưỡng tĩnh cứng
            if "max" in limits and current_val > limits["max"]:
                anomalies.append({
                    "param": param,
                    "value": current_val,
                    "reason": f"Vượt ngưỡng trần {limits['max']}",
                })
            elif "min" in limits and current_val < limits["min"]:
                anomalies.append({
                    "param": param,
                    "value": current_val,
                    "reason": f"Dưới ngưỡng sàn {limits['min']}",
                })

            # 2. So khớp tốc độ biến thiên theo thời gian (Đạo hàm ROC)
            max_roc = limits.get("max_roc_per_min")
            if max_roc is not None:
                window_sec = limits.get("window_sec", 60.0)

                if param not in self._history[machine_id]:
                    self._history[machine_id][param] = deque()

                queue = self._history[machine_id][param]
                queue.append((now, current_val))

                # Dọn các mẫu cũ nằm ngoài phạm vi cửa sổ trượt
                while queue and (now - queue[0][0]).total_seconds() > window_sec:
                    queue.popleft()

                # Cần tích lũy tối thiểu 2 điểm và phủ tối thiểu 40% cửa sổ để tránh nhiễu
                if len(queue) >= 2:
                    oldest_time, oldest_val = queue[0]
                    duration_sec = (now - oldest_time).total_seconds()

                    if duration_sec >= (window_sec * 0.4):
                        roc_per_min = ((current_val - oldest_val) / duration_sec) * 60.0
                        if roc_per_min > max_roc:
                            anomalies.append({
                                "param": param,
                                "value": current_val,
                                "roc_per_min": round(roc_per_min, 2),
                                "reason": f"Tăng nhanh bất thường ({round(roc_per_min, 2)}/phút > {max_roc}/phút)",
                            })

        return anomalies

# nếu ko có gì bất thường thì cứ 10s gửi 1 lần nhãn 'normal' để giám sát trạng thái máy
# nếu bất thường về trạng thái tính hoặc tốc độ biến thiên thì gán nhãn alert và gửi ngay. (sau mỗi lần gửi alert thì đợi 60 mới có alert tiếp)