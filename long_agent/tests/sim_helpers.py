"""Drive simulated machines on a fake clock, through the same procedures the agent's tickets run."""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import patch

from agent.procedures import plan_repair, plan_restart


def simulate(machine, seconds: float, step: float = 1.0) -> Dict[str, Any]:
    """Advance a machine with output noise removed and return the last sample."""
    now = machine.last_update_time
    telemetry: Dict[str, Any] = {}
    with patch("random.uniform", return_value=0.0):
        for _ in range(round(seconds / step)):
            now += step
            with patch("time.time", return_value=now):
                telemetry = machine.generate_telemetry()
    return telemetry


def command(machine, name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send a command at the machine's own simulated time; returns the result payload."""
    with patch("time.time", return_value=machine.last_update_time):
        return machine.receive_plc_command(name, params)["payload"]


def run_steps(machine, steps, max_wait_s: int = 900) -> None:
    """Run procedure steps like ProcedureRunner: retry 'not yet' answers, wait for repairs and start-up."""
    for step in steps:
        for _ in range(max_wait_s):
            res = command(machine, step["command"], step.get("params"))
            if res["status"] == "OK":
                break
            assert res["retryable"], f"{step['command']} refused: {res['execution_detail']}"
            simulate(machine, 1)
        else:
            raise AssertionError(f"{step['command']} never accepted")
        waiting = {"repair": "MAINTENANCE"}.get(step.get("kind")) or ("STARTING" if step["command"] == "START" else None)
        for _ in range(max_wait_s):
            if machine.state != waiting:
                break
            simulate(machine, 1)


def repair(machine, repair_command: str) -> None:
    """Stop, lock out, repair and unlock: the machine ends STOPPED."""
    run_steps(machine, plan_repair(machine.commands, machine.state, repair_command))


def restart(machine) -> None:
    run_steps(machine, plan_restart(machine.commands, machine.state))


def repair_and_restart(machine, repair_command: str) -> None:
    repair(machine, repair_command)
    restart(machine)
