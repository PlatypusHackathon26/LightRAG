from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import evaluate_metric_status, load_machines_config, settings
from app.db import db_manager
from app.monitor import ThresholdMonitorLogic
from app.stream import broadcaster, sse_event_generator

router = APIRouter(prefix="/api/v1", tags=["Dashboard API"])


# -----------------------------------------------------------------------------
# Read-Only Authentication Dependency
# -----------------------------------------------------------------------------
def verify_dashboard_read_access(
    request: Request,
    x_dashboard_token: Optional[str] = Header(None, alias="X-Dashboard-Token"),
    token: Optional[str] = Query(None, alias="token"),
):
    """
    Read-only authentication for Dashboard and SSE Stream.
    If DASHBOARD_TOKEN is empty: access is open (local mode).
    If DASHBOARD_TOKEN has a value: requires either header X-Dashboard-Token or query param ?token=.
    Does NOT log the token value.
    """
    configured = settings.DASHBOARD_TOKEN.strip() if settings.DASHBOARD_TOKEN else ""
    if not configured:
        return True

    provided = (x_dashboard_token or token or "").strip()
    if provided != configured:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: invalid or missing Dashboard access token",
        )
    return True


# -----------------------------------------------------------------------------
# Schemas for Dashboard API
# -----------------------------------------------------------------------------
class DashboardMetricDetail(BaseModel):
    value: Optional[float]
    unit: str
    label: str
    status: Literal["normal", "warn", "critical", "unknown"]
    direction: Literal["above", "below", "info"]
    warn: Optional[float] = None
    critical: Optional[float] = None
    display_min: Optional[float] = None
    display_max: Optional[float] = None
    decimals: int = 1
    trend: Literal["rising", "falling", "stable"] = "stable"
    slope_per_min: float = 0.0
    eta_to_critical_s: Optional[float] = None
    timestamp: Optional[str] = None


class DashboardMachineItem(BaseModel):
    machine_id: str
    name: str
    description: str
    overall_status: Literal["normal", "warn", "critical", "offline"]
    is_online: bool
    is_mitigated: bool = False
    last_seen: Optional[str] = None
    seconds_since_last_seen: Optional[float] = None
    metrics: Dict[str, DashboardMetricDetail]
    active_alarms: List[str] = Field(default_factory=list)
    open_incident: Optional[Dict[str, Any]] = None
    latest_mitigation: Optional[Dict[str, Any]] = None
    pending_action: Optional[Dict[str, Any]] = None


class SystemStatusSummary(BaseModel):
    mqtt_connected: bool
    db_connected: bool
    last_data_received: Optional[str] = None
    seconds_since_last_data: Optional[float] = None
    publish_interval_s: float
    total_machines: int
    counts_by_status: Dict[str, int]


class DashboardOverviewResponse(BaseModel):
    system: SystemStatusSummary
    machines: List[DashboardMachineItem]
    agent_summary: Dict[str, Any]
    timestamp: str


class SeriesPoint(BaseModel):
    time: str
    timestamp_s: float
    value: float


class MetricSeriesData(BaseModel):
    label: str
    unit: str
    direction: Literal["above", "below", "info"]
    warn: Optional[float] = None
    critical: Optional[float] = None
    normal_min: Optional[float] = None
    normal_max: Optional[float] = None
    display_min: Optional[float] = None
    display_max: Optional[float] = None
    decimals: int = 1
    points: List[SeriesPoint]


class MachineSeriesResponse(BaseModel):
    machine_id: str
    minutes: int
    step_s: int
    series: Dict[str, MetricSeriesData]
    events: List[Dict[str, Any]] = Field(default_factory=list)
    agent_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: str


class DashboardEventsResponse(BaseModel):
    total: int
    events: List[Dict[str, Any]]
    timestamp: str


class DashboardAgentStatusResponse(BaseModel):
    autonomy_mode: str
    agent_enabled: bool
    agent_mode: str
    webui_url: str
    counts_by_severity: Dict[str, int]
    open_incidents: List[Dict[str, Any]]
    recent_actions: List[Dict[str, Any]]
    timestamp: str


class DashboardAgentTimelineResponse(BaseModel):
    machine_id: str
    minutes: int
    timeline: List[Dict[str, Any]]
    timestamp: str


# -----------------------------------------------------------------------------
# Internal Helpers
# -----------------------------------------------------------------------------
async def build_dashboard_overview_data() -> Dict[str, Any]:
    """
    Constructs the full system and machine overview dictionary,
    including Agent state, open incidents, and mitigation info.
    Reused by both GET /api/v1/dashboard/overview and SSE initial snapshot.
    """
    cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    publish_interval = settings.PUBLISH_INTERVAL_S
    offline_threshold_s = 3.0 * publish_interval

    machines_list: List[DashboardMachineItem] = []
    status_counts = {"normal": 0, "warn": 0, "critical": 0, "offline": 0}
    overall_last_data: Optional[datetime] = None

    monitor_logic = ThresholdMonitorLogic()
    since_5m = datetime.fromtimestamp(now.timestamp() - 300, tz=timezone.utc)

    # Pre-fetch open incidents and actions for all machines
    all_open_incidents = await db_manager.list_incidents()
    open_inc_by_machine: Dict[str, Dict[str, Any]] = {}
    for inc in all_open_incidents:
        if inc.get("status") != "closed":
            m_target = inc.get("machine_id")
            if m_target and m_target not in open_inc_by_machine:
                open_inc_by_machine[m_target] = inc

    for m_id, m in cfg.machines.items():
        latest_metrics = await db_manager.get_latest_metrics(m_id)
        history_5m = await db_manager.get_metrics_history(m_id, since_5m)

        # Check latest sample time for machine
        latest_sample_time: Optional[datetime] = None
        for _, (ts, _) in latest_metrics.items():
            if latest_sample_time is None or ts > latest_sample_time:
                latest_sample_time = ts

        if latest_sample_time:
            if overall_last_data is None or latest_sample_time > overall_last_data:
                overall_last_data = latest_sample_time

        # Calculate online flag and seconds since last seen
        is_online = False
        sec_since_last: Optional[float] = None
        if latest_sample_time:
            sec_since_last = max(0.0, (now - latest_sample_time).total_seconds())
            is_online = sec_since_last <= offline_threshold_s

        # Calculate metrics details and overall status
        metrics_dict: Dict[str, DashboardMetricDetail] = {}
        worst_metric_status = "normal"
        active_alarms: List[str] = []

        for metric_name, m_cfg in m.metrics.items():
            val = None
            sample_ts_str = None
            if metric_name in latest_metrics:
                s_ts, val = latest_metrics[metric_name]
                sample_ts_str = s_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Status evaluation
            if val is not None:
                st = evaluate_metric_status(val, m_cfg)
            else:
                st = "unknown"

            # Trend & ETA analysis from history
            trend_val = "stable"
            slope_val = 0.0
            eta_val = None
            if metric_name in history_5m and history_5m[metric_name]:
                pts = [(t.timestamp(), v) for t, v in history_5m[metric_name]]
                analysis = monitor_logic.analyze_series(m_id, metric_name, m_cfg, pts)
                trend_val = analysis.trend
                slope_val = round(analysis.slope_per_min, 2)
                eta_val = analysis.eta_to_critical_s

            if st == "critical":
                worst_metric_status = "critical"
                active_alarms.append(f"{m_cfg.label} đạt {val} {m_cfg.unit} (Nguy hiểm)")
            elif st == "warn" and worst_metric_status != "critical":
                worst_metric_status = "warn"
                active_alarms.append(f"{m_cfg.label} đạt {val} {m_cfg.unit} (Cảnh báo)")

            metrics_dict[metric_name] = DashboardMetricDetail(
                value=round(val, m_cfg.decimals) if val is not None else None,
                unit=m_cfg.unit,
                label=m_cfg.label,
                status=st,
                direction=m_cfg.direction,
                warn=m_cfg.warn,
                critical=m_cfg.critical,
                display_min=m_cfg.display_min,
                display_max=m_cfg.display_max,
                decimals=m_cfg.decimals,
                trend=trend_val,
                slope_per_min=slope_val,
                eta_to_critical_s=eta_val,
                timestamp=sample_ts_str,
            )

        # Machine overall status: offline takes precedence if no data in 3*interval
        if not is_online:
            machine_overall = "offline"
        else:
            machine_overall = worst_metric_status

        status_counts[machine_overall] += 1

        # Check open incident and actions for this machine
        open_inc = open_inc_by_machine.get(m_id)
        open_inc_dict = None
        latest_mitigation_dict = None
        pending_act_dict = None
        is_mitigated = False

        if open_inc:
            inc_id = open_inc["id"]
            open_inc_dict = {
                "id": inc_id,
                "status": open_inc.get("status"),
                "severity": open_inc.get("severity"),
                "title": open_inc.get("title"),
                "root_cause": open_inc.get("root_cause"),
                "confidence": open_inc.get("confidence"),
                "opened_at": str(open_inc.get("opened_at", "")),
            }

            # Fetch actions for this incident
            inc_actions = await db_manager.get_actions_for_incident(inc_id)

            # Find pending action if any
            for a in reversed(inc_actions):
                if a.get("status") == "pending":
                    pending_act_dict = {
                        "id": a["id"],
                        "command": a["command"],
                        "params": a.get("params", {}),
                        "rationale": a.get("rationale"),
                        "proposed_at": str(a.get("proposed_at", "")),
                        "expires_at": str(a.get("expires_at", "")),
                        "auto_executed": a.get("auto_executed", False),
                    }
                    break

            # Find latest executed/acked mitigation action
            for a in reversed(inc_actions):
                if a.get("status") in ("acked", "approved", "executing"):
                    rpm_val = a.get("params", {}).get("rpm", "")
                    decided_by = a.get("decided_by", "agent")
                    is_auto = a.get("auto_executed", False)
                    who_vi = "Agent tự động" if is_auto or decided_by == "agent" else f"Người duyệt ({decided_by})"

                    decided_t = a.get("decided_at") or a.get("proposed_at")
                    t_str = ""
                    if decided_t:
                        if isinstance(decided_t, str):
                            t_str = decided_t[11:16]
                        elif isinstance(decided_t, datetime):
                            t_str = decided_t.strftime("%H:%M")

                    summary_vi = f"{who_vi} hạ tốc độ xuống {rpm_val} rpm lúc {t_str}" if rpm_val else f"{who_vi} thực thi {a['command']}"

                    latest_mitigation_dict = {
                        "id": a["id"],
                        "command": a["command"],
                        "params": a.get("params", {}),
                        "status": a.get("status"),
                        "auto_executed": is_auto,
                        "decided_by": decided_by,
                        "summary": summary_vi,
                        "ack": a.get("ack"),
                    }
                    break

            # A machine is considered "mitigated" (Đã giảm nhẹ) when:
            # An action was executed/acked (e.g. SET_RPM), no metrics are currently critical,
            # but the machine still has warning or open incident requiring physical repair.
            if latest_mitigation_dict and worst_metric_status != "critical":
                is_mitigated = True

        machines_list.append(
            DashboardMachineItem(
                machine_id=m_id,
                name=m.name,
                description=m.description or "",
                overall_status=machine_overall,
                is_online=is_online,
                is_mitigated=is_mitigated,
                last_seen=latest_sample_time.strftime("%Y-%m-%dT%H:%M:%SZ") if latest_sample_time else None,
                seconds_since_last_seen=round(sec_since_last, 1) if sec_since_last is not None else None,
                metrics=metrics_dict,
                active_alarms=active_alarms,
                open_incident=open_inc_dict,
                latest_mitigation=latest_mitigation_dict,
                pending_action=pending_act_dict,
            )
        )

    # Sort machines by severity: critical > warn > normal > offline
    severity_order = {"critical": 0, "warn": 1, "normal": 2, "offline": 3}
    machines_list.sort(key=lambda x: (severity_order.get(x.overall_status, 4), x.machine_id))

    sec_since_data = (
        round((now - overall_last_data).total_seconds(), 1) if overall_last_data else None
    )

    from app.main import ingest_service
    mqtt_conn = getattr(ingest_service, "is_connected", False)

    system_summary = SystemStatusSummary(
        mqtt_connected=mqtt_conn,
        db_connected=db_manager.is_connected,
        last_data_received=overall_last_data.strftime("%Y-%m-%dT%H:%M:%SZ") if overall_last_data else None,
        seconds_since_last_data=sec_since_data,
        publish_interval_s=publish_interval,
        total_machines=len(machines_list),
        counts_by_status=status_counts,
    )

    agent_summary = {
        "autonomy_mode": settings.AUTONOMY_MODE,
        "agent_enabled": settings.AGENT_ENABLED,
        "agent_mode": settings.AGENT_MODE,
        "webui_url": settings.WEBUI_URL,
        "open_incidents_count": len(open_inc_by_machine),
    }

    return {
        "system": system_summary.model_dump(),
        "machines": [m.model_dump() for m in machines_list],
        "agent_summary": agent_summary,
        "timestamp": now_iso,
    }


# -----------------------------------------------------------------------------
# Endpoints (Strictly GET-only)
# -----------------------------------------------------------------------------
@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(_: bool = Depends(verify_dashboard_read_access)):
    """
    Returns full system summary, list of all machines with current metrics,
    trends, alarms, open incidents, and mitigation details.
    """
    data = await build_dashboard_overview_data()
    return data


@router.get("/dashboard/agent", response_model=DashboardAgentStatusResponse)
async def get_dashboard_agent_status(_: bool = Depends(verify_dashboard_read_access)):
    """
    Current autonomy mode (advisory/hitl/auto_safe), AGENT_ENABLED, AGENT_MODE,
    open incidents breakdown, and list of recent actions.
    """
    now = datetime.now(timezone.utc)
    all_incidents = await db_manager.list_incidents()
    open_incidents = [inc for inc in all_incidents if inc.get("status") != "closed"]

    counts_by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    sanitized_open_incidents = []

    for inc in open_incidents:
        sev = (inc.get("severity") or "medium").lower()
        counts_by_severity[sev] = counts_by_severity.get(sev, 0) + 1

        sanitized_open_incidents.append({
            "id": inc["id"],
            "machine_id": inc["machine_id"],
            "status": inc.get("status"),
            "severity": inc.get("severity"),
            "title": inc.get("title"),
            "root_cause": inc.get("root_cause"),
            "confidence": inc.get("confidence"),
            "opened_at": str(inc.get("opened_at", "")),
        })

    # Collect recent actions across all open incidents
    recent_actions = []
    for inc in open_incidents:
        actions = await db_manager.get_actions_for_incident(inc["id"])
        for a in actions:
            recent_actions.append({
                "id": a["id"],
                "incident_id": a["incident_id"],
                "machine_id": a["machine_id"],
                "command": a["command"],
                "params": a.get("params", {}),
                "rationale": a.get("rationale"),
                "status": a.get("status"),
                "auto_executed": a.get("auto_executed", False),
                "decided_by": a.get("decided_by"),
                "decided_at": str(a.get("decided_at", "")) if a.get("decided_at") else None,
                "proposed_at": str(a.get("proposed_at", "")),
                "expires_at": str(a.get("expires_at", "")) if a.get("expires_at") else None,
                "ack": a.get("ack"),
            })

    # Sort recent actions newest first
    recent_actions.sort(key=lambda x: x.get("proposed_at", ""), reverse=True)

    return DashboardAgentStatusResponse(
        autonomy_mode=settings.AUTONOMY_MODE,
        agent_enabled=settings.AGENT_ENABLED,
        agent_mode=settings.AGENT_MODE,
        webui_url=settings.WEBUI_URL,
        counts_by_severity=counts_by_severity,
        open_incidents=sanitized_open_incidents,
        recent_actions=recent_actions[:30],
        timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@router.get("/dashboard/agent/timeline", response_model=DashboardAgentTimelineResponse)
async def get_dashboard_agent_timeline(
    machine: str = Query(..., description="Machine ID e.g. COMP-TB-01"),
    minutes: int = Query(default=60, ge=1, le=1440, description="Time window in minutes"),
    _: bool = Depends(verify_dashboard_read_access),
):
    """
    Action and incident timeline markers for a machine to plot on charts.
    """
    now = datetime.now(timezone.utc)
    since_dt = datetime.fromtimestamp(now.timestamp() - minutes * 60, tz=timezone.utc)

    # 1. Fetch audit logs for this machine
    audit_logs = await db_manager.get_audit_logs(limit=200)
    machine_logs = [
        row for row in audit_logs
        if row.get("machine_id") == machine and row.get("ts") and row["ts"] >= since_dt
    ]

    timeline_markers = []
    for row in machine_logs:
        act = row.get("action")
        actor = row.get("actor", "system")
        details = row.get("details", {})
        ts_iso = row["ts"].strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_s = float(row["ts"].timestamp())

        label = act
        badge_type = "info"

        if act == "action_proposed":
            cmd = details.get("command", "ACTION")
            params = details.get("params", {})
            rpm_info = f" -> {params.get('rpm')} rpm" if "rpm" in params else ""
            label = f"Agent đề xuất: {cmd}{rpm_info}"
            badge_type = "proposed"
        elif act == "approve":
            cmd = details.get("command", "ACTION")
            label = f"Duyệt lệnh {cmd} ({actor})"
            badge_type = "approved"
        elif act == "ack":
            code = details.get("code", 200)
            msg = details.get("message", "Thành công")
            label = f"ACK {code}: {msg}"
            badge_type = "ack"
        elif act == "expire":
            label = "Hết hạn không thực thi"
            badge_type = "expired"
        elif act == "reject":
            label = f"Từ chối lệnh ({actor})"
            badge_type = "rejected"
        elif act == "incident_created":
            cause = details.get("root_cause", "Sự cố")
            label = f"Mở sự cố: {cause}"
            badge_type = "incident"
        elif act == "incident_resolved":
            label = "Sự cố được giải quyết (Normal)"
            badge_type = "resolved"

        timeline_markers.append({
            "timestamp": ts_iso,
            "timestamp_s": ts_s,
            "action": act,
            "actor": actor,
            "label": label,
            "badge_type": badge_type,
            "details": details,
        })

    # Sort chronological
    timeline_markers.sort(key=lambda x: x["timestamp_s"])

    return DashboardAgentTimelineResponse(
        machine_id=machine,
        minutes=minutes,
        timeline=timeline_markers,
        timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@router.get("/dashboard/machine/{id}/series", response_model=MachineSeriesResponse)
async def get_machine_series(
    id: str,
    minutes: int = Query(default=15, ge=1, le=1440, description="Time window in minutes"),
    step: int = Query(default=5, ge=1, le=300, description="Downsampling step in seconds"),
    _: bool = Depends(verify_dashboard_read_access),
):
    """
    Time series data per metric downsampled with time_bucket (max ~600 points per metric),
    along with warn and critical thresholds, machine error events, and agent action timeline markers.
    """
    cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    if id not in cfg.machines:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Machine '{id}' not found",
        )

    m_cfg = cfg.machines[id]
    now = datetime.now(timezone.utc)
    since_dt = datetime.fromtimestamp(now.timestamp() - minutes * 60, tz=timezone.utc)

    # 1. Fetch raw metrics history
    history = await db_manager.get_metrics_history(id, since_dt)

    # 2. Downsample series with time bucket (step seconds)
    series_res: Dict[str, MetricSeriesData] = {}

    for metric_name, conf in m_cfg.metrics.items():
        raw_pts = history.get(metric_name, [])
        bucketed_pts: List[SeriesPoint] = []

        if raw_pts:
            # Group points into buckets of `step` seconds
            buckets: Dict[int, List[float]] = {}
            for dt_point, val in raw_pts:
                t_sec = dt_point.timestamp()
                bucket_key = int(math.floor(t_sec / step) * step)
                if bucket_key not in buckets:
                    buckets[bucket_key] = []
                buckets[bucket_key].append(val)

            # Average points in each bucket
            for b_sec in sorted(buckets.keys()):
                avg_val = sum(buckets[b_sec]) / len(buckets[b_sec])
                b_dt = datetime.fromtimestamp(b_sec, tz=timezone.utc)
                bucketed_pts.append(
                    SeriesPoint(
                        time=b_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        timestamp_s=float(b_sec),
                        value=round(avg_val, conf.decimals),
                    )
                )

            # Limit to last 600 points if needed
            if len(bucketed_pts) > 600:
                bucketed_pts = bucketed_pts[-600:]

        series_res[metric_name] = MetricSeriesData(
            label=conf.label,
            unit=conf.unit,
            direction=conf.direction,
            warn=conf.warn,
            critical=conf.critical,
            normal_min=conf.normal_min,
            normal_max=conf.normal_max,
            display_min=conf.display_min,
            display_max=conf.display_max,
            decimals=conf.decimals,
            points=bucketed_pts,
        )

    # 3. Fetch events for this machine within the window
    events = await db_manager.get_recent_events(id, since_dt)

    # 4. Fetch agent action markers within the window
    audit_logs = await db_manager.get_audit_logs(limit=100)
    agent_timeline = []
    for row in audit_logs:
        if row.get("machine_id") == id and row.get("ts") and row["ts"] >= since_dt:
            act = row.get("action")
            det = row.get("details", {})
            lbl = act
            if act == "action_proposed":
                lbl = f"Agent đề xuất: {det.get('command')}"
            elif act == "approve":
                lbl = f"Duyệt lệnh {det.get('command')} ({row.get('actor')})"
            elif act == "ack":
                lbl = f"ACK: {det.get('message', 'Thành công')}"
            elif act == "expire":
                lbl = "Hết hạn không thực thi"

            agent_timeline.append({
                "timestamp": row["ts"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timestamp_s": float(row["ts"].timestamp()),
                "action": act,
                "label": lbl,
                "actor": row.get("actor"),
            })

    return MachineSeriesResponse(
        machine_id=id,
        minutes=minutes,
        step_s=step,
        series=series_res,
        events=events,
        agent_timeline=agent_timeline,
        timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@router.get("/dashboard/events", response_model=DashboardEventsResponse)
async def get_dashboard_events(
    limit: int = Query(default=50, ge=1, le=500, description="Max number of events to return"),
    machine: Optional[str] = Query(None, description="Filter by machine ID"),
    severity: Optional[str] = Query(None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"),
    since: Optional[str] = Query(None, description="Filter events since ISO 8601 timestamp"),
    _: bool = Depends(verify_dashboard_read_access),
):
    """
    List of deduplicated events (newest first) with filtering by machine, severity, and time.
    """
    now = datetime.now(timezone.utc)
    since_dt = datetime.fromtimestamp(now.timestamp() - 86400, tz=timezone.utc)  # Default last 24h
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid timestamp format '{since}'. Expected ISO 8601 string.",
            )

    # If machine is specified, fetch directly
    all_events = []
    cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    target_machines = [machine] if machine else list(cfg.machines.keys())

    for m_id in target_machines:
        evs = await db_manager.get_recent_events(m_id, since_dt)
        all_events.extend(evs)

    # Filter by severity if requested
    if severity:
        sev_upper = severity.upper()
        all_events = [e for e in all_events if e.get("severity", "").upper() == sev_upper]

    # Sort newest first
    all_events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    all_events = all_events[:limit]

    return DashboardEventsResponse(
        total=len(all_events),
        events=all_events,
        timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@router.get("/stream")
async def get_sse_stream(
    request: Request,
    _: bool = Depends(verify_dashboard_read_access),
):
    """
    Server-Sent Events (SSE) endpoint:
    - Sends snapshot immediately upon connection.
    - Streams live metrics, events, machine_status, incidents, and actions.
    - Sends heartbeat every 15 seconds.
    - Drops oldest messages when client queue is full.
    - Rejects connection if max concurrent clients is exceeded.
    """
    client_queue = await broadcaster.register_client()
    if not client_queue:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSE connection rejected: maximum concurrent clients limit reached",
        )

    initial_snapshot = await build_dashboard_overview_data()

    return StreamingResponse(
        sse_event_generator(request, client_queue, initial_snapshot),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
