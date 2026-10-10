import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.agent.agent_analyzer import AgentAnalyzer
from app.agent.rule_analyzer import RuleAnalyzer
from app.config import evaluate_metric_status, load_machines_config, settings
from app.db import DatabaseManager
from app.gateway.actions import ActionService
from app.stream import broadcaster

logger = logging.getLogger("app.gateway.lifecycle")


class IncidentLifecycleManager:
    """
    Manages the lifecycle of incidents, automatic ReAct Agent or playbook analysis,
    HITL gates, autonomy modes, and background monitoring.
    """

    def __init__(self, db: DatabaseManager, action_service: ActionService):
        self.db = db
        self.action_service = action_service
        self.rule_analyzer = RuleAnalyzer(playbooks_path="config/playbooks.yaml")
        self.agent_analyzer = AgentAnalyzer(rule_analyzer=self.rule_analyzer)
        self.running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @property
    def analyzer(self):
        """Dynamically select analyzer based on AGENT_MODE setting."""
        if settings.AGENT_MODE == "rules":
            return self.rule_analyzer
        return self.agent_analyzer

    async def start(self):
        self.running = True
        self._loop_task = asyncio.create_task(self._background_lifecycle_loop())
        logger.info("Incident Lifecycle Manager started.")

    async def stop(self):
        self.running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("Incident Lifecycle Manager stopped.")

    async def handle_inbound_event(self, event_dict: Dict[str, Any]):
        """
        Processes a newly ingested event (already deduped).
        If event is ERROR or WARNING, associates with open incident or creates a new one.
        """
        ev_type = event_dict.get("event_type", "ERROR")
        if ev_type not in ("ERROR", "WARNING"):
            return

        machine_id = event_dict["machine_id"]
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%H:%M:%S")

        async with self._lock:
            open_inc = await self.db.get_open_incident(machine_id)

            if open_inc:
                # Merge into existing open incident
                inc_id = open_inc["id"]
                logger.info(f"Merging event {event_dict.get('error_code')} into existing incident {inc_id} ({machine_id})")

                # Append to timeline
                await self.db.append_incident_timeline(
                    inc_id,
                    {
                        "id": f"EVT-{int(now.timestamp() * 1000)}-merged",
                        "timestamp": now_str,
                        "type": "anomaly_detected",
                        "label": f"Ghi nhận thêm sự kiện: {event_dict.get('error_code')}",
                        "detail": event_dict.get("message", ""),
                    },
                )
                inc_obj = await self.db.get_incident(inc_id)
                if inc_obj:
                    broadcaster.broadcast_incident("updated", inc_obj)
                return

            # No open incident exists for this machine: create a new one
            logger.info(f"Opening new incident for machine {machine_id} on event {event_dict.get('error_code')}")

            # Run Active Analyzer (AgentAnalyzer with fallback, or RuleAnalyzer)
            analysis = await self.analyzer.analyze_incident(
                machine_id=machine_id,
                trigger_event=event_dict,
                db_manager=self.db,
            )

            # Determine initial incident status
            initial_status = "active"
            if analysis.proposed_action and settings.AGENT_ENABLED:
                if settings.AUTONOMY_MODE == "advisory":
                    initial_status = "active"
                elif settings.AUTONOMY_MODE == "auto_safe" and analysis.proposed_action.command == "SET_RPM":
                    # Can be auto executed
                    initial_status = "active"
                else:
                    initial_status = "awaiting_approval"

            # Create incident in DB
            inc_id = await self.db.create_incident({
                "machine_id": machine_id,
                "status": initial_status,
                "severity": analysis.severity,
                "title": analysis.title,
                "opened_at": now,
                "timeline": analysis.timeline_events,
                "root_cause": analysis.root_cause,
                "confidence": analysis.confidence,
                "tags": analysis.tags,
            })

            inc_obj = await self.db.get_incident(inc_id)
            if inc_obj:
                broadcaster.broadcast_incident("created", inc_obj)

            # Audit log for incident creation
            await self.db.insert_audit_log(
                actor="system",
                action="incident_created",
                machine_id=machine_id,
                incident_id=inc_id,
                details={
                    "root_cause": analysis.root_cause,
                    "confidence": analysis.confidence,
                    "severity": analysis.severity,
                },
            )

            # If there is a proposed action, create it in DB
            if analysis.proposed_action and settings.AGENT_ENABLED:
                expires_at = datetime.fromtimestamp(
                    now.timestamp() + settings.ACTION_TTL_S, tz=timezone.utc
                )
                action_id = await self.db.create_action({
                    "incident_id": inc_id,
                    "machine_id": machine_id,
                    "command": analysis.proposed_action.command,
                    "params": analysis.proposed_action.params,
                    "rationale": analysis.proposed_action.rationale,
                    "status": "pending",
                    "proposed_at": now,
                    "expires_at": expires_at,
                    "auto_executed": False,
                })

                act_obj = await self.db.get_action(action_id)
                if act_obj:
                    broadcaster.broadcast_action("proposed", act_obj)

                await self.db.insert_audit_log(
                    actor="agent",
                    action="action_proposed",
                    machine_id=machine_id,
                    incident_id=inc_id,
                    details={
                        "action_id": action_id,
                        "command": analysis.proposed_action.command,
                        "params": analysis.proposed_action.params,
                    },
                )

                # Check auto_safe execution
                if settings.AUTONOMY_MODE == "auto_safe" and analysis.proposed_action.command == "SET_RPM":
                    await self._try_auto_execute_action(
                        inc_id=inc_id,
                        action_id=action_id,
                        machine_id=machine_id,
                        action_plan=analysis.proposed_action,
                    )

    async def _try_auto_execute_action(
        self,
        inc_id: str,
        action_id: str,
        machine_id: str,
        action_plan: Any,
    ):
        """
        Executes action automatically under auto_safe rules:
        - Max 2 auto actions per incident
        - At least 120s between auto actions
        - Actor = agent in audit log
        - Informational timeline note
        """
        auto_count = await self.db.count_auto_actions_for_incident(inc_id)
        if auto_count >= 2:
            logger.info(f"Auto-safe: Maximum 2 auto commands reached for incident {inc_id}. Keeping pending for HITL.")
            await self.db.update_incident(inc_id, {"status": "awaiting_approval"})
            inc_obj = await self.db.get_incident(inc_id)
            if inc_obj:
                broadcaster.broadcast_incident("status_changed", inc_obj)
            return

        last_auto_time = await self.db.get_latest_auto_action_time(inc_id)
        now = datetime.now(timezone.utc)
        if last_auto_time:
            elapsed = (now - last_auto_time).total_seconds()
            if elapsed < 120.0:
                logger.info(
                    f"Auto-safe: Cooldown of 120s not met ({elapsed:.1f}s elapsed). Keeping pending for HITL."
                )
                await self.db.update_incident(inc_id, {"status": "awaiting_approval"})
                inc_obj = await self.db.get_incident(inc_id)
                if inc_obj:
                    broadcaster.broadcast_incident("status_changed", inc_obj)
                return

        logger.info(f"Auto-safe mode executing action {action_id} automatically for incident {inc_id} ({machine_id})")
        await self.db.update_action(action_id, {"auto_executed": True})

        now_str = now.strftime("%H:%M:%S")
        await self.db.append_incident_timeline(
            inc_id,
            {
                "id": f"EVT-{int(now.timestamp() * 1000)}-auto",
                "timestamp": now_str,
                "type": "executing",
                "label": "Tự động thực thi an toàn (Auto-Safe Triggered)",
                "detail": f"Hệ thống tự động thực thi lệnh {action_plan.command} theo chế độ auto_safe (lệnh #{auto_count + 1}/2). Người vận hành có thể hoàn tác.",
            },
        )

        try:
            await self.action_service.approve_action(action_id=action_id, actor="agent")
        except Exception as e:
            logger.error(f"Failed to auto-execute action {action_id}: {e}")

    async def _background_lifecycle_loop(self):
        """
        Background monitor running every 3 seconds:
        1. Checks action TTL expirations.
        2. Checks if incidents can be closed (e.g. sustained normal metrics) or mitigated.
        """
        while self.running:
            try:
                await self._check_expired_actions()
                await self._check_incident_auto_mitigation()
            except Exception as e:
                logger.error(f"Error in lifecycle loop: {e}", exc_info=True)
            await asyncio.sleep(3.0)

    async def _check_expired_actions(self):
        """Marks pending actions past TTL as expired."""
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%H:%M:%S")

        incidents = await self.db.list_incidents()
        for inc in incidents:
            if inc["status"] == "closed":
                continue
            pending_action = await self.db.get_pending_action_for_incident(inc["id"])
            if pending_action:
                exp = pending_action["expires_at"]
                if isinstance(exp, str):
                    exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if exp and now > exp:
                    act_id = pending_action["id"]
                    logger.info(f"Action {act_id} expired past TTL ({settings.ACTION_TTL_S}s).")
                    await self.db.update_action(act_id, {"status": "expired"})
                    act_updated = await self.db.get_action(act_id)
                    if act_updated:
                        broadcaster.broadcast_action("expired", act_updated)

                    await self.db.insert_audit_log(
                        actor="system",
                        action="expire",
                        machine_id=pending_action["machine_id"],
                        incident_id=inc["id"],
                        details={"reason": "Action expired past TTL without operator approval"},
                    )
                    await self.db.append_incident_timeline(
                        inc["id"],
                        {
                            "id": f"EVT-{int(now.timestamp() * 1000)}-exp",
                            "timestamp": now_str,
                            "type": "expired",
                            "label": "Hành động hết hạn phê duyệt (Action expired)",
                            "detail": f"Quá thời hạn {settings.ACTION_TTL_S}s không có phản hồi từ người vận hành. Không thực thi lệnh PLC.",
                        },
                    )
                    if inc["status"] == "awaiting_approval":
                        await self.db.update_incident(inc["id"], {"status": "active"})
                        inc_updated = await self.db.get_incident(inc["id"])
                        if inc_updated:
                            broadcaster.broadcast_incident("status_changed", inc_updated)

    async def _check_incident_auto_mitigation(self):
        """
        Checks open incidents for closed-loop sensitivity recovery.
        If all metrics return to normal, marks incident as resolved/closed.
        """
        machines_cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%H:%M:%S")

        incidents = await self.db.list_incidents()
        for inc in incidents:
            if inc["status"] in ("closed", "resolved"):
                continue

            m_id = inc["machine_id"]
            m_cfg = machines_cfg.machines.get(m_id)
            if not m_cfg:
                continue

            latest_metrics = await self.db.get_latest_metrics(m_id)
            if not latest_metrics:
                continue

            all_normal = True
            has_critical = False
            for m_key, conf in m_cfg.metrics.items():
                if m_key in latest_metrics:
                    val = latest_metrics[m_key][1]
                    st = evaluate_metric_status(val, conf)
                    if st != "normal":
                        all_normal = False
                    if st == "critical":
                        has_critical = True

            # If all metrics are completely normal after derate (e.g. condenser_fouled):
            if all_normal and inc["status"] in ("acknowledged", "active"):
                logger.info(f"All metrics for {m_id} returned to normal. Auto-resolving incident {inc['id']}.")
                await self.db.append_incident_timeline(
                    inc["id"],
                    {
                        "id": f"EVT-{int(now.timestamp() * 1000)}-res",
                        "timestamp": now_str,
                        "type": "acknowledged",
                        "label": "Tất cả thông số đã trở lại bình thường (Normal recovered)",
                        "detail": "Các giá trị cảm biến đã hồi phục vào dải tiêu chuẩn. Sự cố có thể đóng.",
                    },
                )
                await self.db.update_incident(
                    inc["id"],
                    {
                        "status": "resolved",
                        "closed_at": now,
                    },
                )
                await self.db.insert_audit_log(
                    actor="system",
                    action="incident_resolved",
                    machine_id=m_id,
                    incident_id=inc["id"],
                    details={"reason": "All metrics recovered to normal range"},
                )
                inc_updated = await self.db.get_incident(inc["id"])
                if inc_updated:
                    broadcaster.broadcast_incident("resolved", inc_updated)
            elif not has_critical and inc["status"] == "acknowledged":
                # Mitigated state: no longer critical, but root cause ticket open
                pass
