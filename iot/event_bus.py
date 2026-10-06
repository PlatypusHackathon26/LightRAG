from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


class EventBus:
    """In-memory event bus used to distribute plant events between layers."""

    def __init__(self) -> None:
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def publish(self, event: Dict[str, Any]) -> None:
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:
                continue
