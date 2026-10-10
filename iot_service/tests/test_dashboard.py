import asyncio
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import db_manager
from app.main import app
from app.stream import EventBroadcaster, broadcaster


@pytest.fixture(autouse=True)
def reset_db_and_settings():
    db_manager._mem_metrics.clear()
    db_manager._mem_events.clear()
    db_manager._mem_incidents.clear()
    db_manager._mem_actions.clear()
    db_manager._mem_audit_log.clear()
    settings.DASHBOARD_TOKEN = ""
    settings.AUTONOMY_MODE = "hitl"
    settings.AGENT_ENABLED = True
    settings.AGENT_MODE = "rules"


@pytest.mark.asyncio
async def test_dashboard_static_page_served():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/dashboard/")
        assert resp.status_code == 200
        assert "DENSO · Giám sát Bệ thử Máy nén" in resp.text
        assert "chart.umd.min.js" in resp.text


@pytest.mark.asyncio
async def test_dashboard_overview_aggregation():
    now = datetime.now(timezone.utc)
    # Seed metrics for COMP-TB-01 (warning: discharge_temp=110, warn=105, crit=120)
    batch = [
        (now, "COMP-TB-01", "discharge_temp", 110.0),
        (now, "COMP-TB-01", "suction_pressure", 2.2),
        (now, "COMP-TB-01", "compressor_rpm", 1500.0),
        (now, "COMP-TB-02", "discharge_temp", 85.0),
        (now, "COMP-TB-02", "suction_pressure", 2.4),
    ]
    await db_manager.insert_metrics_batch(batch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200
        data = resp.json()

        assert "system" in data
        assert "machines" in data
        assert "agent_summary" in data
        assert len(data["machines"]) == 2

        # Check COMP-TB-01 has status 'warn'
        m1 = next(m for m in data["machines"] if m["machine_id"] == "COMP-TB-01")
        assert m1["overall_status"] == "warn"
        assert m1["is_online"] is True
        assert m1["metrics"]["discharge_temp"]["status"] == "warn"
        assert m1["metrics"]["discharge_temp"]["value"] == 110.0
        assert m1["metrics"]["discharge_temp"]["display_min"] == 50.0
        assert m1["metrics"]["discharge_temp"]["display_max"] == 150.0

        # Check COMP-TB-02 has status 'normal'
        m2 = next(m for m in data["machines"] if m["machine_id"] == "COMP-TB-02")
        assert m2["overall_status"] == "normal"
        assert m2["is_online"] is True


@pytest.mark.asyncio
async def test_dashboard_offline_detection():
    # Insert metric from 60 seconds ago (3 * 5s = 15s threshold)
    past_ts = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 60, tz=timezone.utc)
    batch = [
        (past_ts, "COMP-TB-01", "discharge_temp", 80.0),
    ]
    await db_manager.insert_metrics_batch(batch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200
        data = resp.json()
        m1 = next(m for m in data["machines"] if m["machine_id"] == "COMP-TB-01")
        assert m1["overall_status"] == "offline"
        assert m1["is_online"] is False
        assert m1["seconds_since_last_seen"] >= 60.0


@pytest.mark.asyncio
async def test_dashboard_machine_series_downsampling():
    now_sec = datetime.now(timezone.utc).timestamp()
    batch = []
    # Generate 60 points every second for COMP-TB-01
    for i in range(60):
        t = datetime.fromtimestamp(now_sec - (60 - i), tz=timezone.utc)
        batch.append((t, "COMP-TB-01", "discharge_temp", 80.0 + (i * 0.1)))
    await db_manager.insert_metrics_batch(batch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Request with step=5s
        resp = await ac.get("/api/v1/dashboard/machine/COMP-TB-01/series?minutes=5&step=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["machine_id"] == "COMP-TB-01"
        assert "discharge_temp" in data["series"]
        s_data = data["series"]["discharge_temp"]
        # Downsampled points should be approximately 60 / 5 = 12 points
        assert 10 <= len(s_data["points"]) <= 14
        assert s_data["warn"] == 105.0
        assert s_data["critical"] == 120.0


@pytest.mark.asyncio
async def test_dashboard_events_filtering():
    now = datetime.now(timezone.utc)
    ev1 = {
        "event_id": "ev-01",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine_id": "COMP-TB-01",
        "source": "machine",
        "event_type": "ERROR",
        "severity": "CRITICAL",
        "error_code": "ERR_COMP_OVERHEAT_402",
        "message": "Overheat alert",
    }
    ev2 = {
        "event_id": "ev-02",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine_id": "COMP-TB-02",
        "source": "monitor",
        "event_type": "WARNING",
        "severity": "MEDIUM",
        "error_code": "WARN_SUCTION_PRESSURE_LOW",
        "message": "Low pressure alert",
    }
    await db_manager.insert_or_dedup_event(ev1)
    await db_manager.insert_or_dedup_event(ev2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # All events
        r1 = await ac.get("/api/v1/dashboard/events")
        assert r1.status_code == 200
        assert r1.json()["total"] == 2

        # Filter by machine
        r2 = await ac.get("/api/v1/dashboard/events?machine=COMP-TB-01")
        assert r2.status_code == 200
        assert r2.json()["total"] == 1
        assert r2.json()["events"][0]["machine_id"] == "COMP-TB-01"

        # Filter by severity
        r3 = await ac.get("/api/v1/dashboard/events?severity=CRITICAL")
        assert r3.status_code == 200
        assert r3.json()["total"] == 1
        assert r3.json()["events"][0]["severity"] == "CRITICAL"


@pytest.mark.asyncio
async def test_dashboard_read_only_strictly_enforced():
    """Verifies that all dashboard routes reject non-GET methods with 405 Method Not Allowed."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # POST
        r_post1 = await ac.post("/api/v1/dashboard/overview")
        assert r_post1.status_code == 405

        r_post2 = await ac.post("/api/v1/dashboard/machine/COMP-TB-01/series")
        assert r_post2.status_code == 405

        r_post3 = await ac.post("/api/v1/dashboard/events")
        assert r_post3.status_code == 405

        r_post4 = await ac.post("/api/v1/stream")
        assert r_post4.status_code == 405

        r_post5 = await ac.post("/api/v1/dashboard/agent")
        assert r_post5.status_code == 405

        r_post6 = await ac.post("/api/v1/dashboard/agent/timeline?machine=COMP-TB-01")
        assert r_post6.status_code == 405

        # PUT
        r_put = await ac.put("/api/v1/dashboard/overview")
        assert r_put.status_code == 405

        # DELETE
        r_del = await ac.delete("/api/v1/dashboard/overview")
        assert r_del.status_code == 405


@pytest.mark.asyncio
async def test_dashboard_token_authentication():
    settings.DASHBOARD_TOKEN = "secret-denso-dashboard-2026"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Without token -> 401 Unauthorized
        r_no_token = await ac.get("/api/v1/dashboard/overview")
        assert r_no_token.status_code == 401

        # 2. With invalid token -> 401 Unauthorized
        r_bad_token = await ac.get("/api/v1/dashboard/overview", headers={"X-Dashboard-Token": "wrong-token"})
        assert r_bad_token.status_code == 401

        # 3. With valid header token -> 200 OK
        r_header_token = await ac.get("/api/v1/dashboard/overview", headers={"X-Dashboard-Token": "secret-denso-dashboard-2026"})
        assert r_header_token.status_code == 200

        # 4. With valid query param token (for SSE EventSource) -> 200 OK
        r_query_token = await ac.get("/api/v1/dashboard/overview?token=secret-denso-dashboard-2026")
        assert r_query_token.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_agent_status_and_mitigation():
    now = datetime.now(timezone.utc)
    # 1. Create open incident for COMP-TB-01
    inc_id = await db_manager.create_incident({
        "machine_id": "COMP-TB-01",
        "status": "awaiting_approval",
        "severity": "high",
        "title": "Thiếu môi chất lạnh nghi ngờ",
        "opened_at": now,
        "root_cause": "Thiếu môi chất lạnh (rò rỉ)",
        "confidence": 0.92,
    })

    # 2. Create pending action
    act_id = await db_manager.create_action({
        "incident_id": inc_id,
        "machine_id": "COMP-TB-01",
        "command": "SET_RPM",
        "params": {"rpm": 1000},
        "rationale": "Hạ tốc độ giảm tải hệ thống",
        "status": "pending",
        "proposed_at": now,
        "expires_at": datetime.fromtimestamp(now.timestamp() + 60, tz=timezone.utc),
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Check GET /dashboard/agent
        resp_agent = await ac.get("/api/v1/dashboard/agent")
        assert resp_agent.status_code == 200
        agent_data = resp_agent.json()
        assert agent_data["autonomy_mode"] == "hitl"
        assert agent_data["agent_enabled"] is True
        assert agent_data["counts_by_severity"]["high"] == 1
        assert len(agent_data["open_incidents"]) == 1
        assert agent_data["open_incidents"][0]["id"] == inc_id
        assert len(agent_data["recent_actions"]) == 1
        assert agent_data["recent_actions"][0]["id"] == act_id

        # Check GET /dashboard/overview includes open incident & pending action
        resp_ov = await ac.get("/api/v1/dashboard/overview")
        assert resp_ov.status_code == 200
        ov_data = resp_ov.json()
        m1 = next(m for m in ov_data["machines"] if m["machine_id"] == "COMP-TB-01")
        assert m1["open_incident"] is not None
        assert m1["open_incident"]["id"] == inc_id
        assert m1["pending_action"] is not None
        assert m1["pending_action"]["command"] == "SET_RPM"
        assert m1["is_mitigated"] is False

        # Now simulate action executed (mitigated state)
        await db_manager.update_action(act_id, {
            "status": "acked",
            "decided_by": "user:operator",
            "auto_executed": False,
            "ack": {"code": 200, "message": "Speed adjusted"},
        })
        # Add warning metric (discharge_temp=108, warn=105, crit=120) -> not critical
        await db_manager.insert_metrics_batch([(now, "COMP-TB-01", "discharge_temp", 108.0)])

        resp_ov2 = await ac.get("/api/v1/dashboard/overview")
        m1_after = next(m for m in resp_ov2.json()["machines"] if m["machine_id"] == "COMP-TB-01")
        assert m1_after["is_mitigated"] is True
        assert m1_after["latest_mitigation"] is not None
        assert "hạ tốc độ xuống 1000 rpm" in m1_after["latest_mitigation"]["summary"]


@pytest.mark.asyncio
async def test_dashboard_agent_timeline():
    now = datetime.now(timezone.utc)
    # Insert audit logs
    await db_manager.insert_audit_log(
        actor="agent",
        action="action_proposed",
        machine_id="COMP-TB-01",
        incident_id="INC-0001",
        details={"command": "SET_RPM", "params": {"rpm": 1000}},
    )
    await db_manager.insert_audit_log(
        actor="user:engineer",
        action="approve",
        machine_id="COMP-TB-01",
        incident_id="INC-0001",
        details={"command": "SET_RPM"},
    )
    await db_manager.insert_audit_log(
        actor="user:engineer",
        action="ack",
        machine_id="COMP-TB-01",
        incident_id="INC-0001",
        details={"code": 200, "message": "Success"},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/dashboard/agent/timeline?machine=COMP-TB-01&minutes=60")
        assert resp.status_code == 200
        data = resp.json()
        assert data["machine_id"] == "COMP-TB-01"
        assert len(data["timeline"]) == 3
        labels = [t["label"] for t in data["timeline"]]
        assert any("Agent đề xuất" in l for l in labels)
        assert any("Duyệt lệnh" in l for l in labels)
        assert any("ACK 200" in l for l in labels)


@pytest.mark.asyncio
async def test_sse_stream_initial_snapshot_and_broadcast():
    # Test broadcaster registration and snapshot generation directly
    custom_b = EventBroadcaster(max_clients=2, client_queue_size=5)
    q1 = await custom_b.register_client()
    assert q1 is not None

    # Broadcast incident update
    custom_b.broadcast_incident("created", {
        "id": "INC-0001",
        "machine_id": "COMP-TB-01",
        "status": "awaiting_approval",
        "severity": "critical",
        "title": "Quá nhiệt",
    })
    assert not q1.empty()
    item_inc = q1.get_nowait()
    assert item_inc["event"] == "incident"
    assert item_inc["data"]["incident_id"] == "INC-0001"

    # Broadcast action update
    custom_b.broadcast_action("approved", {
        "id": "ACT-0001",
        "incident_id": "INC-0001",
        "machine_id": "COMP-TB-01",
        "command": "SET_RPM",
        "status": "executing",
        "auto_executed": False,
        "decided_by": "user:operator",
    })
    assert not q1.empty()
    item_act = q1.get_nowait()
    assert item_act["event"] == "action"
    assert item_act["data"]["command"] == "SET_RPM"

    await custom_b.unregister_client(q1)
