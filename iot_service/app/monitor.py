import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.config import MetricConfig, load_machines_config, settings
from app.db import DatabaseManager
from app.stream import broadcaster

logger = logging.getLogger("app.monitor")


@dataclass
class MetricAnalysisResult:
    metric_name: str
    current_value: float
    current_status: Literal["normal", "warn", "critical"]
    slope_per_min: float
    trend: Literal["rising", "falling", "stable"]
    eta_to_critical_s: Optional[float]
    min_value: float
    max_value: float
    avg_value: float
    is_in_alarm: bool
    should_emit_warning: bool
    warning_code: Optional[str]
    warning_message: Optional[str]


class ThresholdMonitorLogic:
    """
    Pure logic for threshold monitoring, hysteresis tracking, and trend analysis.
    Decoupled from DB/Network I/O for unit testing.
    """

    def __init__(self, warn_trigger_samples: int = 3, clear_hysteresis_samples: int = 6):
        self.warn_trigger_samples = warn_trigger_samples
        self.clear_hysteresis_samples = clear_hysteresis_samples

        # State tracking: (machine_id, metric_name) -> {"in_alarm": bool}
        self.states: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def get_or_create_state(self, machine_id: str, metric: str) -> Dict[str, Any]:
        key = (machine_id, metric)
        if key not in self.states:
            self.states[key] = {
                "in_alarm": False,
            }
        return self.states[key]

    @staticmethod
    def calculate_linear_regression(samples: List[Tuple[float, float]]) -> Tuple[float, float]:
        """
        Computes slope (per second) and R^2 from list of (timestamp_seconds, value).
        """
        n = len(samples)
        if n < 2:
            return 0.0, 1.0

        ts_list = [s[0] for s in samples]
        ys_list = [s[1] for s in samples]

        t_mean = sum(ts_list) / n
        y_mean = sum(ys_list) / n

        denom = sum((t - t_mean) ** 2 for t in ts_list)
        if denom == 0:
            return 0.0, 1.0

        numer = sum((ts_list[i] - t_mean) * (ys_list[i] - y_mean) for i in range(n))
        slope = numer / denom
        return slope, 1.0

    def analyze_series(
        self,
        machine_id: str,
        metric_name: str,
        metric_config: MetricConfig,
        samples: List[Tuple[float, float]],  # List of (epoch_seconds, value)
    ) -> MetricAnalysisResult:
        """
        Analyzes a time series of values for one metric.
        samples is ordered chronologically [(t0, v0), (t1, v1), ...]
        """
        if not samples:
            return MetricAnalysisResult(
                metric_name=metric_name,
                current_value=0.0,
                current_status="normal",
                slope_per_min=0.0,
                trend="stable",
                eta_to_critical_s=None,
                min_value=0.0,
                max_value=0.0,
                avg_value=0.0,
                is_in_alarm=False,
                should_emit_warning=False,
                warning_code=None,
                warning_message=None,
            )

        values = [s[1] for s in samples]
        min_v = round(min(values), 2)
        max_v = round(max(values), 2)
        avg_v = round(sum(values) / len(values), 2)
        latest_val = round(values[-1], 2)

        # 1. Slope & Trend calculation (in per-minute unit)
        slope_per_sec, _ = self.calculate_linear_regression(samples)
        slope_per_min = round(slope_per_sec * 60.0, 3)

        if abs(slope_per_min) < 0.05:
            trend: Literal["rising", "falling", "stable"] = "stable"
        elif slope_per_min > 0:
            trend = "rising"
        else:
            trend = "falling"

        # 2. ETA to critical
        eta_to_critical_s: Optional[float] = None
        crit = metric_config.critical
        direction = metric_config.direction
        warn = metric_config.warn

        if crit is not None and direction != "info":
            if direction == "above":
                if latest_val >= crit:
                    eta_to_critical_s = 0.0
                elif slope_per_sec > 0:
                    needed = crit - latest_val
                    eta_to_critical_s = round(needed / slope_per_sec, 1)
            elif direction == "below":
                if latest_val <= crit:
                    eta_to_critical_s = 0.0
                elif slope_per_sec < 0:
                    needed = latest_val - crit
                    eta_to_critical_s = round(needed / abs(slope_per_sec), 1)

        # 3. Trailing consecutive violations / normals inspection for hysteresis
        def is_val_violating(v: float) -> bool:
            if direction == "above":
                return warn is not None and v >= warn
            elif direction == "below":
                return warn is not None and v <= warn
            return False

        trailing_violations = 0
        for v in reversed(values):
            if is_val_violating(v):
                trailing_violations += 1
            else:
                break

        trailing_normals = 0
        for v in reversed(values):
            if not is_val_violating(v):
                trailing_normals += 1
            else:
                break

        state = self.get_or_create_state(machine_id, metric_name)
        was_in_alarm = state["in_alarm"]

        if not was_in_alarm:
            if trailing_violations >= self.warn_trigger_samples:
                state["in_alarm"] = True
        else:
            if trailing_normals >= self.clear_hysteresis_samples:
                state["in_alarm"] = False

        is_in_alarm = state["in_alarm"]
        should_emit_warning = is_in_alarm and is_val_violating(latest_val)

        # Current status string
        current_status: Literal["normal", "warn", "critical"] = "normal"
        if crit is not None and ((direction == "above" and latest_val >= crit) or (direction == "below" and latest_val <= crit)):
            current_status = "critical"
        elif is_val_violating(latest_val):
            current_status = "warn"

        warning_code = None
        warning_message = None
        if should_emit_warning and direction != "info":
            suffix = "HIGH" if direction == "above" else "LOW"
            warning_code = f"WARN_{metric_name.upper()}_{suffix}"
            eta_str = f", dự kiến chạm mức nguy hiểm sau {int(eta_to_critical_s)}s" if eta_to_critical_s and eta_to_critical_s > 0 else ""
            warning_message = (
                f"Cảnh báo sớm: {metric_config.label} đạt {latest_val} {metric_config.unit} "
                f"(xu hướng: {trend}, {slope_per_min:+.2f}/phút{eta_str})"
            )

        return MetricAnalysisResult(
            metric_name=metric_name,
            current_value=latest_val,
            current_status=current_status,
            slope_per_min=slope_per_min,
            trend=trend,
            eta_to_critical_s=eta_to_critical_s,
            min_value=min_v,
            max_value=max_v,
            avg_value=avg_v,
            is_in_alarm=is_in_alarm,
            should_emit_warning=should_emit_warning,
            warning_code=warning_code,
            warning_message=warning_message,
        )


class ThresholdMonitor:
    def __init__(
        self,
        db_manager: DatabaseManager,
        poll_interval_s: float = 5.0,
        lifecycle_manager: Optional[Any] = None,
    ):
        self.db_manager = db_manager
        self.poll_interval_s = poll_interval_s
        self.lifecycle_manager = lifecycle_manager
        self.logic = ThresholdMonitorLogic()
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.machines_cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)

    async def start(self):
        self.running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Threshold Monitor started.")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Threshold Monitor stopped.")

    async def _monitor_loop(self):
        while self.running:
            try:
                await self.check_all_machines()
            except Exception as e:
                logger.error(f"Error in Threshold Monitor loop: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval_s)

    async def check_all_machines(self):
        now = datetime.now(timezone.utc)
        since_time = datetime.fromtimestamp(now.timestamp() - 300, tz=timezone.utc)  # Last 5 minutes

        for m_id, m_cfg in self.machines_cfg.machines.items():
            history = await self.db_manager.get_metrics_history(m_id, since_time)
            for metric_name, m_info in m_cfg.metrics.items():
                if metric_name not in history or not history[metric_name]:
                    continue

                pts = [(ts.timestamp(), val) for ts, val in history[metric_name]]
                res = self.logic.analyze_series(m_id, metric_name, m_info, pts)

                if res.should_emit_warning and res.warning_code:
                    severity = "HIGH" if (res.eta_to_critical_s is not None and res.eta_to_critical_s < 300) else "MEDIUM"
                    event_payload = {
                        "event_id": str(uuid.uuid4()),
                        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "machine_id": m_id,
                        "source": "monitor",
                        "event_type": "WARNING",
                        "severity": severity,
                        "error_code": res.warning_code,
                        "message": res.warning_message,
                        "payload": {
                            "trend": res.trend,
                            "slope_per_min": res.slope_per_min,
                            "eta_to_critical_s": res.eta_to_critical_s,
                            "current_value": res.current_value,
                        },
                    }
                    is_new, canon_id = await self.db_manager.insert_or_dedup_event(event_payload)
                    if is_new:
                        logger.warning(
                            f"[Monitor Early Warning] {m_id} {res.warning_code}: {res.warning_message}"
                        )
                        # Broadcast early warning via SSE
                        try:
                            broadcaster.broadcast_event(event_payload)
                        except Exception as m_ex:
                            logger.error(f"Error broadcasting monitor SSE event: {m_ex}")
                        if self.lifecycle_manager:
                            try:
                                await self.lifecycle_manager.handle_inbound_event(event_payload)
                            except Exception as ex:
                                logger.error(f"Error notifying lifecycle manager from monitor: {ex}", exc_info=True)
