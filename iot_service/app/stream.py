import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set
from fastapi import Request

from app.config import settings

logger = logging.getLogger("app.stream")


class EventBroadcaster:
    """
    In-process Pub/Sub event broadcaster for Server-Sent Events (SSE).
    - Per-client bounded queues (drops oldest message if queue is full, non-blocking for producers).
    - Max concurrent clients limit.
    - SSE event types: snapshot, metrics, event, machine_status, heartbeat, incident, action.
    """

    def __init__(self, max_clients: Optional[int] = None, client_queue_size: int = 50):
        self.max_clients = max_clients or settings.SSE_MAX_CLIENTS
        self.client_queue_size = client_queue_size
        self._clients: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._last_metrics_publish: Dict[str, float] = {}  # machine_id -> timestamp

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def register_client(self) -> Optional[asyncio.Queue]:
        async with self._lock:
            if len(self._clients) >= self.max_clients:
                logger.warning(
                    f"SSE client limit reached ({len(self._clients)}/{self.max_clients}). Rejecting new connection."
                )
                return None
            queue: asyncio.Queue = asyncio.Queue(maxsize=self.client_queue_size)
            self._clients.add(queue)
            logger.info(f"SSE client connected. Active clients: {len(self._clients)}")
            return queue

    async def unregister_client(self, queue: asyncio.Queue):
        async with self._lock:
            if queue in self._clients:
                self._clients.remove(queue)
                logger.info(f"SSE client disconnected. Active clients: {len(self._clients)}")

    def broadcast(self, event_type: str, data: Any):
        """
        Non-blocking broadcast to all active SSE queues.
        If a client queue is full, the oldest message is dropped.
        """
        payload = {
            "event": event_type,
            "data": data,
        }
        for q in list(self._clients):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()  # Drop oldest
                    q.put_nowait(payload)
                except Exception:
                    pass

    def broadcast_metrics(self, machine_id: str, timestamp: str, metrics: Dict[str, Any], machine_status: str):
        """
        Throttled metric broadcast: at most 1 message per machine per PUBLISH_INTERVAL_S.
        """
        now = time.time()
        last_t = self._last_metrics_publish.get(machine_id, 0.0)
        # Allow broadcast if interval elapsed (with small tolerance)
        if now - last_t >= (settings.PUBLISH_INTERVAL_S - 0.2):
            self._last_metrics_publish[machine_id] = now
            self.broadcast(
                "metrics",
                {
                    "machine_id": machine_id,
                    "timestamp": timestamp,
                    "metrics": metrics,
                    "machine_status": machine_status,
                },
            )

    def broadcast_event(self, event_data: Dict[str, Any]):
        self.broadcast("event", event_data)

    def broadcast_machine_status(self, machine_id: str, status: str, previous_status: Optional[str] = None):
        self.broadcast("machine_status", {
            "machine_id": machine_id,
            "status": status,
            "previous_status": previous_status,
            "timestamp": time.time(),
        })

    def broadcast_incident(self, event_type: str, incident_data: Dict[str, Any]):
        """
        Broadcasts sanitized incident updates (created, status_changed, resolved, closed).
        Does NOT expose API keys or raw LLM prompts.
        """
        sanitized = {
            "action": event_type,
            "incident_id": incident_data.get("id"),
            "machine_id": incident_data.get("machine_id"),
            "status": incident_data.get("status"),
            "severity": incident_data.get("severity"),
            "title": incident_data.get("title"),
            "root_cause": incident_data.get("root_cause"),
            "confidence": incident_data.get("confidence"),
            "opened_at": str(incident_data.get("opened_at", "")),
            "closed_at": str(incident_data.get("closed_at", "")) if incident_data.get("closed_at") else None,
            "timestamp": time.time(),
        }
        self.broadcast("incident", sanitized)

    def broadcast_action(self, event_type: str, action_data: Dict[str, Any]):
        """
        Broadcasts sanitized action updates (proposed, approved, rejected, expired, executing, acked, failed).
        """
        sanitized = {
            "action": event_type,
            "action_id": action_data.get("id"),
            "incident_id": action_data.get("incident_id"),
            "machine_id": action_data.get("machine_id"),
            "command": action_data.get("command"),
            "params": action_data.get("params"),
            "rationale": action_data.get("rationale"),
            "status": action_data.get("status"),
            "auto_executed": action_data.get("auto_executed", False),
            "decided_by": action_data.get("decided_by"),
            "decided_at": str(action_data.get("decided_at", "")) if action_data.get("decided_at") else None,
            "expires_at": str(action_data.get("expires_at", "")) if action_data.get("expires_at") else None,
            "ack": action_data.get("ack"),
            "timestamp": time.time(),
        }
        self.broadcast("action", sanitized)

    def broadcast_heartbeat(self):
        self.broadcast("heartbeat", {
            "timestamp": time.time(),
        })


broadcaster = EventBroadcaster()


async def sse_event_generator(request: Request, queue: asyncio.Queue, initial_snapshot: Optional[Dict[str, Any]] = None):
    """
    Asynchronous generator yielding Server-Sent Events formatted strings.
    Sends initial snapshot immediately upon connection, then yields queued events,
    with an internal 15-second heartbeat timer.
    """
    try:
        # 1. Send snapshot immediately
        if initial_snapshot:
            data_json = json.dumps(initial_snapshot, ensure_ascii=False)
            yield f"event: snapshot\ndata: {data_json}\n\n"

        last_heartbeat = time.time()
        heartbeat_interval = 15.0

        while True:
            if await request.is_disconnected():
                break

            now = time.time()
            timeout = max(0.5, heartbeat_interval - (now - last_heartbeat))

            try:
                msg = await asyncio.wait_for(queue.get(), timeout=timeout)
                ev_type = msg.get("event", "message")
                data_json = json.dumps(msg.get("data", {}), ensure_ascii=False)
                yield f"event: {ev_type}\ndata: {data_json}\n\n"
            except asyncio.TimeoutError:
                # Send periodic heartbeat
                last_heartbeat = time.time()
                yield f"event: heartbeat\ndata: {{\"timestamp\": {last_heartbeat}}}\n\n"

    finally:
        await broadcaster.unregister_client(queue)
