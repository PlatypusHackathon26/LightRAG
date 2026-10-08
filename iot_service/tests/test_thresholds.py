import pytest
from pydantic import ValidationError

from app.config import (
    MachineConfig,
    MetricConfig,
    evaluate_metric_status,
    load_machines_config,
)


def test_evaluate_status_above_direction():
    # discharge_temp: warn >= 105, critical >= 120
    metric = MetricConfig(
        label="Nhiệt độ đầu xả",
        unit="°C",
        direction="above",
        normal_min=70.0,
        normal_max=100.0,
        warn=105.0,
        critical=120.0,
    )

    # Normal values
    assert evaluate_metric_status(95.0, metric) == "normal"
    assert evaluate_metric_status(100.0, metric) == "normal"
    assert evaluate_metric_status(104.99, metric) == "normal"

    # Exactly at warn boundary (>= 105)
    assert evaluate_metric_status(105.0, metric) == "warn"
    assert evaluate_metric_status(110.0, metric) == "warn"
    assert evaluate_metric_status(119.99, metric) == "warn"

    # Exactly at critical boundary (>= 120) and above
    assert evaluate_metric_status(120.0, metric) == "critical"
    assert evaluate_metric_status(125.5, metric) == "critical"


def test_evaluate_status_below_direction():
    # suction_pressure: warn <= 1.5, critical <= 1.0
    metric = MetricConfig(
        label="Áp suất hút",
        unit="bar",
        direction="below",
        normal_min=1.8,
        normal_max=3.0,
        warn=1.5,
        critical=1.0,
    )

    # Normal values
    assert evaluate_metric_status(2.4, metric) == "normal"
    assert evaluate_metric_status(1.8, metric) == "normal"
    assert evaluate_metric_status(1.51, metric) == "normal"

    # Exactly at warn boundary (<= 1.5)
    assert evaluate_metric_status(1.5, metric) == "warn"
    assert evaluate_metric_status(1.2, metric) == "warn"
    assert evaluate_metric_status(1.01, metric) == "warn"

    # Exactly at critical boundary (<= 1.0) and below
    assert evaluate_metric_status(1.0, metric) == "critical"
    assert evaluate_metric_status(0.8, metric) == "critical"
    assert evaluate_metric_status(0.0, metric) == "critical"


def test_evaluate_status_info_direction():
    metric = MetricConfig(
        label="Tốc độ máy nén",
        unit="rpm",
        direction="info",
        normal_min=None,
        normal_max=None,
        warn=None,
        critical=None,
    )
    assert evaluate_metric_status(1500.0, metric) == "normal"
    assert evaluate_metric_status(0.0, metric) == "normal"
    assert evaluate_metric_status(3500.0, metric) == "normal"


def test_metric_config_validation():
    # Above: warn must be < critical
    with pytest.raises(ValidationError):
        MetricConfig(
            label="Test",
            unit="unit",
            direction="above",
            warn=120.0,
            critical=100.0,  # Invalid: warn >= critical
        )

    # Below: warn must be > critical
    with pytest.raises(ValidationError):
        MetricConfig(
            label="Test",
            unit="unit",
            direction="below",
            warn=1.0,
            critical=1.5,  # Invalid: warn <= critical
        )


def test_machine_config_rpm_validation():
    # rpm_min_safe cannot exceed rpm_max
    with pytest.raises(ValidationError):
        MachineConfig(
            name="TEST-01",
            rpm_setpoint=1500.0,
            rpm_min_safe=3500.0,
            rpm_max=3000.0,
            metrics={},
        )


def test_load_real_machines_config():
    cfg = load_machines_config()
    assert "COMP-TB-01" in cfg.machines
    assert "COMP-TB-02" in cfg.machines
    m1 = cfg.machines["COMP-TB-01"]
    assert len(m1.metrics) == 7
    assert m1.metrics["discharge_temp"].direction == "above"
    assert m1.metrics["suction_pressure"].direction == "below"
    assert m1.metrics["compressor_rpm"].direction == "info"
