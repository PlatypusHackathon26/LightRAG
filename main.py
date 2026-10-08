# main.py
import threading
import time
import uvicorn

from iot.event_bus import EventBus
from iot.telemetry_receiver import TelemetryReceiver
from iot.actuator_dispatcher import ActuatorDispatcher
from iot.action_approval import ActionApproval

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
                fault_interval_sec=m.fault_interval_sec,
            )
        time.sleep(1.0)


def main():
    # 1. Khởi tạo bus & dịch vụ chấp hành
    bus = EventBus(max_workers=4)
    dispatcher = ActuatorDispatcher(event_bus=bus)
    approval = ActionApproval(dispatcher=dispatcher, event_bus=bus)
    receiver = TelemetryReceiver(event_hub=bus)
    state_store = StateStore()

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
    app = create_app(state_store=state_store, machines_dict=machines_dict)
    print("🌐 Tester Fleet Dashboard running at: http://localhost:8085")
    uvicorn.run(app, host="0.0.0.0", port=8085)


if __name__ == "__main__":
    main()