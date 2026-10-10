# tests/test_rag_schema_formatter.py
from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

from agent.rag_engine import COMMAND_CATALOG, RAGEngine
from agent.brain import AgentBrain
from agent.tools import AgentTools
from iot.event_bus import EventBus


class RagSchemaFormatterTests(unittest.TestCase):
    """Kiểm tra khả năng chuẩn hóa văn phong khác nhau về format cố định của IoT."""

    def setUp(self) -> None:
        self.rag = RAGEngine()

    def test_command_catalog_contains_all_five_machines(self) -> None:
        expected_machines = {
            "CNC_MILLING",
            "ROBOT_ARM",
            "AMR_VEHICLE",
            "AOI_INSPECTION",
            "INJECTION_MOLDING",
        }
        self.assertTrue(expected_machines.issubset(set(COMMAND_CATALOG.keys())))
        for m_type in expected_machines:
            cmds = COMMAND_CATALOG[m_type]
            self.assertGreater(len(cmds), 0)
            for c in cmds:
                self.assertIn("command", c)
                self.assertIn("risk_level", c)
                self.assertIn(c["risk_level"], ("LOW", "HIGH"))

    def test_mock_query_with_schema_returns_valid_structure(self) -> None:
        telemetry = {
            "Spindle_Temp_C": 88.5,
            "Spindle_Load_Pct": 75.0,
            "Vibration_RMS_mm_s": 5.2,
        }
        res = self.rag.query_with_schema(
            machine_id="MC-MILL-01",
            machine_type="CNC_MILLING",
            telemetry=telemetry,
        )
        self.assertIn("diagnosis", res)
        self.assertIn("actions", res)
        self.assertIsInstance(res["actions"], list)
        self.assertGreater(len(res["actions"]), 0)

        for act in res["actions"]:
            self.assertIn("command", act)
            self.assertIn("params", act)
            self.assertIn("risk_level", act)
            self.assertIn(act["risk_level"], ("LOW", "HIGH"))

    def test_safe_parse_json_handles_markdown_and_surrounding_text(self) -> None:
        raw_llm_output = (
            "Chào bạn, dưới đây là chẩn đoán của hệ thống:\n"
            "```json\n"
            "{\n"
            '  "diagnosis": "Áp suất kẹp khuôn tụt dưới ngưỡng.",\n'
            '  "actions": [\n'
            "    {\n"
            '      "command": "REPAIR_HYDRAULIC_VALVE",\n'
            '      "params": {},\n'
            '      "risk_level": "HIGH",\n'
            '      "reason": "Rò van thủy lực"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
            "Vui lòng kiểm tra ngay."
        )
        parsed = self.rag._safe_parse_json(raw_llm_output)
        self.assertEqual(parsed["diagnosis"], "Áp suất kẹp khuôn tụt dưới ngưỡng.")
        self.assertEqual(len(parsed["actions"]), 1)
        self.assertEqual(parsed["actions"][0]["command"], "REPAIR_HYDRAULIC_VALVE")

    def test_whitelisting_filters_out_invented_commands(self) -> None:
        # Giả lập trường hợp LLM tự bịa ra lệnh không có trong whitelist
        fake_llm_callable = lambda prompt: json.dumps({
            "diagnosis": "Lỗi động cơ",
            "actions": [
                {
                    "command": "FAKE_NONEXISTENT_COMMAND",
                    "params": {},
                    "risk_level": "LOW",
                    "reason": "Lệnh không hợp lệ",
                },
                {
                    "command": "SET_FEED_OVERRIDE",
                    "params": {"override_pct": 40.0},
                    "risk_level": "LOW",
                    "reason": "Giảm tốc độ ăn dao",
                },
            ],
        })

        rag_with_llm = RAGEngine(llm_callable=fake_llm_callable)
        res = rag_with_llm.query_with_schema(
            machine_id="MC-MILL-01",
            machine_type="CNC_MILLING",
            telemetry={"Spindle_Load_Pct": 85.0},
        )
        # Chỉ lệnh SET_FEED_OVERRIDE được giữ lại
        commands = [a["command"] for a in res["actions"]]
        self.assertNotIn("FAKE_NONEXISTENT_COMMAND", commands)
        self.assertIn("SET_FEED_OVERRIDE", commands)
        self.assertEqual(len(res["actions"]), 1)

    def test_different_writing_styles_mapped_to_same_canonical_output(self) -> None:
        """
        Kiểm tra 3 văn phong khác nhau (formal, vắn tắt, tiếng Anh)
        nhưng cùng mang 1 ý nghĩa: đều được format về cùng lệnh IoT.
        """
        # Cùng một ý đồ can thiệp: Giảm feedrate 50% + Bơm bôi trơn trục chính
        style_formal_json = json.dumps({
            "diagnosis": "Kính gửi quý kỹ sư, hệ thống ghi nhận nhiệt độ tăng cao vượt mức cho phép.",
            "actions": [
                {"command": "SET_FEED_OVERRIDE", "params": {"override_pct": 50.0}, "risk_level": "LOW", "reason": "Giảm tải"},
                {"command": "REFILL_SPINDLE_LUBRICANT", "params": {}, "risk_level": "HIGH", "reason": "Bôi trơn"}
            ]
        })

        style_brief_json = json.dumps({
            "diagnosis": "Nóng trục chính. Hạ tải dao ngay.",
            "actions": [
                {"command": "SET_FEED_OVERRIDE", "params": {"override_pct": 50.0}, "risk_level": "LOW", "reason": "Hạ tốc 50%"},
                {"command": "REFILL_SPINDLE_LUBRICANT", "params": {}, "risk_level": "HIGH", "reason": "Thêm dầu"}
            ]
        })

        style_english_json = json.dumps({
            "diagnosis": "Critical spindle overheat detected on MC-MILL-01.",
            "actions": [
                {"command": "SET_FEED_OVERRIDE", "params": {"override_pct": 50.0}, "risk_level": "LOW", "reason": "Reduce feed to 50%"},
                {"command": "REFILL_SPINDLE_LUBRICANT", "params": {}, "risk_level": "HIGH", "reason": "Refill lube"}
            ]
        })

        for mock_output in (style_formal_json, style_brief_json, style_english_json):
            rag_engine = RAGEngine(llm_callable=lambda p: mock_output)
            res = rag_engine.query_with_schema("MC-MILL-01", "CNC_MILLING", {"Spindle_Temp_C": 92.0})
            cmds = [a["command"] for a in res["actions"]]
            self.assertEqual(cmds, ["SET_FEED_OVERRIDE", "REFILL_SPINDLE_LUBRICANT"])
            self.assertEqual(res["actions"][0]["params"]["override_pct"], 50.0)


class AgentBrainIntegrationTests(unittest.TestCase):
    """Kiểm tra tích hợp AgentBrain tiếp nhận output đã format từ RAGEngine."""

    def test_brain_handle_alert_publishes_chat_and_commands(self) -> None:
        bus = EventBus(max_workers=2)
        chat_events: List[Dict[str, Any]] = []
        action_events: List[Dict[str, Any]] = []

        bus.subscribe("chat_notification", lambda e: chat_events.append(e))
        bus.subscribe("action_command", lambda e: action_events.append(e))

        tools = AgentTools(event_bus=bus)
        rag = RAGEngine()
        brain = AgentBrain(rag_engine=rag, tools=tools, event_bus=bus, execute_actions=True)

        alert_event = {
            "event_type": "alert",
            "machine_id": "MC-MILL-01",
            "machine_type": "CNC_MILLING",
            "payload": {
                "Spindle_Temp_C": 95.0,
                "Vibration_RMS_mm_s": 5.5,
            },
        }

        brain.handle_alert(alert_event)

        # Chờ nhẹ cho worker event bus
        import time
        time.sleep(0.3)

        # 1. Có thông báo chẩn đoán lên chat cho kỹ sư
        self.assertEqual(len(chat_events), 1)
        self.assertEqual(chat_events[0]["source"], "AI_RAG")
        self.assertEqual(chat_events[0]["machine_id"], "MC-MILL-01")

        # 2. Có lệnh chuẩn đẩy vào action_command
        self.assertGreater(len(action_events), 0)
        cmd_names = [a["command"] for a in action_events]
        self.assertIn("SET_FEED_OVERRIDE", cmd_names)
        self.assertIn("REFILL_SPINDLE_LUBRICANT", cmd_names)

        bus.shutdown()


if __name__ == "__main__":
    unittest.main()
