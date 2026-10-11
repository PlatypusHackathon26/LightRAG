"""Long-agent (long_agent/) seen as the agentic UI's incidents.

An incident is a machine Long-agent's edge filter raised an alert for (its "system_alert"
conversation). Never built from the tester's ground-truth faults (``active_faults``): those are
the answer the agent must find, not something it is told.
"""

from __future__ import annotations

from datetime import datetime

MACHINE_TYPE_VI = {
    "CNC_MILLING": "Máy phay CNC",
    "ROBOT_ARM": "Cánh tay robot",
    "AMR_VEHICLE": "Xe tự hành AMR",
    "AOI_INSPECTION": "Máy kiểm tra quang AOI",
    "INJECTION_MOLDING": "Máy ép phun",
}
SHOWN_MESSAGES = 8  # each alert appends two messages; the sidebar thread keeps the recent ones


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _point(metric: dict, value: float) -> tuple[dict, bool, bool]:
    """A UI telemetry point, whether it is out of its normal range, and whether critically."""
    lo, hi = _number(metric.get("min")), _number(metric.get("max"))
    clo, chi = _number(metric.get("critical_min")), _number(metric.get("critical_max"))
    warn = (hi is not None and value > hi) or (lo is not None and value < lo)
    critical = (chi is not None and value > chi) or (clo is not None and value < clo)
    threshold = hi if hi is not None else (lo if lo is not None else (chi if chi is not None else clo))
    point = {"key": metric["key"], "label": metric.get("label", metric["key"]), "value": value,
             "unit": metric.get("unit", ""), "isAnomalous": warn or critical, "trend": "stable"}
    if threshold is not None:
        point["threshold"] = threshold
    return point, warn or critical, critical


def _messages(machine_id: str, raw: list[dict]) -> list[dict]:
    """The latest alerts and the latest diagnosis, oldest first. Long-agent appends an alert on each
    edge-filter trigger and a diagnosis each time it diagnoses; an older diagnosis was written on
    earlier readings, so only the newest is shown."""
    alerts, diagnoses = [], {}
    for m in raw:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if m.get("role") == "assistant":
            diagnoses[text] = m.get("timestamp")  # keeps the latest time a diagnosis was given
        else:
            alerts.append({"role": "system", "content": f"⚠ {text}", "timestamp": m.get("timestamp")})
    latest = max(diagnoses.items(), key=lambda kv: kv[1] or "", default=None)
    shown = alerts[-3:] + ([{"role": "assistant", "content": f"**Chẩn đoán của agent giám sát (Long-agent):** {latest[0]}",
                             "timestamp": latest[1]}] if latest else [])
    shown = sorted(shown, key=lambda m: m["timestamp"] or "")[-SHOWN_MESSAGES:]
    for i, m in enumerate(shown):
        m["id"] = f"la-{machine_id}-{i}"
    return shown


def _proposal(machine_id: str, incident_id: str, pending: list[dict]) -> dict | None:
    for a in pending:
        if a.get("machine_id") != machine_id:
            continue
        command = a.get("command", "")
        params = {"Lệnh": command, "Thiết bị": machine_id,
                  **{str(k): str(v) for k, v in (a.get("params") or a.get("payload") or {}).items()}}
        return {"id": a.get("approval_id") or a.get("action_id"), "incidentId": incident_id,
                "titleVi": f"Đề xuất: {command}", "subtitleVi": a.get("reason", ""), "diagnosisEn": "",
                "items": [{"type": "plc_command", "title": "Lệnh điều khiển PLC", "description": command,
                           "params": params}],
                "timerSeconds": 300, "createdAt": a.get("timestamp") or datetime.now().isoformat()}
    return None


def incidents_from_state(state: dict) -> list[dict]:
    """Long-agent's GET /api/state -> the UI's Incident list (newest first)."""
    machines = state.get("machines") or {}
    pending = state.get("pending_approvals") or []
    latest_alert = {}
    for a in state.get("alerts") or []:
        latest_alert[a.get("machine_id")] = a
    out = []
    for conv in state.get("conversations") or []:
        if conv.get("category") != "system_alert" or not conv.get("machine_id"):
            continue
        mid = conv["machine_id"]
        machine = machines.get(mid) or {}
        telemetry = machine.get("telemetry") or {}
        labels = {m["key"]: m.get("label", m["key"]) for m in machine.get("metrics") or []}
        points, warn, critical = [], False, False
        for metric in machine.get("metrics") or []:
            value = _number(telemetry.get(metric["key"]))
            if value is None:
                continue
            point, w, c = _point(metric, value)
            points.append(point)
            warn, critical = warn or w, critical or c
        alert = latest_alert.get(mid) or {}
        params = list(dict.fromkeys(labels.get(x.get("param"), x.get("param")) for x in alert.get("anomalies") or []))
        alarm = f"Bất thường: {', '.join(params)}" if params else "Cảnh báo bất thường"
        incident_id = f"LA-{mid}"
        proposal = _proposal(mid, incident_id, pending)
        active = machine.get("label") == "alert" or warn
        msgs = _messages(mid, conv.get("messages") or [])
        timestamp = alert.get("timestamp") or (msgs[-1]["timestamp"] if msgs else datetime.now().isoformat())
        incident = {
            "id": incident_id, "conversationId": f"CONV-LA-{mid}", "device": mid, "alarm": alarm,
            "severity": "critical" if critical else ("high" if active else "medium"),
            "status": "awaiting_approval" if proposal else ("active" if active else "resolved"),
            "timestamp": timestamp,
            "telemetry": {"deviceId": mid, "deviceName": MACHINE_TYPE_VI.get(machine.get("machine_type"), mid),
                          "timestamp": datetime.now().isoformat(), "points": points},
            "messages": msgs,
            "tags": ["long-agent", machine.get("machine_type", "").lower()],
        }
        if proposal:
            incident["proposedAction"] = proposal
        out.append(incident)
    return sorted(out, key=lambda i: i["timestamp"], reverse=True)


def incident_context(inc: dict) -> str:
    """The incident's live state, for the answer prompt of a chat held in its conversation."""
    lines = [f"- Machine: {inc.get('device')} ({(inc.get('telemetry') or {}).get('deviceName', '')}); "
             f"{inc.get('alarm')}; status: {inc.get('status')}"]
    points = (inc.get("telemetry") or {}).get("points") or []
    if points:
        def reading(p: dict) -> str:
            limit = f", limit {p['threshold']:g}" if isinstance(p.get("threshold"), (int, float)) else ""
            return f"{p['label']} {p['value']:g} {p['unit']}".rstrip() + limit + (", OUT OF RANGE" if p.get("isAnomalous") else "")
        lines.append("- Sensor readings now: " + "; ".join(reading(p) for p in points))
    diagnosis = next((m["content"] for m in reversed(inc.get("messages") or []) if m.get("role") == "assistant"), "")
    if diagnosis:
        lines.append(f"- The monitoring agent's own guess (keyword-based, unverified): {diagnosis.split('** ', 1)[-1]}")
    return ("The operator is asking about this live alert on a simulated factory machine (data from the monitoring "
            "system, NOT from the documents):\n" + "\n".join(lines) + "\n"
            "Use it to understand the question. Causes, procedures and specifications must still come from the "
            "documents and be cited as usual; sensor values may be quoted as live readings. If the documents do "
            "not cover the question, say so.")
