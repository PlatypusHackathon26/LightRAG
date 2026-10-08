from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from app.config import evaluate_metric_status, load_machines_config, resolve_file_path, settings
from app.db import DatabaseManager


@dataclass
class ProposedActionPlan:
    command: str
    params: Dict[str, Any]
    title_vi: str
    subtitle_vi: str
    diagnosis_en: str
    rationale: str
    items: List[Dict[str, Any]]
    timer_seconds: int = 60


@dataclass
class AnalysisResult:
    matched_playbook_id: Optional[str]
    title: str
    root_cause: str
    confidence: float
    severity: str
    diagnosis_vi: str
    diagnosis_en: str
    tags: List[str]
    proposed_action: Optional[ProposedActionPlan]
    timeline_events: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)


class BaseAnalyzer(ABC):
    """
    Standard interface for incident root-cause analyzers.
    In Phase 2, RuleAnalyzer implements this interface.
    In Phase 3, this will be implemented by an LLM-based ReAct Agent with LightRAG.
    """

    @abstractmethod
    async def analyze_incident(
        self,
        machine_id: str,
        trigger_event: Dict[str, Any],
        db_manager: DatabaseManager,
    ) -> AnalysisResult:
        pass


class RuleAnalyzer(BaseAnalyzer):
    """
    Rule-based diagnostic analyzer using expert playbooks configured in config/playbooks.yaml.
    Cross-checks real-time telemetry from Tool API / DB, matches symptom combinations,
    and returns root cause, confidence, citation anchors, and safe action proposals.
    """

    def __init__(self, playbooks_path: str = "config/playbooks.yaml"):
        self.playbooks_path = playbooks_path
        self._playbooks: List[Dict[str, Any]] = []
        self._load_playbooks()

    def _load_playbooks(self):
        resolved = resolve_file_path(self.playbooks_path)
        if not resolved.exists():
            # Fallback to local default if file not found
            self._playbooks = []
            return
        with open(resolved, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            self._playbooks = data.get("playbooks", [])

    async def analyze_incident(
        self,
        machine_id: str,
        trigger_event: Dict[str, Any],
        db_manager: DatabaseManager,
    ) -> AnalysisResult:
        machines_cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
        m_cfg = machines_cfg.machines.get(machine_id)
        if not m_cfg:
            return self._build_unknown_result(machine_id, trigger_event, "Không tìm thấy cấu hình máy.")

        # 1. Fetch latest metrics for the machine
        latest_metrics = await db_manager.get_latest_metrics(machine_id)

        # 2. Evaluate status of each metric
        metric_values: Dict[str, float] = {}
        metric_statuses: Dict[str, str] = {}
        for m_name, conf in m_cfg.metrics.items():
            if m_name in latest_metrics:
                _, val = latest_metrics[m_name]
                metric_values[m_name] = round(val, 1)
                metric_statuses[m_name] = evaluate_metric_status(val, conf)
            else:
                metric_values[m_name] = 0.0
                metric_statuses[m_name] = "normal"

        current_rpm = int(metric_values.get("compressor_rpm", m_cfg.rpm_setpoint))
        error_code = trigger_event.get("error_code", "")

        # 3. Match against playbooks
        matched_playbook: Optional[Dict[str, Any]] = None

        # Priority 1: Check conditions combination
        for pb in self._playbooks:
            conds = pb.get("conditions", {})
            match_all = True
            for m_key, allowed_statuses in conds.items():
                cur_st = metric_statuses.get(m_key, "normal")
                if cur_st not in allowed_statuses:
                    match_all = False
                    break
            if match_all:
                matched_playbook = pb
                break

        # Priority 2: Fallback to error_code match if conditions didn't match directly
        if not matched_playbook and error_code:
            for pb in self._playbooks:
                if error_code in pb.get("target_error_codes", []):
                    matched_playbook = pb
                    break

        if not matched_playbook:
            return self._build_unknown_result(
                machine_id, trigger_event, "Không khớp với bất kỳ kịch bản chẩn đoán (playbook) có sẵn."
            )

        # 4. Interpolate variables into playbook text
        fmt_vars = {
            "machine_id": machine_id,
            "current_rpm": current_rpm,
            "discharge_temp": metric_values.get("discharge_temp", "--"),
            "suction_pressure": metric_values.get("suction_pressure", "--"),
            "discharge_pressure": metric_values.get("discharge_pressure", "--"),
            "condenser_fan_rpm": metric_values.get("condenser_fan_rpm", "--"),
            "vibration": metric_values.get("vibration", "--"),
            "oil_level": metric_values.get("oil_level", "--"),
        }

        diagnosis_vi = matched_playbook["diagnosis_vi"].format(**fmt_vars)
        diagnosis_en = matched_playbook["diagnosis_en"].format(**fmt_vars)
        title_vi = matched_playbook.get("title_vi", f"Sự cố {matched_playbook['name']}")
        subtitle_vi = matched_playbook.get("subtitle_vi", "")

        # Format proposed action
        action_cfg = matched_playbook.get("proposed_action")
        proposed_action_plan: Optional[ProposedActionPlan] = None
        if action_cfg and settings.AGENT_ENABLED:
            action_rationale = action_cfg.get("rationale", "").format(**fmt_vars)
            action_items = []
            for item in action_cfg.get("items", []):
                params_fmt = {}
                for k, v in item.get("params", {}).items():
                    params_fmt[k] = str(v).format(**fmt_vars)
                action_items.append({
                    "type": item.get("type", "plc_command"),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "params": params_fmt,
                })

            proposed_action_plan = ProposedActionPlan(
                command=action_cfg["command"],
                params=action_cfg.get("params", {}),
                title_vi=action_cfg.get("title_vi", "").format(**fmt_vars),
                subtitle_vi=action_cfg.get("subtitle_vi", "").format(**fmt_vars),
                diagnosis_en=diagnosis_en,
                rationale=action_rationale,
                items=action_items,
                timer_seconds=settings.ACTION_TTL_S,
            )

        # 5. Determine severity
        ev_type = trigger_event.get("event_type", "ERROR")
        ev_sev = trigger_event.get("severity", "CRITICAL")
        eta = trigger_event.get("payload", {}).get("eta_to_critical_s")

        if ev_type == "ERROR" or ev_sev == "CRITICAL":
            severity = "critical"
        elif ev_type == "WARNING" and (eta is not None and eta < 300):
            severity = "high"
        elif ev_type == "WARNING":
            severity = "medium"
        else:
            severity = "high"

        # 6. Build timeline events in order
        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.strftime("%H:%M:%S")

        timeline: List[Dict[str, Any]] = []

        # Event 1: anomaly_detected
        timeline.append({
            "id": f"EVT-{int(now_dt.timestamp() * 1000)}-1",
            "timestamp": now_str,
            "type": "anomaly_detected",
            "label": "Phát hiện bất thường vận hành (Anomaly detected)",
            "detail": f"Bệ thử {machine_id} ghi nhận mã lỗi {error_code}: {trigger_event.get('message', '')}",
        })

        # Event 2: correlation
        sensor_details = (
            f"Nhiệt độ xả: {fmt_vars['discharge_temp']}°C | "
            f"Áp suất hút: {fmt_vars['suction_pressure']} bar | "
            f"Áp suất xả: {fmt_vars['discharge_pressure']} bar | "
            f"Quạt: {fmt_vars['condenser_fan_rpm']} rpm | "
            f"Rung: {fmt_vars['vibration']} mm/s | "
            f"Dầu: {fmt_vars['oil_level']}%"
        )
        timeline.append({
            "id": f"EVT-{int(now_dt.timestamp() * 1000)}-2",
            "timestamp": now_str,
            "type": "correlation",
            "label": "Kiểm tra chéo cảm biến (Sensor correlation)",
            "detail": f"Đối chiếu trạng thái đa thông số: {sensor_details}",
        })

        # Event 3: knowledge_retrieved
        citations = matched_playbook.get("citations", [])
        timeline.append({
            "id": f"EVT-{int(now_dt.timestamp() * 1000)}-3",
            "timestamp": now_str,
            "type": "knowledge_retrieved",
            "label": f"Tra cứu tài liệu kỹ thuật DENSO ({len(citations)} tài liệu)",
            "detail": "Truy xuất danh mục chẩn đoán sự cố máy nén điều hòa không khí DENSO.",
            "citations": citations,
        })

        # Event 4: sop_matched
        timeline.append({
            "id": f"EVT-{int(now_dt.timestamp() * 1000)}-4",
            "timestamp": now_str,
            "type": "sop_matched",
            "label": f"Khớp kịch bản: {matched_playbook['name']} (Độ tin cậy: {int(matched_playbook['confidence'] * 100)}%)",
            "detail": diagnosis_vi,
            "citations": citations,
        })

        # Event 5 & 6: action_proposed & waiting_approval
        if proposed_action_plan:
            timeline.append({
                "id": f"EVT-{int(now_dt.timestamp() * 1000)}-5",
                "timestamp": now_str,
                "type": "action_proposed",
                "label": f"Đề xuất hành động: {proposed_action_plan.title_vi}",
                "detail": proposed_action_plan.rationale,
            })
            if settings.AUTONOMY_MODE != "advisory":
                timeline.append({
                    "id": f"EVT-{int(now_dt.timestamp() * 1000)}-6",
                    "timestamp": now_str,
                    "type": "waiting_approval",
                    "label": "Chờ xác nhận người vận hành (HITL Gate)",
                    "detail": f"Hành động đang chờ phê duyệt. Hạn thời gian: {settings.ACTION_TTL_S}s trước khi hết hạn an toàn.",
                })

        return AnalysisResult(
            matched_playbook_id=matched_playbook["id"],
            title=title_vi,
            root_cause=matched_playbook["root_cause"],
            confidence=float(matched_playbook["confidence"]),
            severity=severity,
            diagnosis_vi=diagnosis_vi,
            diagnosis_en=diagnosis_en,
            tags=matched_playbook.get("tags", []),
            proposed_action=proposed_action_plan,
            timeline_events=timeline,
            citations=citations,
        )

    def _build_unknown_result(
        self, machine_id: str, trigger_event: Dict[str, Any], detail_reason: str
    ) -> AnalysisResult:
        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.strftime("%H:%M:%S")
        error_code = trigger_event.get("error_code", "UNKNOWN")

        timeline = [
            {
                "id": f"EVT-{int(now_dt.timestamp() * 1000)}-1",
                "timestamp": now_str,
                "type": "anomaly_detected",
                "label": "Phát hiện bất thường viễn trắc (Anomaly detected)",
                "detail": f"Bệ thử {machine_id} ghi nhận mã {error_code}: {trigger_event.get('message', '')}",
            },
            {
                "id": f"EVT-{int(now_dt.timestamp() * 1000)}-2",
                "timestamp": now_str,
                "type": "correlation",
                "label": "Kiểm tra chéo quy trình (Playbook correlation)",
                "detail": f"Chưa khớp mẫu nhận diện playbook: {detail_reason}. Chỉ phát cảnh báo, không đề xuất lệnh can thiệp.",
            },
        ]

        return AnalysisResult(
            matched_playbook_id=None,
            title=f"Cảnh báo: Bất thường vận hành chưa xác định ({machine_id})",
            root_cause="Chưa xác định",
            confidence=0.30,
            severity="medium",
            diagnosis_vi=f"Máy {machine_id} xuất hiện dấu hiệu bất thường nhưng chưa đủ điều kiện khớp với các kịch bản lỗi chuẩn. {detail_reason}",
            diagnosis_en=f"Machine {machine_id} exhibited anomalous telemetry not matching any existing playbook. {detail_reason}",
            tags=["#unknown", "#unresolved"],
            proposed_action=None,
            timeline_events=timeline,
            citations=[],
        )
