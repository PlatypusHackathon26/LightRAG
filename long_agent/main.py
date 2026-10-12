# main.py
import os
import threading
import time
import uvicorn

from iot.event_bus import EventBus
from iot.telemetry_receiver import TelemetryReceiver
from iot.actuator_dispatcher import ActuatorDispatcher
from iot.action_approval import ActionApproval
from iot.recovery import RecoveryTracker, RepairLog, is_repair, withdraw_mitigations

from agent.brain import AgentBrain
from agent.tools import AgentTools
from agent.rag_engine import RAGEngine
from agent.llm_client import llm_callable_from_env

from machines.cnc_milling import CncMilling
from machines.robot_arm import RobotArm
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.injection_molding import InjectionMolding

from dashboard.state_store import StateStore
from dashboard.server import create_app


def start_iot_simulation(machines, receiver, state_store, on_tick=None):
    """Vòng lặp IoT nền: bóc tách lỗi ngầm khỏi telemetry gửi cho AI."""
    while True:
        for m in machines:
            # 1. Sinh dữ liệu động học thời gian thực
            raw_tele = m.generate_telemetry()

            # 2. Tách nhãn lỗi ngầm (Ground Truth) ra khỏi telemetry
            # Tuyệt đối không gửi mảng này vào TelemetryReceiver / AI Prompt
            ground_truth_faults = raw_tele.pop("Simulated_Active_Faults", [])

            # 3. Gói tin IoT chuẩn gửi cho bộ lọc biên & AI Agent
            clean_iot_event = {
                "event_type": "telemetry",
                "machine_id": m.machine_id,
                "machine_type": m.machine_type,
                "payload": raw_tele,  # Chỉ chứa các thông số vật lý thực tế
            }
            result = receiver.process(clean_iot_event)
            label = result.get("label", "normal") if result else "normal"
            if on_tick is not None:
                on_tick(m.machine_id, receiver.is_abnormal(m.machine_id))

            # 4. Gửi dữ liệu lên StateStore: Gồm telemetry sạch + nhãn lỗi ngầm cho Tester đối chiếu
            state_store.update_machine_telemetry(
                machine_id=m.machine_id,
                machine_type=m.machine_type,
                payload=raw_tele,
                label=label,
                active_faults=ground_truth_faults,
            )
        time.sleep(1.0)


def main():
    # 1. Khởi tạo bus & dịch vụ chấp hành
    bus = EventBus(max_workers=4)
    dispatcher = ActuatorDispatcher(event_bus=bus)
    # Mọi lệnh agent đề xuất đều chờ kỹ sư duyệt; LONG_AGENT_AUTO_LOW=1 trả lại hành vi gốc (lệnh LOW chạy ngay).
    approval = ActionApproval(
        dispatcher=dispatcher,
        event_bus=bus,
        require_approval_for_all=os.environ.get("LONG_AGENT_AUTO_LOW") != "1",
    )
    receiver = TelemetryReceiver(event_hub=bus)
    state_store = StateStore()

    # Agent phân tích và đề xuất; lệnh chỉ chạy sau khi kỹ sư duyệt, không tự thay đổi kịch bản lỗi.
    # LLM thật khi có LONG_AGENT_LLM_BASE/MODEL (agent/llm_client.py), nếu không thì chẩn đoán giả lập.
    # LONG_AGENT_PROPOSE=0 tắt đề xuất lệnh (chỉ chẩn đoán, như bản trước).
    rag = RAGEngine(llm_callable=llm_callable_from_env())
    tools = AgentTools(event_bus=bus)
    brain = AgentBrain(
        rag_engine=rag,
        tools=tools,
        event_bus=bus,
        execute_actions=os.environ.get("LONG_AGENT_PROPOSE", "1") != "0",
        repeat_window_s=float(os.environ.get("LONG_AGENT_REPEAT_S", "120")),
    )
    bus.subscribe("alert", brain.handle_alert)
    bus.subscribe("normal", brain.handle_heartbeat)

    # Đợt sự cố: mở ở cảnh báo đầu, đóng khi mọi chỉ số đã bình thường liên tục 8 s -> 'machine_recovered'.
    # Đọc từng mẫu (mỗi giây) chứ không chờ heartbeat 'normal' 10 s một lần của bộ lọc biên.
    recovery = RecoveryTracker(
        hold_s=float(os.environ.get("LONG_AGENT_RECOVERY_S", "8"))
    )
    bus.subscribe("alert", lambda e: recovery.alert(e.get("machine_id", "UNKNOWN")))

    def _on_tick(machine_id: str, abnormal: bool) -> None:
        if abnormal:
            recovery.alert(
                machine_id
            )  # còn ngoài ngưỡng (kể cả khi cảnh báo bị cooldown chặn)
        elif recovery.normal(machine_id):
            bus.publish({"event_type": "machine_recovered", "machine_id": machine_id})

    def _withdraw_mitigations(
        machine_id: str, why: str, everything: bool = False
    ) -> None:
        withdraw_mitigations(approval, machine_id, why, include_repairs=everything)

    repairs = RepairLog()  # lệnh sửa đã chạy trong đợt hiện tại: không đề xuất lại
    bus.subscribe("machine_recovered", brain.handle_recovered)
    bus.subscribe(
        "machine_recovered", lambda e: repairs.clear(e.get("machine_id", "UNKNOWN"))
    )
    bus.subscribe(
        "machine_recovered",
        lambda e: _withdraw_mitigations(
            e.get("machine_id", "UNKNOWN"), "Máy đã bình thường trở lại", True
        ),
    )

    def _decide(action_id: str, decision: str) -> dict:
        ticket = next(
            (
                a
                for a in approval.get_pending_actions()
                if a.get("approval_id") == action_id
            ),
            None,
        )
        result = approval.decide(action_id, decision)
        if (
            ticket
            and result.get("status") == "approved"
            and is_repair(ticket.get("command", ""))
        ):
            _withdraw_mitigations(
                ticket.get("machine_id", "UNKNOWN"),
                f"Đã sửa tận gốc bằng {ticket.get('command')}",
            )
            mid = ticket.get("machine_id", "UNKNOWN")
            repairs.record(mid, ticket.get("command", ""))

            def _after_settle() -> None:
                # Số đo đã có thời gian hồi phục; máy vẫn bất thường thì còn lỗi khác: chẩn đoán lại ngay
                # trên số liệu hiện tại thay vì chờ hết 60 s cooldown của chỉ số đó.
                if receiver.is_abnormal(mid):
                    brain.rediagnose(mid)
                    receiver.reset_cooldown(mid)

            threading.Timer(
                float(os.environ.get("LONG_AGENT_SETTLE_S", "10")), _after_settle
            ).start()
        return result

    def _route_action_command(event: dict) -> None:
        # Lệnh sửa đã chạy trong đợt này: số đo còn đang hồi phục, không đề xuất lại.
        if repairs.done(event.get("machine_id", "UNKNOWN"), event.get("command", "")):
            return
        # Một lệnh đang chờ duyệt cho máy này thì không tạo thêm bản trùng.
        if any(
            a.get("machine_id") == event.get("machine_id")
            and a.get("command") == event.get("command")
            for a in approval.get_pending_actions()
        ):
            return
        approval.process_action_request(
            {
                "machine_id": event.get("machine_id", "UNKNOWN"),
                "command": event.get("command", ""),
                "params": event.get("params", {}),
                "payload": event.get("params", {}),
                "risk_level": event.get("risk_level", "LOW"),
                "reason": event.get("reason", "Agent de xuat"),
            }
        )

    bus.subscribe("action_command", _route_action_command)

    # 1c. Đẩy mọi event bus vào StateStore để dashboard hiển thị
    bus.subscribe("*", state_store.handle_event)

    # 2. Khởi tạo 5 dòng máy
    machines = [
        CncMilling(event_hub=bus),
        RobotArm(event_hub=bus),
        AmrVehicle(event_hub=bus),
        AoiInspection(event_hub=bus),
        InjectionMolding(event_hub=bus),
    ]
    machines_dict = {m.machine_id: m for m in machines}
    dispatcher.register_machines(machines)

    # 3. Khởi chạy luồng giả lập IoT
    sim_thread = threading.Thread(
        target=start_iot_simulation,
        args=(machines, receiver, state_store, _on_tick),
        daemon=True,
    )
    sim_thread.start()
    print("🚀 IoT Simulation Engine started.")

    # 4. Khởi chạy Dashboard Web dành cho Tester tại cổng 8085
    app = create_app(
        state_store=state_store,
        machines_dict=machines_dict,
        approval=approval,
        on_chat=brain.handle_user_query,
        on_decision=_decide,
    )
    # Localhost by default: the fault, decision and PLC routes have no authentication. The DENSO
    # Agent Gateway (denso/gateway) relays the dashboard; LONG_AGENT_HOST=0.0.0.0 opens it to the LAN.
    host = os.environ.get("LONG_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("LONG_AGENT_PORT", "8085"))
    print(f"🌐 Tester Fleet Dashboard running at: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
