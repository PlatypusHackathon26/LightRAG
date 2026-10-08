import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg_pool import AsyncConnectionPool

from app.config import settings

logger = logging.getLogger("app.db")


class DatabaseManager:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or settings.DB_DSN
        self.pool: Optional[AsyncConnectionPool] = None
        self.is_connected = False

        # In-memory stores for testing or fallback when database is not running
        self._mem_metrics: List[Dict[str, Any]] = []
        self._mem_events: List[Dict[str, Any]] = []
        self._mem_dedup: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._mem_incidents: Dict[str, Dict[str, Any]] = {}
        self._mem_actions: Dict[str, Dict[str, Any]] = {}
        self._mem_audit_log: List[Dict[str, Any]] = []
        self._incident_counter: int = 0
        self._action_counter: int = 0
        self._lock = asyncio.Lock()

    async def connect(self):
        try:
            self.pool = AsyncConnectionPool(conninfo=self.dsn, min_size=1, max_size=10, open=False)
            await self.pool.open(wait=True, timeout=5.0)
            self.is_connected = True
            logger.info("Successfully connected to PostgreSQL/TimescaleDB pool")
            # Verify and init tables if needed
            await self._init_tables()
        except Exception as e:
            self.is_connected = False
            logger.warning(
                f"Could not connect to PostgreSQL ({self.dsn}): {e}. Operating in resilient in-memory mode."
            )

    async def _init_tables(self):
        if not self.pool:
            return
        create_sql = """
        CREATE TABLE IF NOT EXISTS metrics (
            time TIMESTAMPTZ NOT NULL,
            machine_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            value DOUBLE PRECISION NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_machine_metric_time 
        ON metrics (machine_id, metric, time DESC);

        CREATE TABLE IF NOT EXISTS events (
            event_id UUID PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL,
            machine_id TEXT NOT NULL,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            error_code TEXT NOT NULL,
            message TEXT NOT NULL,
            payload JSONB DEFAULT '{}'::jsonb,
            incident_id TEXT,
            repeat_count INTEGER DEFAULT 1,
            last_seen_ts TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_events_machine_ts ON events (machine_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_events_machine_error_code ON events (machine_id, error_code, ts DESC);

        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            severity TEXT NOT NULL DEFAULT 'medium',
            title TEXT NOT NULL,
            opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ,
            timeline JSONB NOT NULL DEFAULT '[]'::jsonb,
            root_cause TEXT,
            confidence DOUBLE PRECISION,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_machine_status ON incidents (machine_id, status);
        CREATE INDEX IF NOT EXISTS idx_incidents_opened_at ON incidents (opened_at DESC);

        CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL REFERENCES incidents(id),
            machine_id TEXT NOT NULL,
            command TEXT NOT NULL,
            params JSONB NOT NULL DEFAULT '{}'::jsonb,
            rationale TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            decided_by TEXT,
            decided_at TIMESTAMPTZ,
            ack JSONB,
            auto_executed BOOLEAN NOT NULL DEFAULT FALSE
        );
        CREATE INDEX IF NOT EXISTS idx_actions_incident ON actions (incident_id);
        CREATE INDEX IF NOT EXISTS idx_actions_status ON actions (status);

        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            incident_id TEXT,
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log (ts DESC);
        """
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(create_sql)
                await conn.commit()
            logger.info("Database schema verified.")
        except Exception as ex:
            logger.error(f"Error initializing DB schema: {ex}")

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.is_connected = False
            logger.info("Closed PostgreSQL connection pool.")

    async def insert_metrics_batch(self, batch: List[Tuple[datetime, str, str, float]]):
        if not batch:
            return

        # Store in memory cache
        async with self._lock:
            for ts, m_id, metric, val in batch:
                self._mem_metrics.append({
                    "time": ts,
                    "machine_id": m_id,
                    "metric": metric,
                    "value": val,
                })
            # Bound in-memory metrics to last 50,000 points
            if len(self._mem_metrics) > 50000:
                self._mem_metrics = self._mem_metrics[-40000:]

        if not self.is_connected or not self.pool:
            return

        insert_sql = """
        INSERT INTO metrics (time, machine_id, metric, value)
        VALUES (%s, %s, %s, %s);
        """
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(insert_sql, batch)
                await conn.commit()
        except Exception as e:
            logger.error(f"Failed to batch insert {len(batch)} metrics into TimescaleDB: {e}")

    async def insert_or_dedup_event(self, event_dict: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Inserts event or dedupes within DEDUP_WINDOW_S.
        Returns: (is_new_event, canonical_event_id)
        """
        machine_id = event_dict["machine_id"]
        error_code = event_dict["error_code"]
        event_id = event_dict["event_id"]
        ts = event_dict["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

        dedup_key = (machine_id, error_code)
        window_s = settings.DEDUP_WINDOW_S

        async with self._lock:
            dedup_entry = self._mem_dedup.get(dedup_key)
            if dedup_entry is not None:
                first_seen = dedup_entry["first_seen"]
                age_s = (ts - first_seen).total_seconds()
                if age_s <= window_s:
                    # Deduplicate: increment count
                    dedup_entry["count"] += 1
                    dedup_entry["last_seen"] = ts
                    canonical_id = dedup_entry["event_id"]
                    # Update memory event
                    for ev in self._mem_events:
                        if ev["event_id"] == canonical_id:
                            ev["repeat_count"] = dedup_entry["count"]
                            ev["last_seen_ts"] = ts
                            break

                    # Update DB if available
                    if self.is_connected and self.pool:
                        try:
                            async with self.pool.connection() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        "UPDATE events SET repeat_count = %s, last_seen_ts = %s WHERE event_id = %s;",
                                        (dedup_entry["count"], ts, canonical_id),
                                    )
                                await conn.commit()
                        except Exception as ex:
                            logger.error(f"Failed to update dedup event in DB: {ex}")

                    return False, canonical_id

            # New event or window expired
            self._mem_dedup[dedup_key] = {
                "event_id": event_id,
                "first_seen": ts,
                "last_seen": ts,
                "count": 1,
            }
            ev_record = {
                "event_id": event_id,
                "ts": ts,
                "machine_id": machine_id,
                "source": event_dict.get("source", "machine"),
                "event_type": event_dict.get("event_type", "ERROR"),
                "severity": event_dict.get("severity", "CRITICAL"),
                "error_code": error_code,
                "message": event_dict.get("message", ""),
                "payload": event_dict.get("payload", {}),
                "incident_id": event_dict.get("incident_id"),
                "repeat_count": 1,
                "last_seen_ts": ts,
            }
            self._mem_events.append(ev_record)

        # Insert into DB
        if self.is_connected and self.pool:
            sql = """
            INSERT INTO events (event_id, ts, machine_id, source, event_type, severity, error_code, message, payload, incident_id, repeat_count, last_seen_ts)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING;
            """
            try:
                payload_json = json.dumps(ev_record["payload"])
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            sql,
                            (
                                ev_record["event_id"],
                                ev_record["ts"],
                                ev_record["machine_id"],
                                ev_record["source"],
                                ev_record["event_type"],
                                ev_record["severity"],
                                ev_record["error_code"],
                                ev_record["message"],
                                payload_json,
                                ev_record["incident_id"],
                                ev_record["repeat_count"],
                                ev_record["last_seen_ts"],
                            ),
                        )
                    await conn.commit()
            except Exception as e:
                logger.error(f"Failed to insert event into DB: {e}")

        return True, event_id

    async def get_latest_metrics(self, machine_id: str) -> Dict[str, Tuple[datetime, float]]:
        """
        Returns {metric_name: (timestamp, value)} for the latest sample of each metric.
        """
        if self.is_connected and self.pool:
            try:
                sql = """
                SELECT DISTINCT ON (metric) metric, time, value
                FROM metrics
                WHERE machine_id = %s
                ORDER BY metric, time DESC;
                """
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (machine_id,))
                        rows = await cur.fetchall()
                        return {r[0]: (r[1], float(r[2])) for r in rows}
            except Exception as e:
                logger.error(f"Failed to query latest metrics from DB: {e}")

        # In-memory query
        res: Dict[str, Tuple[datetime, float]] = {}
        async with self._lock:
            for item in reversed(self._mem_metrics):
                if item["machine_id"] == machine_id:
                    m = item["metric"]
                    if m not in res:
                        res[m] = (item["time"], float(item["value"]))
        return res

    async def get_metrics_at(
        self, machine_id: str, target_time: datetime
    ) -> Dict[str, Tuple[datetime, float, float]]:
        """
        Returns {metric_name: (actual_time, value, time_delta_seconds)} closest on or before target_time.
        """
        if self.is_connected and self.pool:
            try:
                sql = """
                SELECT DISTINCT ON (metric) metric, time, value
                FROM metrics
                WHERE machine_id = %s AND time <= %s
                ORDER BY metric, time DESC;
                """
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (machine_id, target_time))
                        rows = await cur.fetchall()
                        res = {}
                        for r in rows:
                            m_name, m_time, m_val = r[0], r[1], float(r[2])
                            delta_s = abs((target_time - m_time).total_seconds())
                            res[m_name] = (m_time, m_val, delta_s)
                        return res
            except Exception as e:
                logger.error(f"Failed to query metrics at time from DB: {e}")

        # In-memory query
        res: Dict[str, Tuple[datetime, float, float]] = {}
        async with self._lock:
            for item in reversed(self._mem_metrics):
                if item["machine_id"] == machine_id and item["time"] <= target_time:
                    m = item["metric"]
                    if m not in res:
                        delta_s = abs((target_time - item["time"]).total_seconds())
                        res[m] = (item["time"], float(item["value"]), delta_s)
        return res

    async def get_metrics_history(
        self, machine_id: str, since_time: datetime
    ) -> Dict[str, List[Tuple[datetime, float]]]:
        """
        Returns {metric_name: [(timestamp, value), ...]} ordered chronologically.
        """
        if self.is_connected and self.pool:
            try:
                sql = """
                SELECT metric, time, value
                FROM metrics
                WHERE machine_id = %s AND time >= %s
                ORDER BY time ASC;
                """
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (machine_id, since_time))
                        rows = await cur.fetchall()
                        result = defaultdict(list)
                        for r in rows:
                            result[r[0]].append((r[1], float(r[2])))
                        return dict(result)
            except Exception as e:
                logger.error(f"Failed to query metrics history from DB: {e}")

        # In-memory query
        result = defaultdict(list)
        async with self._lock:
            for item in self._mem_metrics:
                if item["machine_id"] == machine_id and item["time"] >= since_time:
                    result[item["metric"]].append((item["time"], float(item["value"])))
        return dict(result)

    async def get_recent_events(self, machine_id: str, since_time: datetime) -> List[Dict[str, Any]]:
        """
        Returns list of events since since_time, latest first.
        """
        if self.is_connected and self.pool:
            try:
                sql = """
                SELECT event_id, ts, machine_id, source, event_type, severity, error_code, message, payload, incident_id, repeat_count, last_seen_ts
                FROM events
                WHERE machine_id = %s AND ts >= %s
                ORDER BY ts DESC;
                """
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (machine_id, since_time))
                        rows = await cur.fetchall()
                        events = []
                        for r in rows:
                            events.append({
                                "event_id": str(r[0]),
                                "timestamp": r[1].isoformat(),
                                "machine_id": r[2],
                                "source": r[3],
                                "event_type": r[4],
                                "severity": r[5],
                                "error_code": r[6],
                                "message": r[7],
                                "payload": r[8] if isinstance(r[8], dict) else {},
                                "incident_id": r[9],
                                "repeat_count": r[10],
                                "last_seen_ts": r[11].isoformat() if r[11] else None,
                            })
                        return events
            except Exception as e:
                logger.error(f"Failed to query events from DB: {e}")

        # In-memory query
        events = []
        async with self._lock:
            for ev in reversed(self._mem_events):
                if ev["machine_id"] == machine_id and ev["ts"] >= since_time:
                    events.append({
                        "event_id": ev["event_id"],
                        "timestamp": ev["ts"].isoformat(),
                        "machine_id": ev["machine_id"],
                        "source": ev["source"],
                        "event_type": ev["event_type"],
                        "severity": ev["severity"],
                        "error_code": ev["error_code"],
                        "message": ev["message"],
                        "payload": ev.get("payload", {}),
                        "incident_id": ev.get("incident_id"),
                        "repeat_count": ev.get("repeat_count", 1),
                        "last_seen_ts": ev.get("last_seen_ts", ev["ts"]).isoformat(),
                    })
        return events

    # =========================================================================
    # Phase 2: Incidents Management
    # =========================================================================

    async def get_next_incident_id(self) -> str:
        async with self._lock:
            self._incident_counter += 1
            return f"INC-{self._incident_counter:04d}"

    async def create_incident(self, incident: Dict[str, Any]) -> str:
        now = datetime.now(timezone.utc)
        inc_id = incident.get("id") or await self.get_next_incident_id()
        opened_at = incident.get("opened_at", now)
        if isinstance(opened_at, str):
            opened_at = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))

        rec = {
            "id": inc_id,
            "machine_id": incident["machine_id"],
            "status": incident.get("status", "active"),
            "severity": incident.get("severity", "medium"),
            "title": incident["title"],
            "opened_at": opened_at,
            "updated_at": opened_at,
            "closed_at": None,
            "timeline": incident.get("timeline", []),
            "root_cause": incident.get("root_cause"),
            "confidence": incident.get("confidence", 0.0),
            "tags": incident.get("tags", []),
        }

        async with self._lock:
            self._mem_incidents[inc_id] = rec

        if self.is_connected and self.pool:
            sql = """
            INSERT INTO incidents (id, machine_id, status, severity, title, opened_at, updated_at, closed_at, timeline, root_cause, confidence, tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            sql,
                            (
                                rec["id"],
                                rec["machine_id"],
                                rec["status"],
                                rec["severity"],
                                rec["title"],
                                rec["opened_at"],
                                rec["updated_at"],
                                rec["closed_at"],
                                json.dumps(rec["timeline"]),
                                rec["root_cause"],
                                rec["confidence"],
                                json.dumps(rec["tags"]),
                            ),
                        )
                    await conn.commit()
            except Exception as e:
                logger.error(f"Failed to create incident in DB: {e}")

        return inc_id

    async def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if incident_id in self._mem_incidents:
                return dict(self._mem_incidents[incident_id])

        if self.is_connected and self.pool:
            sql = """
            SELECT id, machine_id, status, severity, title, opened_at, updated_at, closed_at, timeline, root_cause, confidence, tags
            FROM incidents
            WHERE id = %s;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (incident_id,))
                        r = await cur.fetchone()
                        if r:
                            return {
                                "id": r[0],
                                "machine_id": r[1],
                                "status": r[2],
                                "severity": r[3],
                                "title": r[4],
                                "opened_at": r[5],
                                "updated_at": r[6],
                                "closed_at": r[7],
                                "timeline": r[8] if isinstance(r[8], list) else json.loads(r[8] or "[]"),
                                "root_cause": r[9],
                                "confidence": float(r[10]) if r[10] is not None else None,
                                "tags": r[11] if isinstance(r[11], list) else json.loads(r[11] or "[]"),
                            }
            except Exception as e:
                logger.error(f"Failed to get incident from DB: {e}")

        return None

    async def get_open_incident(self, machine_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the currently open (status != 'closed') incident for machine_id, if any.
        """
        async with self._lock:
            for inc in reversed(list(self._mem_incidents.values())):
                if inc["machine_id"] == machine_id and inc["status"] != "closed":
                    return dict(inc)

        if self.is_connected and self.pool:
            sql = """
            SELECT id, machine_id, status, severity, title, opened_at, updated_at, closed_at, timeline, root_cause, confidence, tags
            FROM incidents
            WHERE machine_id = %s AND status != 'closed'
            ORDER BY opened_at DESC
            LIMIT 1;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (machine_id,))
                        r = await cur.fetchone()
                        if r:
                            return {
                                "id": r[0],
                                "machine_id": r[1],
                                "status": r[2],
                                "severity": r[3],
                                "title": r[4],
                                "opened_at": r[5],
                                "updated_at": r[6],
                                "closed_at": r[7],
                                "timeline": r[8] if isinstance(r[8], list) else json.loads(r[8] or "[]"),
                                "root_cause": r[9],
                                "confidence": float(r[10]) if r[10] is not None else None,
                                "tags": r[11] if isinstance(r[11], list) else json.loads(r[11] or "[]"),
                            }
            except Exception as e:
                logger.error(f"Failed to get open incident from DB: {e}")

        return None

    async def list_incidents(
        self, machine_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        results = []
        async with self._lock:
            for inc in self._mem_incidents.values():
                if machine_id and inc["machine_id"] != machine_id:
                    continue
                if status and inc["status"] != status:
                    continue
                results.append(dict(inc))

        # If DB is connected, read all from DB for consistency
        if self.is_connected and self.pool:
            try:
                where_clauses = []
                params = []
                if machine_id:
                    where_clauses.append("machine_id = %s")
                    params.append(machine_id)
                if status:
                    where_clauses.append("status = %s")
                    params.append(status)
                where_str = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                sql = f"""
                SELECT id, machine_id, status, severity, title, opened_at, updated_at, closed_at, timeline, root_cause, confidence, tags
                FROM incidents
                {where_str}
                ORDER BY opened_at DESC;
                """
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, params)
                        rows = await cur.fetchall()
                        db_results = []
                        for r in rows:
                            db_results.append({
                                "id": r[0],
                                "machine_id": r[1],
                                "status": r[2],
                                "severity": r[3],
                                "title": r[4],
                                "opened_at": r[5],
                                "updated_at": r[6],
                                "closed_at": r[7],
                                "timeline": r[8] if isinstance(r[8], list) else json.loads(r[8] or "[]"),
                                "root_cause": r[9],
                                "confidence": float(r[10]) if r[10] is not None else None,
                                "tags": r[11] if isinstance(r[11], list) else json.loads(r[11] or "[]"),
                            })
                        return db_results
            except Exception as e:
                logger.error(f"Failed to list incidents from DB: {e}")

        # Sort by opened_at descending
        results.sort(key=lambda x: x["opened_at"], reverse=True)
        return results

    async def update_incident(self, incident_id: str, updates: Dict[str, Any]) -> bool:
        now = datetime.now(timezone.utc)
        updates["updated_at"] = now

        async with self._lock:
            if incident_id in self._mem_incidents:
                self._mem_incidents[incident_id].update(updates)

        if self.is_connected and self.pool:
            try:
                set_clauses = []
                params = []
                for k, v in updates.items():
                    set_clauses.append(f"{k} = %s")
                    if k in ("timeline", "tags") and isinstance(v, (list, dict)):
                        params.append(json.dumps(v))
                    else:
                        params.append(v)
                params.append(incident_id)

                sql = f"UPDATE incidents SET {', '.join(set_clauses)} WHERE id = %s;"
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, params)
                    await conn.commit()
            except Exception as e:
                logger.error(f"Failed to update incident in DB: {e}")
                return False

        return True

    async def append_incident_timeline(self, incident_id: str, event_item: Dict[str, Any]) -> bool:
        """Appends an event to the incident's timeline jsonb array."""
        inc = await self.get_incident(incident_id)
        if not inc:
            return False
        timeline = inc.get("timeline", []) or []
        timeline.append(event_item)
        return await self.update_incident(incident_id, {"timeline": timeline})

    # =========================================================================
    # Phase 2: Actions Management
    # =========================================================================

    async def get_next_action_id(self) -> str:
        async with self._lock:
            self._action_counter += 1
            return f"ACT-{self._action_counter:04d}"

    async def create_action(self, action: Dict[str, Any]) -> str:
        now = datetime.now(timezone.utc)
        act_id = action.get("id") or await self.get_next_action_id()
        proposed_at = action.get("proposed_at", now)
        expires_at = action.get("expires_at")
        if isinstance(proposed_at, str):
            proposed_at = datetime.fromisoformat(proposed_at.replace("Z", "+00:00"))
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

        rec = {
            "id": act_id,
            "incident_id": action["incident_id"],
            "machine_id": action["machine_id"],
            "command": action["command"],
            "params": action.get("params", {}),
            "rationale": action.get("rationale", ""),
            "status": action.get("status", "pending"),
            "proposed_at": proposed_at,
            "expires_at": expires_at,
            "decided_by": action.get("decided_by"),
            "decided_at": action.get("decided_at"),
            "ack": action.get("ack"),
            "auto_executed": action.get("auto_executed", False),
        }

        async with self._lock:
            self._mem_actions[act_id] = rec

        if self.is_connected and self.pool:
            sql = """
            INSERT INTO actions (id, incident_id, machine_id, command, params, rationale, status, proposed_at, expires_at, decided_by, decided_at, ack, auto_executed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            sql,
                            (
                                rec["id"],
                                rec["incident_id"],
                                rec["machine_id"],
                                rec["command"],
                                json.dumps(rec["params"]),
                                rec["rationale"],
                                rec["status"],
                                rec["proposed_at"],
                                rec["expires_at"],
                                rec["decided_by"],
                                rec["decided_at"],
                                json.dumps(rec["ack"]) if rec["ack"] else None,
                                rec["auto_executed"],
                            ),
                        )
                    await conn.commit()
            except Exception as e:
                logger.error(f"Failed to insert action into DB: {e}")

        return act_id

    async def get_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if action_id in self._mem_actions:
                return dict(self._mem_actions[action_id])

        if self.is_connected and self.pool:
            sql = """
            SELECT id, incident_id, machine_id, command, params, rationale, status, proposed_at, expires_at, decided_by, decided_at, ack, auto_executed
            FROM actions
            WHERE id = %s;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (action_id,))
                        r = await cur.fetchone()
                        if r:
                            return {
                                "id": r[0],
                                "incident_id": r[1],
                                "machine_id": r[2],
                                "command": r[3],
                                "params": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                                "rationale": r[5],
                                "status": r[6],
                                "proposed_at": r[7],
                                "expires_at": r[8],
                                "decided_by": r[9],
                                "decided_at": r[10],
                                "ack": r[11] if isinstance(r[11], dict) else (json.loads(r[11]) if r[11] else None),
                                "auto_executed": r[12],
                            }
            except Exception as e:
                logger.error(f"Failed to get action from DB: {e}")

        return None

    async def get_pending_action_for_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            for act in reversed(list(self._mem_actions.values())):
                if act["incident_id"] == incident_id and act["status"] == "pending":
                    return dict(act)

        if self.is_connected and self.pool:
            sql = """
            SELECT id, incident_id, machine_id, command, params, rationale, status, proposed_at, expires_at, decided_by, decided_at, ack, auto_executed
            FROM actions
            WHERE incident_id = %s AND status = 'pending'
            ORDER BY proposed_at DESC
            LIMIT 1;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (incident_id,))
                        r = await cur.fetchone()
                        if r:
                            return {
                                "id": r[0],
                                "incident_id": r[1],
                                "machine_id": r[2],
                                "command": r[3],
                                "params": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                                "rationale": r[5],
                                "status": r[6],
                                "proposed_at": r[7],
                                "expires_at": r[8],
                                "decided_by": r[9],
                                "decided_at": r[10],
                                "ack": r[11] if isinstance(r[11], dict) else (json.loads(r[11]) if r[11] else None),
                                "auto_executed": r[12],
                            }
            except Exception as e:
                logger.error(f"Failed to get pending action from DB: {e}")

        return None

    async def get_actions_for_incident(self, incident_id: str) -> List[Dict[str, Any]]:
        results = []
        async with self._lock:
            for act in self._mem_actions.values():
                if act["incident_id"] == incident_id:
                    results.append(dict(act))

        if self.is_connected and self.pool:
            sql = """
            SELECT id, incident_id, machine_id, command, params, rationale, status, proposed_at, expires_at, decided_by, decided_at, ack, auto_executed
            FROM actions
            WHERE incident_id = %s
            ORDER BY proposed_at ASC;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, (incident_id,))
                        rows = await cur.fetchall()
                        db_results = []
                        for r in rows:
                            db_results.append({
                                "id": r[0],
                                "incident_id": r[1],
                                "machine_id": r[2],
                                "command": r[3],
                                "params": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                                "rationale": r[5],
                                "status": r[6],
                                "proposed_at": r[7],
                                "expires_at": r[8],
                                "decided_by": r[9],
                                "decided_at": r[10],
                                "ack": r[11] if isinstance(r[11], dict) else (json.loads(r[11]) if r[11] else None),
                                "auto_executed": r[12],
                            })
                        return db_results
            except Exception as e:
                logger.error(f"Failed to get actions for incident from DB: {e}")

        return results

    async def update_action(self, action_id: str, updates: Dict[str, Any]) -> bool:
        async with self._lock:
            if action_id in self._mem_actions:
                self._mem_actions[action_id].update(updates)

        if self.is_connected and self.pool:
            try:
                set_clauses = []
                params = []
                for k, v in updates.items():
                    set_clauses.append(f"{k} = %s")
                    if k in ("params", "ack") and isinstance(v, (dict, list)):
                        params.append(json.dumps(v))
                    else:
                        params.append(v)
                params.append(action_id)

                sql = f"UPDATE actions SET {', '.join(set_clauses)} WHERE id = %s;"
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, params)
                    await conn.commit()
            except Exception as e:
                logger.error(f"Failed to update action in DB: {e}")
                return False

        return True

    async def count_auto_actions_for_incident(self, incident_id: str) -> int:
        count = 0
        async with self._lock:
            for act in self._mem_actions.values():
                if act["incident_id"] == incident_id and act.get("auto_executed") and act["status"] in ("approved", "executing", "acked"):
                    count += 1
        return count

    async def get_latest_auto_action_time(self, incident_id: str) -> Optional[datetime]:
        latest: Optional[datetime] = None
        async with self._lock:
            for act in self._mem_actions.values():
                if act["incident_id"] == incident_id and act.get("auto_executed") and act["status"] in ("approved", "executing", "acked"):
                    t = act.get("decided_at") or act.get("proposed_at")
                    if t and (latest is None or t > latest):
                        latest = t
        return latest

    # =========================================================================
    # Phase 2: Audit Log Management
    # =========================================================================

    async def insert_audit_log(
        self,
        actor: str,
        action: str,
        machine_id: str,
        incident_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        now = datetime.now(timezone.utc)
        record = {
            "id": len(self._mem_audit_log) + 1,
            "ts": now,
            "actor": actor,
            "action": action,
            "machine_id": machine_id,
            "incident_id": incident_id,
            "details": details or {},
        }
        async with self._lock:
            self._mem_audit_log.append(record)

        if self.is_connected and self.pool:
            sql = """
            INSERT INTO audit_log (ts, actor, action, machine_id, incident_id, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            sql,
                            (
                                record["ts"],
                                record["actor"],
                                record["action"],
                                record["machine_id"],
                                record["incident_id"],
                                json.dumps(record["details"]),
                            ),
                        )
                        r = await cur.fetchone()
                        if r:
                            record["id"] = r[0]
                    await conn.commit()
            except Exception as e:
                logger.error(f"Failed to insert audit log into DB: {e}")

        return record["id"]

    async def get_audit_logs(
        self, incident_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        results = []
        async with self._lock:
            for log in reversed(self._mem_audit_log):
                if incident_id and log.get("incident_id") != incident_id:
                    continue
                results.append(dict(log))
                if len(results) >= limit:
                    break
        return results


db_manager = DatabaseManager()
