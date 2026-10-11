"""The commands a machine accepts, declared once by the machine itself.

Every other list of commands (the agent's catalog, risk levels, the dispatcher's checks, the docs)
is derived from these specs, so a command exists exactly when a machine implements it.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

# Machine states shared by every machine. AMR adds CHARGING.
RUNNING = "RUNNING"  # producing
HOLD = "HOLD"  # paused in place: powered, no feed / motion
STARTING = "STARTING"  # START accepted, coming up to speed / temperature
STOPPED = "STOPPED"  # controlled stop, actuators off, may restart
LOCKED_OUT = (
    "LOCKED_OUT"  # energy isolated (lockout/tagout): the only state repairs run in
)
MAINTENANCE = "MAINTENANCE"  # a repair is in progress
E_STOP = "E_STOP"  # emergency stop latched; RESET_ESTOP before anything else
CHARGING = "CHARGING"  # AMR docked on its charger

POWERED = frozenset({RUNNING, HOLD, STARTING, CHARGING})
ANY_STATE = frozenset(
    {RUNNING, HOLD, STARTING, STOPPED, LOCKED_OUT, MAINTENANCE, E_STOP, CHARGING}
)


@dataclass(frozen=True)
class ParamSpec:
    type: str  # "float" | "str"
    min: Optional[float] = None
    max: Optional[float] = None
    default: Any = None
    desc_vi: str = ""


@dataclass(frozen=True)
class CommandSpec:
    name: str
    kind: str  # "control" | "repair" | "setpoint"
    desc_vi: str
    allowed_states: FrozenSet[str]
    next_state: Optional[str] = None  # state after the command (repairs: MAINTENANCE)
    risk: str = "HIGH"
    params: Mapping[str, ParamSpec] = field(default_factory=dict)
    aliases: Tuple[str, ...] = ()
    fixes: Optional[str] = None  # repair: the fault it removes
    duration_s: float = 0.0  # repair: how long the work takes
    return_state: str = LOCKED_OUT  # repair: state once the work is done

    def catalog_entry(self) -> Dict[str, Any]:
        """What the agent is shown: name, purpose, when it may run, parameters."""
        entry: Dict[str, Any] = {
            "command": self.name,
            "kind": self.kind,
            "risk_level": self.risk,
            "desc": self.desc_vi,
            "allowed_states": sorted(self.allowed_states),
        }
        if self.params:
            entry["params"] = {k: _param_hint(p) for k, p in self.params.items()}
        if self.fixes:
            entry["fixes"] = self.fixes
            entry["duration_s"] = self.duration_s
        return entry


def _param_hint(p: ParamSpec) -> str:
    if p.type == "float":
        return f"float ({p.min:g} - {p.max:g}), mặc định {p.default}"
    return f"{p.type}, mặc định {p.default}"


def control_commands(
    hold_aliases: Iterable[str] = (),
    hold_desc: str = "Tạm dừng tại chỗ",
    resume_from: FrozenSet[str] = frozenset({HOLD}),
) -> Dict[str, CommandSpec]:
    """The stop / lockout / start commands every machine has."""
    specs = [
        CommandSpec(
            "SAFE_STOP",
            "control",
            "Dừng máy có kiểm soát; cơ cấu chấp hành tắt, số đo về trạng thái dừng",
            frozenset({RUNNING, HOLD, STARTING, CHARGING}),
            STOPPED,
            risk="LOW",
            aliases=("STOP", "CYCLE_STOP", "DUNG_MAY", "DUNG_AN_TOAN", "SHUTDOWN"),
        ),
        CommandSpec(
            "EMERGENCY_STOP",
            "control",
            "Dừng khẩn cấp: ngắt toàn bộ, chốt E-STOP (cần RESET_ESTOP)",
            ANY_STATE - {E_STOP},
            E_STOP,
            aliases=("E_STOP", "ESTOP", "DUNG_KHAN_CAP", "NGAT_KHAN_CAP"),
        ),
        CommandSpec(
            "RESET_ESTOP",
            "control",
            "Nhả chốt dừng khẩn cấp; máy về STOPPED",
            frozenset({E_STOP}),
            STOPPED,
            aliases=("RESET_EMERGENCY_STOP", "RESET_E_STOP", "ESTOP_RESET"),
        ),
        CommandSpec(
            "LOCKOUT",
            "control",
            "Cô lập năng lượng (khoá an toàn LOTO) để bảo trì; chỉ khi máy đã dừng hẳn",
            frozenset({STOPPED}),
            LOCKED_OUT,
            aliases=("LOTO", "LOCK_OUT", "KHOA_AN_TOAN"),
        ),
        CommandSpec(
            "UNLOCK",
            "control",
            "Gỡ khoá an toàn sau bảo trì; máy về STOPPED",
            frozenset({LOCKED_OUT}),
            STOPPED,
            risk="LOW",
            aliases=("REMOVE_LOCKOUT", "GO_KHOA"),
        ),
        CommandSpec(
            "START",
            "control",
            "Khởi động lại máy đã dừng (kiểm tra liên động, có thời gian khởi động)",
            frozenset({STOPPED}),
            STARTING,
            aliases=("RESTART", "CYCLE_START", "KHOI_DONG", "POWER_ON"),
        ),
        CommandSpec(
            "HOLD",
            "control",
            hold_desc,
            frozenset({RUNNING}),
            HOLD,
            risk="LOW",
            aliases=("PAUSE", "TAM_DUNG", *hold_aliases),
        ),
        CommandSpec(
            "RESUME",
            "control",
            "Tiếp tục chạy sau khi tạm dừng",
            resume_from,
            RUNNING,
            risk="LOW",
            aliases=("CONTINUE", "TIEP_TUC"),
        ),
    ]
    return {s.name: s for s in specs}


def repair(
    name: str,
    fixes: str,
    desc_vi: str,
    duration_s: float,
    aliases: Iterable[str] = (),
    allowed: FrozenSet[str] = frozenset({LOCKED_OUT}),
    return_state: str = LOCKED_OUT,
) -> CommandSpec:
    return CommandSpec(
        name,
        "repair",
        desc_vi,
        allowed,
        MAINTENANCE,
        fixes=fixes,
        duration_s=duration_s,
        aliases=tuple(aliases),
        return_state=return_state,
    )


def _canon(text: str) -> str:
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def normalize_command(raw: Any, specs: Mapping[str, CommandSpec]) -> Optional[str]:
    """The canonical name for `raw`, or None. Case, accents, spaces and dashes are ignored;
    aliases are exact. No fuzzy matching: a name that is not declared is not a command."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    key = _canon(raw)
    for spec in specs.values():
        if key == spec.name or key in (_canon(a) for a in spec.aliases):
            return spec.name
    return None


def validate_params(spec: CommandSpec, params: Any) -> Dict[str, Any]:
    """Params coerced to their declared types, defaults filled in. Raises ValueError on a value
    out of range or of the wrong type. Unknown keys are dropped."""
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise ValueError(f"{spec.name}: tham số phải là object")
    out: Dict[str, Any] = {}
    for key, p in spec.params.items():
        value = params.get(key, p.default)
        if p.type == "float":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{spec.name}.{key} phải là số") from None
            if not math.isfinite(value) or not p.min <= value <= p.max:
                raise ValueError(
                    f"{spec.name}.{key} phải nằm trong {p.min:g}–{p.max:g}"
                )
        else:
            value = str(value).strip().upper()
            if not re.fullmatch(r"[A-Z0-9_]{1,40}", value):
                raise ValueError(f"{spec.name}.{key} không hợp lệ")
        out[key] = value
    return out
