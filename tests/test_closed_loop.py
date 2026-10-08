# tests/test_closed_loop.py
import time
from iot.event_bus import EventBus
from iot.actuator_dispatcher import ActuatorDispatcher
from iot.action_approval import ActionApproval
from iot.telemetry_receiver import TelemetryReceiver

from machines.cnc_milling import CncMilling
from machines.robot_arm import RobotArm


def run_pipeline_test():
    print("=" * 60)
    print("BẮT ĐẦU TEST KHÉP KÍN HỆ THỐNG IOT & MÁY MÓC (MOCK AGENT)")
    print("=" * 60)

    # 1. Khởi tạo hạ tầng Core
    bus = EventBus(max_workers=4)
    dispatcher = ActuatorDispatcher(event_bus=bus)
    approval = ActionApproval(dispatcher=dispatcher, event_bus=bus)
    receiver = TelemetryReceiver(event_hub=bus, heartbeat_interval_sec=2.0, alert_cooldown_sec=5.0)

    # 2. Khởi tạo và đăng ký thiết bị
    cnc = CncMilling(event_hub=bus)
    robot = RobotArm(event_hub=bus)
    dispatcher.register_machines([cnc, robot])

    # 3. Giả lập hành vi của AI Agent (Lắng nghe Alert trên Bus)
    def mock_ai_agent(event):
        label = event.get("label")
        if label != "alert":
            return
        
        machine_id = event.get("machine_id")
        anomalies = event.get("anomalies", [])
        print(f"\n🤖 [MOCK AI AGENT] Phát hiện cảnh báo từ {machine_id}:")
        for anom in anomalies:
            print(f"   - Tham số: {anom.get('param')} | Lý do: {anom.get('reason')}")

        # Tình huống: Máy CNC bị quá nhiệt do thiếu dầu bôi trơn
        if machine_id == "MC-MILL-01":
            # Hành động 1: Giảm tải tức thời (Lệnh LOW RISK -> Tự động thi hành)
            print("🤖 [MOCK AI AGENT] Đề xuất can thiệp nhanh: Hạ Feed Override xuống 50% (LOW RISK)")
            approval.process_action_request({
                "machine_id": "MC-MILL-01",
                "command": "SET_FEED_OVERRIDE",
                "payload": {"override_pct": 50.0},
                "risk_level": "LOW",
                "reason": "AI can thiệp khẩn cấp giảm sinh nhiệt cắt"
            })

            # Hành động 2: Yêu cầu bảo trì tra dầu (Lệnh HIGH RISK -> Phải duyệt)
            print("🤖 [MOCK AI AGENT] Đề xuất lệnh can thiệp bảo trì: Bơm dầu bôi trơn (HIGH RISK)")
            ticket = approval.process_action_request({
                "machine_id": "MC-MILL-01",
                "command": "REFILL_SPINDLE_LUBRICANT",
                "risk_level": "HIGH",
                "reason": "AI chẩn đoán nguyên nhân gốc do thiếu bôi trơn trục chính"
            })
            
            # Giả lập kỹ sư Dashboard kiểm tra và bấm duyệt sau 1 giây
            if ticket and ticket.get("approval_id"):
                action_id = ticket["approval_id"]
                print(f"👨‍💻 [MOCK ENGINEER] Nhận ticket {action_id}. Bấm [DUYỆT] sau 1s...")
                time.sleep(1.0)
                approval.approve(action_id)

    # Đăng ký AI Agent lắng nghe EventBus
    bus.subscribe("alert", mock_ai_agent)

    # Đăng ký log theo dõi command_response
    def log_response(event):
        print(f"⚡ [PLC FEEDBACK] Máy {event.get('machine_id')} thi hành lệnh '{event.get('command')}': "
              f"Status={event.get('status')} | {event.get('details', {}).get('execution_detail')}")
    bus.subscribe("command_response", log_response)

    # 4. GIAI ĐOẠN 1: Chạy bình thường trong 3 giây
    print("\n--- GIAI ĐOẠN 1: Máy chạy bình thường (Kiểm tra Heartbeat 2s) ---")
    for _ in range(3):
        tele = cnc.generate_telemetry()
        receiver.process({
            "event_type": "telemetry",
            "machine_id": cnc.machine_id,
            "machine_type": cnc.machine_type,
            "payload": tele
        })
        time.sleep(1.0)

    # 5. GIAI ĐOẠN 2: Tiêm lỗi thiếu dầu bôi trơn
    print("\n--- GIAI ĐOẠN 2: Tiêm lỗi thiếu dầu (SPINDLE_BEARING_LACK_OF_LUBE) ---")
    cnc.inject_fault("SPINDLE_BEARING_LACK_OF_LUBE")

    # Vòng lặp mô phỏng vật lý biến thiên (nhiệt tăng dần -> kích hoạt alert)
    for step in range(12):
        tele = cnc.generate_telemetry()
        print(f"   [T+{step}s] Temp: {tele['Spindle_Temp_C']}°C | Feed: {tele['Path_Feedrate_Override_Pct']}% | "
              f"Vib: {tele['Vibration_RMS_mm_s']} mm/s | Faults: {tele['Simulated_Active_Faults']}")

        receiver.process({
            "event_type": "telemetry",
            "machine_id": cnc.machine_id,
            "machine_type": cnc.machine_type,
            "payload": tele
        })
        time.sleep(0.8)

    # 6. Kiểm tra lại lịch sử Audit Trail của Dispatcher
    print("\n--- GIAI ĐOẠN 3: Kiểm tra Audit Trail ---")
    history = dispatcher.get_history("MC-MILL-01")
    print(f"Tổng số lệnh đã thực thi thành công trên MC-MILL-01: {len(history)}")
    for record in history:
        print(f" - [{record['timestamp']}] {record['command']} -> {record['status']}")

    bus.shutdown()
    print("\n✅ KIỂM THỬ HOÀN TẤT THÀNH CÔNG!")


if __name__ == "__main__":
    run_pipeline_test()