# agent/rag_engine.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("RAGEngine")


class RAGEngine:
    """RAG Engine phục vụ truy vấn cẩm nang vận hành thiết bị."""

    def __init__(self, storage_dir: str = "./lightrag_storage") -> None:
        self.storage_dir = storage_dir
        logger.info(f"[RAGEngine] Khởi tạo RAG Engine tại: {storage_dir}")

    def query(self, query_text: str, mode: str = "hybrid") -> str:
        """
        Nhận câu hỏi/tình trạng sự cố và trả về văn bản tư vấn kỹ thuật.
        Hiện tại dùng phản hồi mẫu thực tế theo từ khóa để bạn test thông Dashboard & Dispatcher.
        Sau này khi cắm LightRAG thật, bạn chỉ cần thế code vào đây.
        """
        logger.info(f"[RAGEngine] Tiếp nhận truy vấn: {query_text}")
        text_lower = query_text.lower()

        # 1. Kịch bản Máy Phay CNC
        if "cnc_milling" in text_lower or "mc-mill-01" in text_lower:
            if "spindle_temp_c" in text_lower or "nhiệt" in text_lower:
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

        # 2. Kịch bản Máy Ép Nhựa
        elif "injection_molding" in text_lower or "mc-inj-01" in text_lower:
            return (
                "Cảnh báo kỹ thuật FANUC ROBOSHOT: Nhiệt độ nòng phun Zone 1 có xu hướng trôi nhiệt. "
                "Cần điều chỉnh hạ nhiệt nòng phun về 215°C (ADJUST_TEMPERATURE) và kiểm tra áp suất kẹp khuôn."
            )

        # 3. Kịch bản Cánh Tay Robot
        elif "robot_arm" in text_lower or "mc-robot-01" in text_lower:
            return (
                "Cảnh báo quá dòng khớp J3 trên robot DENSO: Xuất hiện lực cản bất thường hoặc va chạm nhẹ. "
                "Khuyến nghị tạm dừng chuyển động (PAUSE_MOTION) hoặc giảm tốc độ quay còn 50% (ADJUST_JOINT_SPEED)."
            )

        # 4. Kịch bản Xe Tự Hành AMR
        elif "amr_vehicle" in text_lower or "mc-amr-01" in text_lower:
            return (
                "Cảnh báo dung lượng pin AMR xuống dưới ngưỡng 20%: Điều phối xe tự hành di chuyển "
                "về dock sạc ngay lập tức (RETURN_TO_CHARGER)."
            )

        # 5. Kịch bản Máy Kiểm Tra Quang Học AOI
        elif "aoi_inspection" in text_lower or "mc-aoi-01" in text_lower:
            return (
                "Tỷ lệ từ chối giả (False Reject) tăng cao do bụi bám lăng kính quang học: "
                "Cần thực hiện chu trình thổi khí tự động và hiệu chuẩn camera (RECALIBRATE_OPTICS)."
            )

        # Mặc định chung
        return (
            "Hệ thống phát hiện biến động thông số ngoài dải tiêu chuẩn. "
            "Khuyến nghị kỹ thuật viên kiểm tra trực tiếp và duy trì chế độ an toàn."
        )