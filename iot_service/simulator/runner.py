import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import paho.mqtt.client as mqtt

from app.config import load_machines_config, settings
from simulator.model import MachineSimulator

logger = logging.getLogger("simulator.runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class SimulatorRunner:
    def __init__(
        self,
        config_path: Optional[str] = None,
        mqtt_host: Optional[str] = None,
        mqtt_port: Optional[int] = None,
        publish_interval_s: Optional[float] = None,
        sim_speedup: Optional[float] = None,
    ):
        self.config_path = config_path or settings.MACHINES_CONFIG_PATH
        self.machines_config = load_machines_config(self.config_path)
        self.mqtt_host = mqtt_host or settings.MQTT_HOST
        self.mqtt_port = mqtt_port or settings.MQTT_PORT
        self.publish_interval_s = publish_interval_s or settings.PUBLISH_INTERVAL_S
        self.sim_speedup = sim_speedup or settings.SIM_SPEEDUP
        if self.sim_speedup <= 0:
            self.sim_speedup = 1.0

        self.running = False
        self.sim_clock = 0.0
        self.simulators: Dict[str, MachineSimulator] = {}
        for m_id, m_cfg in self.machines_config.machines.items():
            self.simulators[m_id] = MachineSimulator(machine_config=m_cfg, default_scenario="normal")

        # Configure MQTT Client
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"denso-simulator-{int(time.time())}",
            )
        except AttributeError:
            self.client = mqtt.Client(client_id=f"denso-simulator-{int(time.time())}")

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        logger.info(f"Connected to MQTT Broker at {self.mqtt_host}:{self.mqtt_port} (rc={rc})")
        # Subscribe to machine command topics and sim control topic
        client.subscribe("denso/+/commands", qos=1)
        client.subscribe("denso/sim/control", qos=1)
        logger.info("Subscribed to denso/+/commands and denso/sim/control")

    def _on_disconnect(self, client, userdata, flags, rc=None, properties=None):
        logger.warning(f"Disconnected from MQTT Broker (rc={rc})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logger.error(f"Malformed JSON on {topic}: {e}")
            return

        if topic == "denso/sim/control":
            self._handle_sim_control(payload)
        elif topic.endswith("/commands"):
            parts = topic.split("/")
            if len(parts) >= 3:
                machine_id = parts[1]
                self._handle_command(machine_id, payload)

    def _handle_sim_control(self, payload: dict):
        action = payload.get("action", "")
        if action == "set_scenario":
            machine_id = payload.get("machine_id", "all")
            scenario = payload.get("scenario", "normal")
            ramp_s = payload.get("ramp_s", None)
            sim_time = self.sim_clock

            targets = [machine_id] if machine_id != "all" else list(self.simulators.keys())
            for m_id in targets:
                if m_id in self.simulators:
                    try:
                        self.simulators[m_id].set_scenario(scenario, current_sim_time=sim_time, ramp_s=ramp_s)
                        logger.info(f"Switched scenario for {m_id} to '{scenario}' (ramp={ramp_s}s, sim_time={sim_time:.1f})")
                    except Exception as ex:
                        logger.error(f"Failed to set scenario on {m_id}: {ex}")
                else:
                    logger.warning(f"Machine {m_id} not found in simulator registry")

    def _handle_command(self, machine_id: str, payload: dict):
        cmd_id = payload.get("command_id", "")
        command = payload.get("command", "")
        params = payload.get("params", {})
        iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if machine_id not in self.simulators:
            ack = {
                "command_id": cmd_id,
                "timestamp": iso_ts,
                "machine_id": machine_id,
                "status": "REJECTED",
                "code": 404,
                "message": f"Machine '{machine_id}' not recognized by simulator",
            }
        else:
            sim = self.simulators[machine_id]
            success, code, message = sim.validate_and_apply_command(command, params)
            ack = {
                "command_id": cmd_id,
                "timestamp": iso_ts,
                "machine_id": machine_id,
                "status": "OK" if success else "REJECTED",
                "code": code,
                "message": message,
            }

        ack_topic = f"denso/{machine_id}/acks"
        self.client.publish(ack_topic, json.dumps(ack), qos=1)
        logger.info(f"Published ACK to {ack_topic}: {ack['status']} ({ack['code']}) - {ack['message']}")

    def start(self):
        logger.info(f"Starting Simulator with {len(self.simulators)} machines: {list(self.simulators.keys())}")
        self.running = True

        try:
            self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker {self.mqtt_host}:{self.mqtt_port}: {e}")
            raise

        last_tick_time = time.time()
        self.sim_clock = 0.0

        try:
            while self.running:
                now = time.time()
                real_dt = now - last_tick_time
                last_tick_time = now

                effective_dt = real_dt * self.sim_speedup
                self.sim_clock += effective_dt

                iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                for m_id, sim in self.simulators.items():
                    metrics, events = sim.step(dt=effective_dt, current_sim_time=self.sim_clock)

                    # Publish metrics
                    metric_payload = {
                        "timestamp": iso_ts,
                        "machine_id": m_id,
                        "metrics": metrics,
                    }
                    metric_topic = f"denso/{m_id}/metrics"
                    self.client.publish(metric_topic, json.dumps(metric_payload), qos=0)

                    # Publish PLC events
                    for event in events:
                        event_topic = f"denso/{m_id}/events"
                        self.client.publish(event_topic, json.dumps(event), qos=1)
                        logger.warning(
                            f"Emitted PLC Event on {event_topic}: {event['error_code']} - {event['message']}"
                        )

                # Sleep until next interval
                sleep_s = self.publish_interval_s / self.sim_speedup
                time.sleep(max(0.1, sleep_s))
        except KeyboardInterrupt:
            logger.info("Simulator stopping from keyboard interrupt...")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        logger.info("Simulator runner stopped.")


def run_simulator():
    runner = SimulatorRunner()

    def handle_sig(sig, frame):
        logger.info("Signal received, stopping...")
        runner.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)
    runner.start()
