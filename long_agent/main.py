# main.py
import os
import threading
import time
import uvicorn

from iot.event_bus import EventBus
from iot.telemetry_receiver import TelemetryReceiver
from iot.actuator_dispatcher import ActuatorDispatcher
from iot.action_approval import ActionApproval
from iot.procedure_runner import ProcedureRunner

from agent.brain import AgentBrain
from agent.procedures import PlanningError, plan_repair
from agent.rag_engine import RAGEngine
from agent.llm_client import llm_callable_from_env
from agent.retriever import retriever_from_env

from machines.cnc_milling import CncMilling
from machines.robot_arm import RobotArm
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.injection_molding import InjectionMolding

from dashboard.state_store import StateStore
from dashboard.server import create_app


def start_iot_simulation(machines, receiver, state_store):
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
    runner = ProcedureRunner(dispatcher, event_bus=bus,
                             verify_s=float(os.environ.get("LONG_AGENT_VERIFY_S", "120")))
    # Mọi lệnh agent đề xuất đều chờ kỹ sư duyệt; LONG_AGENT_AUTO_LOW=1 cho lệnh LOW (do máy khai báo) chạy ngay.
    approval = ActionApproval(dispatcher=dispatcher, event_bus=bus, procedure_runner=runner,
                              default_ttl_sec=float(os.environ.get("LONG_AGENT_APPROVAL_TTL_S", "1800")),
                              require_approval_for_all=os.environ.get("LONG_AGENT_AUTO_LOW") != "1")
    receiver = TelemetryReceiver(event_hub=bus)
    state_store = StateStore()

    # Agent chẩn đoán (LLM khi có LONG_AGENT_LLM_*, tài liệu khi có LONG_AGENT_RAG_URL) và chỉ chọn
    # lệnh sửa; quy trình dừng - khoá - sửa - khởi động lại do agent/procedures.py lập và kỹ sư duyệt 2 lần.
    rag = RAGEngine(llm_callable=llm_callable_from_env(), retriever=retriever_from_env())
    brain = AgentBrain(rag_engine=rag, event_bus=bus,
                       execute_actions=os.environ.get("LONG_AGENT_PROPOSE", "1") != "0",
                       repeat_window_s=float(os.environ.get("LONG_AGENT_REPEAT_S", "120")),
                       busy=lambda mid: runner.is_busy(mid) or approval.has_pending(mid),
                       attempts=runner.attempts)
    bus.subscribe("alert", runner.on_alert)
    bus.subscribe("alert", brain.handle_alert)
    bus.subscribe("normal", brain.handle_heartbeat)
    bus.subscribe("verification", brain.handle_verification)

    def _route_action_command(event: dict) -> None:
        """An agent proposal becomes one ticket: a repair is expanded into its full procedure."""
        machine_id = event.get("machine_id", "UNKNOWN")
        if runner.is_busy(machine_id) or approval.has_pending(machine_id):
            return
        machine = dispatcher.machine(machine_id)
        if machine is None:
            return
        name = event.get("command", "")
        base = {"machine_id": machine_id, "reason": event.get("reason", "Agent đề xuất"),
                "diagnosis": event.get("diagnosis", "")}
        if event.get("kind") == "repair":
            try:
                steps = plan_repair(machine.commands, machine.state, name)
            except PlanningError as exc:
                state_store.add_machine_note(machine_id, f"Không lập được quy trình sửa {name}: {exc}")
                return
            approval.process_action_request({**base, "kind": "repair", "command": name,
                                             "title": f"Sửa: {name}", "steps": steps})
        else:
            approval.process_action_request({**base, "kind": "command", "command": name,
                                             "params": event.get("params", {}), "payload": event.get("params", {}),
                                             "title": f"Lệnh: {name}"})

    def _request_restart(machine_id: str, steps: list, repair_record: dict) -> None:
        approval.process_action_request({
            "machine_id": machine_id, "kind": "restart", "command": "START",
            "title": "Khởi động lại sau sửa chữa", "steps": steps,
            "reason": f"Đã xong {repair_record.get('command')}; kỹ sư kiểm tra máy rồi duyệt khởi động lại.",
        })

    runner.request_restart = _request_restart
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
        args=(machines, receiver, state_store),
        daemon=True,
    )
    sim_thread.start()
    print("🚀 IoT Simulation Engine started.")

    # 4. Khởi chạy Dashboard Web dành cho Tester tại cổng 8085
    app = create_app(
        state_store=state_store,
        machines_dict=machines_dict,
        approval=approval,
        procedures=runner,
        on_chat=brain.handle_user_query,
        on_decision=approval.decide,
    )
    # Localhost by default: the fault, decision and PLC routes have no authentication. The DENSO
    # Agent Gateway (denso/gateway) relays the dashboard; LONG_AGENT_HOST=0.0.0.0 opens it to the LAN.
    host = os.environ.get("LONG_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("LONG_AGENT_PORT", "8085"))
    print(f"🌐 Tester Fleet Dashboard running at: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
