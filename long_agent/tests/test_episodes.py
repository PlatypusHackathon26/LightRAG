"""Alert episodes: one diagnosis per new metric, one episode until the machine recovers,
temporary measures withdrawn once the root cause is fixed (iot/recovery.py)."""

from unittest.mock import MagicMock

from agent.brain import AgentBrain
from dashboard.state_store import StateStore
from iot.action_approval import ActionApproval
from iot.recovery import RecoveryTracker, is_repair, withdraw_mitigations


def _alert(param="Coolant_Pressure_Bar", machine="MC-MILL-01"):
    return {
        "event_type": "telemetry",
        "label": "alert",
        "machine_id": machine,
        "machine_type": "CNC_MILLING",
        "payload": {param: 0.1},
        "anomalies": [{"param": param, "value": 0.1, "reason": "low"}],
    }


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_an_episode_closes_once_after_the_machine_stays_normal():
    clock = Clock()
    tracker = RecoveryTracker(hold_s=30, clock=clock)
    assert tracker.normal("M") is False  # never alerted: nothing to close
    tracker.alert("M")
    assert tracker.normal("M") is False  # first normal reading starts the hold
    clock.t = 20
    assert tracker.normal("M") is False
    tracker.alert("M")  # the reading dipped out again: the hold starts over
    clock.t = 40
    assert tracker.normal("M") is False
    clock.t = 75
    assert tracker.normal("M") is True
    assert tracker.normal("M") is False  # reported once


def test_the_same_fault_is_diagnosed_once_per_episode_not_every_few_minutes():
    rag = MagicMock()
    rag.query_with_schema.return_value = {"diagnosis": "x", "actions": []}
    brain = AgentBrain(
        rag_engine=rag, tools=MagicMock(), event_bus=MagicMock(), repeat_window_s=1
    )
    for _ in range(5):  # the edge filter repeats the alert every minute
        brain.handle_alert(_alert())
    assert rag.query_with_schema.call_count == 1
    brain.handle_alert(_alert("Spindle_Temp_C"))  # a new metric joins: diagnosed again
    assert rag.query_with_schema.call_count == 2
    brain.handle_recovered({"machine_id": "MC-MILL-01"})
    brain.handle_alert(_alert())  # after recovery it is a new incident
    assert rag.query_with_schema.call_count == 3


def test_the_state_store_marks_where_each_episode_starts_and_ends():
    store = StateStore()
    store.handle_event(_alert())
    first = store.get_all_machines()["MC-MILL-01"]["episode_started"]
    # the simulation loop rewrites the machine every second: the marks survive it
    store.update_machine_telemetry("MC-MILL-01", "CNC_MILLING", {}, label="normal")
    store.handle_event(_alert())
    machine = store.get_all_machines()["MC-MILL-01"]
    assert machine["episode_started"] == first and not machine["episode_ended"]
    store.handle_event({"event_type": "machine_recovered", "machine_id": "MC-MILL-01"})
    assert store.get_all_machines()["MC-MILL-01"]["episode_ended"]
    store.handle_event(_alert())
    machine = store.get_all_machines()["MC-MILL-01"]
    assert machine["episode_started"] >= first and not machine["episode_ended"]


def test_a_root_cause_fix_withdraws_temporary_measures_and_recovery_withdraws_all():
    approval = ActionApproval(
        dispatcher_callback=lambda c: {"status": "SUCCESS"},
        require_approval_for_all=True,
    )
    for machine, command in [
        ("MC-MILL-01", "COOLANT_BOOST"),
        ("MC-MILL-01", "REFILL_SPINDLE_LUBRICANT"),
        ("MC-ROBOT-01", "SET_SPEED_OVERRIDE"),
    ]:
        approval.process_action_request({"machine_id": machine, "command": command})
    withdrawn = withdraw_mitigations(approval, "MC-MILL-01", "fixed")
    left = sorted(
        (a["machine_id"], a["command"]) for a in approval.get_pending_actions()
    )
    assert len(withdrawn) == 1
    assert left == [
        ("MC-MILL-01", "REFILL_SPINDLE_LUBRICANT"),
        ("MC-ROBOT-01", "SET_SPEED_OVERRIDE"),
    ]
    # once the machine has recovered, nothing it was waiting for is needed any more
    withdraw_mitigations(approval, "MC-MILL-01", "recovered", include_repairs=True)
    left = [a["machine_id"] for a in approval.get_pending_actions()]
    assert left == ["MC-ROBOT-01"]


def test_repairs_are_the_commands_that_clear_a_fault():
    assert is_repair("REPAIR_COOLANT_SYSTEM") and is_repair("replace_tool")
    assert not is_repair("COOLANT_BOOST") and not is_repair("RETURN_TO_CHARGER")
