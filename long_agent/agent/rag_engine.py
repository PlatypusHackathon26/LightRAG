# agent/rag_engine.py
"""Diagnosis: from an alert to ONE repair the machine declares, chosen with the maintenance documents.

Rules:
- the LLM answers WHAT to repair: a `repair` name from the machine's own catalog (plus an optional
  temporary `mitigation`). HOW (stop, lock out, repair, restart) is planned in code (agent/procedures.py);
- every name is normalised against the machine's specs (machines/commands.py). An answer that names
  no declared command, or a repair already tried without success, is re-asked once with the reason;
  after that nothing is proposed - free text is never turned into a command;
- documents come from LightRAG through `retriever` (agent/retriever.py); without them the diagnosis
  says so instead of pretending to cite.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from machines.commands import CommandSpec, normalize_command, validate_params

logger = logging.getLogger("RAGEngine")


def _machine_classes() -> Dict[str, Any]:
    from machines.amr_vehicle import AmrVehicle
    from machines.aoi_inspection import AoiInspection
    from machines.cnc_milling import CncMilling
    from machines.injection_molding import InjectionMolding
    from machines.robot_arm import RobotArm
    return {c.MACHINE_TYPE: c for c in (CncMilling, RobotArm, AmrVehicle, AoiInspection, InjectionMolding)}


def command_specs(machine_type: str) -> Dict[str, CommandSpec]:
    cls = _machine_classes().get(machine_type)
    return cls.command_specs() if cls else {}


# What the agent is shown per machine type: derived from the machines, never maintained by hand.
COMMAND_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    t: [s.catalog_entry() for s in cls.command_specs().values()] for t, cls in _machine_classes().items()
}

# Offline stand-in for the LLM (no LONG_AGENT_LLM_*): the symptom each repair addresses, checked in
# order. (metric, "high"|"low", command): a repair, or an operating command when the symptom needs no
# repair. It reads only the readings, never the hidden fault flags.
SYMPTOM_RULES: Dict[str, List[tuple]] = {
    "CNC_MILLING": [("Coolant_Pressure_Bar", "low", "REPAIR_COOLANT_SYSTEM"),
                    ("Vibration_RMS_mm_s", "high", "REPLACE_TOOL"),
                    ("Spindle_Temp_C", "high", "REFILL_SPINDLE_LUBRICANT"),
                    ("Spindle_Load_Pct", "high", "LUBRICATE_GUIDEWAYS")],
    "ROBOT_ARM": [("Gripper_Pressure_Bar", "low", "REPAIR_PNEUMATIC_SYSTEM"),
                  ("Payload_Kg", "high", "RESET_PAYLOAD"),
                  ("Joint_3_Current_A", "high", "REFILL_GEARBOX_GREASE"),
                  ("Motor_Temp_C", "high", "REFILL_GEARBOX_GREASE")],
    "AMR_VEHICLE": [("Lidar_Confidence_Pct", "low", "CLEAN_LIDAR_OPTICS"),
                    ("Battery_Temp_C", "high", "REPLACE_BATTERY_MODULE"),
                    ("Current_Velocity_m_s", "low", "SERVICE_DRIVE_MOTOR"),
                    # Low charge at a normal battery temperature is ordinary drain: charge, nothing to repair.
                    ("Battery_Pct", "low", "RETURN_TO_CHARGER")],
    "AOI_INSPECTION": [("Conveyor_Speed_m_min", "low", "CLEAR_CONVEYOR_JAM"),
                       ("Illumination_Intensity_Lux", "low", "REPLACE_LED_MODULE"),
                       ("Optics_Cleanliness_Pct", "low", "RECALIBRATE_OPTICS"),
                       ("False_Reject_Rate_Pct", "high", "RECALIBRATE_OPTICS")],
    "INJECTION_MOLDING": [("Nozzle_Temp_Zone1", "high", "SERVICE_HEATER_SSR"),
                          ("Clamping_Pressure_Bar", "low", "REPAIR_HYDRAULIC_VALVE"),
                          ("Injection_Pressure_Bar", "high", "PURGE_BARREL")],
}


def _metrics(machine_type: str) -> List[Dict[str, Any]]:
    from machines.specifications import MACHINE_METRICS
    return MACHINE_METRICS.get(machine_type, [])


def _limits_text(machine_type: str) -> str:
    """Danh nghĩa và ngưỡng của từng chỉ số (machines/specifications.py)."""
    lines = []
    for m in _metrics(machine_type):
        limits = ", ".join(f"{name} {m[key]}" for key, name in (
            ("min", "tối thiểu"), ("max", "tối đa"),
            ("critical_min", "nguy hiểm dưới"), ("critical_max", "nguy hiểm trên")) if key in m)
        lines.append(f"- {m['key']} ({m['label']}): danh nghĩa {m['nominal']} {m['unit']}"
                     + (f"; {limits}" if limits else ""))
    return "\n".join(lines) or "(không có bảng ngưỡng)"


def _deviations(machine_type: str, telemetry: Dict[str, Any]) -> List[tuple]:
    """(metric dict, value, "high"|"low") for every reading outside [min, max]."""
    out = []
    for m in _metrics(machine_type):
        value = telemetry.get(m["key"])
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if "max" in m and value > m["max"]:
            out.append((m, value, "high"))
        elif "min" in m and value < m["min"]:
            out.append((m, value, "low"))
    return out


def _deviations_text(machine_type: str, telemetry: Dict[str, Any]) -> str:
    lines = [f"- {m['key']} ({m['label']}) = {v} {m['unit']} "
             + (f"> tối đa {m['max']}" if d == "high" else f"< tối thiểu {m['min']}")
             for m, v, d in _deviations(machine_type, telemetry)]
    return "\n".join(lines) or "- Chưa chỉ số nào vượt ngưỡng tĩnh (cảnh báo do tốc độ biến thiên): xét chỉ số đang đổi nhanh."


def _attempts_text(attempts: List[Dict[str, Any]]) -> str:
    done = [a for a in attempts or [] if a.get("repair")]
    if not done:
        return "- (chưa sửa gì)"
    names = {"failed": "đã khởi động lại nhưng triệu chứng quay lại", "verifying": "triệu chứng quay lại sau khi chạy lại",
             "awaiting_restart": "đã sửa, chưa khởi động lại"}
    return "\n".join(f"- {a['repair']}: {names.get(a.get('outcome'), a.get('outcome'))}" for a in done)


class RAGEngine:
    """Chẩn đoán sự cố: đọc tài liệu, chọn lệnh sửa trong danh mục của máy."""

    def __init__(
        self,
        storage_dir: str = "./lightrag_storage",
        lightrag_instance: Optional[Any] = None,
        llm_callable: Optional[Callable[[str], str]] = None,
        retriever: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.storage_dir = storage_dir
        self.rag = lightrag_instance
        self.llm_callable = llm_callable
        self.retriever = retriever

    # ------------------------------------------------------------------ documents
    def retrieve(self, machine_type: str, telemetry: Dict[str, Any]) -> str:
        if not self.retriever:
            return ""
        symptoms = "; ".join(f"{m['label']} {'cao' if d == 'high' else 'thấp'}"
                             for m, _, d in _deviations(machine_type, telemetry))
        query = f"Quy trình bảo trì {machine_type}: triệu chứng {symptoms or 'bất thường'}. Nguyên nhân và lệnh sửa?"
        try:
            return self.retriever(query) or ""
        except Exception as exc:
            logger.warning(f"[RAGEngine] Không lấy được tài liệu: {exc}")
            return ""

    # ------------------------------------------------------------------ prompt
    def build_format_prompt(self, machine_id: str, machine_type: str, telemetry: Dict[str, Any],
                            documents: str = "", attempts: Optional[List[Dict[str, Any]]] = None) -> str:
        catalog = COMMAND_CATALOG.get(machine_type, [])
        repairs = [c for c in catalog if c["kind"] == "repair"]
        others = [c for c in catalog if c["kind"] != "repair" and c["command"] != "EMERGENCY_STOP"]
        docs = documents.strip()[:6000] if documents else ""
        return (
            "Bạn là Kỹ sư AI bảo trì nhà máy DENSO. Chẩn đoán nguyên nhân gốc của cảnh báo và chọn ĐÚNG MỘT lệnh sửa.\n\n"
            f"--- THIẾT BỊ ---\n- Mã: {machine_id}\n- Dòng máy: {machine_type}\n"
            f"- Telemetry hiện tại:\n{json.dumps(telemetry, ensure_ascii=False, indent=2)}\n\n"
            f"--- DANH NGHĨA VÀ NGƯỠNG ---\n{_limits_text(machine_type)}\n"
            f"--- CHỈ SỐ ĐANG VƯỢT NGƯỠNG ---\n{_deviations_text(machine_type, telemetry)}\n"
            "Nguyên nhân phải giải thích được chính các chỉ số đang vượt ngưỡng; dao động nhỏ quanh danh nghĩa là nhiễu.\n\n"
            "--- TÀI LIỆU BẢO TRÌ (từ kho tri thức) ---\n"
            + (docs if docs else "(không lấy được tài liệu: chẩn đoán dựa trên ngưỡng, nói rõ điều này)") + "\n\n"
            f"--- LỆNH SỬA CỦA MÁY (chọn 1; mỗi lệnh sửa đúng một lỗi 'fixes') ---\n"
            f"{json.dumps(repairs, ensure_ascii=False, indent=2)}\n\n"
            f"--- LỆNH VẬN HÀNH TẠM THỜI (tuỳ chọn, chỉ để giảm nhẹ khi chưa sửa được) ---\n"
            f"{json.dumps(others, ensure_ascii=False, indent=2)}\n\n"
            f"--- ĐÃ THỬ TRÊN MÁY NÀY ---\n{_attempts_text(attempts or [])}\n"
            "Không chọn lại lệnh sửa đã thử mà triệu chứng vẫn quay lại.\n\n"
            "--- ĐẦU RA: DUY NHẤT một JSON, không lời dẫn ---\n"
            "{\n"
            '  "diagnosis": "<2-3 câu tiếng Việt: chỉ số lệch (kèm giá trị), nguyên nhân gốc, dẫn tài liệu nếu có>",\n'
            '  "repair": "<tên lệnh sửa, đúng như danh sách; null nếu không có lệnh sửa phù hợp>",\n'
            '  "mitigation": {"command": "<lệnh vận hành>", "params": {}} hoặc null,\n'
            '  "sources": ["<tên tài liệu đã dùng>"],\n'
            '  "reason": "<vì sao lệnh sửa này khắc phục nguyên nhân gốc>"\n'
            "}\n"
            "Quy trình dừng máy, khoá an toàn, khởi động lại do hệ thống tự lập: KHÔNG đưa SAFE_STOP/LOCKOUT/START vào."
        )

    # ------------------------------------------------------------------ diagnosis
    def query_with_schema(self, machine_id: str, machine_type: str, telemetry: Dict[str, Any],
                          mode: str = "naive", attempts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """{"diagnosis", "repair", "mitigation", "sources", "documents_used", "notes", "actions"}.

        `actions` lists the validated commands (repair first, else the mitigation) for callers that
        route commands; it is empty when nothing valid was chosen."""
        specs = command_specs(machine_type)
        tried = {a["repair"] for a in attempts or [] if a.get("repair") and a.get("outcome") != "awaiting_restart"}
        documents = self.retrieve(machine_type, telemetry)
        prompt = self.build_format_prompt(machine_id, machine_type, telemetry, documents, attempts)

        if not self.llm_callable:
            return self._offline_diagnosis(machine_type, telemetry, specs, tried, bool(documents))

        parsed = self._safe_parse_json(self._call_llm(prompt))
        result, problem = self._validate(parsed, specs, tried)
        if problem:
            logger.warning(f"[RAGEngine] {machine_id}: {problem} - hỏi lại một lần")
            retry_prompt = (prompt + f"\n\nCÂU TRẢ LỜI TRƯỚC KHÔNG DÙNG ĐƯỢC: {problem}\n"
                            f"Lệnh sửa hợp lệ: {', '.join(n for n, s in specs.items() if s.kind == 'repair')}. "
                            "Trả lại đúng JSON.")
            parsed = self._safe_parse_json(self._call_llm(retry_prompt))
            result, problem = self._validate(parsed, specs, tried)
            if problem:
                result["notes"].append(f"Agent không chọn được lệnh hợp lệ: {problem}")
        result["documents_used"] = bool(documents)
        return result

    def _validate(self, parsed: Dict[str, Any], specs: Dict[str, CommandSpec], tried: set) -> tuple:
        """The answer reduced to declared commands. Returns (result, problem or None)."""
        result: Dict[str, Any] = {"diagnosis": str(parsed.get("diagnosis") or ""), "repair": None, "mitigation": None,
                                  "sources": [str(s) for s in parsed.get("sources") or [] if s][:5],
                                  "reason": str(parsed.get("reason") or ""), "notes": [], "actions": []}
        problem = None
        raw_repair = parsed.get("repair")
        if raw_repair not in (None, "", "null"):
            name = normalize_command(raw_repair, specs)
            if name is None or specs[name].kind != "repair":
                problem = f"'{raw_repair}' không phải lệnh sửa của máy này"
            elif name in tried:
                problem = f"{name} đã thử mà triệu chứng vẫn quay lại"
            else:
                result["repair"] = name
        raw_mit = parsed.get("mitigation")
        if isinstance(raw_mit, dict) and raw_mit.get("command"):
            name = normalize_command(raw_mit.get("command"), specs)
            if name and specs[name].kind != "repair" and name != "EMERGENCY_STOP":
                try:
                    result["mitigation"] = {"command": name, "params": validate_params(specs[name], raw_mit.get("params"))}
                except ValueError as exc:
                    result["notes"].append(f"Bỏ lệnh tạm thời: {exc}")
            else:
                result["notes"].append(f"Bỏ lệnh tạm thời không hợp lệ '{raw_mit.get('command')}'")
        if result["repair"]:
            result["actions"] = [{"command": result["repair"], "params": {}, "kind": "repair",
                                  "risk_level": specs[result["repair"]].risk, "reason": result["reason"]}]
        elif result["mitigation"]:
            m = result["mitigation"]
            result["actions"] = [{**m, "kind": specs[m["command"]].kind, "risk_level": specs[m["command"]].risk,
                                  "reason": result["reason"]}]
        return result, problem

    def _offline_diagnosis(self, machine_type: str, telemetry: Dict[str, Any], specs: Dict[str, CommandSpec],
                           tried: set, have_docs: bool) -> Dict[str, Any]:
        devs = {(m["key"], d): (m, v) for m, v, d in _deviations(machine_type, telemetry)}
        for key, direction, command in SYMPTOM_RULES.get(machine_type, []):
            if (key, direction) in devs and command not in tried and command in specs:
                m, v = devs[(key, direction)]
                spec = specs[command]
                cause = f"Nguyên nhân khả dĩ: {spec.fixes}." if spec.fixes else f"Không cần sửa: {spec.desc_vi}."
                parsed = {"diagnosis": (f"{m['label']} = {v} {m['unit']} ({'cao' if direction == 'high' else 'thấp'} "
                                        f"bất thường). {cause} (Chẩn đoán theo bảng triệu chứng, chưa có LLM.)"),
                          "reason": spec.desc_vi}
                if spec.kind == "repair":
                    parsed["repair"] = command
                else:
                    parsed["mitigation"] = {"command": command, "params": {}}
                result, _ = self._validate(parsed, specs, tried)
                result["documents_used"] = have_docs
                return result
        return {"diagnosis": "Có cảnh báo nhưng chưa xác định được lệnh sửa phù hợp; cần kỹ sư kiểm tra trực tiếp.",
                "repair": None, "mitigation": None, "sources": [], "reason": "", "notes": [], "actions": [],
                "documents_used": have_docs}

    def query(self, query_text: str, mode: str = "naive") -> str:
        """Câu hỏi tự do của kỹ sư trên bảng tester: trả lời theo tài liệu nếu có LLM."""
        docs = ""
        if self.retriever:
            try:
                docs = self.retriever(query_text) or ""
            except Exception as exc:
                logger.warning(f"[RAGEngine] Không lấy được tài liệu: {exc}")
        if self.llm_callable:
            prompt = ("Trả lời ngắn gọn bằng tiếng Việt cho kỹ sư bảo trì, chỉ dựa trên tài liệu dưới đây; "
                      "không có thông tin thì nói rõ.\n\n--- TÀI LIỆU ---\n"
                      f"{docs[:6000] or '(không có)'}\n\n--- CÂU HỎI ---\n{query_text}")
            answer = self._call_llm(prompt)
            if answer:
                return answer
        if docs:
            return "Trích tài liệu liên quan:\n" + docs[:1500]
        return "Chưa kết nối LLM hay kho tài liệu; hãy hỏi qua giao diện DENSO (Agent Gateway)."

    def _call_llm(self, prompt: str) -> str:
        try:
            return self.llm_callable(prompt) if self.llm_callable else ""
        except Exception as exc:
            logger.error(f"[RAGEngine] Lỗi từ llm_callable: {exc}")
            return ""

    @staticmethod
    def _safe_parse_json(raw_text: str) -> Dict[str, Any]:
        """The first JSON object in an LLM answer (code fences and surrounding text tolerated)."""
        clean = (raw_text or "").strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean)
        if fence:
            clean = fence.group(1).strip()
        obj = re.search(r"\{[\s\S]*\}", clean)
        if obj:
            try:
                data = json.loads(obj.group(0))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as exc:
                logger.warning(f"[RAGEngine] JSON lỗi: {exc} | {raw_text[:120]}")
        return {"diagnosis": raw_text or ""}
