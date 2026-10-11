from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple
from machines.specifications import MACHINE_METRICS

ROC_CONFIG: Dict[str, Dict[str, Dict[str, float]]] = {
    "CNC_MILLING": {
        "Spindle_Temp_C": {"window_sec": 60.0, "max_roc_per_min": 2.5},
        "Vibration_RMS_mm_s": {"window_sec": 5.0, "max_roc_per_min": 1.2},
        "Spindle_Load_Pct": {"window_sec": 10.0, "max_roc_per_min": 25.0},
    },
    "ROBOT_ARM": {
        "Joint_3_Current_A": {"window_sec": 5.0, "max_roc_per_min": 4.0},
        "Motor_Temp_C": {"window_sec": 60.0, "max_roc_per_min": 2.0},
    },
    "AMR_VEHICLE": {
        "Battery_Temp_C": {"window_sec": 60.0, "max_roc_per_min": 2.0},
    },
    "AOI_INSPECTION": {
        "False_Reject_Rate_Pct": {"window_sec": 30.0, "max_roc_per_min": 1.5},
    },
    "INJECTION_MOLDING": {
        "Nozzle_Temp_Zone1": {"window_sec": 60.0, "max_roc_per_min": 5.0},
    },
}

# The dashboard and Edge must use the same documented static thresholds.
MACHINE_THRESHOLDS: Dict[str, Dict[str, Dict[str, float]]] = {}
for machine_type, metrics in MACHINE_METRICS.items():
    MACHINE_THRESHOLDS[machine_type] = {}
    for metric in metrics:
        limits = {}
        for bound in ("min", "max"):
            value = metric.get(bound, metric.get("critical_" + bound))
            if value is not None:
                limits[bound] = value
        limits.update(ROC_CONFIG.get(machine_type, {}).get(metric["key"], {}))
        if limits:
            MACHINE_THRESHOLDS[machine_type][metric["key"]] = limits

# Below this a reading is still on its way up to the operating point: nominal minus three times
# the sensor noise.
WARM_UP_BELOW: Dict[str, Dict[str, float]] = {
    t: {m["key"]: m["nominal"] - 3 * m.get("noise", 0) for m in metrics} for t, metrics in MACHINE_METRICS.items()
}


class TelemetryReceiver:
    def __init__(
        self,
        event_hub: Optional[Any] = None,
        heartbeat_interval_sec: float = 10.0,
        alert_cooldown_sec: float = 60.0,
        settle_sec: float = 60.0,
    ) -> None:
        self.event_hub = event_hub
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.alert_cooldown_sec = alert_cooldown_sec
        # After START a machine's readings climb from rest to their operating values; only ceilings
        # are checked until it has run this long, so the climb is not mistaken for a fault.
        self.settle_sec = settle_sec
        self._running_since: Dict[str, float] = {}

        # Lưu lịch sử mẫu: {machine_id: {param_name: deque([(monotonic_ts, value), ...])}}
        self._history: Dict[str, Dict[str, Deque[Tuple[float, float]]]] = {}

        # Mốc thời gian gửi bản tin gần nhất: {machine_id: float (monotonic)}
        self._last_sent: Dict[str, float] = {}

        # Sổ ghi cooldown theo từng thông số: {machine_id: {param_name: float (monotonic)}}
        self._last_alert_time: Dict[str, Dict[str, float]] = {}

    def process(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not event or event.get("event_type") != "telemetry":
            return None

        machine_id = event.get("machine_id", "UNKNOWN")
        machine_type = event.get("machine_type", "")
        payload = event.get("payload", {})
        now_mono = time.monotonic()
        now_iso = datetime.now().isoformat()

        # 1. Phát hiện toàn bộ bất thường (ngưỡng tĩnh + tốc độ thay đổi ROC)
        raw_anomalies = self._detect_anomalies(machine_id, machine_type, payload, now_mono)

        # 2. Bộ lọc chống spam (Cooldown)
        active_anomalies: List[Dict[str, Any]] = []
        if machine_id not in self._last_alert_time:
            self._last_alert_time[machine_id] = {}

        for anom in raw_anomalies:
            param = anom["param"]
            last_alert = self._last_alert_time[machine_id].get(param)

            if last_alert is None or (now_mono - last_alert) >= self.alert_cooldown_sec:
                active_anomalies.append(anom)
                self._last_alert_time[machine_id][param] = now_mono

        # TRƯỜNG HỢP 1: Có bất thường mới chưa bị cooldown -> Bắn cảnh báo ALERT ngay lập tức
        if active_anomalies:
            alert_event = {
                **event,
                "label": "alert",
                "anomalies": active_anomalies,
                "timestamp": now_iso,
            }
            self._last_sent[machine_id] = now_mono
            if self.event_hub is not None:
                self.event_hub.publish(alert_event)
            return alert_event

        # TRƯỜNG HỢP 2: Máy đang có bất thường nhưng bị chặn bởi Cooldown
        # Không được gửi nhãn 'normal' để tránh hiểu lầm máy đã an toàn
        if raw_anomalies:
            return None

        # TRƯỜNG HỢP 3: Thông số hoàn toàn bình thường -> Gửi heartbeat định kỳ 10s
        last_time = self._last_sent.get(machine_id)
        if last_time is None or (now_mono - last_time) >= self.heartbeat_interval_sec:
            normal_event = {
                **event,
                "label": "normal",
                "timestamp": now_iso,
            }
            self._last_sent[machine_id] = now_mono
            if self.event_hub is not None:
                self.event_hub.publish(normal_event)
            return normal_event

        return None

    def _detect_anomalies(
        self, machine_id: str, machine_type: str, payload: Dict[str, Any], now_mono: float
    ) -> List[Dict[str, Any]]:
        threshold_config = MACHINE_THRESHOLDS.get(machine_type, {})
        if not threshold_config:
            return []

        anomalies: List[Dict[str, Any]] = []
        state = payload.get("Controller_Execution", "RUNNING")

        # Which checks apply depends on what the machine is doing:
        # - isolated or under repair (LOCKED_OUT, MAINTENANCE, E_STOP): nothing - it is in a known safe state;
        # - stopped, paused, charging, starting, or running for less than settle_sec: ceilings only
        #   (overheating still matters; a pressure or speed at zero is what stopping means);
        # - running and settled: every limit plus rate of change.
        if state != "RUNNING":
            self._running_since.pop(machine_id, None)
        elif machine_id not in self._running_since:
            self._running_since[machine_id] = now_mono
        settled = state == "RUNNING" and now_mono - self._running_since[machine_id] >= self.settle_sec
        if not settled:
            self._history.pop(machine_id, None)   # rate of change restarts from settled readings
        if state in ("LOCKED_OUT", "MAINTENANCE", "E_STOP"):
            return []

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
            static_violated = False
            if "max" in limits and current_val > limits["max"]:
                anomalies.append({
                    "param": param,
                    "value": current_val,
                    "reason": f"Vượt ngưỡng trần cho phép ({current_val} > {limits['max']})",
                })
                static_violated = True
            elif settled and "min" in limits and current_val < limits["min"]:
                anomalies.append({
                    "param": param,
                    "value": current_val,
                    "reason": f"Dưới ngưỡng sàn quy định ({current_val} < {limits['min']})",
                })
                static_violated = True

            # 2. So khớp tốc độ biến thiên theo thời gian (ROC)
            max_roc = limits.get("max_roc_per_min")
            if max_roc is not None and settled:
                window_sec = limits.get("window_sec", 60.0)

                if param not in self._history[machine_id]:
                    self._history[machine_id][param] = deque()

                queue = self._history[machine_id][param]
                queue.append((now_mono, current_val))

                while queue and (now_mono - queue[0][0]) > window_sec:
                    queue.popleft()

                if not static_violated and len(queue) >= 2:
                    oldest_time, oldest_val = queue[0]
                    duration_sec = now_mono - oldest_time

                    # Chờ đủ phần lớn cửa sổ để nhiễu cảm biến ngắn hạn không bị
                    # khuếch đại thành ROC/phút và kích hoạt Agent sai.
                    if duration_sec >= (window_sec * 0.8):
                        roc_per_min = ((current_val - oldest_val) / duration_sec) * 60.0
                        # A rise that started below the normal operating point is the machine
                        # warming back up (after a restart), not a fault.
                        floor = WARM_UP_BELOW.get(machine_type, {}).get(param)
                        warming_up = floor is not None and oldest_val < floor
                        if roc_per_min > max_roc and not warming_up:
                            anomalies.append({
                                "param": param,
                                "value": current_val,
                                "roc_per_min": round(roc_per_min, 2),
                                "reason": f"Tốc độ tăng quá nhanh (+{round(roc_per_min, 2)}/phút > {max_roc}/phút)",
                            })

        return anomalies
