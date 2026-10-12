# agent/brain.py
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("AgentBrain")


class AgentBrain:
    def __init__(
        self,
        rag_engine: Any,
        tools: Any,
        event_bus: Any = None,
        execute_actions: bool = True,
        repeat_window_s: float = 0.0,
        has_pending: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.rag = rag_engine
        self.tools = tools
        self.event_bus = event_bus
        self.execute_actions = execute_actions
        # Bộ nhớ lưu trạng thái gần nhất của các máy
        self.machine_states: Dict[str, Dict[str, Any]] = {}
        # Khác 0: trong một đợt sự cố, máy chỉ được chẩn đoán lại khi có THÊM chỉ số bất thường mới -
        # bộ lọc biên báo lại cùng chỉ số mỗi phút, và mỗi lần là một lượt gọi LLM và một chẩn đoán trùng.
        # Đợt kết thúc ở handle_recovered (máy bình thường trở lại). 0 = luôn chẩn đoán (như bản gốc).
        self.repeat_window_s = repeat_window_s
        self._diagnosed: Dict[
            str, set
        ] = {}  # máy -> các chỉ số đã chẩn đoán trong đợt này
        # Máy còn lệnh chờ duyệt không: không còn lệnh nào mà máy vẫn báo lỗi (vd. lỗi thứ hai sau khi
        # đã sửa lỗi thứ nhất) thì cảnh báo lặp được chẩn đoán lại thay vì bỏ qua.
        self.has_pending = has_pending

    def handle_heartbeat(self, event: Dict[str, Any]) -> None:
        """Gói tin 'normal' (chu kỳ định kỳ): chỉ cập nhật trạng thái sống, không gọi RAG."""
        machine_id = event.get("machine_id", "UNKNOWN")
        self.machine_states[machine_id] = {
            "timestamp": event.get("timestamp"),
            "machine_type": event.get("machine_type", ""),
            "payload": event.get("payload", {}),
        }

    def handle_recovered(self, event: Dict[str, Any]) -> None:
        """Gói tin 'machine_recovered': đợt sự cố đã đóng, lần cảnh báo sau là sự cố mới."""
        self._diagnosed.pop(event.get("machine_id", "UNKNOWN"), None)

    def handle_alert(self, event: Dict[str, Any]) -> None:
        """Gói tin 'alert': Quy trình xử lý sự cố chuẩn hóa với LLM/RAG."""
        machine_id = event.get("machine_id", "UNKNOWN")
        machine_type = event.get("machine_type", "")
        payload = event.get("payload", {})

        params = {
            str(a.get("param"))
            for a in event.get("anomalies") or []
            if isinstance(a, dict)
        }
        if self.repeat_window_s:
            seen = self._diagnosed.get(machine_id, set())
            waiting = self.has_pending is None or self.has_pending(machine_id)
            if params <= seen and waiting:
                logger.info(
                    f"[Brain] Bỏ qua cảnh báo lặp {machine_id} {sorted(params)} (đã chẩn đoán trong đợt này)"
                )
                return
            # Chỉ số mới tham gia: chẩn đoán lại với toàn bộ telemetry hiện tại.
            self._diagnosed[machine_id] = seen | params

        logger.info(
            f"[Brain] Bắt đầu xử lý cảnh báo cho máy {machine_id} ({machine_type})"
        )

        # =========================================================================
        # BƯỚC 1: Gọi RAG + LLM với Schema ép buộc để chuẩn hóa định dạng IoT
        # =========================================================================
        diagnosis_text = ""
        actions: List[Dict[str, Any]] = []

        schema_result = None
        # Kiểm tra nếu RAG hỗ trợ query_with_schema và trả về dict thực sự
        if hasattr(self.rag, "query_with_schema") and callable(
            getattr(self.rag, "query_with_schema", None)
        ):
            try:
                res = self.rag.query_with_schema(
                    machine_id=machine_id,
                    machine_type=machine_type,
                    telemetry=payload,
                )
                if isinstance(res, dict):
                    schema_result = res
            except Exception as exc:
                logger.warning(f"[Brain] Lỗi gọi query_with_schema: {exc}")

        if schema_result is not None:
            diagnosis_text = str(schema_result.get("diagnosis", "") or "")
            raw_actions = schema_result.get("actions", [])
            actions = (
                list(raw_actions) if isinstance(raw_actions, (list, tuple)) else []
            )
        else:
            # Fallback tương thích nếu đối tượng RAG chỉ hỗ trợ query chuỗi
            rag_input = (
                f"đây là máy {machine_type} (ID: {machine_id}), "
                f"đang có trạng thái {payload}, "
                f"hãy đưa ra giải pháp giúp máy ổn định"
            )
            raw_advice = self.rag.query(rag_input) if hasattr(self.rag, "query") else ""
            diagnosis_text = str(raw_advice) if raw_advice is not None else ""

        # Phát câu chẩn đoán của RAG lên Chatbot Dashboard cho kỹ sư đọc
        if self.event_bus and diagnosis_text:
            self.event_bus.publish(
                {
                    "event_type": "chat_notification",
                    "machine_id": machine_id,
                    "text": diagnosis_text,
                    "source": "AI_RAG",
                }
            )

        # =========================================================================
        # BƯỚC 2: Phòng vệ an toàn (Defensive Fallback)
        # Nếu LLM không sinh ra actions trong JSON thì dùng Tool bóc tách từ text
        # =========================================================================
        if (
            not actions
            and diagnosis_text
            and hasattr(self.tools, "translate_advice_to_actions")
        ):
            logger.info(
                "[Brain] Kích hoạt Defensive Fallback: Dùng tools để bóc tách hành động từ văn bản."
            )
            extracted = self.tools.translate_advice_to_actions(
                machine_id=machine_id,
                machine_type=machine_type,
                advice_text=diagnosis_text,
            )
            if isinstance(extracted, (list, tuple)):
                actions = list(extracted)

        # =========================================================================
        # BƯỚC 3: Đẩy các hành động chuẩn hóa cố định vào EventBus cho IoT Core
        # =========================================================================
        if actions and self.event_bus:
            for act in actions:
                if not isinstance(act, dict):
                    continue
                cmd_name = act.get("command")
                if not cmd_name:
                    continue

                params = act.get("params", {})
                risk_level = act.get("risk_level", "LOW")
                reason = act.get("reason", "Thực thi theo khuyến nghị chuẩn từ RAG")

                command_event = {
                    "event_type": "action_command"
                    if self.execute_actions
                    else "action_proposed",
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
