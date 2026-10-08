from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.config import evaluate_metric_status, load_machines_config, settings
from app.db import db_manager
from app.monitor import ThresholdMonitorLogic

router = APIRouter(prefix="/api/v1", tags=["Tools API"])


def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-API-Key header",
        )
    valid_keys = {settings.IOT_API_KEY, settings.IOT_ADMIN_KEY}
    if x_api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-API-Key provided",
        )
    return x_api_key


# Response Models
class MetricStatusItem(BaseModel):
    value: Optional[float]
    unit: str
    label: str
    status: Literal["normal", "warn", "critical", "unknown"]
    direction: Literal["above", "below", "info"]
    warn: Optional[float] = None
    critical: Optional[float] = None
    timestamp: Optional[str] = None


class MachineCurrentStatusResponse(BaseModel):
    machine_id: str
    name: str
    timestamp: str
    overall_status: Literal["normal", "warn", "critical"]
    metrics: Dict[str, MetricStatusItem]
    summary: str


class MetricStatusAtItem(MetricStatusItem):
    actual_timestamp: Optional[str] = None
    time_skew_s: Optional[float] = None


class MachineStatusAtResponse(BaseModel):
    machine_id: str
    queried_at: str
    actual_sample_time: Optional[str]
    max_time_skew_s: Optional[float]
    metrics: Dict[str, MetricStatusAtItem]
    summary: str


class MetricHistoryItem(BaseModel):
    label: str
    unit: str
    min: Optional[float]
    max: Optional[float]
    avg: Optional[float]
    slope_per_min: float
    trend: Literal["rising", "falling", "stable"]
    eta_to_critical_s: Optional[float]


class MachineHistoryResponse(BaseModel):
    machine_id: str
    window_minutes: int
    metrics: Dict[str, MetricHistoryItem]
    summary: str


class MachineEventItem(BaseModel):
    event_id: str
    timestamp: str
    source: str
    event_type: str
    severity: str
    error_code: str
    message: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    incident_id: Optional[str] = None
    repeat_count: int = 1


class MachineEventsResponse(BaseModel):
    machine_id: str
    window_minutes: int
    count: int
    events: List[MachineEventItem]
    summary: str


class MachineListItem(BaseModel):
    machine_id: str
    name: str
    description: str
    rpm_setpoint: float
    overall_status: Literal["normal", "warn", "critical"]
    last_updated: Optional[str] = None


class MachinesListResponse(BaseModel):
    total: int
    machines: List[MachineListItem]
    summary: str


def _get_machine_config(machine_id: str):
    cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    if machine_id not in cfg.machines:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Machine '{machine_id}' does not exist. Available: {list(cfg.machines.keys())}",
        )
    return cfg.machines[machine_id]


@router.get("/machines", response_model=MachinesListResponse)
async def list_machines(api_key: str = Depends(verify_api_key)):
    """List all registered machines and their high-level operational status."""
    cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    items: List[MachineListItem] = []
    status_counts = {"normal": 0, "warn": 0, "critical": 0}

    for m_id, m in cfg.machines.items():
        latest = await db_manager.get_latest_metrics(m_id)
        overall: Literal["normal", "warn", "critical"] = "normal"
        last_ts = None

        for metric_name, m_cfg in m.metrics.items():
            if metric_name in latest:
                ts, val = latest[metric_name]
                last_ts = ts.isoformat()
                st = evaluate_metric_status(val, m_cfg)
                if st == "critical":
                    overall = "critical"
                elif st == "warn" and overall != "critical":
                    overall = "warn"

        status_counts[overall] += 1
        items.append(
            MachineListItem(
                machine_id=m_id,
                name=m.name,
                description=m.description or "",
                rpm_setpoint=m.rpm_setpoint,
                overall_status=overall,
                last_updated=last_ts,
            )
        )

    summary_parts = []
    for item in items:
        vn_st = "bình thường" if item.overall_status == "normal" else ("cảnh báo" if item.overall_status == "warn" else "nguy hiểm")
        summary_parts.append(f"{item.machine_id} ({vn_st})")

    summary = f"Hệ thống có {len(items)} bệ thử: " + ", ".join(summary_parts) + "."
    return MachinesListResponse(total=len(items), machines=items, summary=summary)


@router.get("/machine/{id}/current-status", response_model=MachineCurrentStatusResponse)
async def get_current_status(id: str, api_key: str = Depends(verify_api_key)):
    """Get the latest real-time status of all metrics for a specific machine."""
    m_cfg = _get_machine_config(id)
    latest_metrics = await db_manager.get_latest_metrics(id)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    metric_items: Dict[str, MetricStatusItem] = {}
    overall_status: Literal["normal", "warn", "critical"] = "normal"
    problematic_metrics = []

    for m_name, conf in m_cfg.metrics.items():
        if m_name in latest_metrics:
            sample_time, val = latest_metrics[m_name]
            st = evaluate_metric_status(val, conf)
            if st == "critical":
                overall_status = "critical"
                problematic_metrics.append(f"{conf.label} {val} {conf.unit} (nguy hiểm)")
            elif st == "warn":
                if overall_status != "critical":
                    overall_status = "warn"
                problematic_metrics.append(f"{conf.label} {val} {conf.unit} (cảnh báo)")

            metric_items[m_name] = MetricStatusItem(
                value=val,
                unit=conf.unit,
                label=conf.label,
                status=st,
                direction=conf.direction,
                warn=conf.warn,
                critical=conf.critical,
                timestamp=sample_time.isoformat(),
            )
        else:
            metric_items[m_name] = MetricStatusItem(
                value=None,
                unit=conf.unit,
                label=conf.label,
                status="unknown",
                direction=conf.direction,
                warn=conf.warn,
                critical=conf.critical,
                timestamp=None,
            )

    if not latest_metrics:
        summary = f"Máy {id} hiện chưa có dữ liệu đo từ thiết bị."
    elif problematic_metrics:
        summary = f"Máy {id} hiện có " + ", ".join(problematic_metrics) + "."
    else:
        rpm = metric_items.get("compressor_rpm", None)
        rpm_str = f" tại tốc độ {rpm.value} rpm" if rpm and rpm.value is not None else ""
        summary = f"Máy {id} đang hoạt động bình thường{rpm_str}. Tất cả thông số trong giới hạn an toàn."

    return MachineCurrentStatusResponse(
        machine_id=id,
        name=m_cfg.name,
        timestamp=now_iso,
        overall_status=overall_status,
        metrics=metric_items,
        summary=summary,
    )


@router.get("/machine/{id}/status", response_model=MachineStatusAtResponse)
async def get_status_at(
    id: str,
    at: str = Query(..., description="Target time in ISO 8601 format (e.g. 2026-10-07T10:15:00Z)"),
    api_key: str = Depends(verify_api_key),
):
    """Retrieve historical status of machine closest to a specific timestamp."""
    m_cfg = _get_machine_config(id)

    # Validate ISO 8601 format
    try:
        parsed_dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid timestamp format '{at}'. Expected ISO 8601 string (e.g. 2026-10-07T10:15:00Z)",
        )

    metrics_at = await db_manager.get_metrics_at(id, parsed_dt)
    metric_items: Dict[str, MetricStatusAtItem] = {}
    max_skew = 0.0
    latest_sample_time = None
    abnormal_items = []

    for m_name, conf in m_cfg.metrics.items():
        if m_name in metrics_at:
            sample_time, val, skew = metrics_at[m_name]
            if skew > max_skew:
                max_skew = skew
            latest_sample_time = sample_time.isoformat()

            st = evaluate_metric_status(val, conf)
            if st != "normal":
                abnormal_items.append(f"{conf.label} {val} {conf.unit} ({st})")

            metric_items[m_name] = MetricStatusAtItem(
                value=val,
                unit=conf.unit,
                label=conf.label,
                status=st,
                direction=conf.direction,
                warn=conf.warn,
                critical=conf.critical,
                timestamp=sample_time.isoformat(),
                actual_timestamp=sample_time.isoformat(),
                time_skew_s=round(skew, 1),
            )
        else:
            metric_items[m_name] = MetricStatusAtItem(
                value=None,
                unit=conf.unit,
                label=conf.label,
                status="unknown",
                direction=conf.direction,
                warn=conf.warn,
                critical=conf.critical,
                timestamp=None,
                actual_timestamp=None,
                time_skew_s=None,
            )

    if not metrics_at:
        summary = f"Không tìm thấy dữ liệu máy {id} tại thời điểm {at}."
    else:
        skew_msg = f" (độ lệch mẫu thực tế: {round(max_skew, 1)}s)"
        if abnormal_items:
            summary = f"Tại thời điểm {at}{skew_msg}, máy {id} có bất thường: " + ", ".join(abnormal_items) + "."
        else:
            summary = f"Tại thời điểm {at}{skew_msg}, máy {id} hoạt động bình thường."

    return MachineStatusAtResponse(
        machine_id=id,
        queried_at=at,
        actual_sample_time=latest_sample_time,
        max_time_skew_s=round(max_skew, 1) if metrics_at else None,
        metrics=metric_items,
        summary=summary,
    )


@router.get("/machine/{id}/history", response_model=MachineHistoryResponse)
async def get_history(
    id: str,
    minutes: int = Query(default=10, ge=1, le=1440, description="History window in minutes"),
    api_key: str = Depends(verify_api_key),
):
    """Retrieve statistical summary and trend analysis for each metric over specified minutes."""
    m_cfg = _get_machine_config(id)
    now = datetime.now(timezone.utc)
    since_dt = datetime.fromtimestamp(now.timestamp() - minutes * 60, tz=timezone.utc)

    history = await db_manager.get_metrics_history(id, since_dt)
    monitor_logic = ThresholdMonitorLogic()

    metric_items: Dict[str, MetricHistoryItem] = {}
    summary_concerns = []

    for m_name, conf in m_cfg.metrics.items():
        series = history.get(m_name, [])
        if series:
            pts = [(ts.timestamp(), val) for ts, val in series]
            res = monitor_logic.analyze_series(id, m_name, conf, pts)

            metric_items[m_name] = MetricHistoryItem(
                label=conf.label,
                unit=conf.unit,
                min=res.min_value,
                max=res.max_value,
                avg=res.avg_value,
                slope_per_min=res.slope_per_min,
                trend=res.trend,
                eta_to_critical_s=res.eta_to_critical_s,
            )

            if res.trend != "stable":
                eta_text = f", dự kiến chạm mức nguy hiểm sau {int(res.eta_to_critical_s)}s" if res.eta_to_critical_s and res.eta_to_critical_s > 0 else ""
                summary_concerns.append(
                    f"{conf.label} xu hướng {res.trend} ({res.slope_per_min:+.2f} {conf.unit}/phút{eta_text})"
                )
        else:
            metric_items[m_name] = MetricHistoryItem(
                label=conf.label,
                unit=conf.unit,
                min=None,
                max=None,
                avg=None,
                slope_per_min=0.0,
                trend="stable",
                eta_to_critical_s=None,
            )

    if summary_concerns:
        summary = f"Trong {minutes} phút qua trên máy {id}: " + "; ".join(summary_concerns) + "."
    else:
        summary = f"Trong {minutes} phút qua trên máy {id}, các chỉ số đều duy trì ổn định."

    return MachineHistoryResponse(
        machine_id=id,
        window_minutes=minutes,
        metrics=metric_items,
        summary=summary,
    )


@router.get("/machine/{id}/events", response_model=MachineEventsResponse)
async def get_events(
    id: str,
    minutes: int = Query(default=60, ge=1, le=1440, description="Events window in minutes"),
    api_key: str = Depends(verify_api_key),
):
    """Retrieve list of alarm and fault events recorded for the machine."""
    _get_machine_config(id)
    now = datetime.now(timezone.utc)
    since_dt = datetime.fromtimestamp(now.timestamp() - minutes * 60, tz=timezone.utc)

    raw_events = await db_manager.get_recent_events(id, since_dt)
    event_items = [
        MachineEventItem(
            event_id=ev["event_id"],
            timestamp=ev["timestamp"],
            source=ev["source"],
            event_type=ev["event_type"],
            severity=ev["severity"],
            error_code=ev["error_code"],
            message=ev["message"],
            payload=ev.get("payload", {}),
            incident_id=ev.get("incident_id"),
            repeat_count=ev.get("repeat_count", 1),
        )
        for ev in raw_events
    ]

    if not event_items:
        summary = f"Trong {minutes} phút qua, máy {id} không ghi nhận sự cố hay cảnh báo nào."
    else:
        err_counts = {}
        for ev in event_items:
            err_counts[ev.error_code] = err_counts.get(ev.error_code, 0) + ev.repeat_count
        details = [f"{code} (x{cnt})" for code, cnt in err_counts.items()]
        summary = f"Trong {minutes} phút qua, máy {id} ghi nhận {len(event_items)} sự kiện ({', '.join(details)})."

    return MachineEventsResponse(
        machine_id=id,
        window_minutes=minutes,
        count=len(event_items),
        events=event_items,
        summary=summary,
    )
