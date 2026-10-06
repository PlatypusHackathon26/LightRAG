from __future__ import annotations

import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional


class ActionDispatchError(Exception):
    """Raised when an approved proposal could not be sent to its machine."""


class ActionApproval:
    """Stages proposed machine actions and dispatches only engineer-approved ones."""

    def __init__(self, dispatcher: Any) -> None:
        self.dispatcher = dispatcher
        self._lock = threading.RLock()
        self._actions: Dict[str, Dict[str, Any]] = {}
        self._order: Deque[str] = deque()

    def propose(self, machine_id: str, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not machine_id or not action:
            raise ValueError("machine_id and action are required")

        action_id = uuid.uuid4().hex
        proposal = {
            "action_id": action_id,
            "machine_id": machine_id,
            "action": action,
            "payload": dict(payload or {}),
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "decided_at": None,
            "dispatch_result": None,
            "error": None,
        }
        with self._lock:
            self._actions[action_id] = proposal
            self._order.append(action_id)
            return dict(proposal)

    def decide(self, action_id: str, decision: str) -> Dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be 'approve' or 'reject'")

        with self._lock:
            proposal = self._actions.get(action_id)
            if proposal is None:
                raise KeyError(f"Unknown action id: {action_id}")
            if proposal["status"] != "pending":
                raise RuntimeError(f"Action is already {proposal['status']}")

            proposal["status"] = "dispatching" if decision == "approve" else "rejected"
            proposal["decided_at"] = datetime.now(timezone.utc).isoformat()
            machine_id = proposal["machine_id"]
            action = proposal["action"]
            payload = dict(proposal["payload"])

        if decision == "reject":
            with self._lock:
                return dict(self._actions[action_id])

        try:
            dispatch_result = self.dispatcher.dispatch(machine_id, action, payload)
        except Exception as exc:
            with self._lock:
                proposal = self._actions[action_id]
                proposal["status"] = "dispatch_failed"
                proposal["error"] = str(exc)
                raise

        with self._lock:
            proposal = self._actions[action_id]
            if not isinstance(dispatch_result, dict) or dispatch_result.get("status") != "dispatched":
                error = f"Dispatcher returned an unsuccessful result: {dispatch_result!r}"
                proposal["status"] = "dispatch_failed"
                proposal["error"] = error
                raise ActionDispatchError(error)
            proposal["status"] = "approved"
            proposal["dispatch_result"] = dispatch_result
            return dict(proposal)

    def snapshot(self) -> list[Dict[str, Any]]:
        with self._lock:
            return [dict(self._actions[action_id]) for action_id in reversed(self._order)]
