from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Callable, Dict, List, Set

logger = logging.getLogger("EventBus")


class EventBus:
    """In-memory event bus hỗ trợ routing đa topic, wildcard và non-blocking thread pool."""

    def __init__(self, max_workers: int = 6) -> None:
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self._lock = Lock()
        self._is_shutdown = False
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="event_bus_worker"
        )

    def subscribe(
        self, topic: str, handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Đăng ký lắng nghe theo topic (hỗ trợ wildcard '*')."""
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            if handler not in self._subscribers[topic]:
                self._subscribers[topic].append(handler)
                logger.debug(f"[EventBus] Handler '{getattr(handler, '__name__', str(handler))}' subscribed to '{topic}'")

    def unsubscribe(
        self, topic: str, handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Hủy đăng ký lắng nghe."""
        with self._lock:
            if topic in self._subscribers and handler in self._subscribers[topic]:
                self._subscribers[topic].remove(handler)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]

    def publish(self, event: Dict[str, Any], async_dispatch: bool = True) -> None:
        """Phát tán event tới tất cả các topic tương ứng:

        - label (ví dụ: 'alert', 'normal')
        - event_type (ví dụ: 'telemetry', 'approval_required', 'command_response')
        - machine_id (ví dụ: 'MC-MILL-01')
        - wildcard ('*')
        """
        if self._is_shutdown:
            logger.warning("[EventBus] EventBus đã tắt, từ chối nhận publish mới.")
            return

        # Xác định tất cả các topic hợp lệ mà event này thuộc về
        target_topics: Set[str] = {"*"}
        if "label" in event and event["label"]:
            target_topics.add(str(event["label"]))
        if "event_type" in event and event["event_type"]:
            target_topics.add(str(event["event_type"]))
        if "machine_id" in event and event["machine_id"]:
            target_topics.add(str(event["machine_id"]))

        # Lấy danh sách handlers độc bản (không gọi trùng lặp 1 handler nếu khớp nhiều topic)
        handlers_to_invoke: List[Callable[[Dict[str, Any]], None]] = []
        with self._lock:
            visited_handlers = set()
            for t in target_topics:
                for h in self._subscribers.get(t, []):
                    if h not in visited_handlers:
                        visited_handlers.add(h)
                        handlers_to_invoke.append(h)

        # Điều phối thực thi
        for handler in handlers_to_invoke:
            if async_dispatch:
                try:
                    self._executor.submit(self._safe_call, handler, event)
                except RuntimeError:
                    # Đề phòng trường hợp đang submit thì bus bị gọi shutdown
                    break
            else:
                self._safe_call(handler, event)

    def _safe_call(
        self, handler: Callable[[Dict[str, Any]], None], event: Dict[str, Any]
    ) -> None:
        """Bọc try-except bảo vệ luồng bus không bị gián đoạn khi 1 subscriber gặp exception."""
        try:
            handler(event)
        except Exception as e:
            handler_name = getattr(handler, "__name__", str(handler))
            logger.error(
                f"[EventBus] Lỗi trong handler '{handler_name}' khi nhận event: {e}",
                exc_info=True,
            )

    def shutdown(self, wait: bool = False) -> None:
        """Dừng hoàn toàn bus và dọn luồng."""
        self._is_shutdown = True
        self._executor.shutdown(wait=wait)
        logger.info("[EventBus] Đã đóng ThreadPoolExecutor an toàn.")