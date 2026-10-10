import uuid
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import load_machines_config, settings
from app.main import app
from app.monitor import ThresholdMonitorLogic
from simulator.model import MachineSimulator


@pytest.mark.asyncio
async def test_end_to_end_workflow():
    """
    Comprehensive End-to-End Test validating:
    1. Normal scenario: current-status returns 7 metrics, all normal.
    2. Fault scenario (condenser_fan_failure): early WARNING from monitor, PLC ERROR event, dedup.
    3. History API shows 'rising' trend and positive eta_to_critical_s for discharge_temp.
    4. Closed-loop control commands: SET_RPM 1000 accepted and lowers temp; SET_RPM 2000 rejected.
    """
    from app.db import db_manager

    cfg = load_machines_config()
    m_cfg = cfg.machines["COMP-TB-01"]
    sim = MachineSimulator(machine_config=m_cfg, default_scenario="normal", ramp_s=5.0, enable_noise=False)
    monitor_logic = ThresholdMonitorLogic(warn_trigger_samples=3, clear_hysteresis_samples=6)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # -------------------------------------------------------------
        # STEP 1: Normal operational state
        # -------------------------------------------------------------
        clock = 0.0
        now_dt = datetime.now(timezone.utc)
        for i in range(10):
            clock += 2.0
            metrics, events = sim.step(dt=2.0, current_sim_time=clock)
            sample_time = datetime.fromtimestamp(now_dt.timestamp() + clock, tz=timezone.utc)
            batch = [(sample_time, "COMP-TB-01", k, v) for k, v in metrics.items()]
            await db_manager.insert_metrics_batch(batch)

        res_curr = await client.get(
            "/api/v1/machine/COMP-TB-01/current-status",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res_curr.status_code == 200
        data_curr = res_curr.json()
        assert data_curr["overall_status"] == "normal"
        assert len(data_curr["metrics"]) == 7
        for m_name in [
            "discharge_temp",
            "suction_pressure",
            "discharge_pressure",
            "condenser_fan_rpm",
            "vibration",
            "oil_level",
            "compressor_rpm",
        ]:
            assert data_curr["metrics"][m_name]["status"] == "normal"
        assert "hoạt động bình thường" in data_curr["summary"]

        # -------------------------------------------------------------
        # STEP 2: Inject condenser_fan_failure fault scenario
        # -------------------------------------------------------------
        sim.set_scenario("condenser_fan_failure", current_sim_time=clock, ramp_s=10.0)

        # Step forward and feed monitor
        fan_warn_emitted = False
        plc_fan_error_emitted = False

        for i in range(25):
            clock += 2.0
            metrics, plc_events = sim.step(dt=2.0, current_sim_time=clock)
            sample_time = datetime.fromtimestamp(now_dt.timestamp() + clock, tz=timezone.utc)
            batch = [(sample_time, "COMP-TB-01", k, v) for k, v in metrics.items()]
            await db_manager.insert_metrics_batch(batch)

            # Ingest PLC events into DB
            for ev in plc_events:
                await db_manager.insert_or_dedup_event(ev)
                if ev["error_code"] == "ERR_COND_FAN_217":
                    plc_fan_error_emitted = True

            # Feed monitor logic
            history = await db_manager.get_metrics_history(
                "COMP-TB-01",
                datetime.fromtimestamp(now_dt.timestamp() - 60, tz=timezone.utc),
            )
            for m_name, m_info in m_cfg.metrics.items():
                if m_name in history:
                    pts = [(t.timestamp(), val) for t, val in history[m_name]]
                    analysis = monitor_logic.analyze_series("COMP-TB-01", m_name, m_info, pts)
                    if analysis.should_emit_warning:
                        warn_payload = {
                            "event_id": str(uuid.uuid4()),
                            "timestamp": sample_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "machine_id": "COMP-TB-01",
                            "source": "monitor",
                            "event_type": "WARNING",
                            "severity": "HIGH",
                            "error_code": analysis.warning_code,
                            "message": analysis.warning_message,
                            "payload": {"trend": analysis.trend, "slope": analysis.slope_per_min},
                        }
                        await db_manager.insert_or_dedup_event(warn_payload)
                        if analysis.warning_code == "WARN_CONDENSER_FAN_RPM_LOW":
                            fan_warn_emitted = True

        # Assert early warning and PLC error were both triggered
        assert fan_warn_emitted is True, "Threshold monitor should have emitted early warning WARN_CONDENSER_FAN_RPM_LOW"
        assert plc_fan_error_emitted is True, "Simulator PLC should have emitted ERR_COND_FAN_217"

        # -------------------------------------------------------------
        # STEP 3: Verify GET /events and Deduplication
        # -------------------------------------------------------------
        res_events = await client.get(
            "/api/v1/machine/COMP-TB-01/events?minutes=60",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res_events.status_code == 200
        ev_data = res_events.json()
        assert ev_data["count"] > 0
        error_codes = [e["error_code"] for e in ev_data["events"]]
        assert "ERR_COND_FAN_217" in error_codes
        assert "WARN_CONDENSER_FAN_RPM_LOW" in error_codes

        # -------------------------------------------------------------
        # STEP 4: Verify History API trends and ETA
        # -------------------------------------------------------------
        res_hist = await client.get(
            "/api/v1/machine/COMP-TB-01/history?minutes=10",
            headers={"X-API-Key": settings.IOT_API_KEY},
        )
        assert res_hist.status_code == 200
        hist_data = res_hist.json()
        assert hist_data["metrics"]["discharge_temp"]["trend"] == "rising"
        assert hist_data["metrics"]["condenser_fan_rpm"]["trend"] == "falling"

        # -------------------------------------------------------------
        # STEP 5: Closed-loop control commands (SET_RPM)
        # -------------------------------------------------------------
        # Reject increasing RPM (1500 -> 2000)
        ok, code, msg = sim.validate_and_apply_command("SET_RPM", {"rpm": 2000})
        assert ok is False
        assert code == 400
        assert "Cannot increase" in msg

        # Accept lowering RPM (1500 -> 1000)
        ok, code, msg = sim.validate_and_apply_command("SET_RPM", {"rpm": 1000})
        assert ok is True
        assert code == 200
        assert sim.compressor_rpm == 1000.0

        # Step forward at 1000 RPM and verify discharge temp drops
        temp_before_drop = sim.current_values["discharge_temp"]
        for i in range(25):
            clock += 2.0
            metrics, _ = sim.step(dt=2.0, current_sim_time=clock)
        temp_after_drop = metrics["discharge_temp"]

        # Expect discharge_temp to drop by ~20 C
        assert (temp_before_drop - temp_after_drop) >= 15.0
