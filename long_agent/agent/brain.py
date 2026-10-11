# agent/brain.py
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AgentBrain")


class AgentBrain:
    """Turns edge alerts into one diagnosis and at most one proposed command per incident.

    Rules: a machine that is busy (a procedure running or a ticket waiting) is not diagnosed again;
    the diagnosis gets the repairs already tried on the machine; only commands the RAG engine
    validated against the machine's declaration are published - never commands guessed from text.
    """

    def __init__(
        self,
        rag_engine: Any,
        event_bus: Any = None,
        execute_actions: bool = True,
        repeat_window_s: float = 0.0,
        busy: Optional[Callable[[str], bool]] = None,
        attempts: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
    ) -> None:
        self.rag = rag_engine
        self.event_bus = event_bus
        self.execute_actions = execute_actions
        self.busy = busy
        self.attempts = attempts
        self.machine_states: Dict[str, Dict[str, Any]] = {}
        # Trong cửa sổ này, một máy chỉ được chẩn đoán lại khi có THÊM chỉ số bất thường mới: với LLM thật,
        # mỗi cảnh báo lặp là một lượt gọi API và một chẩn đoán trùng. 0 = luôn chẩn đoán.
        self.repeat_window_s = repeat_window_s
        self._diagnosed: Dict[str, Tuple[float, set]] = {}  # máy -> (thời điểm, các chỉ số đã chẩn đoán)

    def handle_heartbeat(self, event: Dict[str, Any]) -> None:
        """Gói tin 'normal': chỉ cập nhật trạng thái sống, không chẩn đoán."""
        machine_id = event.get("machine_id", "UNKNOWN")
        self.machine_states[machine_id] = {
            "timestamp": event.get("timestamp"),
            "machine_type": event.get("machine_type", ""),
            "payload": event.get("payload", {}),
        }

    def handle_verification(self, event: Dict[str, Any]) -> None:
        """A repair was verified or failed: the next alert is a new situation, diagnose it."""
        if event.get("status") in ("failed", "verified"):
            self._diagnosed.pop(event.get("machine_id", ""), None)

    def handle_alert(self, event: Dict[str, Any]) -> None:
        machine_id = event.get("machine_id", "UNKNOWN")
        machine_type = event.get("machine_type", "")
        payload = event.get("payload", {})

        if self.busy and self.busy(machine_id):
            logger.info(f"[Brain] {machine_id} đang có quy trình hoặc vé chờ duyệt: không chẩn đoán thêm")
            return
        params = {str(a.get("param")) for a in event.get("anomalies") or [] if isinstance(a, dict)}
        now = time.monotonic()
        if self.repeat_window_s:
            since, seen = self._diagnosed.get(machine_id, (float("-inf"), set()))
            if now - since < self.repeat_window_s and params <= seen:
                logger.info(f"[Brain] Bỏ qua cảnh báo lặp {machine_id} {sorted(params)} (đã chẩn đoán gần đây)")
                return
            self._diagnosed[machine_id] = (now, (seen | params) if now - since < self.repeat_window_s else params)

        logger.info(f"[Brain] Chẩn đoán {machine_id} ({machine_type})")
        attempts = self.attempts(machine_id) if self.attempts else []
        try:
            result = self.rag.query_with_schema(machine_id=machine_id, machine_type=machine_type,
                                                telemetry=payload, attempts=attempts)
        except Exception as exc:
            logger.exception(f"[Brain] Chẩn đoán {machine_id} lỗi: {exc}")
            result = {"diagnosis": f"Agent không chẩn đoán được cảnh báo này ({exc}); cần kỹ sư kiểm tra.",
                      "actions": []}

        text = str(result.get("diagnosis") or "").strip()
        if result.get("sources"):
            text += "\n\nNguồn: " + "; ".join(result["sources"])
        elif result.get("documents_used") is False:
            text += "\n\n(Không lấy được tài liệu bảo trì: chẩn đoán dựa trên ngưỡng vận hành.)"
        for note in result.get("notes") or []:
            text += f"\n⚠ {note}"
        if self.event_bus and text:
            self.event_bus.publish({"event_type": "chat_notification", "machine_id": machine_id,
                                    "text": text, "source": "AI_RAG"})

        for act in result.get("actions") or []:
            if not self.event_bus or not isinstance(act, dict) or not act.get("command"):
                continue
            self.event_bus.publish({
                "event_type": "action_command" if self.execute_actions else "action_proposed",
                "machine_id": machine_id,
                "command": act["command"],
                "kind": act.get("kind", "control"),
                "params": act.get("params", {}),
                "payload": act.get("params", {}),
                "risk_level": act.get("risk_level", "HIGH"),
                "reason": act.get("reason") or "Theo chẩn đoán của agent",
                "diagnosis": result.get("diagnosis", ""),
            })
            logger.info(f"[Brain] Đề xuất '{act['command']}' cho {machine_id}")

    def handle_user_query(self, query_text: str) -> str:
        """Câu hỏi kỹ sư gõ trên bảng tester."""
        text = (query_text or "").strip()
        if not text:
            return "Vui lòng nhập nội dung cần tra cứu."
        return self.rag.query(text)
