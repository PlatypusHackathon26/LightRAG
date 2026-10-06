from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List

logger = logging.getLogger("EventBus")


class EventBus:
    """In-memory event bus hỗ trợ lọc topic và thực thi không nghẽn luồng (Non-blocking)."""

    def __init__(self, max_workers: int = 4) -> None:
        # Cấu trúc lưu: { "topic_name": [handler1, handler2, ...] }
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        # Thread pool giúp các hàm nặng (như LLM reasoning) chạy ngầm không làm đơ bus
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="event_bus_worker"
        )

    def subscribe(
        self, topic: str, handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Đăng ký hàm lắng nghe theo topic cụ thể (alert, normal, action_command) hoặc '*' cho tất cả."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        if handler not in self._subscribers[topic]:
            self._subscribers[topic].append(handler)

    def unsubscribe(
        self, topic: str, handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Hủy đăng ký lắng nghe."""
        if topic in self._subscribers and handler in self._subscribers[topic]:
            self._subscribers[topic].remove(handler)

    def publish(self, event: Dict[str, Any], async_dispatch: bool = True) -> None:
        """
        Bắn event tới các bên liên quan.
        - async_dispatch=True: Đẩy sang ThreadPool để không bị block khi Agent gọi LLM.
        """
        topic = event.get("label") or event.get("event_type", "default")

        # Gom danh sách: người nghe đúng topic + người nghe wildcard '*'
        listeners = list(self._subscribers.get(topic, [])) + list(
            self._subscribers.get("*", [])
        )

        for handler in listeners:
            if async_dispatch:
                self._executor.submit(self._safe_call, handler, event, topic)
            else:
                self._safe_call(handler, event, topic)

    def _safe_call(
        self, handler: Callable[[Dict[str, Any]], None], event: Dict[str, Any], topic: str
    ) -> None:
        """Bọc try-except để lỗi của 1 subscriber không làm sập các bên khác."""
        try:
            handler(event)
        except Exception as e:
            logger.error(
                f"[EventBus] Lỗi khi xử lý event '{topic}' qua hàm '{handler.__name__}': {e}",
                exc_info=True,
            )

    def shutdown(self) -> None:
        """Dọn dẹp thread pool khi dừng chương trình."""
        self._executor.shutdown(wait=False)