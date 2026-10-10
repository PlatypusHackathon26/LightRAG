# agent/tools.py
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger("AgentTools")

# =============================================================================
# BẢNG TỪ ĐIỂN NĂNG LỰC CỦA TỪNG LOẠI MÁY (MACHINE ACTION CAPABILITIES)
# Dùng cho lớp phòng vệ fallback khi LLM không sinh ra actions trong JSON
# =============================================================================
MACHINE_CAPABILITIES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "CNC_MILLING": {
        "SET_FEED_OVERRIDE": {
            "keywords": [
                "giảm tốc",
                "hạ tốc",
                "chậm lại",
                "feed rate",
                "tốc độ ăn dao",
                "tải trục",
                "giảm tải",
                "feed override",
            ],
            "default_params": {"override_pct": 50.0},
            "risk_level": "LOW",
            "desc": "Điều chỉnh tốc độ ăn dao (%)",
        },
        "COOLANT_BOOST": {
            "keywords": [
                "áp suất cao",
                "coolant boost",
                "tưới nguội tối đa",
                "bơm tưới nguội 35 bar",
                "tăng áp làm mát",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Kích hoạt bơm tưới nguội áp suất cao 35 Bar",
        },
        "TOGGLE_COOLANT": {
            "keywords": [
                "làm mát",
                "dung dịch",
                "coolant",
                "bơm dầu làm mát",
                "hệ thống làm mát",
                "nhiệt độ trục",
            ],
            "default_params": {"enabled": True},
            "risk_level": "LOW",
            "desc": "Bật/tắt bơm làm mát trục chính",
        },
        "FEED_HOLD": {
            "keywords": [
                "feed hold",
                "tạm dừng tiến dao",
                "dừng bàn máy",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Tạm dừng tịnh tiến bàn máy (trục chính vẫn quay)",
        },
        "RESUME": {
            "keywords": [
                "khôi phục",
                "chạy lại",
                "resume",
                "tiếp tục gia công",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Khôi phục chu trình gia công định mức 100%",
        },
        "REFILL_SPINDLE_LUBRICANT": {
            "keywords": [
                "bôi trơn trục chính",
                "dầu bôi trơn",
                "thiếu dầu",
                "ổ bi",
                "lubricant",
                "lack of lube",
                "spindle bearing",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Bơm dầu bôi trơn ổ bi trục chính",
        },
        "REPAIR_COOLANT_SYSTEM": {
            "keywords": [
                "hỏng bơm làm mát",
                "sửa hệ thống làm mát",
                "mất áp tưới",
                "thông ống làm mát",
                "coolant pump failure",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Sửa chữa hệ thống làm mát",
        },
        "REPLACE_TOOL": {
            "keywords": [
                "thay dao",
                "mẻ dao",
                "mòn dao",
                "đổi dao",
                "replace tool",
                "tool chipping",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Thay cụm dao phay mới (ATC Tool Change)",
        },
        "LUBRICATE_GUIDEWAYS": {
            "keywords": [
                "băng trượt",
                "guideway",
                "dầu trượt",
                "bôi trơn x/y/z",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Bôi trơn băng trượt các trục",
        },
        "EMERGENCY_STOP": {
            "keywords": [
                "dừng khẩn cấp",
                "ngắt khẩn cấp",
                "e-stop",
                "emergency stop",
                "dừng an toàn",
                "safe stop",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Ngắt khẩn cấp trục chính và khóa cơ khí",
        },
    },
    "ROBOT_ARM": {
        "PAUSE_MOTION": {
            "keywords": [
                "tạm dừng chuyển động",
                "dừng cánh tay",
                "giữ vị trí",
                "pause motion",
                "quá dòng khớp",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Tạm dừng quỹ đạo di chuyển của robot",
        },
        "SET_SPEED_OVERRIDE": {
            "keywords": [
                "giảm tốc độ quay",
                "chạy chậm",
                "hạ tốc độ robot",
                "giảm vận tốc",
                "set speed",
                "speed override",
            ],
            "default_params": {"speed_pct": 50.0},
            "risk_level": "LOW",
            "desc": "Giới hạn vận tốc các khớp quay (%)",
        },
        "RESET_PAYLOAD": {
            "keywords": [
                "đặt lại tải trọng",
                "về tải 3.5",
                "reset payload",
                "quá tải trọng",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Đưa tải trọng gắp về định mức chuẩn 3.5 kg",
        },
        "RESUME": {
            "keywords": [
                "tiếp tục gắp",
                "chạy lại robot",
                "khôi phục",
                "resume",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Khôi phục chu trình gắp đặt tự động",
        },
        "REFILL_GEARBOX_GREASE": {
            "keywords": [
                "khô mỡ",
                "bơm mỡ",
                "hộp số giảm tốc",
                "grease",
                "gearbox",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Bơm mỡ bôi trơn chuyên dụng cho hộp số giảm tốc J3",
        },
        "REPAIR_PNEUMATIC_SYSTEM": {
            "keywords": [
                "rò khí nén",
                "tay gắp",
                "mất áp kẹp",
                "gioăng ống",
                "pneumatic leak",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Sửa chữa hệ thống rò rỉ khí nén tay gắp",
        },
        "EMERGENCY_STOP": {
            "keywords": [
                "ngắt khẩn cấp",
                "dừng khẩn cấp",
                "e-stop",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Ngắt khẩn cấp nguồn servo, khóa phanh cơ học",
        },
    },
    "AMR_VEHICLE": {
        "RETURN_TO_CHARGER": {
            "keywords": [
                "sạc pin",
                "về dock sạc",
                "pin yếu",
                "hết pin",
                "charger",
                "nạp năng lượng",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Yêu cầu xe tự hành di chuyển về trạm sạc",
        },
        "NAVIGATE_TO": {
            "keywords": [
                "di chuyển tới",
                "vận chuyển",
                "sang trạm",
                "đến trạm",
                "lấy hàng",
                "dỡ hàng",
            ],
            "default_params": {"station": "BUFFER_STATION", "speed_m_s": 1.2},
            "risk_level": "LOW",
            "desc": "Di chuyển xe AMR đến trạm được chỉ định",
        },
        "CLEAN_LIDAR_OPTICS": {
            "keywords": [
                "bụi bẩn lidar",
                "làm sạch kính",
                "vệ sinh lidar",
                "thổi khí lidar",
                "clean lidar",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Thổi khí làm sạch ống kính quang học LiDAR",
        },
        "RESUME": {
            "keywords": [
                "tiếp tục lộ trình",
                "chạy lại",
                "resume",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Tiếp tục lộ trình vận chuyển tự hành",
        },
        "SERVICE_DRIVE_MOTOR": {
            "keywords": [
                "kẹt bánh xe",
                "động cơ di chuyển",
                "kháng lực bánh",
                "service drive motor",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Bảo dưỡng bôi trơn trục động cơ di chuyển bị kẹt",
        },
        "REPLACE_BATTERY_MODULE": {
            "keywords": [
                "chai pin",
                "lão hóa pin",
                "thay pin",
                "pin hỏng",
                "battery degradation",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Thay cụm cell pin LiFePO4 mới",
        },
        "EMERGENCY_STOP": {
            "keywords": [
                "phanh gấp",
                "dừng khẩn cấp",
                "vật cản",
                "nguy cơ va chạm",
                "e-stop",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Phanh điện từ khẩn cấp",
        },
    },
    "AOI_INSPECTION": {
        "RECALIBRATE_OPTICS": {
            "keywords": [
                "hiệu chuẩn camera",
                "lấy nét lại",
                "recalibrate",
                "chỉnh quang học",
                "lỗi từ chối giả",
                "false reject",
                "bụi bám lăng kính",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Tự động hiệu chuẩn lại camera và cụm quang học",
        },
        "PAUSE_INSPECTION_LINE": {
            "keywords": [
                "dừng băng chuyền kiểm tra",
                "tạm dừng soi",
                "dừng kiểm định",
                "tạm dừng băng tải",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Tạm dừng luồng kiểm tra chất lượng",
        },
        "RESUME": {
            "keywords": [
                "tiếp tục soi",
                "chạy lại băng tải",
                "resume",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Tiếp tục chu trình kiểm tra quang học tự động",
        },
        "REPLACE_LED_MODULE": {
            "keywords": [
                "thay đèn led",
                "suy hao nguồn led",
                "driver led",
                "thiếu sáng",
                "replace led",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Bảo trì driver và mô-đun LED",
        },
        "CLEAR_CONVEYOR_JAM": {
            "keywords": [
                "kẹt pcb",
                "kẹt bảng mạch",
                "kẹt băng chuyền",
                "clear jam",
                "conveyor jam",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Gỡ kẹt bo mạch trên băng chuyền",
        },
    },
    "INJECTION_MOLDING": {
        "ADJUST_TEMPERATURE": {
            "keywords": [
                "nhiệt độ nòng",
                "hạ nhiệt nòng",
                "nozzle temp",
                "nhiệt độ đầu phun",
                "giảm nhiệt",
                "chỉnh nhiệt",
            ],
            "default_params": {"target_temp": 215.0},
            "risk_level": "LOW",
            "desc": "Điều chỉnh nhiệt độ đầu phun nhựa Zone 1",
        },
        "RESUME": {
            "keywords": [
                "tiếp tục ép",
                "chạy lại máy ép",
                "resume",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Tiếp tục chu kỳ ép khuôn",
        },
        "PURGE_BARREL": {
            "keywords": [
                "đùn xả",
                "thông nòng",
                "nghẹt nhựa",
                "purge barrel",
                "clogging",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Chu trình đùn xả nhựa cặn thông nòng phun",
        },
        "SERVICE_HEATER_SSR": {
            "keywords": [
                "kẹt rơ le",
                "rơ-le bán dẫn",
                "vòng nhiệt",
                "ssr",
                "heater runaway",
                "quá nhiệt nòng",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Thay rơ-le SSR vòng nhiệt kẹt",
        },
        "REPAIR_HYDRAULIC_VALVE": {
            "keywords": [
                "rò van thủy lực",
                "mất áp kẹp khuôn",
                "áp suất kẹp",
                "hydraulic valve",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Thay gioăng van tỉ lệ thủy lực kẹp khuôn",
        },
        "EMERGENCY_STOP": {
            "keywords": [
                "dừng khẩn cấp",
                "dừng máy ép",
                "ngắt máy",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Dừng khẩn cấp máy ép khuôn",
        },
    },
}


class AgentTools:
    """Tập hợp công cụ phân tích và thực thi hành động của Agent."""

    def __init__(self, event_bus: Any = None) -> None:
        self.event_bus = event_bus

    def translate_advice_to_actions(
        self, machine_id: str, machine_type: str, advice_text: str
    ) -> List[Dict[str, Any]]:
        """
        Quét văn bản từ RAG và dùng logic so khớp từ khóa để sinh ra
        danh sách các hành động máy móc phù hợp với từng loại máy.
        """
        text_lower = (advice_text or "").lower()
        actions: List[Dict[str, Any]] = []

        supported_commands = MACHINE_CAPABILITIES.get(machine_type, {})
        if not supported_commands:
            logger.warning(
                f"[Tools] Chưa có cấu hình khả năng điều khiển cho dòng máy: {machine_type}"
            )
            return []

        for cmd_name, cmd_info in supported_commands.items():
            matched = any(kw in text_lower for kw in cmd_info["keywords"])

            if matched:
                params = dict(cmd_info["default_params"])

                # Bóc tách tham số chi tiết nếu có
                if "speed_pct" in params or "override_pct" in params:
                    pct_match = re.search(r"(\d+)\s*%", text_lower)
                    if pct_match:
                        key = "override_pct" if "override_pct" in params else "speed_pct"
                        params[key] = float(pct_match.group(1))

                if "target_temp" in params:
                    temp_match = re.search(
                        r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*(?:°\s*c|độ(?:\s*c)?|c\b)",
                        text_lower,
                    )
                    if temp_match:
                        params["target_temp"] = float(temp_match.group(1))

                actions.append({
                    "command": cmd_name,
                    "params": params,
                    "risk_level": cmd_info["risk_level"],
                    "reason": f"Khuyến nghị từ RAG: {cmd_info['desc']}",
                })

        logger.info(
            f"[Tools] Đã phân tích văn bản cho {machine_id} -> Tìm thấy {len(actions)} hành động: "
            f"{[a['command'] for a in actions]}"
        )
        return actions

    def send_raw_command(
        self,
        machine_id: str,
        command: str,
        params: Dict[str, Any],
        risk_level: str = "LOW",
        reason: str = "",
    ) -> None:
        """Hàm hỗ trợ gửi trực tiếp 1 lệnh đơn lẻ vào EventBus khi cần."""
        if self.event_bus:
            self.event_bus.publish({
                "event_type": "action_command",
                "machine_id": machine_id,
                "command": command,
                "params": params,
                "risk_level": risk_level,
                "reason": reason,
            })
