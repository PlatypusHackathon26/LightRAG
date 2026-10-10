"""
Helper script to send commands to the test bench via MQTT and wait for ACK.
Usage:
  python iot_service/scripts/send_command.py COMP-TB-01 SET_RPM --rpm 1000
  python iot_service/scripts/send_command.py COMP-TB-01 SET_RPM --rpm 2000
  python iot_service/scripts/send_command.py COMP-TB-01 STOP_TEST
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from app.config import settings


def send_command(machine_id: str, command: str, params: dict, timeout_s: float = 5.0):
    cmd_id = str(uuid.uuid4())
    iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "command_id": cmd_id,
        "timestamp": iso_ts,
        "machine_id": machine_id,
        "command": command,
        "params": params,
        "issued_by": "operator_script",
        "incident_id": f"INC-TEST-{int(time.time())}",
    }

    ack_received = None

    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"cmd-sender-{int(time.time())}",
        )
    except AttributeError:
        client = mqtt.Client(client_id=f"cmd-sender-{int(time.time())}")

    def on_connect(c, userdata, flags, rc, properties=None):
        c.subscribe(f"denso/{machine_id}/acks", qos=1)

    def on_message(c, userdata, msg):
        nonlocal ack_received
        try:
            ack_data = json.loads(msg.payload.decode("utf-8"))
            if ack_data.get("command_id") == cmd_id:
                ack_received = ack_data
        except Exception:
            pass

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Connecting to MQTT broker {settings.MQTT_HOST}:{settings.MQTT_PORT}...")
    client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=10)
    client.loop_start()

    time.sleep(0.5)  # Allow subscribe to register
    cmd_topic = f"denso/{machine_id}/commands"
    print(f"Publishing command to {cmd_topic}: {json.dumps(payload, indent=2)}")
    client.publish(cmd_topic, json.dumps(payload), qos=1)

    start_t = time.time()
    while ack_received is None and (time.time() - start_t) < timeout_s:
        time.sleep(0.1)

    client.loop_stop()
    client.disconnect()

    if ack_received:
        print("\n=== RECEIVED ACK ===")
        print(json.dumps(ack_received, indent=2))
        return ack_received
    else:
        print(f"\n[Timeout] No ACK received from {machine_id} within {timeout_s}s.")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send command to DENSO machine via MQTT")
    parser.add_argument("machine_id", help="Target machine ID (e.g. COMP-TB-01)")
    parser.add_argument("command", choices=["SET_RPM", "STOP_TEST"], help="Command name")
    parser.add_argument("--rpm", type=float, help="Target RPM for SET_RPM")

    args = parser.parse_args()
    params = {}
    if args.command == "SET_RPM":
        if args.rpm is None:
            print("Error: --rpm is required for SET_RPM")
            sys.exit(1)
        params["rpm"] = args.rpm

    res = send_command(args.machine_id, args.command, params)
    if res and res.get("status") == "OK":
        sys.exit(0)
    elif res and res.get("status") == "REJECTED":
        sys.exit(2)
    else:
        sys.exit(1)
