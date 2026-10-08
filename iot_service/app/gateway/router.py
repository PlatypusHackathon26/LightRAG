import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from pydantic import BaseModel, Field

from app.config import evaluate_metric_status, load_machines_config, settings
from app.db import DatabaseManager
from app.gateway.actions import ActionService
from app.gateway.lifecycle import IncidentLifecycleManager

logger = logging.getLogger("app.gateway.router")

router = APIRouter(prefix="/agent", tags=["Agent Gateway"])


# -----------------------------------------------------------------------------
# Pydantic Schemas strictly matching lightrag_webui/src/features/agentic/types/agentic.ts
# -----------------------------------------------------------------------------

class CitationSchema(BaseModel):
    id: str
    documentId: str
    documentName: str
    pages: Optional[str] = None
    excerpt: Optional[str] = None


class TelemetryPointSchema(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    threshold: Optional[float] = None
    isAnomalous: bool
    trend: Literal["up", "down", "stable"]
    direction: Optional[Literal["above", "below", "info"]] = None


class TelemetrySnapshotSchema(BaseModel):
    deviceId: str
    deviceName: str
    timestamp: str
    points: List[TelemetryPointSchema]
    predictionHorizonMin: Optional[int] = None


class ProposedActionItemSchema(BaseModel):
    type: Literal["plc_command", "inventory", "notify", "escalate"]
    title: str
    description: str
    params: Dict[str, str]


class ProposedActionSchema(BaseModel):
    id: str
    incidentId: str
    titleVi: str
    subtitleVi: str
    diagnosisEn: str
    items: List[ProposedActionItemSchema]
    timerSeconds: int
    createdAt: str


class ActionExecutionSchema(BaseModel):
    actionId: str
    status: Literal["waiting", "executing", "success", "rejected", "expired"]
    executedAt: Optional[str] = None
    ackCode: Optional[str] = None
    responseText: Optional[str] = None
    rejectedAt: Optional[str] = None
    expiredAt: Optional[str] = None


class IncidentSchema(BaseModel):
    id: str
    conversationId: str
    device: str
    alarm: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    status: Literal["active", "awaiting_approval", "resolved", "acknowledged", "closed"]
    timestamp: str
    resolvedAt: Optional[str] = None
    telemetry: Optional[TelemetrySnapshotSchema] = None
    proposedAction: Optional[ProposedActionSchema] = None
    actionExecution: Optional[ActionExecutionSchema] = None
    tags: Optional[List[str]] = None


class AgentChatRequestSchema(BaseModel):
    conversationId: str
    message: str


class AgentChatResponseSchema(BaseModel):
    content: str
    citations: Optional[List[Dict[str, str]]] = None


class ApproveResponseSchema(BaseModel):
    ack: str


# -----------------------------------------------------------------------------
# Dependency helpers
# -----------------------------------------------------------------------------

def get_db() -> DatabaseManager:
    from app.db import db_manager
    return db_manager


def get_action_service(db: DatabaseManager = Depends(get_db)) -> ActionService:
    from app.gateway.actions import action_service
    action_service.db = db
    return action_service


async def build_telemetry_snapshot(machine_id: str, db: DatabaseManager) -> TelemetrySnapshotSchema:
    machines_cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    m_cfg = machines_cfg.machines.get(machine_id)
    device_name = m_cfg.name if m_cfg else machine_id

    latest_metrics = await db.get_latest_metrics(machine_id)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    points: List[TelemetryPointSchema] = []
    if m_cfg:
        for m_key, conf in m_cfg.metrics.items():
            if m_key in latest_metrics:
                _, val = latest_metrics[m_key]
                st = evaluate_metric_status(val, conf)
                is_anom = (st != "normal")
            else:
                val = 0.0
                is_anom = False

            # Set threshold based on direction (warn threshold)
            thresh = conf.warn if conf.warn is not None else conf.critical

            points.append(
                TelemetryPointSchema(
                    key=m_key,
                    label=conf.label,
                    value=round(val, 1),
                    unit=conf.unit,
                    threshold=thresh,
                    isAnomalous=is_anom,
                    trend="stable",  # Default stable or calculated
                    direction=conf.direction,
                )
            )

    return TelemetrySnapshotSchema(
        deviceId=machine_id,
        deviceName=device_name,
        timestamp=now_iso,
        points=points,
        predictionHorizonMin=25 if any(p.isAnomalous for p in points) else None,
    )


async def incident_dict_to_schema(inc: Dict[str, Any], db: DatabaseManager) -> IncidentSchema:
    m_id = inc["machine_id"]
    opened_at = inc["opened_at"]
    if isinstance(opened_at, datetime):
        ts_str = opened_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        ts_str = str(opened_at)

    resolved_at_str = None
    if inc.get("closed_at"):
        cl = inc["closed_at"]
        resolved_at_str = cl.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(cl, datetime) else str(cl)

    # Build or fetch telemetry snapshot
    telemetry_snap = await build_telemetry_snapshot(m_id, db)

    # Proposed action and action execution
    proposed_action: Optional[ProposedActionSchema] = None
    action_execution: Optional[ActionExecutionSchema] = None

    actions = await db.get_actions_for_incident(inc["id"])
    if actions:
        latest_act = actions[-1]  # Most recent action
        # Build ProposedActionSchema
        act_created = latest_act.get("proposed_at")
        act_created_str = (
            act_created.strftime("%Y-%m-%dT%H:%M:%SZ")
            if isinstance(act_created, datetime)
            else str(act_created or ts_str)
        )

        items_raw = latest_act.get("params", {}).get("items")
        if not items_raw:
            # Default action items
            items_raw = [
                {
                    "type": "plc_command",
                    "title": "Lệnh điều khiển PLC",
                    "description": f"Thực thi {latest_act['command']}",
                    "params": {
                        "Lệnh": latest_act["command"],
                        "Thiết bị": m_id,
                    },
                }
            ]

        action_items = []
        for it in items_raw:
            action_items.append(
                ProposedActionItemSchema(
                    type=it.get("type", "plc_command"),
                    title=it.get("title", ""),
                    description=it.get("description", ""),
                    params={str(k): str(v) for k, v in it.get("params", {}).items()},
                )
            )

        proposed_action = ProposedActionSchema(
            id=latest_act["id"],
            incidentId=inc["id"],
            titleVi=latest_act.get("title_vi") or f"Đề xuất: {latest_act['command']}",
            subtitleVi=latest_act.get("rationale") or f"Điều chỉnh thông số bệ thử {m_id}",
            diagnosisEn=f"Proposed {latest_act['command']} to bring machine telemetry back to safe operational limits.",
            items=action_items,
            timerSeconds=settings.ACTION_TTL_S,
            createdAt=act_created_str,
        )

        # Map action execution status
        act_st = latest_act.get("status", "pending")
        ui_exec_status: Literal["waiting", "executing", "success", "rejected", "expired"] = "waiting"
        if act_st == "pending":
            ui_exec_status = "waiting"
        elif act_st == "executing":
            ui_exec_status = "executing"
        elif act_st in ("approved", "acked"):
            ui_exec_status = "success"
        elif act_st == "rejected":
            ui_exec_status = "rejected"
        elif act_st == "expired":
            ui_exec_status = "expired"

        ack_data = latest_act.get("ack") or {}
        action_execution = ActionExecutionSchema(
            actionId=latest_act["id"],
            status=ui_exec_status,
            executedAt=latest_act.get("decided_at", "").isoformat() if isinstance(latest_act.get("decided_at"), datetime) else latest_act.get("decided_at"),
            ackCode=f"ACK {ack_data.get('code', 200)}" if ack_data else None,
            responseText=ack_data.get("message"),
            rejectedAt=latest_act.get("decided_at", "").isoformat() if act_st == "rejected" and isinstance(latest_act.get("decided_at"), datetime) else None,
            expiredAt=latest_act.get("expires_at", "").isoformat() if act_st == "expired" and isinstance(latest_act.get("expires_at"), datetime) else None,
        )

    # Map incident status to UI contract
    inc_status = inc["status"]
    if inc_status not in ("active", "awaiting_approval", "resolved", "acknowledged", "closed"):
        inc_status = "active"

    return IncidentSchema(
        id=inc["id"],
        conversationId=f"CONV-{inc['id'].replace('INC-', '')}",
        device=m_id,
        alarm=inc["title"],
        severity=inc.get("severity", "medium"),
        status=inc_status,
        timestamp=ts_str,
        resolvedAt=resolved_at_str,
        telemetry=telemetry_snap,
        proposedAction=proposed_action,
        actionExecution=action_execution,
        tags=inc.get("tags", []),
    )


# -----------------------------------------------------------------------------
# Gateway Endpoints
# -----------------------------------------------------------------------------

@router.get("/incidents", response_model=List[IncidentSchema])
async def list_agent_incidents(db: DatabaseManager = Depends(get_db)):
    """Retrieve all incidents for the Agentic Copilot dashboard."""
    incidents = await db.list_incidents()
    result = []
    for inc in incidents:
        schema = await incident_dict_to_schema(inc, db)
        result.append(schema)
    return result


@router.get("/incidents/{id}", response_model=IncidentSchema)
async def get_agent_incident(id: str = Path(...), db: DatabaseManager = Depends(get_db)):
    """Retrieve specific incident details by ID."""
    inc = await db.get_incident(id)
    if not inc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{id}' not found",
        )
    return await incident_dict_to_schema(inc, db)


@router.get("/telemetry/{device_id}", response_model=TelemetrySnapshotSchema)
async def get_agent_telemetry(
    device_id: str = Path(...), db: DatabaseManager = Depends(get_db)
):
    """
    Retrieve live telemetry snapshot by deviceId (or by incidentId for frontend compatibility).
    """
    target_machine_id = device_id
    if device_id.startswith("INC-"):
        inc = await db.get_incident(device_id)
        if inc:
            target_machine_id = inc["machine_id"]

    return await build_telemetry_snapshot(target_machine_id, db)


@router.post("/actions/{id}/approve", response_model=ApproveResponseSchema)
async def approve_agent_action(
    id: str = Path(...),
    action_svc: ActionService = Depends(get_action_service),
):
    """Approve and dispatch proposed action (HITL)."""
    return await action_svc.approve_action(action_id=id, actor="user:operator")


@router.post("/actions/{id}/reject")
async def reject_agent_action(
    id: str = Path(...),
    action_svc: ActionService = Depends(get_action_service),
):
    """Reject proposed action."""
    return await action_svc.reject_action(action_id=id, reason="Từ chối bởi người vận hành.", actor="user:operator")


@router.post("/chat", response_model=AgentChatResponseSchema)
async def post_agent_chat(
    req: AgentChatRequestSchema, db: DatabaseManager = Depends(get_db)
):
    """
    Phase 2: Structured rule-based chat response based on incident data and playbook citations.
    """
    # Extract incident from conversationId (e.g. CONV-0001 -> INC-0001)
    conv_id = req.conversationId
    inc_id = f"INC-{conv_id.replace('CONV-', '')}"
    inc = await db.get_incident(inc_id)

    query_lower = req.message.lower()

    if not inc:
        # Generic response when no incident is selected
        return AgentChatResponseSchema(
            content=(
                f"**[Chế độ phân tích theo luật / Rule-based mode]**\n\n"
                f"Hệ thống Agent Gateway DENSO đang giám sát bệ thử máy nén khí.\n\n"
                f"Yêu cầu của bạn: *\"{req.message}\"*\n\n"
                f"Hiện tại chưa có sự cố nào được liên kết với phiên hội thoại {conv_id}. "
                f"Vui lòng chọn một sự cố từ danh sách bên trái để xem chẩn đoán chi tiết và phiếu hành động."
            ),
            citations=[],
        )

    # Information about the current incident
    m_id = inc["machine_id"]
    actions = await db.get_actions_for_incident(inc["id"])
    pending_act = actions[-1] if actions else None

    # Fetch citation anchors from playbook
    timeline = inc.get("timeline", [])
    citations: List[Dict[str, str]] = []
    for ev in timeline:
        for c in ev.get("citations", []):
            citations.append({
                "documentId": c.get("document_id", "doc-denso"),
                "documentName": c.get("document_name", "DENSO Technical Manual"),
                "pages": c.get("pages", "1"),
            })

    # Build response content based on query keywords
    if any(k in query_lower for k in ("lệnh", "plc", "rpm", "command", "hành động", "action")):
        if pending_act:
            content = (
                f"**[Chế độ phân tích theo luật / Rule-based mode]**\n\n"
                f"**Hành động đề xuất cho sự cố {inc['id']} ({m_id}):**\n\n"
                f"- **Lệnh điều khiển**: `{pending_act['command']}`\n"
                f"- **Tham số**: `{json.dumps(pending_act.get('params', {}))}`\n"
                f"- **Trạng thái**: `{pending_act.get('status', 'pending').upper()}`\n"
                f"- **Cơ sở kỹ thuật**: {pending_act.get('rationale', '')}\n\n"
                f"Vui lòng kiểm tra thẻ **HITL Action Card** trên giao diện để phê duyệt hoặc từ chối thực thi."
            )
        else:
            content = (
                f"**[Chế độ phân tích theo luật / Rule-based mode]**\n\n"
                f"Hiện tại không có hành động nào đang chờ duyệt cho máy {m_id}."
            )
    elif any(k in query_lower for k in ("nguyên nhân", "tại sao", "lý do", "root cause", "chẩn đoán")):
        content = (
            f"**[Chế độ phân tích theo luật / Rule-based mode]**\n\n"
            f"**Kết luận chẩn đoán nguyên nhân gốc rễ ({m_id}):**\n\n"
            f"- **Nguyên nhân nghi ngờ**: **{inc.get('root_cause', 'Chưa xác định')}**\n"
            f"- **Độ tin cậy**: **{int((inc.get('confidence') or 0.0) * 100)}%**\n"
            f"- **Mức độ nghiêm trọng**: `{inc.get('severity', 'medium').upper()}`\n\n"
            f"Chẩn đoán được xác lập bằng cách đối chiếu cảm biến viễn trắc với danh mục lỗi kỹ thuật tiêu chuẩn của DENSO."
        )
    else:
        # Summary response
        content = (
            f"**[Chế độ phân tích theo luật / Rule-based mode]**\n\n"
            f"**Thông tin sự cố {inc['id']} trên bệ thử {m_id}:**\n\n"
            f"- **Tiêu đề cảnh báo**: {inc['title']}\n"
            f"- **Nguyên nhân nghi ngờ**: {inc.get('root_cause', 'Chưa xác định')}\n"
            f"- **Trạng thái xử lý**: `{inc['status'].upper()}`\n\n"
            f"Hệ thống đã ghi nhận đầy đủ dòng thời gian kiểm tra chéo cảm biến và tra cứu tài liệu liên quan."
        )

    return AgentChatResponseSchema(
        content=content,
        citations=citations if citations else None,
    )
