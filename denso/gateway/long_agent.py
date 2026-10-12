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
DIAGNOSIS_PREFIX = "**Chẩn đoán của Agent giám sát:** "
SHOWN_MESSAGES = (
    16  # one line per metric, the episode's diagnosis and the decisions' results
)
EPISODE_GAP_S = (
    600  # without Long-agent's episode marks: alerts closer than this are one incident
)


def _number(value) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _point(metric: dict, value: float) -> tuple[dict, bool, bool]:
    """A UI telemetry point, whether it is out of its normal range, and whether critically."""
    lo, hi = _number(metric.get("min")), _number(metric.get("max"))
    clo, chi = _number(metric.get("critical_min")), _number(metric.get("critical_max"))
    warn = (hi is not None and value > hi) or (lo is not None and value < lo)
    critical = (chi is not None and value > chi) or (clo is not None and value < clo)
    threshold = (
        hi
        if hi is not None
        else (lo if lo is not None else (chi if chi is not None else clo))
    )
    point = {
        "key": metric["key"],
        "label": metric.get("label", metric["key"]),
        "value": value,
        "unit": metric.get("unit", ""),
        "isAnomalous": warn or critical,
        "trend": "stable",
    }
    if threshold is not None:
        point["threshold"] = threshold
    return point, warn or critical, critical


def _messages(
    machine_id: str,
    raw: list[dict],
    episode: list[dict],
    labels: dict[str, str],
    since: str,
) -> list[dict]:
    """The current episode's thread, oldest first, with ids that never change meaning.

    Long-agent's edge filter repeats an alert for a metric every minute while it stays out of range;
    that is one line per metric here, carrying its latest reading and how often it was raised.
    Earlier episodes are left out, and of this one's diagnoses only the newest is shown; the results
    of the operator's decisions (run, rejected, withdrawn) and the recovery follow in time order.
    """
    lines: dict[str, dict] = {}
    for a in episode:
        for x in a.get("anomalies") or []:
            param = x.get("param")
            if not param:
                continue
            line = lines.setdefault(
                param, {"first": a.get("timestamp") or "", "count": 0}
            )
            line.update(last=x, count=line["count"] + 1)
    shown = []
    for param, line in lines.items():
        x = line["last"]
        repeated = f" · báo {line['count']} lần" if line["count"] > 1 else ""
        shown.append(
            {
                "id": f"la-{machine_id}-{since}-{param}",
                "role": "system",
                "content": f"⚠ [{machine_id}] {labels.get(param, param)} = {x.get('value')}"
                f" – {x.get('reason', 'ngoài ngưỡng')}{repeated}",
                "timestamp": line["first"],
            }
        )
    # What came of the operator's decisions: commands run, rejected or withdrawn, and the recovery.
    for m in raw:
        ts = m.get("timestamp") or ""
        if m.get("role") == "result" and (m.get("text") or "").strip() and ts >= since:
            shown.append(
                {
                    "id": f"la-{machine_id}-result-{ts}",
                    "role": "assistant",
                    "content": f"**Kết quả:** {m['text'].strip()}",
                    "timestamp": ts,
                }
            )
    # Only the newest diagnosis of the episode: an earlier one was written on fewer, earlier readings.
    latest = max(
        (
            m
            for m in raw
            if m.get("role") == "assistant"
            and (m.get("text") or "").strip()
            and (m.get("timestamp") or "") >= since
        ),
        key=lambda m: m.get("timestamp") or "",
        default=None,
    )
    if latest:
        shown.append(
            {
                "id": f"la-{machine_id}-{since}-diagnosis",
                "role": "assistant",
                "content": DIAGNOSIS_PREFIX + latest["text"].strip(),
                "timestamp": latest.get("timestamp") or "",
            }
        )
    return sorted(shown, key=lambda m: m["timestamp"])[-SHOWN_MESSAGES:]


def _proposal(machine_id: str, incident_id: str, pending: list[dict]) -> dict | None:
    for a in pending:
        if a.get("machine_id") != machine_id:
            continue
        command = a.get("command", "")
        params = {
            "Lệnh": command,
            "Thiết bị": machine_id,
            **{
                str(k): str(v)
                for k, v in (a.get("params") or a.get("payload") or {}).items()
            },
        }
        return {
            "id": a.get("approval_id") or a.get("action_id"),
            "incidentId": incident_id,
            "titleVi": f"Đề xuất: {command}",
            "subtitleVi": a.get("reason", ""),
            "diagnosisEn": "",
            "items": [
                {
                    "type": "plc_command",
                    "title": "Lệnh điều khiển PLC",
                    "description": command,
                    "params": params,
                }
            ],
            "timerSeconds": 300,
            "createdAt": a.get("timestamp") or datetime.now().isoformat(),
        }
    return None


def _episode(alerts: list[dict], started: str | None = None) -> list[dict]:
    """The machine's current episode of alerts. Long-agent marks when it began (``episode_started``,
    reset once the machine has recovered); without that mark, walking back from the newest alert,
    it ends at the first gap over EPISODE_GAP_S."""
    if started:
        return [a for a in alerts if (a.get("timestamp") or "") >= started]

    def seconds(a: dict) -> float:
        try:
            return datetime.fromisoformat(a.get("timestamp") or "").timestamp()
        except ValueError:
            return 0.0

    run = []
    for a in reversed(alerts):
        if run and seconds(run[-1]) - seconds(a) > EPISODE_GAP_S:
            break
        run.append(a)
    return list(reversed(run))


def incidents_from_state(state: dict) -> list[dict]:
    """Long-agent's GET /api/state -> the UI's Incident list (newest first)."""
    machines = state.get("machines") or {}
    pending = state.get("pending_approvals") or []
    alerts_by_machine: dict[str, list[dict]] = {}
    for a in state.get("alerts") or []:
        alerts_by_machine.setdefault(a.get("machine_id"), []).append(a)
    out = []
    for conv in state.get("conversations") or []:
        if conv.get("category") != "system_alert" or not conv.get("machine_id"):
            continue
        mid = conv["machine_id"]
        machine = machines.get(mid) or {}
        telemetry = machine.get("telemetry") or {}
        labels = {
            m["key"]: m.get("label", m["key"]) for m in machine.get("metrics") or []
        }
        points, warn, critical = [], False, False
        for metric in machine.get("metrics") or []:
            value = _number(telemetry.get(metric["key"]))
            if value is None:
                continue
            point, w, c = _point(metric, value)
            points.append(point)
            warn, critical = warn or w, critical or c
        # Every metric of the current episode, in the order they tripped: the title grows with the fault
        # instead of jumping to whichever metric alerted last.
        episode = _episode(
            alerts_by_machine.get(mid) or [], machine.get("episode_started")
        )
        alert = episode[-1] if episode else {}
        params = list(
            dict.fromkeys(
                labels.get(x.get("param"), x.get("param"))
                for a in episode
                for x in a.get("anomalies") or []
            )
        )
        alarm = f"Bất thường: {', '.join(params)}" if params else "Cảnh báo bất thường"
        incident_id = f"LA-{mid}"
        proposal = _proposal(mid, incident_id, pending)
        since = (
            machine.get("episode_started")
            or (episode[0].get("timestamp") if episode else "")
            or ""
        )
        in_episode = bool(machine.get("episode_started")) and not machine.get(
            "episode_ended"
        )
        active = in_episode or machine.get("label") == "alert" or warn
        msgs = _messages(mid, conv.get("messages") or [], episode, labels, since)
        timestamp = alert.get("timestamp") or (
            msgs[-1]["timestamp"] if msgs else datetime.now().isoformat()
        )
        incident = {
            "id": incident_id,
            "conversationId": f"CONV-LA-{mid}",
            "device": mid,
            "alarm": alarm,
            "severity": "critical" if critical else ("high" if active else "medium"),
            "status": "awaiting_approval"
            if proposal
            else ("active" if active else "resolved"),
            "timestamp": timestamp,
            "telemetry": {
                "deviceId": mid,
                "deviceName": MACHINE_TYPE_VI.get(machine.get("machine_type"), mid),
                "timestamp": datetime.now().isoformat(),
                "points": points,
            },
            "messages": msgs,
            "tags": ["long-agent", machine.get("machine_type", "").lower()],
        }
        if proposal:
            incident["proposedAction"] = proposal
        out.append(incident)
    return sorted(out, key=lambda i: i["timestamp"], reverse=True)


def incident_context(inc: dict) -> str:
    """The incident's live state, for the answer prompt of a chat held in its conversation."""
    lines = [
        f"- Machine: {inc.get('device')} ({(inc.get('telemetry') or {}).get('deviceName', '')}); "
        f"{inc.get('alarm')}; status: {inc.get('status')}"
    ]
    points = (inc.get("telemetry") or {}).get("points") or []
    if points:

        def reading(p: dict) -> str:
            limit = (
                f", limit {p['threshold']:g}"
                if isinstance(p.get("threshold"), (int, float))
                else ""
            )
            return (
                f"{p['label']} {p['value']:g} {p['unit']}".rstrip()
                + limit
                + (", OUT OF RANGE" if p.get("isAnomalous") else "")
            )

        lines.append("- Sensor readings now: " + "; ".join(reading(p) for p in points))
    diagnosis = next(
        (
            m["content"]
            for m in reversed(inc.get("messages") or [])
            if m.get("role") == "assistant"
            and m["content"].startswith(DIAGNOSIS_PREFIX)
        ),
        "",
    )
    if diagnosis:
        lines.append(
            f"- The monitoring agent's own guess (keyword-based, unverified): {diagnosis.split('** ', 1)[-1]}"
        )
    return (
        "The operator is asking about this live alert on a simulated factory machine (data from the monitoring "
        "system, NOT from the documents):\n" + "\n".join(lines) + "\n"
        "Use it to understand the question. Causes, procedures and specifications must still come from the "
        "documents and be cited as usual; sensor values may be quoted as live readings. If the documents do "
        "not cover the question, say so."
    )
