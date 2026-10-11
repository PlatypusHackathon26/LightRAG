"""Repair and restart procedures planned from a machine's declared commands.

The agent only chooses WHAT to repair (one declared repair command). The steps around it - stop,
lock out, repair, unlock, and later start - come from the machine's state graph, so two answers
that mean the same repair always produce the same procedure.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Mapping, Optional

from machines import commands as cmd
from machines.commands import CommandSpec

# Never planned automatically: an emergency stop is an operator's decision, and HOLD/RESUME/
# RETURN_TO_CHARGER are operating moves, not part of making a machine safe to work on.
_PLANNABLE = {"SAFE_STOP", "RESET_ESTOP", "LOCKOUT", "UNLOCK", "START"}


class PlanningError(ValueError):
    pass


def _path(
    specs: Mapping[str, CommandSpec], start: str, goals: Iterable[str]
) -> Optional[List[str]]:
    """Shortest list of control commands taking the machine from `start` into one of `goals`."""
    goals = set(goals)
    if start in goals:
        return []
    edges = [
        s
        for s in specs.values()
        if s.kind == "control" and s.name in _PLANNABLE and s.next_state
    ]
    seen, queue = {start}, deque([(start, [])])
    while queue:
        state, path = queue.popleft()
        for spec in edges:
            if state in spec.allowed_states and spec.next_state not in seen:
                nxt = (
                    cmd.RUNNING if spec.next_state == cmd.STARTING else spec.next_state
                )
                if nxt in goals or spec.next_state in goals:
                    return path + [spec.name]
                seen.add(spec.next_state)
                queue.append((spec.next_state, path + [spec.name]))
    return None


def _step(spec: CommandSpec, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    step = {
        "command": spec.name,
        "params": params or {},
        "desc": spec.desc_vi,
        "kind": spec.kind,
    }
    if spec.kind == "repair":
        step["duration_s"] = spec.duration_s
    return step


def plan_repair(
    specs: Mapping[str, CommandSpec], state: str, repair: str
) -> List[Dict[str, Any]]:
    """Steps from `state` through `repair` to a stopped machine that may be restarted."""
    spec = specs.get(repair)
    if spec is None or spec.kind != "repair":
        raise PlanningError(f"'{repair}' không phải lệnh sửa của máy này")
    if state == cmd.MAINTENANCE:
        raise PlanningError("máy đang được bảo trì")
    before = _path(specs, state, spec.allowed_states)
    after = _path(specs, spec.return_state, {cmd.STOPPED})
    if before is None or after is None:
        raise PlanningError(
            f"không có đường từ {state} tới trạng thái sửa {sorted(spec.allowed_states)}"
        )
    return (
        [_step(specs[n]) for n in before]
        + [_step(spec)]
        + [_step(specs[n]) for n in after]
    )


def plan_restart(specs: Mapping[str, CommandSpec], state: str) -> List[Dict[str, Any]]:
    """Steps from `state` (normally STOPPED) to a running machine."""
    path = _path(specs, state, {cmd.RUNNING})
    if path is None:
        raise PlanningError(f"không có đường từ {state} tới RUNNING")
    return [_step(specs[n]) for n in path]
