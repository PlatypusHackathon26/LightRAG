import pytest
from datetime import datetime, timezone
from app.commands import validate_command_guardrails
from app.config import settings
from app.gateway.lifecycle import IncidentLifecycleManager
from app.gateway.actions import ActionService
from app.db import DatabaseManager

def test_guardrails_whitelist():
    # Whitelist is SET_RPM and STOP_TEST
    valid_rpm, _ = validate_command_guardrails(
        machine_id="COMP-TB-01",
        command="SET_RPM",
        params={"rpm": 1500},
        current_rpm=2000,
    )
    assert valid_rpm is True

    valid_stop, _ = validate_command_guardrails(
        machine_id="COMP-TB-01",
        command="STOP_TEST",
        params={},
        current_rpm=2000,
    )
    assert valid_stop is True

    invalid_cmd, reason = validate_command_guardrails(
        machine_id="COMP-TB-01",
        command="REBOOT_SYSTEM",
        params={},
        current_rpm=2000,
    )
    assert invalid_cmd is False
    assert "whitelist" in reason.lower()

def test_guardrails_speed_decrease_and_limits():
    # Attempt to increase speed: current 2000 -> 2500
    valid_inc, reason_inc = validate_command_guardrails(
        machine_id="COMP-TB-01",
        command="SET_RPM",
        params={"rpm": 2500},
        current_rpm=2000,
    )
    assert valid_inc is False
    assert "chỉ được phép giảm" in reason_inc or "giảm tốc độ" in reason_inc

    # Attempt to set below rpm_min_safe (800)
    valid_low, reason_low = validate_command_guardrails(
        machine_id="COMP-TB-01",
        command="SET_RPM",
        params={"rpm": 500},
        current_rpm=2000,
    )
    assert valid_low is False
    assert "an toàn tối thiểu" in reason_low

    # Attempt above max (3000)
    valid_high, reason_high = validate_command_guardrails(
        machine_id="COMP-TB-01",
        command="SET_RPM",
        params={"rpm": 3200},
        current_rpm=3500,
    )
    assert valid_high is False
    assert "tối đa" in reason_high

def test_stop_test_requires_human_approval_in_auto_safe():
    # STOP_TEST in auto_safe cannot be auto-executed
    valid, reason = validate_command_guardrails(
        machine_id="COMP-TB-01",
        command="STOP_TEST",
        params={},
        current_rpm=1000,
        is_auto=True,
    )
    assert valid is False
    assert "phê duyệt" in reason.lower() or "hitl" in reason.lower()

@pytest.mark.asyncio
async def test_action_ttl_expiration():
    db = DatabaseManager()
    action_svc = ActionService(db=db)
    lm = IncidentLifecycleManager(db=db, action_service=action_svc)
    
    # Ingest event with metrics to match condenser_fan_failure playbook
    now = datetime.now(timezone.utc)
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
    assert inc is not None
    action = await db.get_pending_action_for_incident(inc["id"])
    assert action is not None
    
    # Update action expires_at in DB
    past_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await db.update_action(action["id"], {"expires_at": past_date})
    
    # Run _check_expired_actions
    await lm._check_expired_actions()
    
    updated_act = await db.get_action(action["id"])
    assert updated_act["status"] == "expired"

@pytest.mark.asyncio
async def test_idempotent_double_approval():
    from unittest.mock import AsyncMock
    import app.gateway.actions as act_mod
    
    db = DatabaseManager()
    action_svc = ActionService(db=db)
    lm = IncidentLifecycleManager(db=db, action_service=action_svc)
    
    now = datetime.now(timezone.utc)
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
    action = await db.get_pending_action_for_incident(inc["id"])
    assert action is not None
    
    # Mock command dispatcher
    mock_dispatcher = AsyncMock()
    mock_dispatcher.dispatch_command = AsyncMock(return_value={"status": "OK", "code": 200, "machine_id": "COMP-TB-01"})
    
    orig_dispatcher = act_mod.command_dispatcher
    act_mod.command_dispatcher = mock_dispatcher
    try:
        # First approval
        res1 = await action_svc.approve_action(action["id"], actor="operator_lan")
        assert res1["ack"].startswith("ACK")
        assert mock_dispatcher.dispatch_command.call_count == 1
        
        # Second approval (must be idempotent)
        res2 = await action_svc.approve_action(action["id"], actor="operator_lan")
        assert res2["ack"].startswith("ACK")
        assert mock_dispatcher.dispatch_command.call_count == 1
    finally:
        act_mod.command_dispatcher = orig_dispatcher

@pytest.mark.asyncio
async def test_auto_safe_limits_and_cooldown():
    from unittest.mock import AsyncMock
    import app.gateway.actions as act_mod
    
    db = DatabaseManager()
    action_svc = ActionService(db=db)
    lm = IncidentLifecycleManager(db=db, action_service=action_svc)
    
    mock_dispatcher = AsyncMock()
    mock_dispatcher.dispatch_command = AsyncMock(return_value={"status": "OK", "code": 200, "machine_id": "COMP-TB-01"})
    
    orig_dispatcher = act_mod.command_dispatcher
    act_mod.command_dispatcher = mock_dispatcher
    
    orig_mode = settings.AUTONOMY_MODE
    settings.AUTONOMY_MODE = "auto_safe"
    try:
        now = datetime.now(timezone.utc)
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
        assert inc is not None
        # Auto count should be 1
        count = await db.count_auto_actions_for_incident(inc["id"])
        assert count == 1
        assert mock_dispatcher.dispatch_command.call_count == 1
    finally:
        settings.AUTONOMY_MODE = orig_mode
        act_mod.command_dispatcher = orig_dispatcher

@pytest.mark.asyncio
async def test_agent_enabled_false():
    db = DatabaseManager()
    action_svc = ActionService(db=db)
    lm = IncidentLifecycleManager(db=db, action_service=action_svc)
    
    orig_enabled = settings.AGENT_ENABLED
    settings.AGENT_ENABLED = False
    try:
        now = datetime.now(timezone.utc)
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
        assert inc is not None
        # No pending action created when AGENT_ENABLED=False
        act = await db.get_pending_action_for_incident(inc["id"])
        assert act is None
    finally:
        settings.AGENT_ENABLED = orig_enabled
