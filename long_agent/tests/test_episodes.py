"""Alert episodes: one diagnosis per new metric, one episode until the machine recovers,
temporary measures withdrawn once the root cause is fixed (iot/recovery.py)."""

from unittest.mock import MagicMock

from agent.brain import AgentBrain
from dashboard.state_store import StateStore
from iot.action_approval import ActionApproval
from iot.recovery import RecoveryTracker, RepairLog, is_repair, withdraw_mitigations


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


def test_the_receiver_says_per_sample_whether_a_machine_is_still_out_of_range():
    from iot.telemetry_receiver import TelemetryReceiver

    receiver = TelemetryReceiver()

    def sample(pressure):
        receiver.process(
            {
                "event_type": "telemetry",
                "machine_id": "MC-MILL-01",
                "machine_type": "CNC_MILLING",
                "payload": {
                    "Controller_Execution": "RUNNING",
                    "Coolant_Pressure_Bar": pressure,
                },
            }
        )
        return receiver.is_abnormal("MC-MILL-01")

    assert sample(0.0) is True
    assert (
        sample(0.0) is True
    )  # the alert is in cooldown, the machine is still abnormal
    assert sample(20.0) is False


def test_what_came_of_each_decision_is_written_to_the_incident_thread():
    store = StateStore()
    store.handle_event(_alert())
    store.handle_event(
        {
            "event_type": "command_response",
            "machine_id": "MC-MILL-01",
            "command": "REPAIR_COOLANT_SYSTEM",
            "status": "SUCCESS",
            "details": {"execution_detail": "Ap suat phuc hoi"},
        }
    )
    store.handle_event(
        {
            "event_type": "approval_rejected",
            "command": {"machine_id": "MC-MILL-01", "command": "COOLANT_BOOST"},
            "reason": "Đã sửa tận gốc bằng REPAIR_COOLANT_SYSTEM",
        }
    )
    store.handle_event({"event_type": "machine_recovered", "machine_id": "MC-MILL-01"})
    (conv,) = store.get_snapshot()["conversations"]
    results = [m["text"] for m in conv["messages"] if m["role"] == "result"]
    assert results[0] == "✅ Đã thực hiện REPAIR_COOLANT_SYSTEM: Ap suat phuc hoi"
    assert results[1].startswith("↩ Đã rút đề xuất COOLANT_BOOST")
    assert results[2].startswith("✅ Mọi chỉ số đã về bình thường")


def test_a_second_fault_is_diagnosed_once_the_first_one_is_repaired():
    """Seen live: coolant failure + tool wear. The coolant repair ran, vibration stayed high, and no
    REPLACE_TOOL came because vibration had been part of the first diagnosis."""
    rag = MagicMock()
    rag.query_with_schema.return_value = {"diagnosis": "x", "actions": []}
    brain = AgentBrain(
        rag_engine=rag, tools=MagicMock(), event_bus=MagicMock(), repeat_window_s=1
    )
    brain.handle_alert(_alert("Vibration_RMS_mm_s"))
    brain.handle_alert(_alert("Vibration_RMS_mm_s"))
    assert rag.query_with_schema.call_count == 1
    brain.rediagnose("MC-MILL-01")  # REPAIR_COOLANT_SYSTEM was approved and ran
    brain.handle_alert(
        _alert("Vibration_RMS_mm_s")
    )  # still high: diagnosed on current readings
    assert rag.query_with_schema.call_count == 2


def test_resetting_the_cooldown_lets_the_next_sample_alert_again():
    from iot.telemetry_receiver import TelemetryReceiver

    receiver = TelemetryReceiver()
    sample = {
        "event_type": "telemetry",
        "machine_id": "MC-MILL-01",
        "machine_type": "CNC_MILLING",
        "payload": {"Controller_Execution": "RUNNING", "Coolant_Pressure_Bar": 0.0},
    }
    assert receiver.process(dict(sample))["label"] == "alert"
    assert receiver.process(dict(sample)) is None  # in cooldown
    receiver.reset_cooldown("MC-MILL-01")
    assert receiver.process(dict(sample))["label"] == "alert"


def test_a_command_the_machine_does_not_have_is_reported_as_refused():
    """Seen live: TOGGLE_COOLANT on the CNC came back "khong hop le" and showed as executed.
    Each machine words its refusal differently; none may pass as executed."""
    from iot.actuator_dispatcher import ActuatorDispatcher
    from machines.amr_vehicle import AmrVehicle
    from machines.aoi_inspection import AoiInspection
    from machines.cnc_milling import CncMilling
    from machines.injection_molding import InjectionMolding
    from machines.robot_arm import RobotArm

    machines = [
        CncMilling(),
        RobotArm(),
        AmrVehicle(),
        AoiInspection(),
        InjectionMolding(),
    ]
    dispatcher = ActuatorDispatcher()
    dispatcher.register_machines(machines)
    for m in machines:
        result = dispatcher.execute(
            {"machine_id": m.machine_id, "command": "TOGGLE_COOLANT"}
        )
        assert result["status"] == "REJECTED", (m.machine_id, result)
    ok = dispatcher.execute({"machine_id": "MC-MILL-01", "command": "REPLACE_TOOL"})
    assert ok["status"] == "SUCCESS"


def test_a_repair_that_ran_in_this_episode_is_not_proposed_again():
    """Seen live: while the AOI's readings were still recovering, REPLACE_LED_MODULE and
    RECALIBRATE_OPTICS were proposed (and run) three and four times in one episode."""
    log = RepairLog()
    log.record("MC-AOI-01", "REPLACE_LED_MODULE")
    assert log.done("MC-AOI-01", "replace_led_module")
    assert not log.done("MC-AOI-01", "RECALIBRATE_OPTICS")
    assert not log.done("MC-MILL-01", "REPLACE_LED_MODULE")
    log.clear("MC-AOI-01")  # the machine recovered: a new episode may need it again
    assert not log.done("MC-AOI-01", "REPLACE_LED_MODULE")
