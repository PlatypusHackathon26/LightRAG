# agent/tools.py
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger("AgentTools")

# =============================================================================
# BẢNG TỪ ĐIỂN NĂNG LỰC CỦA TỪNG LOẠI MÁY (MACHINE ACTION CAPABILITIES)
# =============================================================================
MACHINE_CAPABILITIES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "CNC_MILLING": {
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
        "SET_FEED_OVERRIDE": {
            "keywords": [
                "giảm tốc",
                "hạ tốc",
                "chậm lại",
                "feed rate",
                "tốc độ ăn dao",
                "tải trục",
                "giảm tải",
            ],
            "default_params": {"override_pct": 50.0},
            "risk_level": "LOW",
            "desc": "Điều chỉnh tốc độ ăn dao (%)",
        },
        "SAFE_STOP": {
            "keywords": [
                "dừng an toàn",
                "safe stop",
                "dừng máy",
                "tắt máy",
                "dừng chu trình",
                "khởi động lại",
                "kẹt phôi",
            ],
            "default_params": {"graceful": True},
            "risk_level": "HIGH",
            "desc": "Dừng an toàn sau khi hoàn tất chu trình cắt",
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
            ],
            "default_params": {"target_temp": 210.0},
            "risk_level": "LOW",
            "desc": "Điều chỉnh nhiệt độ đầu phun nhựa",
        },
        "SET_CLAMP_PRESSURE": {
            "keywords": [
                "áp suất kẹp",
                "giảm áp kẹp",
                "chỉnh áp lực",
                "clamping pressure",
            ],
            "default_params": {"pressure_bar": 130.0},
            "risk_level": "LOW",
            "desc": "Hiệu chỉnh áp suất kẹp khuôn",
        },
        "SAFE_STOP": {
            "keywords": [
                "dừng ép",
                "dừng máy",
                "tắt máy",
                "nghẹt nhựa",
                "cháy nhựa",
                "khởi động lại",
            ],
            "default_params": {"graceful": True},
            "risk_level": "HIGH",
            "desc": "Dừng chu kỳ ép nhựa an toàn",
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
            "risk_level": "HIGH",
            "desc": "Tạm dừng quỹ đạo di chuyển của robot",
        },
        "RESET_TRAJECTORY": {
            "keywords": [
                "về gốc",
                "về vị trí ban đầu",
                "reset",
                "home",
                "vị trí an toàn",
            ],
            "default_params": {},
            "risk_level": "LOW",
            "desc": "Đưa các khớp cánh tay về tọa độ gốc",
        },
        "ADJUST_JOINT_SPEED": {
            "keywords": [
                "giảm tốc độ quay",
                "chạy chậm",
                "hạ tốc độ robot",
                "giảm vận tốc",
            ],
            "default_params": {"speed_factor": 0.5},
            "risk_level": "LOW",
            "desc": "Giới hạn vận tốc các khớp",
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
            ],
            "default_params": {"profile": "standard"},
            "risk_level": "LOW",
            "desc": "Tự động hiệu chuẩn lại camera và cụm quang học",
        },
        "PAUSE_INSPECTION_LINE": {
            "keywords": [
                "dừng băng chuyền kiểm tra",
                "tạm dừng soi",
                "dừng kiểm định",
            ],
            "default_params": {},
            "risk_level": "HIGH",
            "desc": "Tạm dừng luồng kiểm tra chất lượng",
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
            "default_params": {"station": "BUFFER_STATION"},
            "risk_level": "LOW",
            "desc": "Di chuyển xe AMR đến trạm được chỉ định",
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
            "desc": "Phanh khẩn cấp lập tức",
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
        text_lower = advice_text.lower()
        actions: List[Dict[str, Any]] = []

        # 1. Tra cứu xem loại máy này hỗ trợ những lệnh nào
        supported_commands = MACHINE_CAPABILITIES.get(machine_type, {})
        if not supported_commands:
            logger.warning(
                f"[Tools] Chưa có cấu hình khả năng điều khiển cho dòng máy: {machine_type}"
            )
            return []

        # 2. Duyệt qua từng lệnh mà dòng máy này có thể thực thi
        for cmd_name, cmd_info in supported_commands.items():
            matched = any(kw in text_lower for kw in cmd_info["keywords"])

            if matched:
                params = dict(cmd_info["default_params"])

                # Bóc tách tham số chi tiết (nếu trong đoạn văn có đề cập số cụ thể)
                # Trường hợp: lệnh chỉnh tốc độ có số % (ví dụ: 'giảm còn 40%', '50%')
                if "speed_pct" in params or "override_pct" in params:
                    pct_match = re.search(r"(\d+)\s*%", text_lower)
                    if pct_match:
                        key = "override_pct" if "override_pct" in params else "speed_pct"
                        params[key] = float(pct_match.group(1))

                # Trường hợp: lệnh chỉnh nhiệt độ có số độ C (ví dụ: '215 độ', '220°C')
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
