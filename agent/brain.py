# agent/brain.py
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("AgentBrain")


class AgentBrain:
    def __init__(
        self,
        rag_engine: Any,
        tools: Any,
        event_bus: Any = None,
        execute_actions: bool = True,
    ) -> None:
        self.rag = rag_engine
        self.tools = tools
        self.event_bus = event_bus
        self.execute_actions = execute_actions
        # Bộ nhớ lưu trạng thái gần nhất của các máy
        self.machine_states: Dict[str, Dict[str, Any]] = {}

    def handle_heartbeat(self, event: Dict[str, Any]) -> None:
        """Gói tin 'normal' (chu kỳ định kỳ): chỉ cập nhật trạng thái sống, không gọi RAG."""
        machine_id = event.get("machine_id", "UNKNOWN")
        self.machine_states[machine_id] = {
            "timestamp": event.get("timestamp"),
            "machine_type": event.get("machine_type", ""),
            "payload": event.get("payload", {}),
        }

    def handle_alert(self, event: Dict[str, Any]) -> None:
        """Gói tin 'alert': Quy trình xử lý sự cố chuẩn hóa với LLM/RAG."""
        machine_id = event.get("machine_id", "UNKNOWN")
        machine_type = event.get("machine_type", "")
        payload = event.get("payload", {})

        logger.info(f"[Brain] Bắt đầu xử lý cảnh báo cho máy {machine_id} ({machine_type})")

        # =========================================================================
        # BƯỚC 1: Gọi RAG + LLM với Schema ép buộc để chuẩn hóa định dạng IoT
        # =========================================================================
        diagnosis_text = ""
        actions: List[Dict[str, Any]] = []

        if hasattr(self.rag, "query_with_schema"):
            schema_result = self.rag.query_with_schema(
                machine_id=machine_id,
                machine_type=machine_type,
                telemetry=payload,
            )
            diagnosis_text = schema_result.get("diagnosis", "")
            actions = schema_result.get("actions", [])
        else:
            # Tương thích nếu đối tượng RAG cũ chỉ hỗ trợ query chuỗi
            rag_input = (
                f"đây là máy {machine_type} (ID: {machine_id}), "
                f"đang có trạng thái {payload}, "
                f"hãy đưa ra giải pháp giúp máy ổn định"
            )
            diagnosis_text = self.rag.query(rag_input)

        # Phát câu chẩn đoán của RAG lên Chatbot Dashboard cho kỹ sư đọc
        if self.event_bus and diagnosis_text:
            self.event_bus.publish({
                "event_type": "chat_notification",
                "machine_id": machine_id,
                "text": diagnosis_text,
                "source": "AI_RAG",
            })

        # =========================================================================
        # BƯỚC 2: Phòng vệ an toàn (Defensive Fallback)
        # Nếu LLM không sinh ra actions trong JSON thì dùng Tool bóc tách từ text
        # =========================================================================
        if not actions and diagnosis_text and hasattr(self.tools, "translate_advice_to_actions"):
            logger.info("[Brain] Kích hoạt Defensive Fallback: Dùng tools để bóc tách hành động từ văn bản.")
            actions = self.tools.translate_advice_to_actions(
                machine_id=machine_id,
                machine_type=machine_type,
                advice_text=diagnosis_text,
            )

        # =========================================================================
        # BƯỚC 3: Đẩy các hành động chuẩn hóa cố định vào EventBus cho IoT Core
        # =========================================================================
        if actions and self.event_bus:
            for act in actions:
                cmd_name = act.get("command")
                if not cmd_name:
                    continue

                params = act.get("params", {})
                risk_level = act.get("risk_level", "LOW")
                reason = act.get("reason", "Thực thi theo khuyến nghị chuẩn từ RAG")

                command_event = {
                    "event_type": "action_command" if self.execute_actions else "action_proposed",
                    "machine_id": machine_id,
                    "command": cmd_name,
                    "params": params,
                    "payload": params,
                    "risk_level": risk_level,
                    "reason": reason,
                }
                self.event_bus.publish(command_event)
                logger.info(
                    f"[Brain] Đã đẩy lệnh chuẩn '{cmd_name}' (Risk: {risk_level}) "
                    f"vào Bus cho máy {machine_id}"
                )

    def handle_user_query(self, query_text: str) -> str:
        """Xử lý tin nhắn do user chủ động gửi từ ô chat trên Dashboard."""
        text = (query_text or "").strip()
        if not text:
            return "Vui lòng nhập nội dung cần tra cứu."

        logger.info(f"[Brain] User truy vấn: {text[:80]}")
        advice = self.rag.query(text)
        return advice
