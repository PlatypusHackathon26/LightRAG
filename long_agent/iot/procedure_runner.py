"""Runs approved repair and restart procedures on the simulated machines, then verifies the result.

Lifecycle per machine: repair ticket approved -> steps run in order (each waits for the machine:
spindle stopped before LOCKOUT, repair time in MAINTENANCE) -> a restart ticket is requested ->
restart approved -> START, wait for RUNNING -> verification window: no alert for verify_s means
the repair is verified; an alert means it failed and the agent diagnoses again with that attempt
on record. Rules: a machine runs one procedure at a time; nothing here decides what to repair.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from machines import commands as cmd

logger = logging.getLogger("ProcedureRunner")


class ProcedureRunner:
    def __init__(
        self,
        dispatcher: Any,
        event_bus: Optional[Any] = None,
        verify_s: float = 120.0,
        step_timeout_s: float = 300.0,
        poll_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        background: bool = True,
    ) -> None:
        self.dispatcher = dispatcher
        self.event_bus = event_bus
        self.verify_s = verify_s
        self.step_timeout_s = step_timeout_s
        self.poll_s = poll_s
        self.sleep = sleep
        self.clock = clock
        self.background = background
        self.request_restart: Optional[
            Callable[[str, List[Dict[str, Any]], Dict[str, Any]], Any]
        ] = None
        self._lock = threading.Lock()
        self._busy: Dict[str, str] = {}  # machine -> phase ("repair" / "restart")
        self._verifying: Dict[
            str, Dict[str, Any]
        ] = {}  # machine -> {"until", "repair"}
        self._attempts: Dict[str, List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------------ queries
    def phase(self, machine_id: str) -> Optional[str]:
        with self._lock:
            if machine_id in self._busy:
                return self._busy[machine_id]
            if machine_id in self._verifying:
                return "verifying"
            return None

    def is_busy(self, machine_id: str) -> bool:
        """True while a procedure runs on the machine: the agent must not propose another one."""
        with self._lock:
            return machine_id in self._busy

    def attempts(self, machine_id: str) -> List[Dict[str, Any]]:
        """Repairs done since the machine was last verified healthy, with their outcome."""
        with self._lock:
            return [dict(a) for a in self._attempts.get(machine_id, [])]

    # ------------------------------------------------------------------ running
    def start(self, record: Dict[str, Any]) -> bool:
        machine_id = record.get("machine_id", "")
        with self._lock:
            if machine_id in self._busy:
                return False
            self._busy[machine_id] = record.get("kind", "repair")
            self._verifying.pop(machine_id, None)
        if self.background:
            threading.Thread(
                target=self._run, args=(record,), daemon=True, name=f"proc-{machine_id}"
            ).start()
        else:
            self._run(record)
        return True

    def _run(self, record: Dict[str, Any]) -> None:
        machine_id, kind = record.get("machine_id", ""), record.get("kind", "repair")
        ok, failed_step = True, None
        try:
            for i, step in enumerate(record.get("steps") or []):
                self._publish(
                    "procedure_step",
                    record,
                    step=i,
                    command=step["command"],
                    status="running",
                )
                ok, detail = self._run_step(machine_id, step)
                self._publish(
                    "procedure_step",
                    record,
                    step=i,
                    command=step["command"],
                    status="done" if ok else "failed",
                    detail=detail,
                )
                if not ok:
                    failed_step = step["command"]
                    break
        except Exception as exc:  # never leave a machine marked busy
            logger.exception("[Procedure] %s crashed", machine_id)
            ok, failed_step = False, f"lỗi nội bộ: {exc}"
        finally:
            with self._lock:
                self._busy.pop(machine_id, None)
        self._publish("procedure_done", record, ok=ok, failed_step=failed_step)
        if not ok:
            return
        if kind == "repair":
            repair = next(
                (s["command"] for s in record["steps"] if s.get("kind") == "repair"),
                None,
            )
            with self._lock:
                self._attempts.setdefault(machine_id, []).append(
                    {
                        "repair": repair,
                        "outcome": "awaiting_restart",
                        "at": datetime.now().isoformat(),
                    }
                )
            if self.request_restart:
                self.request_restart(
                    machine_id, self._restart_steps(machine_id), record
                )
        elif kind == "restart":
            with self._lock:
                attempts = self._attempts.get(machine_id) or []
                if attempts and attempts[-1]["outcome"] == "awaiting_restart":
                    attempts[-1]["outcome"] = "verifying"
                self._verifying[machine_id] = {
                    "until": self.clock() + self.verify_s,
                    "repair": attempts[-1]["repair"] if attempts else None,
                }
            self._publish(
                "verification", record, status="started", seconds=self.verify_s
            )
            if self.background:
                threading.Thread(
                    target=self._watch_verification,
                    args=(machine_id, record),
                    daemon=True,
                ).start()

    def _restart_steps(self, machine_id: str) -> List[Dict[str, Any]]:
        from agent.procedures import plan_restart

        machine = self.dispatcher.machine(machine_id)
        return plan_restart(machine.commands, machine.state)

    def _run_step(self, machine_id: str, step: Dict[str, Any]) -> tuple[bool, str]:
        """Dispatch one step, retrying while the machine says 'not yet', then wait for its effect."""
        deadline = self.clock() + self.step_timeout_s
        while True:
            res = self.dispatcher.execute(
                {
                    "machine_id": machine_id,
                    "command": step["command"],
                    "params": step.get("params") or {},
                    "reason": "Quy trình đã duyệt",
                }
            )
            details = res.get("details") or {}
            if res.get("status") == "SUCCESS":
                break
            if not details.get("retryable") or self.clock() >= deadline:
                return False, res.get("error") or str(
                    details.get("execution_detail") or res.get("status")
                )
            self.sleep(self.poll_s)
        machine = self.dispatcher.machine(machine_id)
        if step.get("kind") == "repair":
            while machine.state == cmd.MAINTENANCE:
                if self.clock() >= deadline:
                    return False, "quá thời gian chờ bảo trì"
                self.sleep(self.poll_s)
            fixed = (machine.last_repair or {}).get("fault_was_present")
            return True, "đã sửa xong" + (
                "" if fixed else " (bộ phận này không có lỗi)"
            )
        if step["command"] == "START":
            while machine.state != cmd.RUNNING:
                if machine.state != cmd.STARTING or self.clock() >= deadline:
                    return False, f"máy không vào RUNNING (đang {machine.state})"
                self.sleep(self.poll_s)
            return True, "máy đã chạy"
        return True, str(details.get("execution_detail", ""))

    # ------------------------------------------------------------------ verification
    def on_alert(self, event: Dict[str, Any]) -> None:
        """Edge alert for a machine under verification: the repair did not hold."""
        machine_id = event.get("machine_id", "")
        with self._lock:
            watch = self._verifying.pop(machine_id, None)
            if watch is None:
                return
            for a in self._attempts.get(machine_id, []):
                if a["outcome"] == "verifying":
                    a["outcome"] = "failed"
        params = [a.get("param") for a in event.get("anomalies") or []]
        self._publish(
            "verification",
            {"machine_id": machine_id},
            status="failed",
            repair=watch["repair"],
            params=params,
        )

    def check_verification(self, machine_id: str) -> Optional[str]:
        """Close the window once it has passed without an alert. Returns the outcome if it closed."""
        with self._lock:
            watch = self._verifying.get(machine_id)
            if watch is None or self.clock() < watch["until"]:
                return None
            self._verifying.pop(machine_id)
            self._attempts.pop(
                machine_id, None
            )  # healthy again: the attempt history starts over
        self._publish(
            "verification",
            {"machine_id": machine_id},
            status="verified",
            repair=watch["repair"],
        )
        return "verified"

    def _watch_verification(self, machine_id: str, record: Dict[str, Any]) -> None:
        while self.phase(machine_id) == "verifying":
            if self.check_verification(machine_id):
                return
            self.sleep(self.poll_s)

    def _publish(self, event_type: str, record: Dict[str, Any], **extra: Any) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            {
                "event_type": event_type,
                "machine_id": record.get("machine_id"),
                "procedure_id": record.get("approval_id"),
                "kind": record.get("kind"),
                "timestamp": datetime.now().isoformat(),
                **extra,
            }
        )
