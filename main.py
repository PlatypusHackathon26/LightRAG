from __future__ import annotations

import argparse
import threading
from typing import Any, Dict, List

from agent.brain import AgentBrain
from agent.knowledge_base import KnowledgeBase
from agent.tools import AgentTools
from dashboard.server import DashboardServer
from dashboard.state_store import DashboardState
from iot.action_approval import ActionApproval
from iot.actuator_dispatcher import ActuatorDispatcher
from iot.event_bus import EventBus
from machines.amr_vehicle import AmrVehicle
from machines.aoi_inspection import AoiInspection
from machines.cnc_milling import CncMilling
from machines.injection_molding import InjectionMolding
from machines.robot_arm import RobotArm


class FactorySimulator:
    """Start the machine simulators and expose their state in a local web UI."""

    def __init__(self) -> None:
        self.event_hub = EventBus()
        self.dashboard_state = DashboardState()
        self.machine_registry: Dict[str, Any] = {}
        self.dispatcher = ActuatorDispatcher(machine_registry=self.machine_registry)
        self.action_approval = ActionApproval(dispatcher=self.dispatcher)
        self.tools = AgentTools()
        self.knowledge_base = KnowledgeBase()
        self.brain = AgentBrain(tools=self.tools, knowledge_base=self.knowledge_base)
        self.machines = [
            CncMilling(event_hub=self.event_hub),
            RobotArm(event_hub=self.event_hub),
            InjectionMolding(event_hub=self.event_hub),
            AoiInspection(event_hub=self.event_hub),
            AmrVehicle(event_hub=self.event_hub),
        ]
        for machine in self.machines:
            self.machine_registry[machine.machine_id] = machine

        self.dashboard_state.register_machines(self.machines)
        self._threads: List[threading.Thread] = []

    def _on_event(self, event: Dict[str, Any]) -> None:
        if event.get("event_type") != "alert":
            return

        try:
            result = self.brain.handle_alert(event)
        except Exception as exc:
            print(f"[AGENT ERROR] {event.get('machine_id')}: {exc}", flush=True)
            return

        machine_id = event.get("machine_id", "unknown")
        for recommendation in result["recommendations"]:
            proposal = self.action_approval.propose(
                machine_id,
                recommendation["action"],
                recommendation.get("payload", {}),
            )
            print(
                f"[APPROVAL REQUIRED] {machine_id}: "
                f"{proposal['action']} (id={proposal['action_id']})",
                flush=True,
            )
        self.dashboard_state.record_agent_result(machine_id, result)
        print(f"[ALERT] {machine_id}: {result['issue']} — {result['diagnosis']}", flush=True)

    def _decide_action(self, action_id: str, decision: str) -> Dict[str, Any]:
        result = self.action_approval.decide(action_id, decision)
        print(
            f"[ACTION {result['status'].upper()}] {result['machine_id']}: {result['action']}",
            flush=True,
        )
        return result

    def run(self, host: str = "127.0.0.1", port: int = 8000, interval: float = 1.0) -> None:
        self.event_hub.subscribe(self.dashboard_state.handle_event)
        self.event_hub.subscribe(self._on_event)

        server = DashboardServer(
            (host, port),
            self.dashboard_state,
            self.action_approval,
            on_decision=self._decide_action,
        )
        for machine in self.machines:
            thread = threading.Thread(
                target=machine.run,
                kwargs={"interval": interval},
                name=f"sim-{machine.machine_id}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

        display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
        print(f"DENSO Edge Dashboard: http://{display_host}:{port}", flush=True)
        print("Press Ctrl+C to stop the simulator and dashboard.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping simulator...", flush=True)
        finally:
            for machine in self.machines:
                machine.stop()
            server.server_close()
            print("DENSO Edge Dashboard stopped.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the DENSO edge simulator and live dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Dashboard port (default: 8000)")
    parser.add_argument("--interval", type=float, default=1.0, help="Telemetry interval in seconds (default: 1.0)")
    args = parser.parse_args()

    simulator = FactorySimulator()
    simulator.run(host=args.host, port=args.port, interval=args.interval)
