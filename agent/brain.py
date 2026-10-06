# agent/brain.py
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("AgentBrain")


class AgentBrain:
    def __init__(self, rag_engine: Any, tools: Any, event_bus: Any = None) -> None:
        self.rag = rag_engine
        self.tools = tools
        self.event_bus = event_bus
        # Bộ nhớ lưu trạng thái gần nhất của các máy
        self.machine_states: Dict[str, Dict[str, Any]] = {}

    def handle_heartbeat(self, event: Dict[str, Any]) -> None:
        """Gói tin 'normal' (chu kỳ 10s): chỉ cập nhật trạng thái sống, không gọi RAG."""
        machine_id = event.get("machine_id", "UNKNOWN")
        self.machine_states[machine_id] = {
            "timestamp": event.get("timestamp"),
            "machine_type": event.get("machine_type", ""),
            "payload": event.get("payload", {}),
        }

    def handle_alert(self, event: Dict[str, Any]) -> None:
        """Gói tin 'alert': Kích hoạt quy trình 3 bước xử lý sự cố."""
        machine_id = event.get("machine_id", "UNKNOWN")
        machine_type = event.get("machine_type", "")
        payload = event.get("payload", {})

        logger.info(f"[Brain] Bắt đầu xử lý cảnh báo cho máy {machine_id} ({machine_type})")

        # =========================================================================
        # BƯỚC 1: Gọi RAG với định dạng input theo yêu cầu
        # =========================================================================
        rag_input = (
            f"đây là máy {machine_type} (ID: {machine_id}), "
            f"đang có trạng thái {payload}, "
            f"hãy đưa ra giải pháp giúp máy ổn định"
        )

        # Hàm query từ RAG trả về một đoạn text tư vấn kỹ thuật
        advice_text = self.rag.query(rag_input)

        # Phát câu trả lời của RAG lên Chatbot để kỹ sư đọc
        if self.event_bus:
            self.event_bus.publish({
                "event_type": "chat_notification",
                "machine_id": machine_id,
                "text": advice_text,
                "source": "AI_RAG",
            })

        # =========================================================================
        # BƯỚC 2: Gọi hàm ở tool để dịch text của RAG thành chuỗi hành động chuẩn
        # =========================================================================
        # Tool sẽ dựa trên machine_type và nội dung advice_text để bóc tách hành động
        actions = self.tools.translate_advice_to_actions(
            machine_id=machine_id,
            machine_type=machine_type,
            advice_text=advice_text,
        )

        # =========================================================================
        # BƯỚC 3: Chuyển toàn bộ danh sách hành động chuẩn đó cho EventBus
        # =========================================================================
        if actions and self.event_bus:
            for act in actions:
                command_event = {
                    "event_type": "action_command",
                    "machine_id": machine_id,
                    "command": act.get("command"),
                    "params": act.get("params", {}),
                    "risk_level": act.get("risk_level", "LOW"),
                    "reason": act.get("reason", "Thực thi theo khuyến nghị từ RAG"),
                }
                # Bắn ra EventBus để action_approval hoặc actuator_dispatcher tiếp nhận
                self.event_bus.publish(command_event)
                logger.info(f"[Brain] Đã đẩy lệnh '{act.get('command')}' vào Bus cho máy {machine_id}")