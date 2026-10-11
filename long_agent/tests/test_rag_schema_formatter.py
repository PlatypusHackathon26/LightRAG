"""From an LLM answer, however it is worded, to exactly one command the machine declares."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

from agent.brain import AgentBrain
from agent.rag_engine import COMMAND_CATALOG, RAGEngine, command_specs
from iot.event_bus import EventBus

CNC_COOLANT_LOSS = {
    "Controller_Execution": "RUNNING",
    "Coolant_Pressure_Bar": 0.0,
    "Spindle_Temp_C": 64.0,
    "Spindle_Load_Pct": 46.0,
    "Vibration_RMS_mm_s": 1.3,
}


class ScriptedLLM:
    """Returns the given answers in order and records every prompt."""

    def __init__(self, *answers: Any) -> None:
        self.answers = [
            a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
            for a in answers
        ]
        self.prompts: List[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers[min(len(self.prompts), len(self.answers)) - 1]


def diagnose(
    llm, telemetry=CNC_COOLANT_LOSS, attempts=None, retriever=None
) -> Dict[str, Any]:
    return RAGEngine(llm_callable=llm, retriever=retriever).query_with_schema(
        "MC-MILL-01", "CNC_MILLING", telemetry, attempts=attempts
    )


class CatalogTests(unittest.TestCase):
    def test_the_catalog_is_exactly_what_each_machine_declares(self) -> None:
        self.assertEqual(
            set(COMMAND_CATALOG),
            {
                "CNC_MILLING",
                "ROBOT_ARM",
                "AMR_VEHICLE",
                "AOI_INSPECTION",
                "INJECTION_MOLDING",
            },
        )
        for machine_type, entries in COMMAND_CATALOG.items():
            with self.subTest(machine_type=machine_type):
                self.assertEqual(
                    {e["command"] for e in entries}, set(command_specs(machine_type))
                )
                for e in entries:
                    self.assertIn(e["risk_level"], ("LOW", "HIGH"))
        self.assertNotIn(
            "TOGGLE_COOLANT", {e["command"] for e in COMMAND_CATALOG["CNC_MILLING"]}
        )


class WordingTests(unittest.TestCase):
    def test_different_wordings_of_the_same_repair_map_to_one_command(self) -> None:
        for wording in (
            "REPAIR_COOLANT_SYSTEM",
            "repair coolant system",
            "Repair-Coolant-System",
            "REPAIR_COOLANT_PUMP",
            "replace coolant pump",
        ):
            with self.subTest(wording=wording):
                result = diagnose(
                    ScriptedLLM({"diagnosis": "Bơm tưới nguội hỏng", "repair": wording})
                )
                self.assertEqual(result["repair"], "REPAIR_COOLANT_SYSTEM")
                self.assertEqual(
                    [a["command"] for a in result["actions"]], ["REPAIR_COOLANT_SYSTEM"]
                )

    def test_an_invented_command_is_reasked_once_with_the_reason(self) -> None:
        llm = ScriptedLLM(
            {"diagnosis": "x", "repair": "FIX_EVERYTHING"},
            {"diagnosis": "Bơm hỏng", "repair": "REPAIR_COOLANT_SYSTEM"},
        )
        result = diagnose(llm)
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("FIX_EVERYTHING", llm.prompts[1])
        self.assertEqual(result["repair"], "REPAIR_COOLANT_SYSTEM")

    def test_free_text_is_never_turned_into_a_command(self) -> None:
        llm = ScriptedLLM(
            "Cần làm mát và giảm tốc chạy dao ngay.", "Vẫn là văn bản tự do."
        )
        result = diagnose(llm)
        self.assertEqual(result["actions"], [])
        self.assertEqual(len(llm.prompts), 1)  # nothing named, so nothing to correct

    def test_still_invalid_after_the_reask_proposes_nothing_and_says_so(self) -> None:
        result = diagnose(
            ScriptedLLM({"repair": "TOGGLE_COOLANT"}, {"repair": "TOGGLE_COOLANT"})
        )
        self.assertEqual(result["actions"], [])
        self.assertTrue(
            any("không chọn được lệnh hợp lệ" in n for n in result["notes"])
        )

    def test_a_control_command_is_not_accepted_as_a_repair(self) -> None:
        result = diagnose(ScriptedLLM({"repair": "SAFE_STOP"}, {"repair": "SAFE_STOP"}))
        self.assertIsNone(result["repair"])

    def test_a_repair_that_already_failed_is_not_proposed_again(self) -> None:
        llm = ScriptedLLM(
            {"repair": "REFILL_SPINDLE_LUBRICANT"}, {"repair": "REPAIR_COOLANT_SYSTEM"}
        )
        result = diagnose(
            llm, attempts=[{"repair": "REFILL_SPINDLE_LUBRICANT", "outcome": "failed"}]
        )
        self.assertIn("REFILL_SPINDLE_LUBRICANT", llm.prompts[0])  # told what was tried
        self.assertEqual(result["repair"], "REPAIR_COOLANT_SYSTEM")

    def test_mitigation_params_are_validated_against_the_declaration(self) -> None:
        result = diagnose(
            ScriptedLLM(
                {
                    "repair": None,
                    "mitigation": {
                        "command": "set feed override",
                        "params": {"override_pct": 999},
                    },
                }
            )
        )
        self.assertIsNone(result["mitigation"])
        self.assertTrue(result["notes"])
        ok = diagnose(
            ScriptedLLM(
                {
                    "repair": None,
                    "mitigation": {
                        "command": "SET_FEED_OVERRIDE",
                        "params": {"override_pct": "40"},
                    },
                }
            )
        )
        self.assertEqual(
            ok["mitigation"],
            {"command": "SET_FEED_OVERRIDE", "params": {"override_pct": 40.0}},
        )
        self.assertEqual(ok["actions"][0]["kind"], "setpoint")

    def test_json_inside_fences_and_chatter_is_read(self) -> None:
        raw = 'Đây là kết quả:\n```json\n{"diagnosis": "Bơm hỏng", "repair": "REPAIR_COOLANT_SYSTEM"}\n```\nXong.'
        self.assertEqual(diagnose(ScriptedLLM(raw))["repair"], "REPAIR_COOLANT_SYSTEM")


class DocumentTests(unittest.TestCase):
    def test_retrieved_documents_are_put_in_the_prompt(self) -> None:
        queries: List[str] = []

        def retriever(q: str) -> str:
            queries.append(q)
            return "SOP-CNC-02: áp suất tưới nguội < 5 Bar -> REPAIR_COOLANT_SYSTEM"

        llm = ScriptedLLM(
            {
                "diagnosis": "Theo SOP-CNC-02",
                "repair": "REPAIR_COOLANT_SYSTEM",
                "sources": ["maintenance_sop.md"],
            }
        )
        result = diagnose(llm, retriever=retriever)
        self.assertIn("Áp suất tưới nguội", queries[0])
        self.assertIn("SOP-CNC-02", llm.prompts[0])
        self.assertTrue(result["documents_used"])
        self.assertEqual(result["sources"], ["maintenance_sop.md"])

    def test_a_failing_knowledge_base_does_not_stop_the_diagnosis(self) -> None:
        def broken(q: str) -> str:
            raise ConnectionError("LightRAG down")

        result = diagnose(
            ScriptedLLM({"repair": "REPAIR_COOLANT_SYSTEM"}), retriever=broken
        )
        self.assertEqual(result["repair"], "REPAIR_COOLANT_SYSTEM")
        self.assertFalse(result["documents_used"])


class OfflineTests(unittest.TestCase):
    def test_without_an_llm_the_symptom_table_picks_the_repair(self) -> None:
        result = RAGEngine().query_with_schema(
            "MC-MILL-01", "CNC_MILLING", CNC_COOLANT_LOSS
        )
        self.assertEqual(result["repair"], "REPAIR_COOLANT_SYSTEM")

    def test_ordinary_battery_drain_means_charging_not_a_new_battery(self) -> None:
        result = RAGEngine().query_with_schema(
            "MC-AMR-01", "AMR_VEHICLE", {"Battery_Pct": 20.0, "Battery_Temp_C": 33.0}
        )
        self.assertIsNone(result["repair"])
        self.assertEqual(result["mitigation"]["command"], "RETURN_TO_CHARGER")
        hot = RAGEngine().query_with_schema(
            "MC-AMR-01", "AMR_VEHICLE", {"Battery_Pct": 20.0, "Battery_Temp_C": 58.0}
        )
        self.assertEqual(hot["repair"], "REPLACE_BATTERY_MODULE")


class BrainIntegrationTests(unittest.TestCase):
    def test_the_brain_publishes_the_diagnosis_and_one_repair(self) -> None:
        bus = EventBus(max_workers=2)
        chats: List[Dict[str, Any]] = []
        commands: List[Dict[str, Any]] = []
        bus.subscribe("chat_notification", chats.append)
        bus.subscribe("action_command", commands.append)
        rag = RAGEngine(
            llm_callable=ScriptedLLM(
                {"diagnosis": "Bơm tưới nguội hỏng", "repair": "REPAIR_COOLANT_SYSTEM"}
            )
        )
        AgentBrain(rag_engine=rag, event_bus=bus).handle_alert(
            {
                "machine_id": "MC-MILL-01",
                "machine_type": "CNC_MILLING",
                "payload": CNC_COOLANT_LOSS,
            }
        )
        bus.shutdown(wait=True)  # waits for the handlers
        self.assertEqual(len(chats), 1)
        self.assertIn("Bơm tưới nguội hỏng", chats[0]["text"])
        self.assertEqual(
            [(c["command"], c["kind"]) for c in commands],
            [("REPAIR_COOLANT_SYSTEM", "repair")],
        )


if __name__ == "__main__":
    unittest.main()
