🏭 DENSO Smart Maintenance Agent (IIoT & Knowledge AI)
Dự án tham dự DENSO Factory Hacks 2026

Hệ thống AI Agent chủ động giám sát IIoT thời gian thực, chẩn đoán sự cố dựa trên RAG tri thức và điều phối can thiệp máy móc an toàn (Human-in-the-Loop).

📌 1. Bối cảnh & Bài toán đặt ra
Trong môi trường sản xuất linh kiện ô tô chính xác của DENSO (bugi, kim phun, cụm HVAC...):

Downtime tốn kém: Mỗi phút dừng dây chuyền đột ngột (Unplanned Downtime) gây thiệt hại lớn về sản lượng và tiến độ giao hàng Just-In-Time.

Tra cứu cẩm nang mất thời gian: Tài liệu kỹ thuật (SOP, cẩm nang máy) đồ sộ khiến kỹ thuật viên mất nhiều thời gian tra cứu mã lỗi khi máy gặp sự cố.

Mất mát tri thức chuyên gia: Kinh nghiệm xử lý lỗi của các thợ bậc cao thường nằm ở dạng ghi chép rời rạc hoặc truyền miệng, chưa được số hóa thành tri thức chung.

💡 2. Giải pháp: Hệ thống 3 lớp (3-Tier Industrial Architecture)
Hệ thống kết hợp giữa IoT Gateway lọc dữ liệu biên, RAG đóng gói tri thức nhà xưởng và AI Agent tự hành với cơ chế Human-in-the-Loop (HITL):

┌─────────────────────────┐
│ 1. FACTORY FLOOR        │  5 máy móc đại diện DENSO (CNC, Cobot, Mold, AGV, Tester)
│    (Telemetry & Act)    │  Bắn thông số chu kỳ: Rung động, nhiệt độ, áp suất...
└────────────┬────────────┘
             │ Giao thức công nghiệp (OPC UA / Telemetry stream)
             ▼
┌─────────────────────────┐
│ 2. EDGE IOT GATEWAY     │  Lọc ngưỡng bất thường (Anomaly Filtering) để tối ưu băng thông
│    (Rule & Protection)  │  Kiểm tra tính hợp lệ (Sanity check) trước khi nạp lệnh vào máy
└────────────┬────────────┘
             │ Event Bus / Function Calling
             ▼
┌─────────────────────────┐
│ 3. AUTONOMOUS AI AGENT  │  Nhận alert ➔ Tra cứu tài liệu (RAG) ➔ Ra quyết định bảo trì
│    (Reasoning & HITL)   │  Tự động: Tạo ticket ERP, thông báo Telegram
│                         │  Nguy cơ cao (Can thiệp PLC): Chờ Kỹ sư bấm DUYỆT (HITL)
└─────────────────────────┘
⚙️ 3. Thiết bị mô phỏng trong nhà máy (machines/)
Hệ thống mô phỏng 5 dòng máy móc chủ lực trong chu trình sản xuất của DENSO:

CNC_LATHE_01 (Máy tiện CNC trục chính): Gia công vỏ bugi, kim phun. Theo dõi nhiệt độ trục chính (spindle_temp), độ rung (vibration), lưu lượng dầu làm mát.

MOLD_PRESS_02 (Máy ép nhựa kỹ thuật): Đúc vỏ giắc cắm, cụm điều hòa. Theo dõi nhiệt độ buồng gia nhiệt (barrel_temp), áp suất phun (injection_pressure).

COBOTTA_ARM_03 (Robot cộng tác DENSO COBOTTA Pro): Lắp ráp, siết ốc chính xác. Theo dõi dòng motor (motor_current), nhiệt độ driver khớp xoay (joint_temp).

AGV_CARRIER_04 (Xe tự hành nội bộ): Chuyển phôi và khay linh kiện giữa các xưởng. Theo dõi dung lượng pin (battery_soc), vận tốc xe.

LEAK_TESTER_05 (Bàn kiểm tra kín khí): Thử áp suất rò rỉ kim phun theo chuẩn IATF 16949. Theo dõi tốc độ tụt áp buồng thử (pressure_drop_rate).

🚀 4. Điểm nhấn kỹ thuật nổi bật
Edge Anomaly Filtering: Tránh spam API LLM; chỉ những telemetry vượt ngưỡng an toàn (hoặc có xu hướng suy thoái) mới kích hoạt Agent.

RAG Domain-Specific: Truy vấn chính xác cẩm nang sự cố và kinh nghiệm sửa chữa thực tế của xưởng DENSO.

Human-in-the-Loop (HITL) via LangGraph: AI không tự tiện dừng máy hay ghi đè thông số PLC nếu chưa có sự phê duyệt từ kỹ sư phụ trách ca trực.

Continuous Learning Loop: Sau khi sửa xong, giải pháp thực tế của thợ kỹ thuật được lưu ngược lại Vector DB để nâng cao độ chính xác cho các lần sau.

## Chạy dashboard mô phỏng

Chạy từ thư mục gốc dự án:

```powershell
python main.py
```

Mở `http://localhost:8000` trong trình duyệt. Dashboard tự cập nhật telemetry, xu hướng các mẫu gần nhất, cảnh báo/chẩn đoán agent và các lệnh đang chờ kỹ sư phê duyệt. Chọn **Duyệt lệnh** để gửi lệnh đến simulator hoặc **Từ chối** để giữ máy không nhận lệnh đó. Ticket và thông báo bảo trì được tạo khi agent xử lý cảnh báo, không phụ thuộc quyết định PLC.

Lệnh đã đề xuất không tự hết hạn. Nếu dashboard được tải lại, trạng thái được giữ trong bộ nhớ đến khi simulator tắt.

Có thể đổi cổng hoặc chu kỳ gửi telemetry:

```powershell
python main.py --port 8080 --interval 0.5
```

Đây là dashboard mô phỏng cục bộ, không kết nối PLC thật và chỉ sử dụng thư viện Python chuẩn. Nút phê duyệt chỉ gửi lệnh tới máy mô phỏng; không dùng server này như giao diện điều khiển sản xuất.

Chạy kiểm thử luồng phê duyệt:

```powershell
python -m unittest discover -s tests -v
```