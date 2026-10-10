import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import DatabaseManager
from app.main import app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_timescale_db_real_integration():
    """
    Integration test strictly requiring a live TimescaleDB container.
    Validates:
    1. Successful connection to live TimescaleDB (is_connected=True, _in_memory=False).
    2. Writing real metrics into TimescaleDB and reading back via Tool API (/current-status, /history).
    3. Writing real events into TimescaleDB and reading back via Tool API (/events).
    4. Health endpoint reports 'ok' and database 'connected'.
    This test will fail if DB is broken or running in fallback in-memory mode.
    """
    # Create DB manager pointing to real DSN
    real_db = DatabaseManager(dsn=settings.DB_DSN)
    await real_db.connect()

    # Strict assertion: MUST NOT be in-memory mode!
    assert real_db.is_connected is True, "Failed to connect to real TimescaleDB container"
    assert real_db._in_memory is False, "DB is unexpectedly operating in-memory"

    # Swap in real_db as the app's db_manager for this test
    from app import db as db_module
    from app.routers import tools as tools_module  # binds db_manager at import time
    original_db = db_module.db_manager
    db_module.db_manager = real_db
    tools_module.db_manager = real_db
    app.state.db = real_db

    try:
        test_machine = "COMP-TB-01"
        test_metric = "discharge_temp"
        # Above anything the simulator publishes, and stamped a little ahead: a running simulator
        # writes the same machine into the same database while this test runs.
        test_value = 199.5
        now = datetime.now(timezone.utc)

        # 1. Insert real metric batch directly into TimescaleDB
        batch = [
            (now + timedelta(seconds=10), test_machine, test_metric, 182.0),
            (now + timedelta(seconds=20), test_machine, test_metric, 185.0),
            (now + timedelta(seconds=30), test_machine, test_metric, test_value),
        ]
        await real_db.insert_metrics_batch(batch)

        # 2. Insert real PLC event into TimescaleDB
        test_event_code = f"ERR_INTEG_{uuid.uuid4().hex[:6].upper()}"
        event_payload = {
            "event_id": str(uuid.uuid4()),
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "machine_id": test_machine,
            "source": "plc",
            "event_type": "ERROR",
            "severity": "CRITICAL",
            "error_code": test_event_code,
            "message": "Integration test error event",
            "payload": {"test": True},
        }
        await real_db.insert_or_dedup_event(event_payload)

        # 3. Read back via Tool API
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Check /health endpoint
            res_health = await client.get("/health")
            assert res_health.status_code == 200
            h_data = res_health.json()
            assert h_data["status"] == "ok"
            assert h_data["database"] == "connected"
            assert h_data["db_mode"] == "timescale"

            # Check /current-status via Tool API
            res_curr = await client.get(
                f"/api/v1/machine/{test_machine}/current-status",
                headers={"X-API-Key": settings.IOT_API_KEY},
            )
            assert res_curr.status_code == 200
            curr_data = res_curr.json()
            assert curr_data["machine_id"] == test_machine
            assert test_metric in curr_data["metrics"]
            # Current value should match the latest inserted point
            assert curr_data["metrics"][test_metric]["value"] == test_value

            # Check /history via Tool API
            res_hist = await client.get(
                f"/api/v1/machine/{test_machine}/history?minutes=10",
                headers={"X-API-Key": settings.IOT_API_KEY},
            )
            assert res_hist.status_code == 200
            hist_data = res_hist.json()
            assert test_metric in hist_data["metrics"]
            assert hist_data["metrics"][test_metric]["max"] == test_value

            # Check /events via Tool API
            res_ev = await client.get(
                f"/api/v1/machine/{test_machine}/events?minutes=10",
                headers={"X-API-Key": settings.IOT_API_KEY},
            )
            assert res_ev.status_code == 200
            ev_data = res_ev.json()
            error_codes = [e["error_code"] for e in ev_data["events"]]
            assert test_event_code in error_codes, f"Expected event {test_event_code} in retrieved events"

    finally:
        # The rows go into the live database: left there, a running monitor would read 199.5 °C as
        # the bench's latest discharge temperature and open an incident.
        async with real_db.pool.connection() as conn:
            await conn.execute("DELETE FROM metrics WHERE machine_id = %s AND metric = %s AND value IN (182.0, 185.0, 199.5)",
                               (test_machine, test_metric))
            await conn.execute("DELETE FROM events WHERE error_code = %s", (test_event_code,))
        # Cleanup and restore
        db_module.db_manager = original_db
        tools_module.db_manager = original_db
        app.state.db = original_db
        await real_db.disconnect()
