from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import db_manager
from app.main import app


@pytest.fixture(autouse=True)
async def seed_test_data():
    # Insert some sample metrics for COMP-TB-01
    now = datetime.now(timezone.utc)
    batch = [
        (now, "COMP-TB-01", "discharge_temp", 95.5),
        (now, "COMP-TB-01", "suction_pressure", 2.3),
        (now, "COMP-TB-01", "discharge_pressure", 14.2),
        (now, "COMP-TB-01", "condenser_fan_rpm", 2400.0),
        (now, "COMP-TB-01", "vibration", 2.1),
        (now, "COMP-TB-01", "oil_level", 88.0),
        (now, "COMP-TB-01", "compressor_rpm", 1500.0),
    ]
    await db_manager.insert_metrics_batch(batch)


@pytest.mark.asyncio
async def test_auth_headers():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing key -> 401
        res = await client.get("/api/v1/machines")
        assert res.status_code == 401

        # Invalid key -> 401
        res = await client.get("/api/v1/machines", headers={"X-API-Key": "wrong-key"})
        assert res.status_code == 401

        # Valid key -> 200
        res = await client.get("/api/v1/machines", headers={"X-API-Key": settings.IOT_API_KEY})
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_get_machines_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/machines", headers={"X-API-Key": settings.IOT_API_KEY})
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        machine_ids = [m["machine_id"] for m in data["machines"]]
        assert "COMP-TB-01" in machine_ids
        assert "COMP-TB-02" in machine_ids
        assert "summary" in data
        assert "Hệ thống có 2 bệ thử" in data["summary"]


@pytest.mark.asyncio
async def test_get_current_status_all_7_metrics():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/machine/COMP-TB-01/current-status",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["machine_id"] == "COMP-TB-01"
        assert len(data["metrics"]) == 7
        for m_name in [
            "discharge_temp",
            "suction_pressure",
            "discharge_pressure",
            "condenser_fan_rpm",
            "vibration",
            "oil_level",
            "compressor_rpm",
        ]:
            assert m_name in data["metrics"]
            item = data["metrics"][m_name]
            assert "value" in item
            assert "unit" in item
            assert "label" in item
            assert "status" in item
            assert "direction" in item
            assert item["status"] == "normal"
        assert "summary" in data
        assert "bình thường" in data["summary"]


@pytest.mark.asyncio
async def test_get_current_status_unknown_machine_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/machine/COMP-NONEXISTENT/current-status",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_status_at_time():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = await client.get(
            f"/api/v1/machine/COMP-TB-01/status?at={now_iso}",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["machine_id"] == "COMP-TB-01"
        assert "time_skew_s" in data["metrics"]["discharge_temp"]
        assert "summary" in data

        # Invalid timestamp format -> 422
        res_bad = await client.get(
            "/api/v1/machine/COMP-TB-01/status?at=invalid-date",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res_bad.status_code == 422


@pytest.mark.asyncio
async def test_get_history():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/machine/COMP-TB-01/history?minutes=10",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["machine_id"] == "COMP-TB-01"
        assert "discharge_temp" in data["metrics"]
        dt = data["metrics"]["discharge_temp"]
        assert "slope_per_min" in dt
        assert "trend" in dt
        assert "eta_to_critical_s" in dt
        assert "summary" in data


@pytest.mark.asyncio
async def test_get_events():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/machine/COMP-TB-01/events?minutes=60",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res.status_code == 200
        data = res.json()
        assert "events" in data
        assert "summary" in data


@pytest.mark.asyncio
async def test_health_check_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "database" in data
        assert "mqtt" in data
        if data["database"] == "in_memory":
            assert data["status"] == "degraded"
        else:
            assert data["status"] == "ok"
