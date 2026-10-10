from datetime import datetime, timezone
import pytest

from app.agent.rule_analyzer import RuleAnalyzer
from app.db import DatabaseManager


@pytest.fixture
def mock_db():
    return DatabaseManager()


@pytest.mark.asyncio
async def test_playbook_matching_refrigerant_leak(mock_db):
    analyzer = RuleAnalyzer("config/playbooks.yaml")
    machine_id = "COMP-TB-01"

    # Seed latest metrics simulating refrigerant_leak:
    # discharge_temp=126 (critical), suction_pressure=0.8 (critical), condenser_fan_rpm=2400 (normal)
    now = datetime.now(timezone.utc)
    batch = [
        (now, machine_id, "discharge_temp", 126.0),
        (now, machine_id, "suction_pressure", 0.8),
        (now, machine_id, "condenser_fan_rpm", 2400.0),
        (now, machine_id, "discharge_pressure", 11.5),
        (now, machine_id, "vibration", 3.8),
        (now, machine_id, "oil_level", 86.0),
        (now, machine_id, "compressor_rpm", 1500.0),
    ]
    await mock_db.insert_metrics_batch(batch)

    trigger_event = {
        "event_id": "test-ev-1",
        "machine_id": machine_id,
        "event_type": "ERROR",
        "severity": "CRITICAL",
        "error_code": "ERR_COMP_LOWPRESS_310",
        "message": "Suction pressure <= 1.0 bar",
    }

    res = await analyzer.analyze_incident(machine_id, trigger_event, mock_db)
    assert res.matched_playbook_id == "refrigerant_leak"
    assert "môi chất lạnh" in res.root_cause.lower()
    assert res.confidence >= 0.90
    assert res.severity == "critical"
    assert res.proposed_action is not None
    assert res.proposed_action.command == "SET_RPM"
    assert res.proposed_action.params["rpm"] == 1000
    assert len(res.citations) > 0
    assert any("Poster" in c["document_name"] for c in res.citations)


@pytest.mark.asyncio
async def test_playbook_matching_condenser_fan_failure(mock_db):
    analyzer = RuleAnalyzer("config/playbooks.yaml")
    machine_id = "COMP-TB-01"

    # Seed latest metrics simulating condenser_fan_failure:
    # discharge_temp=128 (critical), discharge_pressure=24.0 (critical), condenser_fan_rpm=0.0 (critical)
    now = datetime.now(timezone.utc)
    batch = [
        (now, machine_id, "discharge_temp", 128.0),
        (now, machine_id, "suction_pressure", 2.6),
        (now, machine_id, "condenser_fan_rpm", 0.0),
        (now, machine_id, "discharge_pressure", 24.0),
        (now, machine_id, "vibration", 3.2),
        (now, machine_id, "oil_level", 88.0),
        (now, machine_id, "compressor_rpm", 1500.0),
    ]
    await mock_db.insert_metrics_batch(batch)

    trigger_event = {
        "event_id": "test-ev-2",
        "machine_id": machine_id,
        "event_type": "ERROR",
        "severity": "CRITICAL",
        "error_code": "ERR_COND_FAN_217",
        "message": "Condenser fan stopped",
    }

    res = await analyzer.analyze_incident(machine_id, trigger_event, mock_db)
    assert res.matched_playbook_id == "condenser_fan_failure"
    assert "quạt" in res.root_cause.lower()
    assert res.confidence >= 0.90
    assert res.proposed_action is not None
    assert res.proposed_action.command == "SET_RPM"
    assert res.proposed_action.params["rpm"] == 1000
    assert any("Condenser" in c["document_name"] for c in res.citations)


@pytest.mark.asyncio
async def test_playbook_matching_condenser_fouled(mock_db):
    analyzer = RuleAnalyzer("config/playbooks.yaml")
    machine_id = "COMP-TB-01"

    # Seed metrics simulating condenser_fouled:
    # discharge_temp=112 (warn), discharge_pressure=21.5 (warn), condenser_fan_rpm=2300 (normal)
    now = datetime.now(timezone.utc)
    batch = [
        (now, machine_id, "discharge_temp", 112.0),
        (now, machine_id, "suction_pressure", 2.9),
        (now, machine_id, "condenser_fan_rpm", 2300.0),
        (now, machine_id, "discharge_pressure", 21.5),
        (now, machine_id, "vibration", 2.6),
        (now, machine_id, "oil_level", 88.0),
        (now, machine_id, "compressor_rpm", 1500.0),
    ]
    await mock_db.insert_metrics_batch(batch)

    trigger_event = {
        "event_id": "test-ev-3",
        "machine_id": machine_id,
        "event_type": "WARNING",
        "severity": "HIGH",
        "error_code": "WARN_DISCHARGE_PRESSURE_HIGH",
        "message": "Discharge pressure high",
    }

    res = await analyzer.analyze_incident(machine_id, trigger_event, mock_db)
    assert res.matched_playbook_id == "condenser_fouled"
    assert "dàn ngưng" in res.root_cause.lower() or "bụi bẩn" in res.root_cause.lower()
    assert res.proposed_action is not None
    assert res.proposed_action.command == "SET_RPM"
    assert res.proposed_action.params["rpm"] == 1000


@pytest.mark.asyncio
async def test_playbook_matching_low_oil(mock_db):
    analyzer = RuleAnalyzer("config/playbooks.yaml")
    machine_id = "COMP-TB-01"

    # Seed metrics simulating low_oil:
    # discharge_temp=122 (critical), oil_level=35 (critical), vibration=7.5 (critical)
    now = datetime.now(timezone.utc)
    batch = [
        (now, machine_id, "discharge_temp", 122.0),
        (now, machine_id, "suction_pressure", 2.3),
        (now, machine_id, "condenser_fan_rpm", 2400.0),
        (now, machine_id, "discharge_pressure", 15.0),
        (now, machine_id, "vibration", 7.5),
        (now, machine_id, "oil_level", 35.0),
        (now, machine_id, "compressor_rpm", 1500.0),
    ]
    await mock_db.insert_metrics_batch(batch)

    trigger_event = {
        "event_id": "test-ev-4",
        "machine_id": machine_id,
        "event_type": "ERROR",
        "severity": "CRITICAL",
        "error_code": "ERR_COMP_LOWOIL_118",
        "message": "Oil level critically low",
    }

    res = await analyzer.analyze_incident(machine_id, trigger_event, mock_db)
    assert res.matched_playbook_id == "low_oil"
    assert "dầu" in res.root_cause.lower()
    assert res.confidence >= 0.90
    assert res.proposed_action is not None
    assert res.proposed_action.command == "STOP_TEST"
    assert any("Installation-Manual" in c["document_name"] for c in res.citations)


@pytest.mark.asyncio
async def test_playbook_unmatched_fallback(mock_db):
    analyzer = RuleAnalyzer("config/playbooks.yaml")
    machine_id = "COMP-TB-01"

    # Normal metrics with an unexpected error code
    now = datetime.now(timezone.utc)
    batch = [
        (now, machine_id, "discharge_temp", 95.0),
        (now, machine_id, "suction_pressure", 2.4),
        (now, machine_id, "condenser_fan_rpm", 2400.0),
        (now, machine_id, "discharge_pressure", 14.5),
        (now, machine_id, "vibration", 2.2),
        (now, machine_id, "oil_level", 88.0),
        (now, machine_id, "compressor_rpm", 1500.0),
    ]
    await mock_db.insert_metrics_batch(batch)

    trigger_event = {
        "event_id": "test-ev-5",
        "machine_id": machine_id,
        "event_type": "WARNING",
        "severity": "MEDIUM",
        "error_code": "ERR_UNKNOWN_RANDOM_999",
        "message": "Unknown random glitch",
    }

    res = await analyzer.analyze_incident(machine_id, trigger_event, mock_db)
    assert res.matched_playbook_id is None
    assert res.root_cause == "Chưa xác định"
    assert res.confidence == 0.30
    assert res.proposed_action is None


@pytest.mark.asyncio
async def test_severity_mapping(mock_db):
    analyzer = RuleAnalyzer("config/playbooks.yaml")
    machine_id = "COMP-TB-01"

    # 1. ERROR or CRITICAL event -> critical
    res1 = await analyzer.analyze_incident(
        machine_id,
        {"event_type": "ERROR", "severity": "CRITICAL", "error_code": "ERR_COND_FAN_217"},
        mock_db,
    )
    assert res1.severity == "critical"

    # 2. WARNING with ETA < 300s -> high
    res2 = await analyzer.analyze_incident(
        machine_id,
        {
            "event_type": "WARNING",
            "severity": "HIGH",
            "error_code": "WARN_DISCHARGE_TEMP_HIGH",
            "payload": {"eta_to_critical_s": 120.0},
        },
        mock_db,
    )
    assert res2.severity == "high"

    # 3. WARNING with ETA >= 300s -> medium
    res3 = await analyzer.analyze_incident(
        machine_id,
        {
            "event_type": "WARNING",
            "severity": "MEDIUM",
            "error_code": "WARN_DISCHARGE_TEMP_HIGH",
            "payload": {"eta_to_critical_s": 450.0},
        },
        mock_db,
    )
    assert res3.severity == "medium"
