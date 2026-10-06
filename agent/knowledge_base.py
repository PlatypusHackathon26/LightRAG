from __future__ import annotations

from typing import Any, Dict, List


class KnowledgeBase:
    """Mock DENSO maintenance knowledge store with local troubleshooting guidance."""

    def __init__(self) -> None:
        self.entries: Dict[str, str] = {
            "spindle thermal overload": "Vệ sinh hệ thống làm mát, kiểm tra dầu bôi trơn trục chính và thay dao nếu độ mòn vượt ngưỡng. Dừng máy nếu nhiệt độ > 90°C trong 3 chu kỳ liên tiếp.",
            "vibration anomaly": "Kiểm tra cân bằng trục chính, độ lệch kẹp dao và sự mòn của ổ trục. Nếu rung > 7.5 mm/s, kích hoạt FEED_HOLD và yêu cầu kỹ thuật kiểm tra cơ học.",
            "pressure deviation": "Kiểm tra nhiệt độ nòng, độ kín khuôn và độ đều áp suất phun. Nếu lệch > ±20% so với tiêu chuẩn, dừng lô đang ép và rà soát khuôn.",
            "robot overload": "Kiểm tra motor servo J3, định vị khớp và tải công việc trên robot. Giảm tốc độ và đưa về Safe-Home nếu quá nhiệt hoặc dòng điện tăng đột ngột.",
            "false reject spike": "Kiểm tra bụi trên ống kính, hiệu chuẩn camera và dao động cường độ đèn máy. Dừng quy trình kiểm tra tạm thời nếu tỷ lệ báo lỗi giả > 4%.",
            "battery low": "Đưa AMR về docking station hoặc điểm sạc an toàn và kiểm tra lịch sử pin trước khi tiếp tục tuyến dịch chuyển.",
        }

    def query(self, issue: str) -> str:
        normalized = issue.lower().strip()
        for key, guidance in self.entries.items():
            if key in normalized or normalized in key:
                return guidance
        return "Kiểm tra theo dõi telemetry và làm việc với kỹ sư ca trực để xác định nguyên nhân thực tế trước khi can thiệp."
