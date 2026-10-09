import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status

from app.commands import command_dispatcher, validate_command_guardrails
from app.config import load_machines_config, settings
from app.db import DatabaseManager
from app.stream import broadcaster

logger = logging.getLogger("app.gateway.actions")


class ActionService:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def approve_action(self, action_id: str, actor: str = "user:operator") -> Dict[str, Any]:
        """
        Approves and executes a proposed action.
        Idempotent: Approving an already approved/acked action will NOT re-send command.
        """
        action = await self.db.get_action(action_id)
        if not action:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Action '{action_id}' not found",
            )

        # Idempotency check: if already approved or acked, return previous ACK without re-sending
        if action["status"] in ("approved", "acked"):
            prev_ack = action.get("ack") or {}
            ack_msg = prev_ack.get("message", "Action already executed")
            code = prev_ack.get("code", 200)
            return {"ack": f"ACK {code}: {ack_msg}"}

        now = datetime.now(timezone.utc)

        # Check expiration
        expires_at = action["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_at and now > expires_at:
            await self.db.update_action(action_id, {"status": "expired"})
            action_updated = await self.db.get_action(action_id)
            if action_updated:
                broadcaster.broadcast_action("expired", action_updated)
            await self.db.insert_audit_log(
                actor="system",
                action="expire",
                machine_id=action["machine_id"],
                incident_id=action["incident_id"],
                details={"reason": "Action expired before approval"},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Action has expired. It cannot be approved or executed.",
            )

        if action["status"] == "rejected":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Action was already rejected.",
            )

        # Re-validate safety guardrails at execution time using real-time machine telemetry
        machine_id = action["machine_id"]
        latest_metrics = await self.db.get_latest_metrics(machine_id)
        current_rpm = 1500.0
        if "compressor_rpm" in latest_metrics:
            current_rpm = float(latest_metrics["compressor_rpm"][1])
        else:
            cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
            if machine_id in cfg.machines:
                current_rpm = cfg.machines[machine_id].rpm_setpoint

        is_valid, reason = validate_command_guardrails(
            machine_id=machine_id,
            command=action["command"],
            params=action["params"],
            current_rpm=current_rpm,
            is_auto=action.get("auto_executed", False),
        )
        if not is_valid:
            await self.db.update_action(action_id, {"status": "failed"})
            action_updated = await self.db.get_action(action_id)
            if action_updated:
                broadcaster.broadcast_action("failed", action_updated)
            await self.db.insert_audit_log(
                actor=actor,
                action="guardrail_reject",
                machine_id=machine_id,
                incident_id=action["incident_id"],
                details={"violation": reason},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Safety guardrails rejected execution: {reason}",
            )

        # Mark action as executing
        await self.db.update_action(
            action_id,
            {
                "status": "executing",
                "decided_by": actor,
                "decided_at": now,
            },
        )
        action_updated = await self.db.get_action(action_id)
        if action_updated:
            broadcaster.broadcast_action("executing", action_updated)

        await self.db.insert_audit_log(
            actor=actor,
            action="approve",
            machine_id=machine_id,
            incident_id=action["incident_id"],
            details={"command": action["command"], "params": action["params"]},
        )

        # Dispatch command via MQTT
        ack_res = await command_dispatcher.dispatch_command(
            machine_id=machine_id,
            command=action["command"],
            params=action["params"],
            issued_by=actor,
            incident_id=action["incident_id"],
            command_id=action_id,
            timeout_s=10.0,
        )

        ack_status = ack_res.get("status", "FAILED")
        ack_code = ack_res.get("code", 500)
        ack_message = ack_res.get("message", "No response")

        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

        if ack_status == "OK":
            # Successful execution
            await self.db.update_action(
                action_id,
                {
                    "status": "acked",
                    "ack": ack_res,
                },
            )
            action_updated = await self.db.get_action(action_id)
            if action_updated:
                broadcaster.broadcast_action("acked", action_updated)

            await self.db.insert_audit_log(
                actor=actor,
                action="ack",
                machine_id=machine_id,
                incident_id=action["incident_id"],
                details=ack_res,
            )

            # Update timeline and incident status
            await self.db.append_incident_timeline(
                action["incident_id"],
                {
                    "id": f"EVT-{int(datetime.now(timezone.utc).timestamp() * 1000)}-ack",
                    "timestamp": now_str,
                    "type": "acknowledged",
                    "label": f"Lệnh PLC hoàn tất: {action['command']} ({ack_code})",
                    "detail": f"{ack_message}. Tốc độ máy nén đã được điều chỉnh.",
                },
            )
            await self.db.update_incident(
                action["incident_id"],
                {"status": "acknowledged"},
            )
            inc_updated = await self.db.get_incident(action["incident_id"])
            if inc_updated:
                broadcaster.broadcast_incident("status_changed", inc_updated)

            return {"ack": f"ACK {ack_code}: {ack_message}"}
        else:
            # Command rejected or failed
            await self.db.update_action(
                action_id,
                {
                    "status": "failed",
                    "ack": ack_res,
                },
            )
            action_updated = await self.db.get_action(action_id)
            if action_updated:
                broadcaster.broadcast_action("failed", action_updated)

            await self.db.insert_audit_log(
                actor=actor,
                action="command_failed",
                machine_id=machine_id,
                incident_id=action["incident_id"],
                details=ack_res,
            )
            await self.db.append_incident_timeline(
                action["incident_id"],
                {
                    "id": f"EVT-{int(datetime.now(timezone.utc).timestamp() * 1000)}-fail",
                    "timestamp": now_str,
                    "type": "rejected",
                    "label": f"Lệnh PLC thất bại: {action['command']} ({ack_code})",
                    "detail": f"Mã lỗi {ack_code}: {ack_message}",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"PLC command failed: {ack_message} (code {ack_code})",
            )

    async def reject_action(
        self, action_id: str, reason: str = "", actor: str = "user:operator"
    ) -> Dict[str, Any]:
        """
        Rejects a proposed action.
        """
        action = await self.db.get_action(action_id)
        if not action:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Action '{action_id}' not found",
            )

        now = datetime.now(timezone.utc)
        await self.db.update_action(
            action_id,
            {
                "status": "rejected",
                "decided_by": actor,
                "decided_at": now,
            },
        )
        action_updated = await self.db.get_action(action_id)
        if action_updated:
            broadcaster.broadcast_action("rejected", action_updated)

        await self.db.insert_audit_log(
            actor=actor,
            action="reject",
            machine_id=action["machine_id"],
            incident_id=action["incident_id"],
            details={"reason": reason or "Người vận hành từ chối."},
        )

        now_str = now.strftime("%H:%M:%S")
        await self.db.append_incident_timeline(
            action["incident_id"],
            {
                "id": f"EVT-{int(now.timestamp() * 1000)}-rej",
                "timestamp": now_str,
                "type": "rejected",
                "label": "Người vận hành từ chối thực thi",
                "detail": reason or "Giữ nguyên trạng thái vận hành hiện tại.",
            },
        )
        await self.db.update_incident(action["incident_id"], {"status": "active"})
        inc_updated = await self.db.get_incident(action["incident_id"])
        if inc_updated:
            broadcaster.broadcast_incident("status_changed", inc_updated)

        return {"status": "ok"}


action_service = ActionService(DatabaseManager())
