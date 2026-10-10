import pytest
from app.config import MetricConfig
from app.monitor import ThresholdMonitorLogic


def test_monitor_warn_consecutive_3_samples_trigger():
    """Monitor does not alert on 1 or 2 violations, but triggers on 3 consecutive violations."""
    monitor = ThresholdMonitorLogic(warn_trigger_samples=3, clear_hysteresis_samples=6)
    conf = MetricConfig(
        label="Nhiệt độ đầu xả",
        unit="°C",
        direction="above",
        normal_min=70.0,
        normal_max=100.0,
        warn=105.0,
        critical=120.0,
    )
    m_id = "COMP-TB-01"
    metric_name = "discharge_temp"

    # Sample 1: 106.0 (violation 1) -> no alarm
    s1 = [(0.0, 106.0)]
    r1 = monitor.analyze_series(m_id, metric_name, conf, s1)
    assert r1.is_in_alarm is False
    assert r1.should_emit_warning is False

    # Sample 2: 107.0 (violation 2) -> no alarm
    s2 = [(0.0, 106.0), (5.0, 107.0)]
    r2 = monitor.analyze_series(m_id, metric_name, conf, s2)
    assert r2.is_in_alarm is False
    assert r2.should_emit_warning is False

    # Sample 3: 108.0 (violation 3) -> ALARM triggered!
    s3 = [(0.0, 106.0), (5.0, 107.0), (10.0, 108.0)]
    r3 = monitor.analyze_series(m_id, metric_name, conf, s3)
    assert r3.is_in_alarm is True
    assert r3.should_emit_warning is True
    assert r3.warning_code == "WARN_DISCHARGE_TEMP_HIGH"


def test_monitor_hysteresis_requires_6_normal_samples_to_clear():
    """Once in alarm, status does not clear on 1-5 normal samples; clears only after 6 consecutive normals."""
    monitor = ThresholdMonitorLogic(warn_trigger_samples=3, clear_hysteresis_samples=6)
    conf = MetricConfig(
        label="Áp suất hút",
        unit="bar",
        direction="below",
        normal_min=1.8,
        normal_max=3.0,
        warn=1.5,
        critical=1.0,
    )
    m_id = "COMP-TB-01"
    metric_name = "suction_pressure"

    # Trigger alarm with 3 violating samples (<= 1.5)
    samples = [(0.0, 1.4), (5.0, 1.3), (10.0, 1.2)]
    res = monitor.analyze_series(m_id, metric_name, conf, samples)
    assert res.is_in_alarm is True

    # Now provide normal samples (e.g. 2.0 bar)
    t = 15.0
    for i in range(1, 6):
        t += 5.0
        samples.append((t, 2.0))
        r = monitor.analyze_series(m_id, metric_name, conf, samples)
        # Should still be in alarm through sample 1..5 of normal!
        assert r.is_in_alarm is True, f"Alarm unexpectedly cleared at normal sample {i}"

    # 6th normal sample: must now clear!
    t += 5.0
    samples.append((t, 2.0))
    r6 = monitor.analyze_series(m_id, metric_name, conf, samples)
    assert r6.is_in_alarm is False, "Alarm should have cleared after 6 consecutive normal samples"


def test_monitor_slope_and_eta_linear_series():
    """Verify linear regression slope calculation and ETA to critical."""
    monitor = ThresholdMonitorLogic()
    conf = MetricConfig(
        label="Nhiệt độ đầu xả",
        unit="°C",
        direction="above",
        normal_min=70.0,
        normal_max=100.0,
        warn=105.0,
        critical=120.0,
    )
    # Series increasing by 1.0 deg C every 10 seconds (0.1 deg C/sec = 6.0 deg C/min)
    # Starting at 100.0 deg C at t=0, at t=100s it is 110.0 deg C.
    samples = [(float(i * 10), 100.0 + float(i)) for i in range(11)]  # t: 0..100, v: 100..110
    res = monitor.analyze_series("COMP-TB-01", "discharge_temp", conf, samples)

    assert res.trend == "rising"
    assert abs(res.slope_per_min - 6.0) <= 0.05

    # At t=100, current value is 110.0 C.
    # Critical is 120.0 C.
    # Remaining difference is 10.0 C.
    # Rate is 0.1 C/s.
    # Expected ETA is 10.0 / 0.1 = 100.0 seconds!
    assert res.eta_to_critical_s is not None
    assert abs(res.eta_to_critical_s - 100.0) <= 1.0
