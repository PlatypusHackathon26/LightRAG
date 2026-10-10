# agent/rag_engine.py
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("RAGEngine")

# =============================================================================
# DANH MỤC LỆNH PLC CHUẨN CỦA TỪNG DÒNG MÁY (IOT COMMAND WHITELIST)
# Đồng bộ 100% với hàm receive_plc_command() trong machines/*.py
# =============================================================================
COMMAND_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "CNC_MILLING": [
        {
            "command": "SET_FEED_OVERRIDE",
            "params": {"override_pct": "float (0 - 150)"},
            "risk_level": "LOW",
            "desc": "Điều chỉnh tốc độ ăn dao (%) để giảm tải cắt tức thời",
        },
        {
            "command": "COOLANT_BOOST",
            "params": {},
            "risk_level": "LOW",
            "desc": "Kích hoạt bơm tưới nguội áp suất cao (35 Bar)",
        },
        {
            "command": "TOGGLE_COOLANT",
            "params": {"enabled": "bool"},
            "risk_level": "LOW",
            "desc": "Bật/tắt bơm làm mát trục chính",
        },
        {
            "command": "FEED_HOLD",
            "params": {},
            "risk_level": "LOW",
            "desc": "Tạm dừng tiến dao bàn máy, trục chính vẫn duy trì quay",
        },
        {
            "command": "RESUME",
            "params": {},
            "risk_level": "LOW",
            "desc": "Khôi phục chu trình gia công định mức 100%",
        },
        {
            "command": "REFILL_SPINDLE_LUBRICANT",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Bơm dầu bôi trơn trục chính (khắc phục thiếu dầu ổ bi)",
        },
        {
            "command": "REPAIR_COOLANT_SYSTEM",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Sửa chữa hệ thống bơm làm mát và thông ống",
        },
        {
            "command": "REPLACE_TOOL",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Thay cụm dao phay mới (ATC Tool Change, reset mòn về 0%)",
        },
        {
            "command": "LUBRICATE_GUIDEWAYS",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Bôi trơn băng trượt các trục X/Y/Z",
        },
        {
            "command": "EMERGENCY_STOP",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Ngắt khẩn cấp trục chính và khóa trục cơ khí",
        },
    ],
    "ROBOT_ARM": [
        {
            "command": "PAUSE_MOTION",
            "params": {},
            "risk_level": "LOW",
            "desc": "Tạm dừng quỹ đạo di chuyển, động cơ giữ phanh an toàn",
        },
        {
            "command": "SET_SPEED_OVERRIDE",
            "params": {"speed_pct": "float (0 - 100)"},
            "risk_level": "LOW",
            "desc": "Hạ giới hạn vận tốc các khớp quay (%)",
        },
        {
            "command": "RESET_PAYLOAD",
            "params": {},
            "risk_level": "LOW",
            "desc": "Đặt lại tải trọng gắp về định mức chuẩn 3.5 kg",
        },
        {
            "command": "RESUME",
            "params": {},
            "risk_level": "LOW",
            "desc": "Khôi phục chu trình gắp đặt tự động",
        },
        {
            "command": "REFILL_GEARBOX_GREASE",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Bơm mỡ bôi trơn chuyên dụng cho hộp số giảm tốc Khớp 3",
        },
        {
            "command": "REPAIR_PNEUMATIC_SYSTEM",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Sửa chữa hệ thống rò rỉ khí nén tay gắp (khôi phục 6 Bar)",
        },
        {
            "command": "EMERGENCY_STOP",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Ngắt khẩn cấp nguồn driver servo, khóa chốt phanh cơ học",
        },
    ],
    "AMR_VEHICLE": [
        {
            "command": "RETURN_TO_CHARGER",
            "params": {},
            "risk_level": "LOW",
            "desc": "Điều phối xe tự hành di chuyển về dock sạc tiếp xúc",
        },
        {
            "command": "NAVIGATE_TO",
            "params": {"station": "str", "speed_m_s": "float"},
            "risk_level": "LOW",
            "desc": "Điều hướng xe tới trạm đích theo giao thức VDA 5050",
        },
        {
            "command": "CLEAN_LIDAR_OPTICS",
            "params": {},
            "risk_level": "LOW",
            "desc": "Thổi khí làm sạch ống kính LiDAR (phục hồi SLAM)",
        },
        {
            "command": "RESUME",
            "params": {},
            "risk_level": "LOW",
            "desc": "Tiếp tục lộ trình vận chuyển tự hành",
        },
        {
            "command": "SERVICE_DRIVE_MOTOR",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Kiểm tra và bôi trơn trục động cơ di chuyển bị kẹt",
        },
        {
            "command": "REPLACE_BATTERY_MODULE",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Thay cụm cell pin LiFePO4 mới (sạc lại 95%)",
        },
        {
            "command": "EMERGENCY_STOP",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Phanh điện từ khẩn cấp dừng xe lập tức",
        },
    ],
    "AOI_INSPECTION": [
        {
            "command": "RECALIBRATE_OPTICS",
            "params": {},
            "risk_level": "LOW",
            "desc": "Thổi khí tự động và hiệu chuẩn cân bằng trắng buồng quang học",
        },
        {
            "command": "PAUSE_INSPECTION_LINE",
            "params": {},
            "risk_level": "LOW",
            "desc": "Tạm dừng băng tải nạp để ngăn ngừa phế phẩm dây chuyền SMT",
        },
        {
            "command": "RESUME",
            "params": {},
            "risk_level": "LOW",
            "desc": "Tiếp tục chu trình kiểm tra quang học 3D tự động",
        },
        {
            "command": "REPLACE_LED_MODULE",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Bảo trì driver đèn LED; khôi phục cường độ chiếu sáng tiêu chuẩn",
        },
        {
            "command": "CLEAR_CONVEYOR_JAM",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Gỡ kẹt bảng mạch PCB trên băng chuyền nạp",
        },
    ],
    "INJECTION_MOLDING": [
        {
            "command": "ADJUST_TEMPERATURE",
            "params": {"target_temp": "float (180 - 245)"},
            "risk_level": "LOW",
            "desc": "Điều chỉnh nhiệt độ đặt đầu phun nhựa Zone 1 (°C)",
        },
        {
            "command": "RESUME",
            "params": {},
            "risk_level": "LOW",
            "desc": "Tiếp tục chu kỳ ép khuôn tự động",
        },
        {
            "command": "PURGE_BARREL",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Thực hiện chu trình đùn xả nhựa cặn thông nòng phun",
        },
        {
            "command": "SERVICE_HEATER_SSR",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Ngắt điện cưỡng bức và thay rơ-le bán dẫn SSR vòng nhiệt kẹt",
        },
        {
            "command": "REPAIR_HYDRAULIC_VALVE",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Thay gioăng phớt van tỉ lệ thủy lực kẹp khuôn",
        },
        {
            "command": "EMERGENCY_STOP",
            "params": {},
            "risk_level": "HIGH",
            "desc": "Dừng khẩn cấp máy ép khuôn",
        },
    ],
}


class RAGEngine:
    """RAG Engine phục vụ truy vấn cẩm nang và chuẩn hóa output hành động IoT."""

    def __init__(
        self,
        storage_dir: str = "./lightrag_storage",
        lightrag_instance: Optional[Any] = None,
        llm_callable: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.storage_dir = storage_dir
        self.rag = lightrag_instance
        self.llm_callable = llm_callable
        logger.info(f"[RAGEngine] Khởi tạo RAG Engine tại: {storage_dir}")

    def build_format_prompt(
        self,
        machine_id: str,
        machine_type: str,
        telemetry: Dict[str, Any],
    ) -> str:
        """Sinh prompt ép LLM đọc hiểu ngữ cảnh và trả về JSON Schema cố định."""
        available_cmds = COMMAND_CATALOG.get(machine_type, [])
        return (
            "Bạn là Kỹ sư AI Điều hành Nhà máy Thông minh DENSO.\n"
            "Nhiệm vụ: Đối chiếu dữ liệu vận hành thời gian thực của máy móc với tài liệu quy chuẩn kỹ thuật, "
            "chẩn đoán nguyên nhân sự cố và đề xuất các hành động can thiệp chuẩn hóa cho hệ thống IoT.\n\n"
            f"--- THÔNG TIN THIẾT BỊ ---\n"
            f"- Mã thiết bị: {machine_id}\n"
            f"- Dòng máy: {machine_type}\n"
            f"- Telemetry cảm biến hiện tại:\n{json.dumps(telemetry, ensure_ascii=False, indent=2)}\n\n"
            f"--- DANH MỤC LỆNH PLC HỢP LỆ CHO DÒNG MÁY NÀY (BẮT BUỘC TUÂN THỦ) ---\n"
            f"{json.dumps(available_cmds, ensure_ascii=False, indent=2)}\n\n"
            "--- QUY TẮC ĐỊNH DẠNG ĐẦU RA (JSON SCHEMA BẮT BUỘC) ---\n"
            "1. CHỈ ĐƯỢC CHỌN các 'command' có trong danh mục lệnh hợp lệ ở trên. Tuyệt đối không tự đặt tên lệnh mới.\n"
            "2. 'params' phải đúng kiểu dữ liệu và giá trị quy định.\n"
            "3. 'risk_level' phải đúng giá trị đã định nghĩa cho lệnh đó ('LOW' hoặc 'HIGH').\n"
            "4. Phải trả về DUY NHẤT một đối tượng JSON hợp lệ, không có lời mở đầu hay kết thúc, theo định dạng:\n"
            "{\n"
            '  "diagnosis": "<Văn bản tiếng Việt giải thích nguyên nhân và khuyến nghị cho kỹ sư vận hành>",\n'
            '  "actions": [\n'
            "    {\n"
            '      "command": "<TÊN_LỆNH_CHUẨN>",\n'
            '      "params": { ... },\n'
            '      "risk_level": "<LOW hoặc HIGH>",\n'
            '      "reason": "<Lý do kỹ thuật cho lệnh này>"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

    def query_with_schema(
        self,
        machine_id: str,
        machine_type: str,
        telemetry: Dict[str, Any],
        mode: str = "hybrid",
    ) -> Dict[str, Any]:
        """
        Tra cứu cẩm nang kỹ thuật và sử dụng LLM để format output
        thành cấu trúc cố định được quy định trong IoT:
        {
            "diagnosis": str,
            "actions": [
                {
                    "command": str,
                    "params": dict,
                    "risk_level": "LOW" | "HIGH",
                    "reason": str
                }
            ]
        }
        """
        prompt = self.build_format_prompt(machine_id, machine_type, telemetry)
        logger.info(f"[RAGEngine] Gửi truy vấn có Schema tới LLM cho {machine_id} ({machine_type})")

        raw_output = self._call_llm_or_rag(prompt, mode=mode)
        parsed = self._safe_parse_json(raw_output)

        # Hậu kiểm tra danh mục lệnh (Whitelisting check)
        valid_commands = {cmd["command"] for cmd in COMMAND_CATALOG.get(machine_type, [])}
        filtered_actions: List[Dict[str, Any]] = []
        for act in parsed.get("actions", []):
            cmd_name = act.get("command", "").strip().upper()
            if cmd_name in valid_commands:
                act["command"] = cmd_name
                # Đồng bộ risk_level theo danh mục
                meta = next(
                    (c for c in COMMAND_CATALOG[machine_type] if c["command"] == cmd_name),
                    None,
                )
                if meta:
                    act["risk_level"] = meta["risk_level"]
                filtered_actions.append(act)
            else:
                logger.warning(
                    f"[RAGEngine] Lệnh '{cmd_name}' không thuộc danh mục hợp lệ của {machine_type}, đã loại bỏ."
                )

        parsed["actions"] = filtered_actions
        return parsed

    def query(self, query_text: str, mode: str = "hybrid") -> str:
        """
        Hàm tương thích cũ cho ô chat giao diện hoặc truy vấn văn bản tự do.
        """
        logger.info(f"[RAGEngine] Tiếp nhận truy vấn tự do: {query_text[:80]}")
        text_lower = query_text.lower()

        # Nếu có instance LightRAG thật
        if self.rag and hasattr(self.rag, "query"):
            try:
                return str(self.rag.query(query_text))
            except Exception as e:
                logger.error(f"[RAGEngine] Lỗi khi gọi LightRAG: {e}")

        # Phản hồi mẫu thông minh theo từ khóa (khi chạy không LLM key)
        if "cnc_milling" in text_lower or "mc-mill-01" in text_lower:
            if "spindle_temp_c" in text_lower or "nhiệt" in text_lower or "lube" in text_lower:
                return (
                    "Khuyến nghị khẩn cấp từ cẩm nang DMG MORI: Nhiệt độ trục chính vượt ngưỡng an toàn. "
                    "Yêu cầu kích hoạt dung dịch làm mát tối đa (TOGGLE_COOLANT) và giảm tải tốc độ chạy dao "
                    "xuống 50% (SET_FEED_OVERRIDE) để bảo vệ cụm bạc đạn số 2."
                )
            elif "vibration" in text_lower or "rung" in text_lower:
                return (
                    "Cảnh báo rung chấn vượt tiêu chuẩn ISO 10816: Nguy cơ gãy dao hoặc kẹt phôi. "
                    "Yêu cầu thực hiện dừng máy an toàn (SAFE_STOP) để kiểm tra độ đảo dao."
                )

        elif "injection_molding" in text_lower or "mc-inj-01" in text_lower:
            return (
                "Cảnh báo kỹ thuật FANUC ROBOSHOT: Nhiệt độ nòng phun Zone 1 có xu hướng trôi nhiệt. "
                "Cần điều chỉnh hạ nhiệt nòng phun về 215°C (ADJUST_TEMPERATURE) và kiểm tra áp suất kẹp khuôn."
            )

        elif "robot_arm" in text_lower or "mc-robot-01" in text_lower:
            return (
                "Cảnh báo quá dòng khớp J3 trên robot DENSO: Xuất hiện lực cản bất thường hoặc va chạm nhẹ. "
                "Khuyến nghị tạm dừng chuyển động (PAUSE_MOTION) hoặc giảm tốc độ quay còn 50% (SET_SPEED_OVERRIDE)."
            )

        elif "amr_vehicle" in text_lower or "mc-amr-01" in text_lower:
            return (
                "Cảnh báo dung lượng pin AMR xuống dưới ngưỡng 20%: Điều phối xe tự hành di chuyển "
                "về dock sạc ngay lập tức (RETURN_TO_CHARGER)."
            )

        elif "aoi_inspection" in text_lower or "mc-aoi-01" in text_lower:
            return (
                "Tỷ lệ từ chối giả (False Reject) tăng cao do bụi bám lăng kính quang học: "
                "Cần thực hiện chu trình thổi khí tự động và hiệu chuẩn camera (RECALIBRATE_OPTICS)."
            )

        return (
            "Hệ thống phát hiện biến động thông số ngoài dải tiêu chuẩn. "
            "Khuyến nghị kỹ thuật viên kiểm tra trực tiếp và duy trì chế độ an toàn."
        )

    def _call_llm_or_rag(self, prompt: str, mode: str = "hybrid") -> str:
        """Thực thi gọi LLM từ LightRAG hoặc hàm callable được cung cấp."""
        if self.llm_callable:
            try:
                return self.llm_callable(prompt)
            except Exception as exc:
                logger.error(f"[RAGEngine] Lỗi từ llm_callable: {exc}")

        if self.rag and hasattr(self.rag, "query"):
            try:
                return str(self.rag.query(prompt))
            except Exception as exc:
                logger.error(f"[RAGEngine] Lỗi từ LightRAG query: {exc}")

        # Khi chưa kết nối LLM thật: Tự động phân tích prompt để trả về JSON mẫu chuẩn xác
        return self._generate_mock_structured_response(prompt)

    def _generate_mock_structured_response(self, prompt: str) -> str:
        """Sinh JSON mẫu chuẩn xác phục vụ testbed và demo khi chưa có API key."""
        text = prompt.lower()
        if "cnc_milling" in text or "mc-mill-01" in text:
            if "spindle_temp_c" in text or "rung" in text or "vibration" in text or "lube" in text:
                return json.dumps(
                    {
                        "diagnosis": (
                            "Nhiệt độ trục chính hoặc rung chấn vượt ngưỡng do thiếu bôi trơn bạc đạn. "
                            "Cần giảm tốc chạy dao xuống 50% và chuẩn bị bổ sung dầu bôi trơn trục chính."
                        ),
                        "actions": [
                            {
                                "command": "SET_FEED_OVERRIDE",
                                "params": {"override_pct": 50.0},
                                "risk_level": "LOW",
                                "reason": "Giảm tải cắt tức thời nhằm hạ nhiệt độ sinh ra",
                            },
                            {
                                "command": "REFILL_SPINDLE_LUBRICANT",
                                "params": {},
                                "risk_level": "HIGH",
                                "reason": "Bơm dầu bôi trơn trục chính theo khuyến nghị DMG MORI",
                            },
                        ],
                    },
                    ensure_ascii=False,
                )

        if "injection_molding" in text or "mc-inj-01" in text:
            return json.dumps(
                {
                    "diagnosis": "Nhiệt độ nòng phun Zone 1 có xu hướng trôi nhiệt. Khuyến nghị hạ nhiệt về 215°C.",
                    "actions": [
                        {
                            "command": "ADJUST_TEMPERATURE",
                            "params": {"target_temp": 215.0},
                            "risk_level": "LOW",
                            "reason": "Điều chỉnh nhiệt độ nòng phun về dải an toàn",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        if "robot_arm" in text or "mc-robot-01" in text:
            return json.dumps(
                {
                    "diagnosis": "Quá dòng khớp J3. Khuyến nghị tạm dừng chuyển động và kiểm tra tải trọng gắp.",
                    "actions": [
                        {
                            "command": "PAUSE_MOTION",
                            "params": {},
                            "risk_level": "LOW",
                            "reason": "Tạm dừng cánh tay robot để bảo vệ motor servo",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        if "amr_vehicle" in text or "mc-amr-01" in text:
            return json.dumps(
                {
                    "diagnosis": "Pin xe AMR giảm thấp dưới ngưỡng. Điều phối xe quay về trạm sạc.",
                    "actions": [
                        {
                            "command": "RETURN_TO_CHARGER",
                            "params": {},
                            "risk_level": "LOW",
                            "reason": "Điều phối xe tự hành về dock sạc pin tự động",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        if "aoi_inspection" in text or "mc-aoi-01" in text:
            return json.dumps(
                {
                    "diagnosis": "Bụi bám lăng kính gây tăng tỷ lệ từ chối giả. Khuyến nghị hiệu chuẩn quang học.",
                    "actions": [
                        {
                            "command": "RECALIBRATE_OPTICS",
                            "params": {},
                            "risk_level": "LOW",
                            "reason": "Kích hoạt thổi khí làm sạch và cân bằng trắng quang học",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "diagnosis": "Thông số máy nằm ngoài tiêu chuẩn vận hành danh nghĩa.",
                "actions": [],
            },
            ensure_ascii=False,
        )

    def _safe_parse_json(self, raw_text: str) -> Dict[str, Any]:
        """Trích xuất và sửa lỗi JSON tự động từ chuỗi phản hồi của LLM."""
        clean = (raw_text or "").strip()
        # Loại bỏ các khối code block ```json ... ```
        if "```" in clean:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean)
            if match:
                clean = match.group(1).strip()

        # Tìm kiếm object JSON đầu tiên
        json_match = re.search(r"\{[\s\S]*\}", clean)
        if json_match:
            clean = json_match.group(0)

        try:
            data = json.loads(clean)
            if isinstance(data, dict):
                return {
                    "diagnosis": str(data.get("diagnosis", "")),
                    "actions": list(data.get("actions", [])),
                }
        except Exception as exc:
            logger.warning(f"[RAGEngine] Không thể parse JSON trực tiếp: {exc} | Raw text: {raw_text[:120]}")

        # Fallback an toàn nếu LLM trả về văn bản tự do
        return {
            "diagnosis": raw_text,
            "actions": [],
        }
