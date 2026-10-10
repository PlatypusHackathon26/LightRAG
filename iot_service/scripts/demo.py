"""
Demo runner for DENSO test bench monitoring and closed-loop control (Phase 2).
Usage:
  python -m iot_service.scripts.demo condenser_fan_failure
  python -m iot_service.scripts.demo refrigerant_leak --approve
  python -m iot_service.scripts.demo condenser_fouled --approve
  python -m iot_service.scripts.demo low_oil
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
import paho.mqtt.client as mqtt

# Ensure stdout handles UTF-8 on Windows console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure iot_service is on sys.path
script_dir = Path(__file__).resolve().parent
iot_dir = script_dir.parent
if str(iot_dir) not in sys.path:
    sys.path.insert(0, str(iot_dir))

from app.config import settings


def publish_sim_control(machine_id: str, scenario: str, ramp_s: float = 10.0):
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2 if hasattr(mqtt, "CallbackAPIVersion") else None,
        client_id=f"demo-runner-{int(time.time())}",
    )
    payload = {
        "scenario": scenario,
        "machine_ids": [machine_id],
        "ramp_s": ramp_s,
    }
    client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=10)
    client.publish("denso/sim/control", json.dumps(payload), qos=1)
    client.disconnect()


def api_get(endpoint: str, base_url: str):
    url = f"{base_url}{endpoint}"
    req = urllib.request.Request(url, headers={"X-API-Key": settings.IOT_API_KEY})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post(endpoint: str, base_url: str, data: dict = None):
    url = f"{base_url}{endpoint}"
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "X-API-Key": settings.IOT_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_demo(machine_id: str, scenario: str, auto_approve: bool = False, gateway_url: str = "http://localhost:9700"):
    print("=" * 70)
    print(f" DENSO COMPRESSOR TEST BENCH - KICH BAN DEMO: {scenario.upper()}")
    print(f" Thiet bi muc tieu: {machine_id}")
    print(f" Agent Gateway URL: {gateway_url}")
    print("=" * 70)

    # Buoc 1: Kich hoat kich ban tren Simulator
    print(f"\n[BUOC 1] Gui lenh doi kich ban '{scenario}' (ramp=10s) toi Simulator...")
    try:
        publish_sim_control(machine_id, scenario, ramp_s=10.0)
        print("  -> Da gui thanh cong qua MQTT topic 'denso/sim/control'")
    except Exception as e:
        print(f"  -> [Canh bao] Khong the gui MQTT truc tiep ({e}). Tiep tuc theo doi API.")

    # Buoc 2: Theo doi cac moc quan trong
    print("\n[BUOC 2] Dang lang nghe vien trac va cac moc su kien tu Gateway...")
    start_time = time.time()
    seen_warn = False
    seen_err = False
    target_incident = None
    target_action = None

    max_wait = 60.0
    while time.time() - start_time < max_wait:
        elapsed = int(time.time() - start_time)

        # 1. Kiem tra su kien
        try:
            ev_data = api_get(f"/api/v1/machine/{machine_id}/events?minutes=5", gateway_url)
            events = ev_data.get("events", [])
            for ev in events:
                if not seen_warn and ev["event_type"] == "WARNING":
                    seen_warn = True
                    print(f"  [MOC 1 - {elapsed}s] [WARN] CANH BAO SO (Early Warning): {ev['error_code']}")
                    print(f"             Chi tiet: {ev['message']}")
                if not seen_err and ev["event_type"] == "ERROR":
                    seen_err = True
                    print(f"  [MOC 2 - {elapsed}s] [ERR] LOI BAO VE MAY (PLC Critical Error): {ev['error_code']}")
                    print(f"             Chi tiet: {ev['message']}")
        except Exception:
            pass

        # 2. Kiem tra Incidents & Actions
        try:
            incidents = api_get("/agent/incidents", gateway_url)
            for inc in incidents:
                if inc["device"] == machine_id and inc["status"] in ("active", "awaiting_approval"):
                    target_incident = inc
                    if inc.get("proposedAction"):
                        target_action = inc["proposedAction"]
                    break
        except Exception:
            pass

        if target_incident and target_action:
            print(f"  [MOC 3 - {elapsed}s] [INCIDENT] SU CO DA MO: {target_incident['id']} ({target_incident['severity'].upper()})")
            print(f"             Tieu de: {target_incident['alarm']}")
            print(f"             Hanh dong de xuat: {target_action['titleVi']}")
            print(f"             Lenh: {target_action['items'][0]['params']}")
            break

        time.sleep(2.0)

    if not target_incident:
        print(f"\n[Ket qua] Het thoi gian cho {max_wait}s: Chua thay su co mo tren {machine_id}.")
        return False

    # Buoc 3: Phe duyet hanh dong (HITL)
    if auto_approve and target_action:
        print(f"\n[BUOC 3] Ky su van hanh bam 'Xac nhan' phe duyet the HITL ({target_action['id']})...")
        try:
            approve_res = api_post(f"/agent/actions/{target_action['id']}/approve", gateway_url)
            print("  [MOC 4] [ACK] Nhan phan hoi PLC ACK:")
            print(f"             {approve_res.get('ack')}")
        except urllib.error.HTTPError as he:
            print(f"  [Loi duyet] {he.code}: {he.read().decode('utf-8')}")
            return False

        # Buoc 4: Quan sat vong dieu khien kin (Closed-loop Sensitivity)
        print("\n[BUOC 4] Quan sat vong dieu khien kin sau khi ha tai (doi 8s)...")
        time.sleep(8.0)
        try:
            telemetry = api_get(f"/agent/telemetry/{machine_id}", gateway_url)
            print(f"  [MOC 5] Vien trac hien tai cua {machine_id}:")
            for p in telemetry.get("points", []):
                flag = "[BAT THUONG]" if p.get("isAnomalous") else "[BINH THUONG]"
                print(f"             - {p['label']}: {p['value']} {p['unit']} {flag}")
        except Exception as te:
            print(f"  [Loi doc telemetry] {te}")

    print("\n" + "=" * 70)
    print(" HOAN TAT KICH BAN DEMO.")
    print("=" * 70)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DENSO Test Bench Scenario Demo Runner")
    parser.add_argument(
        "scenario",
        choices=["normal", "refrigerant_leak", "condenser_fan_failure", "condenser_fouled", "low_oil"],
        help="Kich ban thu nghiem",
    )
    parser.add_argument("--machine", default="COMP-TB-01", help="ID may (mac dinh: COMP-TB-01)")
    parser.add_argument("--approve", action="store_true", help="Tu dong bam phe duyet hanh dong HITL")
    parser.add_argument("--gateway", default="http://localhost:9700", help="URL Agent Gateway")

    args = parser.parse_args()
    success = run_demo(args.machine, args.scenario, auto_approve=args.approve, gateway_url=args.gateway)
    sys.exit(0 if success else 1)
