import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.agent.rag_client import search_manual
from app.commands import validate_command_guardrails
from app.config import evaluate_metric_status, load_machines_config, settings
from app.db import DatabaseManager
from app.monitor import ThresholdMonitorLogic

logger = logging.getLogger("app.agent.tools")


# --- Tool Schemas ---
class SearchManualArgs(BaseModel):
    query: str = Field(..., description="Cụm từ tìm kiếm cụ thể: thiết bị, triệu chứng, linh kiện hoặc quy trình cần tra cứu.")


class GetCurrentStatusArgs(BaseModel):
    machine_id: str = Field(..., description="Mã bệ thử máy nén, ví dụ 'COMP-TB-01'")


class GetHistoryArgs(BaseModel):
    machine_id: str = Field(..., description="Mã bệ thử máy nén")
    minutes: int = Field(default=10, ge=1, le=1440, description="Khoảng thời gian cần xem xu hướng tính bằng phút")


class GetRecentEventsArgs(BaseModel):
    machine_id: str = Field(..., description="Mã bệ thử máy nén")
    minutes: int = Field(default=60, ge=1, le=1440, description="Khoảng thời gian xem sự kiện gần nhất tính bằng phút")


class ProposeActionArgs(BaseModel):
    machine_id: str = Field(..., description="Mã bệ thử máy nén")
    command: Literal["SET_RPM", "STOP_TEST"] = Field(..., description="Lệnh điều khiển nằm trong whitelist an toàn")
    params: Dict[str, Any] = Field(default_factory=dict, description="Tham số lệnh (ví dụ: {'rpm': 1000})")
    rationale: str = Field(..., description="Lý do kỹ thuật và cơ sở dữ liệu đề xuất hành động")


class CreateWorkOrderArgs(BaseModel):
    machine_id: str = Field(..., description="Mã bệ thử máy nén")
    title: str = Field(..., description="Tiêu đề phiếu bảo trì / sửa chữa")
    steps: List[str] = Field(..., description="Danh sách các bước kiểm tra, sửa chữa cụ thể")
    parts: List[str] = Field(default_factory=list, description="Danh mục vật tư, linh kiện, phụ tùng khuyến nghị")
    priority: Literal["low", "medium", "high", "critical"] = Field(default="medium", description="Mức độ ưu tiên")
    citations: List[Dict[str, Any]] = Field(default_factory=list, description="Danh sách trích dẫn tài liệu kỹ thuật")


class FinishArgs(BaseModel):
    root_cause: str = Field(..., description="Kết luận nguyên nhân gốc rễ cụ thể")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Độ tin cậy của chẩn đoán (0.0 đến 1.0)")
    summary: str = Field(..., description="Tóm tắt chẩn đoán kỹ thuật bằng tiếng Việt kèm số liệu đo đạc thực tế")


# --- Tool Executor ---
class AgentToolExecutor:
    """
    Executes Agent tools in a controlled environment.
    Applies guardrails, parameter validation, and formats summaries for ReAct reasoning.
    """

    def __init__(self, db: DatabaseManager, incident_id: Optional[str] = None):
        self.db = db
        self.incident_id = incident_id
        self.action_counter = 0
        self.work_orders_created: List[str] = []
        self.actions_proposed: List[str] = []

    async def execute_tool(self, tool_name: str, raw_args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates arguments against schema and executes tool.
        Returns a dictionary result (safe, sanitized, and compact for LLM context).
        """
        try:
            if tool_name == "search_manual":
                args = SearchManualArgs.model_validate(raw_args)
                return await self.tool_search_manual(args.query)

            elif tool_name == "get_current_status":
                args = GetCurrentStatusArgs.model_validate(raw_args)
                return await self.tool_get_current_status(args.machine_id)

            elif tool_name == "get_history":
                args = GetHistoryArgs.model_validate(raw_args)
                return await self.tool_get_history(args.machine_id, args.minutes)

            elif tool_name == "get_recent_events":
                args = GetRecentEventsArgs.model_validate(raw_args)
                return await self.tool_get_recent_events(args.machine_id, args.minutes)

            elif tool_name == "propose_action":
                args = ProposeActionArgs.model_validate(raw_args)
                return await self.tool_propose_action(
                    args.machine_id, args.command, args.params, args.rationale
                )

            elif tool_name == "create_work_order":
                args = CreateWorkOrderArgs.model_validate(raw_args)
                return await self.tool_create_work_order(
                    args.machine_id,
                    args.title,
                    args.steps,
                    args.parts,
                    args.priority,
                    args.citations,
                )

            elif tool_name == "finish":
                args = FinishArgs.model_validate(raw_args)
                return {
                    "status": "completed",
                    "root_cause": args.root_cause,
                    "confidence": args.confidence,
                    "summary": args.summary,
                }

            else:
                return {
                    "error": f"Công cụ '{tool_name}' không tồn tại trong danh mục cho phép.",
                    "allowed_tools": [
                        "search_manual",
                        "get_current_status",
                        "get_history",
                        "get_recent_events",
                        "propose_action",
                        "create_work_order",
                        "finish",
                    ],
                }
        except Exception as e:
            logger.warning(f"Tool execution failed for {tool_name}: {e}")
            return {"error": f"Lỗi tham số hoặc thực thi công cụ '{tool_name}': {str(e)}"}

    async def tool_search_manual(self, query: str) -> Dict[str, Any]:
        """Calls RAG client to search technical documentation."""
        rag_res = await search_manual(query)
        # Compact representation for LLM prompt
        return {
            "source": rag_res.get("source", "mock"),
            "answer": rag_res.get("answer", ""),
            "citations": rag_res.get("citations", []),
        }

    async def tool_get_current_status(self, machine_id: str) -> Dict[str, Any]:
        """Internal call to get latest machine telemetry and evaluations."""
        machines_cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
        m_cfg = machines_cfg.machines.get(machine_id)
        if not m_cfg:
            return {"error": f"Không tìm thấy cấu hình cho máy '{machine_id}'"}

        latest_metrics = await self.db.get_latest_metrics(machine_id)
        metrics_dict = {}
        abnormal = []

        for m_name, conf in m_cfg.metrics.items():
            if m_name in latest_metrics:
                _, val = latest_metrics[m_name]
                st = evaluate_metric_status(val, conf)
                metrics_dict[m_name] = {
                    "value": val,
                    "unit": conf.unit,
                    "status": st,
                    "direction": conf.direction,
                    "warn": conf.warn,
                    "critical": conf.critical,
                }
                if st in ("warn", "critical"):
                    abnormal.append(f"{conf.label}: {val} {conf.unit} ({st})")
            else:
                metrics_dict[m_name] = {"value": None, "status": "unknown"}

        summary = (
            f"Máy {machine_id} có thông số bất thường: " + ", ".join(abnormal)
            if abnormal
            else f"Máy {machine_id} hoạt động bình thường."
        )

        return {
            "machine_id": machine_id,
            "metrics": metrics_dict,
            "abnormal_metrics": abnormal,
            "summary": summary,
        }

    async def tool_get_history(self, machine_id: str, minutes: int) -> Dict[str, Any]:
        """Internal call to analyze metric trends and slopes."""
        machines_cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
        m_cfg = machines_cfg.machines.get(machine_id)
        if not m_cfg:
            return {"error": f"Không tìm thấy cấu hình cho máy '{machine_id}'"}

        now = datetime.now(timezone.utc)
        since_dt = datetime.fromtimestamp(now.timestamp() - minutes * 60, tz=timezone.utc)
        history = await self.db.get_metrics_history(machine_id, since_dt)
        monitor_logic = ThresholdMonitorLogic()

        trends = {}
        concerns = []

        for m_name, conf in m_cfg.metrics.items():
            series = history.get(m_name, [])
            if series:
                pts = [(ts.timestamp(), val) for ts, val in series]
                analysis = monitor_logic.analyze_series(machine_id, m_name, conf, pts)
                trends[m_name] = {
                    "label": conf.label,
                    "unit": conf.unit,
                    "min": round(analysis.min_value, 2) if analysis.min_value is not None else None,
                    "max": round(analysis.max_value, 2) if analysis.max_value is not None else None,
                    "avg": round(analysis.avg_value, 2) if analysis.avg_value is not None else None,
                    "slope_per_min": round(analysis.slope_per_min, 2),
                    "trend": analysis.trend,
                    "eta_to_critical_s": analysis.eta_to_critical_s,
                }
                if analysis.trend != "stable":
                    concerns.append(f"{conf.label} {analysis.trend} ({analysis.slope_per_min:+.2f} {conf.unit}/phút)")
            else:
                trends[m_name] = {"trend": "no_data"}

        return {
            "machine_id": machine_id,
            "window_minutes": minutes,
            "trends": trends,
            "summary": f"Xu hướng {minutes} phút: " + (", ".join(concerns) if concerns else "ổn định."),
        }

    async def tool_get_recent_events(self, machine_id: str, minutes: int) -> Dict[str, Any]:
        """Fetches recent events and alarm history."""
        now = datetime.now(timezone.utc)
        since_dt = datetime.fromtimestamp(now.timestamp() - minutes * 60, tz=timezone.utc)
        events = await self.db.get_recent_events(machine_id, since_dt)

        simplified = []
        for ev in events[:10]:
            simplified.append({
                "error_code": ev.get("error_code"),
                "event_type": ev.get("event_type"),
                "severity": ev.get("severity"),
                "message": ev.get("message"),
                "repeat_count": ev.get("repeat_count", 1),
                "timestamp": ev.get("timestamp"),
            })

        return {
            "machine_id": machine_id,
            "total_events": len(events),
            "recent_events": simplified,
        }

    async def tool_propose_action(
        self, machine_id: str, command: str, params: Dict[str, Any], rationale: str
    ) -> Dict[str, Any]:
        """
        Validates proposed action through Phase 2 Guardrails.
        Creates action record in pending status (or auto-executes if auto_safe allows).
        """
        # Guardrails check (Independent, deterministic)
        latest_metrics = await self.db.get_latest_metrics(machine_id)
        current_rpm = 1500.0
        if "compressor_rpm" in latest_metrics:
            current_rpm = float(latest_metrics["compressor_rpm"][1])

        is_valid, reason = validate_command_guardrails(
            machine_id=machine_id,
            command=command,
            params=params,
            current_rpm=current_rpm,
            is_auto=False,
        )

        if not is_valid:
            logger.warning(
                f"Agent proposed action REJECTED by guardrails: {command} on {machine_id}. Reason: {reason}"
            )
            return {
                "accepted": False,
                "error": f"Rào chắn an toàn từ chối lệnh '{command}': {reason}",
                "guardrail_status": "REJECTED",
            }

        # Build proposed action record
        action_dict = {
            "incident_id": self.incident_id or "INC-AGENT-TEMP",
            "machine_id": machine_id,
            "command": command,
            "params": params,
            "rationale": rationale,
            "status": "pending",
            "expires_at": datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + settings.ACTION_TTL_S,
                tz=timezone.utc,
            ),
        }

        action_id = await self.db.create_action(action_dict)
        self.actions_proposed.append(action_id)

        # Audit log
        await self.db.insert_audit_log(
            actor="agent",
            action="action_proposed",
            machine_id=machine_id,
            incident_id=self.incident_id,
            details={"action_id": action_id, "command": command, "params": params, "rationale": rationale},
        )

        return {
            "accepted": True,
            "action_id": action_id,
            "status": "pending",
            "message": f"Hành động '{command}' đã vượt qua kiểm tra an toàn và được đưa vào hàng đợi phê duyệt (HITL).",
        }

    async def tool_create_work_order(
        self,
        machine_id: str,
        title: str,
        steps: List[str],
        parts: List[str],
        priority: str,
        citations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Creates work order in work_orders table and logs audit."""
        wo_dict = {
            "incident_id": self.incident_id or "INC-AGENT-TEMP",
            "machine_id": machine_id,
            "title": title,
            "priority": priority,
            "steps": steps,
            "parts": parts,
            "citations": citations,
            "status": "open",
        }

        wo_id = await self.db.create_work_order(wo_dict)
        self.work_orders_created.append(wo_id)

        await self.db.insert_audit_log(
            actor="agent",
            action="work_order_created",
            machine_id=machine_id,
            incident_id=self.incident_id,
            details={"work_order_id": wo_id, "title": title, "priority": priority},
        )

        return {
            "status": "created",
            "work_order_id": wo_id,
            "title": title,
            "message": f"Phiếu bảo trì {wo_id} đã được tạo thành công cho bệ thử {machine_id}.",
        }
