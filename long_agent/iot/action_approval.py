# iot/action_approval.py
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("ActionApproval")


class ActionDispatchError(RuntimeError):
    """Lỗi khi dispatcher không thể thực thi lệnh đã duyệt."""


class ActionApproval:
    """Chốt chặn Human-in-the-Loop: phân loại rủi ro, giữ vé chờ duyệt, ghi lịch sử quyết định.

    A ticket is either one command or a procedure (`steps`, `kind` "repair" / "restart"). Rules:
    - risk comes from the machine's declaration (spec_lookup); a request cannot lower it, and a
      procedure or an undeclared command is HIGH;
    - an approved procedure is handed to the procedure runner, never dispatched here;
    - every decision, expiry and execution is appended to `history` (newest last).
    """

    def __init__(
        self,
        dispatcher: Optional[Any] = None,
        dispatcher_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        event_bus: Optional[Any] = None,
        default_ttl_sec: float = 300.0,
        require_approval_for_all: bool = False,  # True: cả lệnh LOW cũng chờ kỹ sư duyệt
        spec_lookup: Optional[Callable[[str, str], Any]] = None,
        procedure_runner: Optional[Any] = None,
    ) -> None:
        self.event_bus = event_bus
        self.default_ttl_sec = default_ttl_sec
        self.require_approval_for_all = require_approval_for_all
        self.spec_lookup = spec_lookup
        self.procedure_runner = procedure_runner
        self._lock = Lock()

        if dispatcher_callback is not None:
            self.dispatcher_callback = dispatcher_callback
        elif dispatcher is not None and hasattr(dispatcher, "execute"):
            self.dispatcher_callback = dispatcher.execute
        else:
            self.dispatcher_callback = None
        if spec_lookup is None and dispatcher is not None and hasattr(dispatcher, "machine"):
            def _lookup(machine_id: str, name: str) -> Any:
                machine = dispatcher.machine(machine_id)
                return machine.commands.get(name) if machine is not None else None
            self.spec_lookup = _lookup

        # Danh sách chờ: {approval_id: command_record}
        self.pending_actions: Dict[str, Dict[str, Any]] = {}
        self.history: Deque[Dict[str, Any]] = deque(maxlen=300)

    def _assess_risk_level(self, machine_id: str, cmd_name: str) -> str:
        """Risk declared by the machine for this command (machines/commands.py). A request cannot
        lower it; a command the machine does not declare, or a multi-step procedure, is HIGH."""
        spec = self.spec_lookup(machine_id, cmd_name) if self.spec_lookup else None
        return spec.risk if spec is not None else "HIGH"

    def _record(self, event: str, rec: Dict[str, Any], **extra: Any) -> None:
        entry = {"ts": datetime.now().isoformat(), "event": event, "approval_id": rec.get("approval_id"),
                 "machine_id": rec.get("machine_id"), "command": rec.get("command"), "kind": rec.get("kind"),
                 "title": rec.get("title"), **extra}
        self.history.append(entry)
        if self.event_bus:
            self.event_bus.publish({"event_type": f"approval_{event}", "approval_id": rec.get("approval_id"),
                                    "machine_id": rec.get("machine_id"), "command": rec, **extra})

    def _cleanup_expired(self) -> None:
        now = time.time()
        for aid in [a for a, rec in self.pending_actions.items() if now > rec.get("expires_at", float("inf"))]:
            rec = self.pending_actions.pop(aid)
            logger.warning(f"[Approval] Ticket {aid} ({rec.get('title') or rec.get('command')}) ĐÃ HẾT HẠN.")
            self._record("expired", rec)

    def process_action_request(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Run a LOW-risk single command at once; hold anything else as a ticket."""
        with self._lock:
            self._cleanup_expired()
            machine_id = command.get("machine_id", "UNKNOWN")
            cmd_name = str(command.get("command") or command.get("action") or "UNKNOWN")
            steps = command.get("steps")
            risk = "HIGH" if steps or self.require_approval_for_all else self._assess_risk_level(machine_id, cmd_name)

            if risk == "LOW":
                logger.info(f"[Approval] Lệnh an toàn [{cmd_name}] trên [{machine_id}] -> thi hành ngay.")
                if not self.dispatcher_callback:
                    return {"status": "NO_DISPATCHER_ATTACHED", "command": command}
                res = self.dispatcher_callback(command)
                self._record("executed", {**command, "command": cmd_name}, result=res.get("status"))
                return res

            approval_id = f"APP-{str(uuid.uuid4())[:8].upper()}"
            now_ts = time.time()
            record = {
                **command,
                "command": cmd_name if not steps else command.get("command") or command.get("title"),
                "kind": command.get("kind") or ("command" if not steps else "repair"),
                "approval_id": approval_id,
                "action_id": approval_id,
                "risk_level": "HIGH",
                "status": "PENDING_APPROVAL",
                "created_at": datetime.now().isoformat(),
                "expires_at": now_ts + self.default_ttl_sec,
            }
            self.pending_actions[approval_id] = record
            logger.warning(f"[Approval] Chờ kỹ sư duyệt [{record.get('title') or cmd_name}] trên [{machine_id}] "
                           f"[{approval_id}]")
            if self.event_bus:
                self.event_bus.publish({"event_type": "approval_required", "approval_id": approval_id,
                                        "command": record})
            return record

    def propose(self, machine_id: str, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """A single-command ticket (shorthand for process_action_request)."""
        return self.process_action_request({"machine_id": machine_id, "command": action,
                                            "payload": payload or {}, "params": payload or {}})

    def approve(self, action_id: str) -> Dict[str, Any]:
        """Kỹ sư bấm [Duyệt]. A procedure starts on the runner; a single command is dispatched and
        must succeed, otherwise ActionDispatchError (the ticket is consumed either way, and recorded)."""
        with self._lock:
            self._cleanup_expired()
            record = self.pending_actions.pop(action_id, None)
        if not record:
            raise KeyError(action_id)

        if record.get("steps"):
            if self.procedure_runner is None or not self.procedure_runner.start(record):
                self._record("failed", record, error="máy đang chạy một quy trình khác")
                raise ActionDispatchError("Máy đang chạy một quy trình khác")
            self._record("approved", record)
            return {"status": "approved", "action_id": action_id, "procedure": "started"}

        if not self.dispatcher_callback:
            return {"status": "DISPATCHER_UNAVAILABLE", "action_id": action_id}
        try:
            exec_res = self.dispatcher_callback(record)
        except Exception as exc:
            self._record("failed", record, error=str(exc))
            raise ActionDispatchError(str(exc)) from exc
        status = exec_res.get("status") if isinstance(exec_res, dict) else None
        if status not in ("SUCCESS", "dispatched", "EXECUTED"):
            error = (exec_res or {}).get("error") or status
            self._record("failed", record, error=error)
            raise ActionDispatchError(f"Máy từ chối lệnh: {error}")
        self._record("approved", record, result=status)
        return {"status": "approved", "action_id": action_id, "dispatch_result": exec_res}

    def reject(self, action_id: str, reason: str = "Rejected by operator") -> Dict[str, Any]:
        """Kỹ sư bấm [Từ chối]."""
        with self._lock:
            record = self.pending_actions.pop(action_id, None)
        if not record:
            raise KeyError(action_id)
        logger.info(f"[Approval] Đã TỪ CHỐI {action_id}. Lý do: {reason}")
        self._record("rejected", record, reason=reason)
        return {"status": "rejected", "action_id": action_id}

    def decide(self, action_id: str, decision: str) -> Dict[str, Any]:
        dec = decision.strip().upper()
        if dec in ("APPROVE", "APPROVED", "YES", "CONFIRM"):
            return self.approve(action_id)
        if dec in ("REJECT", "REJECTED", "NO", "DENY"):
            return self.reject(action_id)
        raise ValueError(f"Decision không hợp lệ: {decision}")

    def get_pending_actions(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._cleanup_expired()
            return list(self.pending_actions.values())

    def has_pending(self, machine_id: str) -> bool:
        return any(a.get("machine_id") == machine_id for a in self.get_pending_actions())

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._cleanup_expired()
            return list(self.history)
