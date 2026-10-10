import math
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import MachineConfig

SCENARIO_TARGETS: Dict[str, Dict[str, float]] = {
    "normal": {
        "discharge_temp": 95.0,
        "suction_pressure": 2.4,
        "discharge_pressure": 14.5,
        "condenser_fan_rpm": 2400.0,
        "vibration": 2.2,
        "oil_level": 88.0,
    },
    "refrigerant_leak": {
        "discharge_temp": 126.0,
        "suction_pressure": 0.8,
        "discharge_pressure": 11.5,
        "condenser_fan_rpm": 2400.0,
        "vibration": 3.8,
        "oil_level": 86.0,
    },
    "condenser_fan_failure": {
        "discharge_temp": 128.0,
        "suction_pressure": 2.6,
        "discharge_pressure": 24.0,
        "condenser_fan_rpm": 0.0,
        "vibration": 3.2,
        "oil_level": 88.0,
    },
    "condenser_fouled": {
        "discharge_temp": 112.0,
        "suction_pressure": 2.9,
        "discharge_pressure": 21.5,
        "condenser_fan_rpm": 2300.0,
        "vibration": 2.6,
        "oil_level": 88.0,
    },
    "low_oil": {
        "discharge_temp": 122.0,
        "suction_pressure": 2.3,
        "discharge_pressure": 15.0,
        "condenser_fan_rpm": 2400.0,
        "vibration": 7.5,
        "oil_level": 35.0,
    },
}

# PLC Error codes and triggers from BRIEF section 5
PLC_ERROR_SPECS = [
    {
        "code": "ERR_COMP_OVERHEAT_402",
        "metric": "discharge_temp",
        "check": lambda m: m["discharge_temp"] >= 120.0,
        "message": "Discharge temperature exceeded 120 C",
    },
    {
        "code": "ERR_COMP_LOWPRESS_310",
        "metric": "suction_pressure",
        "check": lambda m: m["suction_pressure"] <= 1.0,
        "message": "Suction pressure dropped below 1.0 bar",
    },
    {
        "code": "ERR_COMP_HIGHPRESS_325",
        "metric": "discharge_pressure",
        "check": lambda m: m["discharge_pressure"] >= 23.0,
        "message": "Discharge pressure exceeded 23.0 bar",
    },
    {
        "code": "ERR_COND_FAN_217",
        "metric": "condenser_fan_rpm",
        "check": lambda m: m["condenser_fan_rpm"] <= 500.0 and m["compressor_rpm"] > 0,
        "message": "Condenser fan speed fell below 500 rpm while running",
    },
    {
        "code": "ERR_COMP_LOWOIL_118",
        "metric": "oil_level",
        "check": lambda m: m["oil_level"] <= 40.0,
        "message": "Oil level fell below 40%",
    },
    {
        "code": "ERR_COMP_VIB_505",
        "metric": "vibration",
        "check": lambda m: m["vibration"] >= 7.0,
        "message": "Compressor vibration exceeded 7.0 mm/s",
    },
]


class MachineSimulator:
    def __init__(
        self,
        machine_config: MachineConfig,
        default_scenario: str = "normal",
        ramp_s: float = 180.0,
        enable_noise: bool = True,
    ):
        self.config = machine_config
        self.machine_id = machine_config.name
        self.compressor_rpm = float(machine_config.rpm_setpoint)
        self.is_running = True
        self.enable_noise = enable_noise
        self.default_ramp_s = ramp_s

        self.scenario = default_scenario
        self.target_scenario = default_scenario
        self.scenario_start_time = 0.0
        self.ramp_duration_s = ramp_s
        self.from_targets = self._calculate_targets("normal", self.compressor_rpm)

        # Initialize current state to normal targets
        self.current_values: Dict[str, float] = self._calculate_targets("normal", self.compressor_rpm).copy()

        # PLC tracking: consecutive critical violations count and last emitted time
        self.plc_consecutive_counts: Dict[str, int] = {spec["code"]: 0 for spec in PLC_ERROR_SPECS}
        self.plc_last_emit_time: Dict[str, float] = {spec["code"]: -999.0 for spec in PLC_ERROR_SPECS}

    def _calculate_targets(self, scenario: str, rpm: float) -> Dict[str, float]:
        base = SCENARIO_TARGETS.get(scenario, SCENARIO_TARGETS["normal"]).copy()
        if rpm <= 0:
            # Compressor stopped
            return {
                "discharge_temp": 30.0,
                "suction_pressure": 1.0,
                "discharge_pressure": 1.0,
                "condenser_fan_rpm": 0.0,
                "vibration": 0.0,
                "oil_level": base["oil_level"],
            }

        # Sensitivity response to RPM changes:
        # Lowering compressor_rpm by 500 reduces discharge_temp by ~20 C, discharge_pressure by ~3 bar, vibration by ~1 mm/s
        rpm_factor = (rpm - 1500.0) / 500.0
        base["discharge_temp"] += rpm_factor * 20.0
        base["discharge_pressure"] += rpm_factor * 3.0
        base["vibration"] = max(0.1, base["vibration"] + rpm_factor * 1.0)
        return base

    def set_scenario(self, scenario: str, current_sim_time: float, ramp_s: Optional[float] = None):
        if scenario not in SCENARIO_TARGETS:
            raise ValueError(f"Unknown scenario: {scenario}. Available: {list(SCENARIO_TARGETS.keys())}")
        self.target_scenario = scenario
        self.scenario = scenario
        self.scenario_start_time = current_sim_time
        self.ramp_duration_s = ramp_s if ramp_s is not None else self.default_ramp_s
        self.from_targets = self.current_values.copy()

    def step(self, dt: float, current_sim_time: float) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
        """
        Advance simulation by dt seconds at current_sim_time.
        Returns: (metrics_dict, list_of_plc_events)
        """
        # 1. Compute ramp progress [0.0, 1.0]
        if self.ramp_duration_s <= 0:
            progress = 1.0
        else:
            elapsed = current_sim_time - self.scenario_start_time
            progress = min(1.0, max(0.0, elapsed / self.ramp_duration_s))

        target_at_rpm = self._calculate_targets(self.target_scenario, self.compressor_rpm)

        # 2. First-order inertia update for each metric
        # dx/dt = (target - x) / tau. tau ~ 10.0 seconds
        tau = 8.0
        alpha = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0

        for metric_name, final_target in target_at_rpm.items():
            start_val = self.from_targets.get(metric_name, final_target)
            current_target = start_val + progress * (final_target - start_val)

            val = self.current_values.get(metric_name, current_target)
            val = val + alpha * (current_target - val)

            # Add minor noise if enabled
            if self.enable_noise:
                if metric_name == "discharge_temp":
                    val += random.uniform(-0.15, 0.15)
                elif metric_name in ("suction_pressure", "discharge_pressure"):
                    val += random.uniform(-0.03, 0.03)
                elif metric_name == "vibration":
                    val += random.uniform(-0.04, 0.04)
                elif metric_name == "condenser_fan_rpm":
                    if val > 100:
                        val += random.uniform(-5.0, 5.0)
                elif metric_name == "oil_level":
                    val += random.uniform(-0.05, 0.05)

            self.current_values[metric_name] = round(val, 2)

        # Build full metrics dictionary including compressor_rpm
        published_metrics = self.current_values.copy()
        published_metrics["compressor_rpm"] = round(self.compressor_rpm, 1)

        # 3. Check PLC Error triggers
        plc_events: List[Dict[str, Any]] = []
        for spec in PLC_ERROR_SPECS:
            code = spec["code"]
            is_violating = spec["check"](published_metrics)

            if is_violating:
                self.plc_consecutive_counts[code] += 1
                # Trigger when violation lasts for at least 2 consecutive samples
                if self.plc_consecutive_counts[code] >= 2:
                    # Repeat every 15 seconds while violating
                    last_emit = self.plc_last_emit_time[code]
                    if (current_sim_time - last_emit) >= 15.0:
                        self.plc_last_emit_time[code] = current_sim_time
                        iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        plc_events.append({
                            "event_id": str(uuid.uuid4()),
                            "timestamp": iso_ts,
                            "machine_id": self.machine_id,
                            "source": "machine",
                            "event_type": "ERROR",
                            "severity": "CRITICAL",
                            "error_code": code,
                            "message": spec["message"],
                        })
            else:
                self.plc_consecutive_counts[code] = 0

        return published_metrics, plc_events

    def validate_and_apply_command(self, cmd_name: str, params: Dict[str, Any]) -> Tuple[bool, int, str]:
        """
        Validate and execute inbound commands according to BRIEF rules:
        - Only SET_RPM and STOP_TEST allowed.
        - SET_RPM can only decrease speed, must be >= rpm_min_safe and <= rpm_max.
        Returns: (success, http_code, message)
        """
        if cmd_name not in ("SET_RPM", "STOP_TEST"):
            return False, 400, f"Unsupported command '{cmd_name}'. Allowed commands: SET_RPM, STOP_TEST"

        if cmd_name == "SET_RPM":
            if "rpm" not in params:
                return False, 400, "Missing required parameter 'rpm'"
            try:
                new_rpm = float(params["rpm"])
            except (ValueError, TypeError):
                return False, 400, "Parameter 'rpm' must be a valid number"

            if new_rpm > self.compressor_rpm:
                return (
                    False,
                    400,
                    f"Rejected: Cannot increase speed from {self.compressor_rpm} to {new_rpm} rpm. SET_RPM can only decrease speed.",
                )

            if new_rpm < self.config.rpm_min_safe:
                return (
                    False,
                    400,
                    f"Rejected: Requested speed {new_rpm} rpm is below safe minimum {self.config.rpm_min_safe} rpm",
                )

            if new_rpm > self.config.rpm_max:
                return (
                    False,
                    400,
                    f"Rejected: Requested speed {new_rpm} rpm exceeds maximum allowable {self.config.rpm_max} rpm",
                )

            self.compressor_rpm = new_rpm
            return True, 200, f"Compressor speed set to {new_rpm} rpm"

        elif cmd_name == "STOP_TEST":
            self.compressor_rpm = 0.0
            self.is_running = False
            return True, 200, "Test bench safely stopped"

        return False, 400, "Invalid command"
