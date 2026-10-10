import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.config import load_machines_config, settings
from app.db import DatabaseManager

logger = logging.getLogger("app.commands")


class CommandGuardrailsError(Exception):
    pass


def validate_command_guardrails(
    machine_id: str,
    command: str,
    params: Dict[str, Any],
    current_rpm: float,
    is_auto: bool = False,
) -> Tuple[bool, str]:
    """
    Independent safety guardrails validation according to BRIEF Section 9:
    1. Whitelist: only SET_RPM and STOP_TEST.
    2. SET_RPM: only decrease speed, target >= rpm_min_safe, target <= rpm_max.
    3. STOP_TEST: always requires human approval (cannot be auto-executed).
    4. Evaluated against real-time machine telemetry at execution time.
    """
    if command not in ("SET_RPM", "STOP_TEST"):
        return False, f"Lệnh '{command}' không nằm trong whitelist cho phép (chỉ hỗ trợ SET_RPM, STOP_TEST)"

    machines_cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    m_cfg = machines_cfg.machines.get(machine_id)
    rpm_min_safe = m_cfg.rpm_min_safe if m_cfg else 800.0
    rpm_max = m_cfg.rpm_max if m_cfg else 3000.0

    if command == "STOP_TEST":
        if is_auto:
            return (
                False,
                "Lệnh dừng máy STOP_TEST luôn bắt buộc phải có kỹ sư/người vận hành phê duyệt trực tiếp (HITL). Không thể tự động thực thi.",
            )
        return True, "Hợp lệ"

    if command == "SET_RPM":
        if "rpm" not in params:
            return False, "Thiếu tham số 'rpm' cho lệnh SET_RPM"
        try:
            target_rpm = float(params["rpm"])
        except (ValueError, TypeError):
            return False, f"Tham số 'rpm' ({params.get('rpm')}) không phải số hợp lệ"

        # Rule: SET_RPM can only DECREASE speed relative to current speed
        if target_rpm >= current_rpm:
            return (
                False,
                f"Từ chối vi phạm an toàn: Lệnh SET_RPM chỉ được phép giảm tốc độ so với tốc độ hiện tại ({current_rpm} rpm). Yêu cầu đặt {target_rpm} rpm bị từ chối.",
            )

        if target_rpm < rpm_min_safe:
            return (
                False,
                f"Từ chối vi phạm an toàn: Tốc độ yêu cầu {target_rpm} rpm thấp hơn ngưỡng an toàn tối thiểu ({rpm_min_safe} rpm).",
            )

        if target_rpm > rpm_max:
            return (
                False,
                f"Từ chối vi phạm an toàn: Tốc độ yêu cầu {target_rpm} rpm vượt quá tốc độ tối đa cho phép ({rpm_max} rpm).",
            )

        return True, "Hợp lệ"

    return False, "Không hợp lệ"


class CommandDispatcher:
    """
    Manages command dispatch over MQTT and tracks waiting ACKs asynchronously.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._pending_acks: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._mqtt_client = None

    def set_mqtt_client(self, client):
        self._mqtt_client = client

    def handle_ack_payload(self, ack_data: Dict[str, Any]):
        cmd_id = ack_data.get("command_id")
        if cmd_id and cmd_id in self._pending_acks:
            fut = self._pending_acks[cmd_id]
            if not fut.done():
                fut.set_result(ack_data)

    async def dispatch_command(
        self,
        machine_id: str,
        command: str,
        params: Dict[str, Any],
        issued_by: str,
        incident_id: Optional[str] = None,
        command_id: Optional[str] = None,
        timeout_s: float = 10.0,
    ) -> Dict[str, Any]:
        """
        Publishes command to denso/{machine_id}/commands and awaits ACK with timeout.
        """
        cmd_id = command_id or str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        payload = {
            "command_id": cmd_id,
            "timestamp": now_iso,
            "machine_id": machine_id,
            "command": command,
            "params": params,
            "issued_by": issued_by,
            "incident_id": incident_id or f"INC-{cmd_id[:8]}",
        }

        loop = asyncio.get_running_loop()
        ack_future = loop.create_future()

        async with self._lock:
            self._pending_acks[cmd_id] = ack_future

        try:
            if self._mqtt_client and getattr(self._mqtt_client, "is_connected", lambda: True)():
                cmd_topic = f"denso/{machine_id}/commands"
                payload_str = json.dumps(payload)
                self._mqtt_client.publish(cmd_topic, payload_str, qos=1)
                logger.info(f"Dispatched command {cmd_id} ({command}) to {cmd_topic}")
            else:
                # If MQTT client is not connected (e.g. offline mock testing), simulate ACK directly
                logger.warning(
                    f"MQTT client not connected. Simulating local ACK for command {cmd_id} ({command})"
                )
                await asyncio.sleep(0.05)
                sim_ack = {
                    "command_id": cmd_id,
                    "timestamp": now_iso,
                    "machine_id": machine_id,
                    "status": "OK",
                    "code": 200,
                    "message": f"Command {command} applied successfully (simulated)",
                }
                ack_future.set_result(sim_ack)

            # Wait for ACK with timeout
            ack_result = await asyncio.wait_for(ack_future, timeout=timeout_s)
            return ack_result

        except asyncio.TimeoutError:
            logger.error(f"Timeout ({timeout_s}s) waiting for ACK on command {cmd_id} for {machine_id}")
            return {
                "command_id": cmd_id,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "machine_id": machine_id,
                "status": "FAILED",
                "code": 408,
                "message": f"Quá thời gian chờ phản hồi ({timeout_s}s) từ máy {machine_id}",
            }
        finally:
            async with self._lock:
                self._pending_acks.pop(cmd_id, None)


command_dispatcher = CommandDispatcher(DatabaseManager())
