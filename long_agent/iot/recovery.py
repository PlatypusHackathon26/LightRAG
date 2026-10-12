# iot/recovery.py
"""Đợt sự cố (episode) của từng máy: mở khi có cảnh báo, đóng khi máy đã bình thường đủ lâu.

Vòng mô phỏng báo từng mẫu (mỗi giây) máy còn chỉ số bất thường hay không; một mẫu bình thường
đơn lẻ có thể chỉ là số đo dao động quanh ngưỡng, nên đợt chỉ đóng khi máy bình thường liên tục
`hold_s` giây.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

# Lệnh khắc phục nguyên nhân gốc: các lệnh mà máy mô phỏng dùng để gỡ cờ lỗi (clear_fault).
# Mọi lệnh khác (COOLANT_BOOST, SET_FEED_OVERRIDE, RETURN_TO_CHARGER, ...) chỉ là biện pháp tạm thời.
REPAIR_COMMANDS = frozenset(
    {
        "CLEAN_LIDAR_OPTICS",
        "CLEAR_CONVEYOR_JAM",
        "LUBRICATE_GUIDEWAYS",
        "PURGE_BARREL",
        "RECALIBRATE_OPTICS",
        "REFILL_GEARBOX_GREASE",
        "REFILL_SPINDLE_LUBRICANT",
        "REPAIR_COOLANT_SYSTEM",
        "REPAIR_HYDRAULIC_VALVE",
        "REPAIR_PNEUMATIC_SYSTEM",
        "REPLACE_BATTERY_MODULE",
        "REPLACE_LED_MODULE",
        "REPLACE_TOOL",
        "RESET_PAYLOAD",
        "SERVICE_DRIVE_MOTOR",
        "SERVICE_HEATER_SSR",
    }
)


def is_repair(command: str) -> bool:
    return str(command or "").upper() in REPAIR_COMMANDS


class RecoveryTracker:
    """alert(machine) mở / giữ đợt; normal(machine) trả True đúng một lần khi đợt đóng."""

    def __init__(
        self, hold_s: float = 8.0, clock: Optional[Callable[[], float]] = None
    ) -> None:
        self.hold_s = hold_s
        self._clock = clock or time.monotonic
        self._lock = Lock()
        self._open: Dict[
            str, Optional[float]
        ] = {}  # máy -> thời điểm bắt đầu bình thường lại

    def alert(self, machine_id: str) -> None:
        with self._lock:
            self._open[machine_id] = None

    def normal(self, machine_id: str) -> bool:
        with self._lock:
            if machine_id not in self._open:
                return False
            now = self._clock()
            since = self._open[machine_id]
            if since is None:
                self._open[machine_id] = now
                return False
            if now - since < self.hold_s:
                return False
            del self._open[machine_id]
            return True


def withdraw_mitigations(
    approval: Any, machine_id: str, why: str, include_repairs: bool = False
) -> List[str]:
    """Rút các ticket còn chờ duyệt của máy; trả về các ticket đã rút.

    Lỗi vừa được sửa tận gốc: chỉ rút biện pháp tạm thời (một lệnh sửa khác có thể là của lỗi
    thứ hai). Máy đã hồi phục hẳn (include_repairs=True): không lệnh nào còn cần.
    """
    withdrawn = []
    for a in approval.get_pending_actions():
        if a.get("machine_id") != machine_id:
            continue
        if is_repair(a.get("command", "")) and not include_repairs:
            continue
        try:
            approval.reject(a["approval_id"], reason=why)
            withdrawn.append(a["approval_id"])
        except KeyError:
            pass  # vừa được duyệt hoặc hết hạn
    return withdrawn


class RepairLog:
    """Lệnh sửa gốc đã chạy thành công trong đợt sự cố hiện tại của từng máy.

    Ngay sau khi sửa, số đo còn đang hồi phục; chẩn đoán lúc đó dễ đề xuất lại đúng lệnh vừa chạy.
    Trong cùng một đợt, một lệnh sửa đã chạy không được đề xuất lại; đợt mới thì xoá sổ.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._done: Dict[str, set] = {}

    def record(self, machine_id: str, command: str) -> None:
        with self._lock:
            self._done.setdefault(machine_id, set()).add(str(command).upper())

    def done(self, machine_id: str, command: str) -> bool:
        with self._lock:
            return str(command).upper() in self._done.get(machine_id, set())

    def clear(self, machine_id: str) -> None:
        with self._lock:
            self._done.pop(machine_id, None)
