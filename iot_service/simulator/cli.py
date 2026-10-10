import argparse
import json
import sys
import time

import paho.mqtt.client as mqtt

from app.config import load_machines_config, settings
from simulator.model import SCENARIO_TARGETS
from simulator.runner import SimulatorRunner


def cmd_run(args):
    print("=" * 60)
    print(" DENSO Compressor Test Bench Simulator")
    print("=" * 60)
    print(f"MQTT Broker: {settings.MQTT_HOST}:{settings.MQTT_PORT}")
    print(f"Publish Interval: {settings.PUBLISH_INTERVAL_S}s (Speedup: x{settings.SIM_SPEEDUP})")
    print("Press Ctrl+C to stop.\n")
    runner = SimulatorRunner(sim_speedup=args.speedup)
    runner.start()


def cmd_list(args):
    cfg = load_machines_config(settings.MACHINES_CONFIG_PATH)
    print("=" * 60)
    print(" CONFIGURED MACHINES")
    print("=" * 60)
    for m_id, m in cfg.machines.items():
        print(f"  * Machine: {m_id} ({m.description})")
        print(f"    RPM Setpoint: {m.rpm_setpoint} (Safe Range: {m.rpm_min_safe} - {m.rpm_max})")
        print(f"    Metrics: {', '.join(m.metrics.keys())}")
        print()

    print("=" * 60)
    print(" AVAILABLE FAULT SCENARIOS")
    print("=" * 60)
    for sc, targets in SCENARIO_TARGETS.items():
        print(f"  * {sc}:")
        print(f"    Target (1500 RPM): {targets}")
    print()


def cmd_set(args):
    machine_id = args.machine_id
    scenario = args.scenario
    ramp_s = args.ramp

    if scenario not in SCENARIO_TARGETS:
        print(f"Error: Unknown scenario '{scenario}'. Available scenarios:")
        for sc in SCENARIO_TARGETS:
            print(f"  - {sc}")
        sys.exit(1)

    payload = {
        "action": "set_scenario",
        "machine_id": machine_id,
        "scenario": scenario,
        "ramp_s": ramp_s,
    }

    try:
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"denso-cli-{int(time.time())}",
            )
        except AttributeError:
            client = mqtt.Client(client_id=f"denso-cli-{int(time.time())}")

        client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=10)
        client.loop_start()

        topic = "denso/sim/control"
        client.publish(topic, json.dumps(payload), qos=1)
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()

        print(f"Successfully commanded scenario for '{machine_id}' -> '{scenario}' (ramp={ramp_s}s)")
    except Exception as e:
        print(f"Failed to publish scenario command to MQTT broker ({settings.MQTT_HOST}:{settings.MQTT_PORT}): {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="DENSO Compressor Test Bench Simulator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: run
    p_run = subparsers.add_parser("run", help="Run the simulator background loop")
    p_run.add_argument("--speedup", type=float, default=settings.SIM_SPEEDUP, help="Simulation speedup factor")
    p_run.set_defaults(func=cmd_run)

    # Subcommand: list
    p_list = subparsers.add_parser("list", help="List configured machines and scenarios")
    p_list.set_defaults(func=cmd_list)

    # Subcommand: set
    p_set = subparsers.add_parser("set", help="Set machine fault scenario via MQTT")
    p_set.add_argument("machine_id", help="Machine ID (e.g. COMP-TB-01 or 'all')")
    p_set.add_argument("scenario", help="Fault scenario name")
    p_set.add_argument("--ramp", type=float, default=180.0, help="Ramp duration in seconds (default: 180)")
    p_set.set_defaults(func=cmd_set)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
