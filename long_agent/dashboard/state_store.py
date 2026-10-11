# dashboard/state_store.py (phan 1/2)
from __future__ import annotations
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional
import uuid as _uuid


def _now() -> str:
    return datetime.now().isoformat()


def _uid(prefix: str = "sess") -> str:
    return f"{prefix}-{str(_uuid.uuid4())[:8]}"


class StateStore:
    """State tap trung: may, hoi thoai 2 nhanh, HITL, uploads."""

    def __init__(self) -> None:
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        self._conversations: List[Dict[str, Any]] = []
        self._alerts: List[Dict[str, Any]] = []
        self._uploads: List[Dict[str, Any]] = []

    def update_machine_telemetry(
        self, machine_id: str, machine_type: str, payload: Dict[str, Any],
        label: str = "normal", active_faults: Optional[List[str]] = None,
    ) -> None:
        with self._lock:
            self._states[machine_id] = {
                "machine_id": machine_id, "machine_type": machine_type,
                "label": label, "telemetry": payload,
                "active_faults": active_faults or [],
            }

    def get_all_machines(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._states)

    def register_machines(self, machines: List[Any]) -> None:
        with self._lock:
            for m in machines:
                mid = getattr(m, "machine_id", "UNKNOWN")
                self._states[mid] = {
                    "machine_id": mid, "machine_type": getattr(m, "machine_type", ""),
                    "model": getattr(m, "model", ""), "location": getattr(m, "location", ""),
                    "label": "normal", "status": "normal", "telemetry": {},
                    "history": {}, "active_faults": [],
                    "last_agent_result": None,
                }
    # ---- Event bus -> state ----
    def handle_event(self, event: Dict[str, Any]) -> None:
        etype = event.get("event_type", "")
        mid = event.get("machine_id", "UNKNOWN")
        with self._lock:
            if etype == "telemetry":
                label = event.get("label", "normal")
                payload = event.get("payload", {})
                st = self._states.get(mid, {
                    "machine_id": mid, "machine_type": "", "telemetry": {},
                    "history": {}, "status": "normal", "label": "normal",
                    "active_faults": [],
                    "last_agent_result": None,
                })
                st["telemetry"] = payload
                st["label"] = label
                hist = st.setdefault("history", {})
                for k, v in payload.items():
                    if isinstance(v, (int, float)):
                        hist.setdefault(k, []).append(v)
                if label == "alert":
                    st["status"] = "alert"
                    anomalies = event.get("anomalies", [])
                    detail = "; ".join(
                        f"{a.get('param')}={a.get('value')} ({a.get('reason', '')})"
                        for a in anomalies
                    ) or "Thong so vuot nguong"
                    conv = self._find_or_create_conv(mid, "system_alert")
                    conv["messages"].append({
                        "role": "system",
                        "text": f"[{mid}] Canh bao: {detail}",
                        "timestamp": _now(),
                    })
                    self._alerts.append({
                        "machine_id": mid, "timestamp": _now(),
                        "anomalies": anomalies, "agent_result": None,
                    })
                elif st.get("status") != "alert":
                    st["status"] = "normal"
                self._states[mid] = st
            elif etype == "alert":
                st = self._states.get(mid, {
                    "machine_id": mid, "machine_type": "", "telemetry": {},
                    "history": {}, "status": "alert", "label": "alert",
                    "active_faults": [],
                    "last_agent_result": None,
                })
                st["status"] = "alert"
                st["label"] = "alert"
                tele = (event.get("payload") or {}).get("telemetry", {})
                if tele:
                    st["telemetry"] = tele
                self._states[mid] = st
                conv = self._find_or_create_conv(mid, "system_alert")
                conv["messages"].append({
                    "role": "system",
                    "text": f"[{mid}] Alert: {(event.get('payload') or {}).get('issue', 'unknown')}",
                    "timestamp": _now(),
                })
                self._alerts.append({
                    "machine_id": mid, "timestamp": _now(),
                    "anomalies": [], "agent_result": None,
                })
            elif etype == "chat_notification":
                conv = self._find_or_create_conv(mid, "system_alert")
                conv["messages"].append({
                    "role": "assistant", "text": event.get("text", ""),
                    "source": event.get("source", "AI_RAG"), "timestamp": _now(),
                })
            elif etype == "approval_required":
                aid = event.get("approval_id", "")
                cmd = event.get("command", {}) or {}
                conv = self._find_or_create_conv(cmd.get("machine_id", mid), "system_alert")
                conv["messages"].append({
                    "role": "approval", "approval_id": aid,
                    "command": cmd.get("command", ""),
                    "params": cmd.get("params") or cmd.get("payload") or {},
                    "reason": cmd.get("reason", ""),
                    "risk_level": cmd.get("risk_level", "HIGH"),
                    "status": "pending", "timestamp": _now(),
                })

    def _find_or_create_conv(self, machine_id: str, category: str) -> Dict[str, Any]:
        for c in self._conversations:
            if c.get("machine_id") == machine_id and c.get("category") == category:
                return c
        conv = {
            "session_id": _uid("conv"), "category": category,
            "machine_id": machine_id, "title": f"Canh bao {machine_id}",
            "messages": [],
        }
        self._conversations.append(conv)
        return conv

    # ---- Chat 2 nhanh (test_api_chat) ----
    def create_user_session(self, title: str) -> str:
        with self._lock:
            sid = _uid("sess")
            self._conversations.append({
                "session_id": sid, "category": "user", "machine_id": "",
                "title": title, "messages": [],
            })
            return sid

    def add_message(self, session_id: str, role: str, text: str) -> bool:
        with self._lock:
            for c in self._conversations:
                if c.get("session_id") == session_id:
                    c["messages"].append({
                        "role": role, "text": text, "timestamp": _now(),
                    })
                    return True
            return False

    def remove_approval(self, approval_id: str, status: str) -> bool:
        st = status.strip().upper()
        mapped = "approved" if st in ("APPROVE", "APPROVED", "YES") else "rejected"
        with self._lock:
            for c in self._conversations:
                for m in c.get("messages", []):
                    if m.get("role") == "approval" and m.get("approval_id") == approval_id:
                        m["status"] = mapped
                        return True
            return False

    def register_upload(self, filename: str) -> Dict[str, Any]:
        with self._lock:
            rec = {"filename": filename, "timestamp": _now()}
            self._uploads.append(rec)
            return rec

    # ---- Snapshot / API cu ----
    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "server_time": _now(), "machines": dict(self._states),
                "conversations": list(self._conversations),
                "pending_approvals": [],
                "alerts": list(self._alerts), "uploads": list(self._uploads),
            }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            machines = []
            for mid, st in self._states.items():
                machines.append({
                    "machine_id": mid,
                    "machine_type": st.get("machine_type", ""),
                    "model": st.get("model", ""), "location": st.get("location", ""),
                    "status": st.get("status", st.get("label", "normal")),
                    "telemetry": st.get("telemetry", {}),
                    "history": st.get("history", {}),
                    "last_agent_result": st.get("last_agent_result"),
                    "active_faults": st.get("active_faults", []),
                })
            return {"machines": machines, "alerts": list(self._alerts)}

    def record_agent_result(self, machine_id: str, result: Dict[str, Any]) -> None:
        with self._lock:
            st = self._states.get(machine_id)
            if st is not None:
                st["last_agent_result"] = result
            for a in reversed(self._alerts):
                if a.get("machine_id") == machine_id:
                    a["agent_result"] = result
                    break

    def register_upload(self, filename: str) -> Dict[str, Any]:
        with self._lock:
            rec = {"filename": filename, "timestamp": _now()}
            self._uploads.append(rec)
            return rec

    # ---- Snapshot / API cu ----
    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "server_time": _now(), "machines": dict(self._states),
                "conversations": list(self._conversations),
                "pending_approvals": [],
                "alerts": list(self._alerts), "uploads": list(self._uploads),
            }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            machines = []
            for mid, st in self._states.items():
                machines.append({
                    "machine_id": mid,
                    "machine_type": st.get("machine_type", ""),
                    "model": st.get("model", ""), "location": st.get("location", ""),
                    "status": st.get("status", st.get("label", "normal")),
                    "telemetry": st.get("telemetry", {}),
                    "history": st.get("history", {}),
                    "last_agent_result": st.get("last_agent_result"),
                    "active_faults": st.get("active_faults", []),
                })
            return {"machines": machines, "alerts": list(self._alerts)}

    def record_agent_result(self, machine_id: str, result: Dict[str, Any]) -> None:
        with self._lock:
            st = self._states.get(machine_id)
            if st is not None:
                st["last_agent_result"] = result
            for a in reversed(self._alerts):
                if a.get("machine_id") == machine_id:
                    a["agent_result"] = result
                    break


DashboardState = StateStore
