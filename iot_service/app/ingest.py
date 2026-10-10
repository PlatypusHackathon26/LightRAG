import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.db import DatabaseManager
from app.config import evaluate_metric_status, load_machines_config
from app.stream import broadcaster

logger = logging.getLogger("app.ingest")


class InboundMetricPayload(BaseModel):
    timestamp: datetime
    machine_id: str
    metrics: Dict[str, float]


class InboundEventPayload(BaseModel):
    event_id: str
    timestamp: datetime
    machine_id: str
    source: str
    event_type: str
    severity: str
    error_code: str
    message: str
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)
    incident_id: Optional[str] = None


class MqttIngestService:
    def __init__(
        self,
        db: DatabaseManager,
        batch_flush_interval_s: float = 1.0,
        max_batch_size: int = 50,
        lifecycle_manager: Optional[Any] = None,
        command_dispatcher: Optional[Any] = None,
    ):
        self.db = db
        self.batch_flush_interval_s = batch_flush_interval_s
        self.max_batch_size = max_batch_size
        self.lifecycle_manager = lifecycle_manager
        self.command_dispatcher = command_dispatcher

        self.mqtt_host = settings.MQTT_HOST
        self.mqtt_port = settings.MQTT_PORT
        self.is_connected = False
        self.running = False

        self._metric_queue: Optional[asyncio.Queue] = None
        self._event_queue: Optional[asyncio.Queue] = None
        self._batch_task: Optional[asyncio.Task] = None
        self._event_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Setup MQTT Client
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"denso-iot-ingest-{int(time.time())}",
            )
        except AttributeError:
            self.client = mqtt.Client(client_id=f"denso-iot-ingest-{int(time.time())}")

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.is_connected = True
        logger.info(f"Ingest MQTT Connected to {self.mqtt_host}:{self.mqtt_port} (rc={rc})")
        # Subscribe to metrics, events, and command ACKs
        client.subscribe("denso/+/metrics", qos=0)
        client.subscribe("denso/+/events", qos=1)
        client.subscribe("denso/+/acks", qos=1)
        logger.info("Subscribed to denso/+/metrics, denso/+/events, denso/+/acks")

    def _on_disconnect(self, client, userdata, flags, rc=None, properties=None):
        self.is_connected = False
        logger.warning(f"Ingest MQTT Disconnected (rc={rc}). Will automatically reconnect.")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload_bytes = msg.payload
        if not self._loop or not self.running:
            return

        try:
            raw_json = json.loads(payload_bytes.decode("utf-8"))
        except Exception as e:
            logger.warning(f"Discarding invalid JSON payload on {topic}: {e}")
            return

        # Handle ACKs directly
        if topic.endswith("/acks"):
            if self.command_dispatcher:
                self.command_dispatcher.handle_ack_payload(raw_json)
            return

        # Bridge thread-safe to asyncio queues
        if topic.endswith("/metrics"):
            self._loop.call_soon_threadsafe(self._metric_queue.put_nowait, (topic, raw_json))
        elif topic.endswith("/events"):
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, (topic, raw_json))

    async def start(self):
        self._loop = asyncio.get_running_loop()
        self._metric_queue = asyncio.Queue(maxsize=10000)
        self._event_queue = asyncio.Queue(maxsize=1000)
        self.running = True

        if self.command_dispatcher:
            self.command_dispatcher.set_mqtt_client(self.client)

        self._batch_task = asyncio.create_task(self._process_metrics_batches())
        self._event_task = asyncio.create_task(self._process_events())

        try:
            self.client.connect_async(self.mqtt_host, self.mqtt_port, keepalive=60)
            self.client.loop_start()
            logger.info(f"Ingest MQTT client loop started connecting to {self.mqtt_host}:{self.mqtt_port}")
        except Exception as e:
            logger.warning(f"Initial MQTT connect failed ({e}). Reconnect loop is running in background.")
            try:
                self.client.loop_start()
            except Exception:
                pass

    async def stop(self):
        self.running = False
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

        if self._batch_task:
            self._batch_task.cancel()
        if self._event_task:
            self._event_task.cancel()

        logger.info("Ingest MQTT service stopped.")

    async def _process_metrics_batches(self):
        """Batches metric points and flushes periodically."""
        batch: List[Tuple[datetime, str, str, float]] = []
        last_flush = time.time()

        while self.running:
            try:
                timeout = max(0.1, self.batch_flush_interval_s - (time.time() - last_flush))
                try:
                    topic, raw_data = await asyncio.wait_for(self._metric_queue.get(), timeout=timeout)
                    try:
                        validated = InboundMetricPayload.model_validate(raw_data)
                        ts = validated.timestamp
                        m_id = validated.machine_id
                        for metric_name, val in validated.metrics.items():
                            batch.append((ts, m_id, metric_name, float(val)))
                        # Broadcast metrics to SSE stream
                        try:
                            m_cfg_all = load_machines_config(settings.MACHINES_CONFIG_PATH)
                            m_conf = m_cfg_all.machines.get(m_id)
                            m_status = "normal"
                            detailed_metrics = {}
                            if m_conf:
                                for k, v in validated.metrics.items():
                                    k_conf = m_conf.metrics.get(k)
                                    st = evaluate_metric_status(float(v), k_conf) if k_conf else "normal"
                                    if st == "critical":
                                        m_status = "critical"
                                    elif st == "warn" and m_status != "critical":
                                        m_status = "warn"
                                    detailed_metrics[k] = {"value": float(v), "status": st}
                            broadcaster.broadcast_metrics(
                                machine_id=m_id,
                                timestamp=ts.isoformat(),
                                metrics=detailed_metrics,
                                machine_status=m_status,
                            )
                        except Exception as b_ex:
                            logger.error(f"Error broadcasting metrics: {b_ex}")
                    except ValidationError as ve:
                        logger.warning(f"Malformed metrics payload on {topic}: {ve}")
                    self._metric_queue.task_done()
                except asyncio.TimeoutError:
                    pass

                # Flush if time elapsed or batch reached threshold
                if batch and (len(batch) >= self.max_batch_size or (time.time() - last_flush) >= self.batch_flush_interval_s):
                    to_insert = batch
                    batch = []
                    last_flush = time.time()
                    await self.db.insert_metrics_batch(to_insert)

            except asyncio.CancelledError:
                if batch:
                    await self.db.insert_metrics_batch(batch)
                break
            except Exception as ex:
                logger.error(f"Error in metrics batch processing: {ex}", exc_info=True)
                await asyncio.sleep(0.5)

    async def _process_events(self):
        """Processes and deduplicates events."""
        while self.running:
            try:
                topic, raw_data = await self._event_queue.get()
                try:
                    validated = InboundEventPayload.model_validate(raw_data)
                    event_dict = {
                        "event_id": validated.event_id,
                        "timestamp": validated.timestamp,
                        "machine_id": validated.machine_id,
                        "source": validated.source,
                        "event_type": validated.event_type,
                        "severity": validated.severity,
                        "error_code": validated.error_code,
                        "message": validated.message,
                        "payload": validated.payload or {},
                        "incident_id": validated.incident_id,
                    }
                    is_new, canon_id = await self.db.insert_or_dedup_event(event_dict)
                    if is_new:
                        logger.warning(
                            f"[Ingest Event] Stored event {validated.error_code} for machine {validated.machine_id} (ID: {validated.event_id})"
                        )
                        # Broadcast event via SSE
                        try:
                            broadcaster.broadcast_event(event_dict)
                        except Exception as bev_ex:
                            logger.error(f"Error broadcasting SSE event: {bev_ex}")
                        # Trigger Incident Lifecycle
                        if self.lifecycle_manager:
                            try:
                                await self.lifecycle_manager.handle_inbound_event(event_dict)
                            except Exception as lex:
                                logger.error(f"Error in lifecycle manager handling event: {lex}", exc_info=True)
                    else:
                        logger.info(
                            f"[Ingest Dedup] Deduplicated event {validated.error_code} for machine {validated.machine_id} -> canonical ID {canon_id}"
                        )
                except ValidationError as ve:
                    logger.warning(f"Malformed event payload on {topic}: {ve}")
                self._event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as ex:
                logger.error(f"Error processing inbound event: {ex}", exc_info=True)
                await asyncio.sleep(0.5)
