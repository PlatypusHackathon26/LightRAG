import pytest
from app.config import load_machines_config
from simulator.model import SCENARIO_TARGETS, MachineSimulator


@pytest.fixture
def machine_sim():
    cfg = load_machines_config()
    m_cfg = cfg.machines["COMP-TB-01"]
    # Fast ramp and no noise for deterministic unit test
    sim = MachineSimulator(machine_config=m_cfg, default_scenario="normal", ramp_s=1.0, enable_noise=False)
    return sim


def test_simulator_scenarios_reach_targets(machine_sim):
    """Verify all 5 scenarios converge to their expected target values."""
    for sc, targets in SCENARIO_TARGETS.items():
        machine_sim.set_scenario(sc, current_sim_time=0.0, ramp_s=1.0)
        # Advance simulation sufficiently for first-order filter to settle (e.g. 50 steps of dt=2.0s)
        current_time = 0.0
        for _ in range(50):
            current_time += 2.0
            metrics, _ = machine_sim.step(dt=2.0, current_sim_time=current_time)

        for metric_name, expected_val in targets.items():
            actual_val = metrics[metric_name]
            assert abs(actual_val - expected_val) <= 0.8, (
                f"Scenario '{sc}' metric '{metric_name}' expected {expected_val}, got {actual_val}"
            )


def test_simulator_speed_sensitivity_response(machine_sim):
    """
    Lowering compressor_rpm by 500 reduces discharge_temp by ~20 C,
    discharge_pressure by ~3 bar, and vibration by ~1 mm/s.
    """
    machine_sim.set_scenario("condenser_fouled", current_sim_time=0.0, ramp_s=1.0)
    current_time = 0.0
    for _ in range(50):
        current_time += 2.0
        metrics_1500, _ = machine_sim.step(dt=2.0, current_sim_time=current_time)

    # Now reduce speed by 500 rpm (1500 -> 1000)
    success, code, msg = machine_sim.validate_and_apply_command("SET_RPM", {"rpm": 1000})
    assert success is True
    assert code == 200

    # Settle at 1000 RPM
    for _ in range(50):
        current_time += 2.0
        metrics_1000, _ = machine_sim.step(dt=2.0, current_sim_time=current_time)

    temp_drop = metrics_1500["discharge_temp"] - metrics_1000["discharge_temp"]
    press_drop = metrics_1500["discharge_pressure"] - metrics_1000["discharge_pressure"]
    vib_drop = metrics_1500["vibration"] - metrics_1000["vibration"]

    assert abs(temp_drop - 20.0) <= 1.0, f"Expected temp drop ~20, got {temp_drop}"
    assert abs(press_drop - 3.0) <= 0.5, f"Expected pressure drop ~3, got {press_drop}"
    assert abs(vib_drop - 1.0) <= 0.3, f"Expected vibration drop ~1, got {vib_drop}"


def test_simulator_command_validation(machine_sim):
    """Test safety guardrails for command execution."""
    # 1. Rejects increasing RPM (1500 -> 2000)
    ok, code, msg = machine_sim.validate_and_apply_command("SET_RPM", {"rpm": 2000})
    assert ok is False
    assert code == 400
    assert "Cannot increase" in msg

    # 2. Rejects below rpm_min_safe (safe min is 800)
    ok, code, msg = machine_sim.validate_and_apply_command("SET_RPM", {"rpm": 500})
    assert ok is False
    assert code == 400
    assert "below safe minimum" in msg

    # 3. Accepts decreasing RPM (1500 -> 1200)
    ok, code, msg = machine_sim.validate_and_apply_command("SET_RPM", {"rpm": 1200})
    assert ok is True
    assert code == 200
    assert machine_sim.compressor_rpm == 1200.0

    # 4. Accepts STOP_TEST
    ok, code, msg = machine_sim.validate_and_apply_command("STOP_TEST", {})
    assert ok is True
    assert code == 200
    assert machine_sim.compressor_rpm == 0.0

    # 5. Rejects unsupported commands
    ok, code, msg = machine_sim.validate_and_apply_command("OVERCLOCK", {"speed": 9999})
    assert ok is False
    assert code == 400


def test_plc_error_events_trigger_on_critical_consecutive(machine_sim):
    """Test PLC triggers ERROR when critical reached 2 consecutive samples and emits UUID."""
    machine_sim.set_scenario("refrigerant_leak", current_sim_time=0.0, ramp_s=0.1)
    current_time = 0.0

    # Step until critical condition is met
    events_collected = []
    for _ in range(30):
        current_time += 1.0
        metrics, events = machine_sim.step(dt=1.0, current_sim_time=current_time)
        if events:
            events_collected.extend(events)

    assert len(events_collected) > 0
    # In refrigerant leak, suction pressure <= 1.0 triggers ERR_COMP_LOWPRESS_310
    # and discharge_temp >= 120 triggers ERR_COMP_OVERHEAT_402
    codes = [e["error_code"] for e in events_collected]
    assert "ERR_COMP_LOWPRESS_310" in codes or "ERR_COMP_OVERHEAT_402" in codes
    for e in events_collected:
        assert e["source"] == "machine"
        assert e["event_type"] == "ERROR"
        assert e["severity"] == "CRITICAL"
        assert "event_id" in e
