import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import db_manager
from app.gateway.lifecycle import IncidentLifecycleManager
from app.gateway.actions import action_service

@pytest.mark.asyncio
async def test_machine_incident_grouping():
    db = db_manager
    action_svc = action_service
    action_svc.db = db
    lm = IncidentLifecycleManager(db=db, action_service=action_svc)
    
    # Event 1 on COMP-TB-01 creates INC-0001
    await lm.handle_inbound_event({
        "event_type": "WARNING",
        "machine_id": "COMP-TB-01",
        "error_code": "WARN_TEMP",
        "severity": "WARNING",
        "message": "Temp elevated",
    })
    inc1 = await db.get_open_incident("COMP-TB-01")
    assert inc1 is not None
    assert inc1["machine_id"] == "COMP-TB-01"
    
    # Event 2 on COMP-TB-01 merges into existing incident
    await lm.handle_inbound_event({
        "event_type": "ERROR",
        "machine_id": "COMP-TB-01",
        "error_code": "ERR_TEMP",
        "severity": "CRITICAL",
        "message": "Temp critical",
    })
    inc2 = await db.get_open_incident("COMP-TB-01")
    assert inc2["id"] == inc1["id"]
    
    # Event 3 on COMP-TB-02 creates separate incident
    await lm.handle_inbound_event({
        "event_type": "WARNING",
        "machine_id": "COMP-TB-02",
        "error_code": "WARN_PRESS",
        "severity": "WARNING",
        "message": "Pressure low",
    })
    inc3 = await db.get_open_incident("COMP-TB-02")
    assert inc3 is not None
    assert inc3["id"] != inc1["id"]
    assert inc3["machine_id"] == "COMP-TB-02"

@pytest.mark.asyncio
async def test_gateway_rest_endpoints():
    db = db_manager
    action_svc = action_service
    action_svc.db = db
    lm = IncidentLifecycleManager(db=db, action_service=action_svc)
    
    await lm.handle_inbound_event({
        "event_type": "ERROR",
        "machine_id": "COMP-TB-01",
        "error_code": "ERR_COND_FAN_217",
        "severity": "CRITICAL",
        "message": "Condenser fan stopped",
    })
    inc = await db.get_open_incident("COMP-TB-01")
    assert inc is not None
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # GET /agent/incidents
        res = await ac.get("/agent/incidents")
        assert res.status_code == 200
        data = res.json()
        assert any(i["id"] == inc["id"] for i in data)
        
        # GET /agent/telemetry/COMP-TB-01
        res_tel = await ac.get("/agent/telemetry/COMP-TB-01")
        assert res_tel.status_code == 200
        snapshot = res_tel.json()
        assert "points" in snapshot
        assert len(snapshot["points"]) > 0
        assert "direction" in snapshot["points"][0]
        
        # Also test telemetry lookup via incident ID (WebUI contract compatibility)
        res_tel_inc = await ac.get(f"/agent/telemetry/{inc['id']}")
        assert res_tel_inc.status_code == 200
        
        # POST /agent/chat
        res_chat = await ac.post("/agent/chat", json={
            "message": "Tình trạng sự cố hiện tại thế nào?",
            "conversationId": f"CONV-{inc['id'].replace('INC-', '')}",
        })
        assert res_chat.status_code == 200
        chat_data = res_chat.json()
        assert "phân tích theo luật" in chat_data["content"].lower() or "rule-based" in chat_data["content"].lower()

@pytest.mark.asyncio
async def test_end_to_end_closed_loop():
    from unittest.mock import AsyncMock
    import app.gateway.actions as act_mod
    
    db = db_manager
    action_svc = action_service
    action_svc.db = db
    lm = IncidentLifecycleManager(db=db, action_service=action_svc)
    
    # 1. Fault inject event with metrics triggering a playbook proposal
    now = pytest.importorskip("datetime").datetime.now(pytest.importorskip("datetime").timezone.utc)
    await db.insert_metrics_batch([
        (now, "COMP-TB-01", "discharge_temp", 128.0),
        (now, "COMP-TB-01", "condenser_fan_rpm", 0.0),
        (now, "COMP-TB-01", "discharge_pressure", 24.0),
    ])
    
    await lm.handle_inbound_event({
        "event_type": "ERROR",
        "machine_id": "COMP-TB-01",
        "error_code": "ERR_COND_FAN_217",
        "severity": "CRITICAL",
        "message": "Condenser fan stopped",
    })
    
    inc = await db.get_open_incident("COMP-TB-01")
    act = await db.get_pending_action_for_incident(inc["id"])
    assert act is not None
    assert act["status"] == "pending"
    
    # 2. Operator approves action
    mock_dispatcher = AsyncMock()
    mock_dispatcher.dispatch_command = AsyncMock(return_value={
        "status": "OK",
        "code": 200,
        "command": act["command"],
        "machine_id": "COMP-TB-01",
        "message": "Applied successfully",
    })
    
    orig_dispatcher = act_mod.command_dispatcher
    act_mod.command_dispatcher = mock_dispatcher
    try:
        res = await action_svc.approve_action(action_id=act["id"], actor="operator_lan")
        assert res["ack"].startswith("ACK")
        
        # 3. Telemetry recovery: insert normal telemetry into db
        normal_batch = [
            (now, "COMP-TB-01", "discharge_temp", 80.0),
            (now, "COMP-TB-01", "suction_pressure", 2.1),
            (now, "COMP-TB-01", "discharge_pressure", 15.0),
            (now, "COMP-TB-01", "motor_current", 18.0),
            (now, "COMP-TB-01", "vibration", 1.2),
            (now, "COMP-TB-01", "oil_level", 75.0),
            (now, "COMP-TB-01", "condenser_fan_rpm", 1200.0),
            (now, "COMP-TB-01", "compressor_rpm", 1000.0),
        ]
        await db.insert_metrics_batch(normal_batch)
        
        # Check incident auto mitigation/resolution in background cycle
        await lm._check_incident_auto_mitigation()
        
        updated_inc = await db.get_incident(inc["id"])
        assert updated_inc["status"] in ("resolved", "acknowledged")
    finally:
        act_mod.command_dispatcher = orig_dispatcher
