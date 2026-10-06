from __future__ import annotations

import argparse
import logging
import threading
import time
from typing import Any, Dict, List

from agent.brain import AgentBrain
from agent.rag_engine import RAGEngine
from agent.tools import AgentTools
from dashboard.server import DashboardServer
from dashboard.state_store import DashboardState
from iot.action_approval import ActionApproval
from iot.actuator_dispatcher import ActuatorDispatcher
from iot.event_bus import EventBus
from iot.telemetry_receiver import TelemetryReceiver
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.cnc_milling import CncMilling
from machines.injection_molding import InjectionMolding
from machines.robot_arm import RobotArm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
)
logger = logging.getLogger("FactoryMain")


class FactorySimulator:
    """Khởi chạy mô phỏng 5 dòng máy Denso, bộ não Agent, Telemetry và Dashboard UI."""

    def __init__(self) -> None:
        # 1. Khởi tạo trục truyền thông EventBus
        self.event_bus = EventBus(max_workers=8)

        # 2. Khởi tạo 5 dòng máy công nghiệp
        self.machines = [
            CncMilling(event_hub=self.event_bus),
            RobotArm(event_hub=self.event_bus),
            InjectionMolding(event_hub=self.event_bus),
            AoiInspection(event_hub=self.event_bus),
            AmrVehicle(event_hub=self.event_bus),
        ]

        # 3. Khởi tạo tầng Chấp hành (Actuator Dispatcher) và nạp danh bạ máy
        self.dispatcher = ActuatorDispatcher(event_bus=self.event_bus)
        self.dispatcher.register_machines(self.machines)

        # 4. Khởi tạo tầng Chốt kiểm duyệt an toàn (Human-in-the-Loop)
        self.action_approval = ActionApproval(
            dispatcher_callback=self.dispatcher.execute,
            event_bus=self.event_bus,
        )

        # 5. Khởi tạo Bộ não Agent, Tools và RAG Engine
        self.rag = RAGEngine()
        self.tools = AgentTools(event_bus=self.event_bus)
        self.brain = AgentBrain(
            rag_engine=self.rag,
            tools=self.tools,
            event_bus=self.event_bus,
        )

        # 6. Khởi tạo Bộ tiếp nhận Telemetry & Lọc bất thường (ROC + Cooldown 60s)
        self.receiver = TelemetryReceiver(
            event_hub=self.event_bus,
            heartbeat_interval_sec=10.0,
            alert_cooldown_sec=60.0,
        )

        # 7. Khởi tạo Bộ lưu trữ State cho Dashboard Web UI
        self.dashboard_state = DashboardState()
        self.dashboard_state.register_machines(self.machines)

        self._threads: List[threading.Thread] = []
        self._running = False

    def setup_routes(self) -> None:
        """Đăng ký định tuyến các kênh truyền trên EventBus."""
        # TelemetryReceiver xử lý dữ liệu thô từ các máy
        self.event_bus.subscribe("telemetry", self.receiver.process)

        # AgentBrain nghe các gói tin đã được gán nhãn
        self.event_bus.subscribe("normal", self.brain.handle_heartbeat)
        self.event_bus.subscribe("alert", self.brain.handle_alert)

        # Lệnh điều khiển từ Agent được chuyển qua chốt kiểm duyệt an toàn
        self.event_bus.subscribe("action_command", self.action_approval.process_action_request)

        # Dashboard UI lắng nghe toàn bộ sự kiện (*) để cập nhật giao diện
        self.event_bus.subscribe("*", self.dashboard_state.handle_event)

    def _decide_action(self, action_id: str, decision: str) -> Dict[str, Any]:
        """Callback khi kỹ sư bấm nút DUYỆT hoặc TỪ CHỐI trên giao diện Web UI."""
        decision_upper = decision.strip().upper()
        if decision_upper in ("APPROVE", "APPROVED", "YES"):
            success = self.action_approval.approve(action_id)
            status = "APPROVED" if success else "NOT_FOUND"
        else:
            success = self.action_approval.reject(action_id)
            status = "REJECTED" if success else "NOT_FOUND"

        logger.info(f"[UI Decision] Action {action_id} -> {status}")
        return {"action_id": action_id, "status": status}

    def _machine_telemetry_loop(self, machine: Any, interval: float) -> None:
        """Vòng lặp sinh dữ liệu cảm biến định kỳ cho từng máy."""
        while self._running:
            try:
                # Đọc dữ liệu mô phỏng từ cỗ máy
                payload = machine.generate_telemetry()
                telemetry_event = {
                    "event_type": "telemetry",
                    "machine_id": machine.machine_id,
                    "machine_type": machine.machine_type,
                    "timestamp": time.time(),
                    "payload": payload,
                }
                # Phát dữ liệu thô vào EventBus
                self.event_bus.publish(telemetry_event)
            except Exception as e:
                logger.error(f"Lỗi khi đọc telemetry từ máy {machine.machine_id}: {e}")
            time.sleep(interval)

    def run(self, host: str = "127.0.0.1", port: int = 8000, interval: float = 1.0) -> None:
        self.setup_routes()
        self._running = True

        # Khởi chạy Server giao diện Dashboard Web UI
        server = DashboardServer(
            (host, port),
            self.dashboard_state,
            self.action_approval,
            on_decision=self._decide_action,
        )

        # Khởi chạy luồng telemetry riêng cho từng máy
        for machine in self.machines:
            thread = threading.Thread(
                target=self._machine_telemetry_loop,
                args=(machine, interval),
                name=f"sim-{machine.machine_id}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

        display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
        print(f"\n=======================================================", flush=True)
        print(f"  DENSO AI-IIoT System Running at: http://{display_host}:{port}", flush=True)
        print(f"  Telemetry Interval: {interval}s | Cooldown: 60s", flush=True)
        print(f"  Press Ctrl+C to stop the system.", flush=True)
        print(f"=======================================================\n", flush=True)

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nĐang dừng hệ thống mô phỏng...", flush=True)
        finally:
            self._running = False
            self.event_bus.shutdown()
            server.server_close()
            print("Hệ thống đã dừng hoàn toàn.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy hệ thống mô phỏng nhà máy Denso AI-IIoT.")
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ host (mặc định: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Cổng Dashboard Web UI (mặc định: 8000)")
    parser.add_argument("--interval", type=float, default=1.0, help="Chu kỳ cảm biến giây (mặc định: 1.0)")
    args = parser.parse_args()

    simulator = FactorySimulator()
    simulator.run(host=args.host, port=args.port, interval=args.interval)