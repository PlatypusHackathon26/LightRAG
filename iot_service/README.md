# HỆ THỐNG IOT GIÁM SÁT VÀ PHẢN ỨNG SỰ CỐ BỆ THỬ MÁY NÉN DENSO (GIAI ĐOẠN 3 & 4: DASHBOARD PHÒNG ĐIỀU KHIỂN & AGENT REACT)

> **Lưu ý quan trọng**: Dự án phục vụ cuộc thi Hackathon. Các chỉ số kỹ thuật vận hành, ngưỡng cảnh báo, mã lỗi và tên định danh thiết bị (`COMP-TB-01`, `COMP-TB-02`) trong dự án này là **GIẢ LẬP**, được xây dựng dựa trên nguyên lý hoạt động của catalogue và poster sự cố điều hòa DENSO, **không phải số liệu đo đạc thực tế bí mật của tập đoàn DENSO**. Toàn bộ các playbook và kiến thức neo là do nhóm biên soạn từ poster và catalogue tài liệu kỹ thuật, không phải quy trình vận hành chính thức của DENSO.

---

## 1. Tổng quan dự án

Hệ thống IoT cho bệ thử máy nén DENSO là tầng hạ tầng thu thập viễn trắc (telemetry), phát hiện bất thường sớm, quản lý vòng đời sự cố (Incidents), chẩn đoán tự động bằng **Agent LLM theo vòng lặp ReAct**, tra cứu tri thức kỹ thuật qua **LightRAG**, phê duyệt hành động có sự can thiệp của con người (**HITL - Human-In-The-Loop**), thực thi kiểm soát vòng kín (**Closed-Loop Control**), và **Dashboard phòng điều khiển công nghiệp giám sát máy và hoạt động Agent theo thời gian thực (Giai đoạn 4A & 4B)**.

---

## 2. Dashboard phòng điều khiển công nghiệp (Giai đoạn 4A & 4B)

Dashboard là giao diện quan sát trực quan thời gian thực dành cho kỹ sư vận hành trong phòng điều khiển, được thiết kế theo các nguyên tắc:
- **Chỉ đọc tuyệt đối (Read-Only)**: Mọi endpoint API và giao diện Dashboard hoàn toàn chỉ phục vụ tác vụ đọc (`GET`). Không có bất kỳ nút bấm, form hay API nào gửi lệnh can thiệp bệ thử, thay đổi kịch bản hay phê duyệt/từ chối hành động.
- **Minh bạch hoạt động của Agent**: Người vận hành trên Dashboard theo dõi trực tiếp Agent đang làm gì (kết luận nguyên nhân, độ tin cậy, lệnh đề xuất, đếm ngược thời hạn HITL, mốc thực thi và kết quả ACK), nhưng **không thực hiện phê duyệt/từ chối tại đây** (việc phê duyệt và tương tác hội thoại thuộc về WebUI của nhóm).
- **Ý nghĩa trạng thái "Đã giảm nhẹ" (Mitigated) so với "Bình thường" (Normal)**:
  - Khi sự cố xảy ra, Agent đề xuất hoặc tự động hạ tốc độ máy nén (ví dụ `SET_RPM 1000`).
  - Sau khi hạ tốc độ, các chỉ số nguy cấp (`critical`) như nhiệt độ xả và áp suất xả giảm xuống vùng an toàn hơn, nhưng nguyên nhân gốc rễ (như hỏng quạt dàn ngưng, rò rỉ gas) vẫn còn tồn tại.
  - Máy chuyển sang trạng thái **🛡 Đã giảm nhẹ** (hiển thị màu xanh dương nổi bật, khác với **✓ Bình thường** màu xanh lục). Điều này nhắc nhở kỹ sư rằng máy đang vận hành ở chế độ giảm tải tạm thời và phiếu sửa chữa vật lý vẫn đang mở.
- **Không cần bước Build (Zero-Build Frontend)**: Giao diện xây dựng bằng HTML5, CSS hiện đại và JavaScript thuần, được FastAPI phục vụ trực tiếp tại đường dẫn `/dashboard/`.
- **Hoạt động Offline (Zero-CDN)**: Toàn bộ thư viện đồ họa (Chart.js v4.4.3 UMD) được tải sẵn và đặt tại `dashboard/vendor/chart.umd.min.js`, đảm bảo hệ thống vận hành hoàn hảo ngay cả khi mất kết nối mạng Internet.
- **Không hard-code cấu hình**: Mọi tên máy, nhãn hiển thị, đơn vị đo, ngưỡng cảnh báo/nguy hiểm và thang đo đều được lấy động từ `config/machines.yaml` thông qua API. Thêm máy hoặc metric mới chỉ cần chỉnh sửa file YAML.

### 2.1. Cách truy cập Dashboard & Tích hợp WebUI
- **Chế độ thông thường**: Mở trình duyệt tại địa chỉ `http://localhost:9710/dashboard/`.
- **Chế độ màn hình lớn / Kiosk (`?kiosk=1`)**: Mở `http://localhost:9710/dashboard/?kiosk=1`. Chế độ này sẽ ẩn thanh điều khiển trên cùng, phóng to kích thước chữ và số liệu viễn trắc, tự động ẩn con trỏ chuột sau vài giây không tương tác, rất phù hợp để trình chiếu trên màn hình TV lớn của phòng điều hành.
- **Tích hợp WebUI Agent Copilot**: Cấu hình biến môi trường `WEBUI_URL=http://localhost:5173`. Trên tab "HOẠT ĐỘNG AGENT" của Dashboard sẽ xuất hiện liên kết `Mở trong Agent Copilot ↗` giúp kỹ sư chuyển ngay sang WebUI để bấm duyệt/từ chối hoặc chat với Agent. Nếu để trống biến `WEBUI_URL`, liên kết sẽ tự động ẩn đi.

### 2.2. Cách đọc giao diện & Chỉ số viễn trắc
1. **Thanh trạng thái Agent (ở đầu trang)**:
   - **Chế độ tự chủ (`autonomy_mode`)**: `ADVISORY` (chỉ cảnh báo), `HITL` (chờ kỹ sư duyệt lệnh), hoặc `AUTO_SAFE` (tự động hạ tốc độ an toàn). Rê chuột vào để xem giải thích chi tiết.
   - **Công nghệ phân tích (`agent_mode`)**: `LLM ReAct` hoặc `Playbook Luật`.
   - **Trạng thái Agent (`agent_enabled`)**: `Bật` (đèn xanh) hoặc `Tắt khẩn cấp` (đèn đỏ khi `AGENT_ENABLED=false`).
2. **Thanh trạng thái hệ thống**:
   - Trạng thái kết nối MQTT Broker và Cơ sở dữ liệu TimescaleDB.
   - Trạng thái truyền thông thời gian thực: `● TRỰC TIẾP (SSE)` hoặc `● DỰ PHÒNG (POLL)`.
   - Thời gian nhận dữ liệu gần nhất (ví dụ: `2 giây trước`).
3. **Thẻ máy & Biểu ngữ hoạt động Agent**:
   - **Khi có sự cố mở**: Hiển thị mã sự cố, mức độ nghiêm trọng, kết luận nguyên nhân và độ tin cậy.
   - **Khi có hành động chờ duyệt (HITL)**: Hiển thị biểu ngữ màu đỏ nổi bật `⚡ Đang chờ kỹ sư duyệt lệnh (SET_RPM) còn X giây` có đồng hồ đếm ngược thời gian thực (không có nút bấm).
   - **Khi đã thực thi giảm nhẹ**: Hiển thị `🛡 Đã thực thi can thiệp: Agent tự động (hoặc Người duyệt) hạ tốc độ xuống 1000 rpm lúc 10:15`. Thẻ máy gắn huy hiệu `🛡 ĐÃ GIẢM NHẸ`.
4. **Tab kép: "CẢNH BÁO & SỰ KIỆN" vs "HOẠT ĐỘNG AGENT"**:
   - Chuyển tab nhanh chóng để xem luồng lỗi PLC hoặc dòng thời gian các sự cố mở và lịch sử hành động (lệnh, tham số, người quyết định, kết quả ACK).
5. **Đánh dấu can thiệp trên Biểu đồ chi tiết máy (`#/machine/{id}`)**:
   - Khi mở modal chi tiết máy, bên trên biểu đồ chuỗi thời gian hiển thị các mốc can thiệp của Agent (`Agent đề xuất`, `Duyệt lệnh (user:operator)`, `ACK 200`, `Hết hạn không thực thi`). Người xem thấy rõ ngay nhiệt độ và áp suất giảm xuống sau thời điểm Agent can thiệp hạ tốc độ.

### 2.3. Cơ chế thời gian thực: SSE & Bản tin Agent
- Luồng SSE đẩy tức thì các sự kiện:
  - `incident`: Khi có sự cố mới, thay đổi trạng thái hoặc đóng sự cố.
  - `action`: Khi có hành động được đề xuất, duyệt, từ chối, hết hạn hoặc nhận phản hồi ACK từ PLC.
  - Các bản tin được làm sạch (sanitized), tuyệt đối không để lộ prompt hệ thống hay khóa API.

---

## 3. Kiến trúc hệ thống IoT & Agent

```
[Simulator bệ thử]  --MQTT-->  [Mosquitto]  --subscribe-->  [Ingest]  --> [TimescaleDB]
   ^   metrics/events                                          |  ^           |
   |                                                           |  |           | (time_bucket / series)
   | commands            [Threshold Monitor] <-- đọc DB -------+  |           v
   |                              |                               |    [Dashboard API & SSE]
   +-- acks <-- [Command Executor] <-- [Gateway: incidents/actions/HITL]      |  /dashboard
                                          ^   |                       |       v
                                          |   v                       |   [Web Control Room UI]
                                      [WebUI /agent/*]  <-------------+
```

---

## 4. Hướng dẫn khởi chạy toàn bộ hệ thống

### Bước 1: Khởi động Hạ tầng Docker (Mosquitto & TimescaleDB)
```powershell
docker compose -f iot_service/docker-compose.yml up -d --wait
```
Cả hai chỉ nghe trên `127.0.0.1` (1883, 5433). `db/init.sql` tạo bảng ở lần chạy đầu; dữ liệu nằm trong volume
`denso-iot_timescale-data` (`down -v` để xoá). `denso/scripts/serve_chat.ps1 -WithIoT` tự chạy bước này.

### Bước 2: Khởi động IoT Service, Dashboard & Gateway (:9710)
```powershell
cd iot_service
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="."
python -m uvicorn app.main:app --host 127.0.0.1 --port 9710
```
Truy cập Dashboard tại: `http://localhost:9710/dashboard/` (hoặc `http://localhost:9710/dashboard/?kiosk=1`).

### Bước 3: Khởi động Simulator Bệ thử Máy nén
```powershell
cd iot_service
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="."
python -m simulator.cli run
```

### Bước 4: Khởi động WebUI Agentic (Duyệt lệnh HITL & Chat)
WebUI nói chuyện với **DENSO Agent Gateway :9700**; gateway chuyển tiếp sự cố, telemetry và duyệt lệnh
sang service này (:9710) khi chạy với `DENSO_IOT_URL=http://127.0.0.1:9710`. Cách gọn nhất là để
`denso/scripts/serve_chat.ps1 -WithIoT -WithUI` bật cả gateway, service này, Mosquitto và simulator
(xem `denso/README.md` mục 4.4). WebUI cần `VITE_AGENT_LIVE=true` trong
`lightrag_webui/.env.development.local`.

---

## 5. Thử nghiệm thực tế: Kịch bản Agent trên Dashboard

### 5.1. Bơm sự cố Hỏng quạt (`condenser_fan_failure`) ở chế độ HITL
```powershell
cd iot_service
.\.venv\Scripts\Activate.ps1
python -m simulator.cli set COMP-TB-01 condenser_fan_failure
```
**Quan sát trên Dashboard**:
- Thẻ máy `COMP-TB-01` chuyển sang cảnh báo/nguy hiểm.
- Xuất hiện biểu ngữ: `⚡ Đang chờ kỹ sư duyệt lệnh (SET_RPM) còn 58s`.
- Tab "HOẠT ĐỘNG AGENT" hiển thị sự cố mở `Quạt dàn ngưng hỏng` (tin cậy 95%) và hành động đề xuất `SET_RPM (rpm=1000)`.

### 5.2. Phê duyệt hành động từ WebUI hoặc API Gateway
Phê duyệt qua API Gateway:
```powershell
# Lấy danh sách actions và bấm approve action_id tương ứng
curl -X POST http://localhost:9710/agent/actions/ACT-0001/approve -H "Content-Type: application/json" -d "{\"actor\": \"user:engineer\"}"
```
**Quan sát trên Dashboard (Cập nhật thời gian thực không tải lại trang)**:
- Biểu ngữ hành động chuyển thành `🛡 Đã thực thi can thiệp: Người duyệt (user:engineer) hạ tốc độ xuống 1000 rpm lúc ...`.
- Thẻ máy chuyển sang trạng thái `🛡 ĐÃ GIẢM NHẸ`.
- Tốc độ máy nén giảm xuống 1000 rpm, nhiệt độ đầu xả và áp suất xả giảm dần trên biểu đồ thời gian kèm mốc can thiệp đánh dấu.

### 5.3. Thử nghiệm Hết hạn không duyệt (Action Expired)
- Bơm sự cố và không bấm duyệt trong 60 giây (`ACTION_TTL_S=60`).
- Dashboard tự động cập nhật trạng thái hành động thành `Hết hạn, không thực thi`. Tốc độ máy nén giữ nguyên không đổi.

### 5.4. Thử nghiệm Tự động hạ tốc độ (`AUTONOMY_MODE=auto_safe`)
- Đặt `AUTONOMY_MODE=auto_safe` trong file cấu hình.
- Bơm sự cố: Agent tự động thực thi lệnh `SET_RPM` (nhãn hiển thị `Agent tự động`) với giới hạn tối đa 2 lần mỗi sự cố và cách nhau tối thiểu 120 giây.

---

## 6. Chạy kiểm thử tự động (Pytest)

Chạy toàn bộ 59 bài kiểm thử bao phủ toàn bộ hệ thống:
```powershell
cd iot_service
.\.venv\Scripts\pytest.exe tests -v
```
**Kết quả: 59/59 bài test XANH (100% Pass)**:
* `test_dashboard.py`: 10 bài test kiểm thử toàn diện: phục vụ file tĩnh, tổng hợp overview kèm trạng thái Agent, cờ `is_mitigated`, mốc dòng thời gian `GET /dashboard/agent/timeline`, chặn toàn bộ method non-GET trả 405, xác thực token, và phát sóng SSE cho incident và action.
* 49 bài test của Giai đoạn 1, 2, và 3 (Simulator, Monitor, Dedup, Tool API, ReAct Agent, Guardrails, Playbooks).

---

## 7. Khắc phục sự cố thường gặp (Troubleshooting)

1. **Dashboard không hiển thị số liệu / Báo "Mất kết nối, đang thử lại..."**:
   - Kiểm tra service IoT FastAPI đã chạy tại cổng 9710 chưa (`http://localhost:9710/health`).
   - Kiểm tra Simulator đã được bật để phát dữ liệu lên MQTT chưa.
2. **Không thấy liên kết "Mở trong Agent Copilot"**:
   - Kiểm tra biến `WEBUI_URL` trong file `.env` (mặc định: `http://localhost:5173`).
3. **Vì sao Dashboard không có nút bấm Duyệt / Từ chối?**:
   - Theo nguyên tắc phân quyền và an toàn công nghiệp, Dashboard phục vụ mục đích quan sát phòng điều khiển (Read-Only) để theo dõi diện rộng và trình chiếu kiosk. Quyền can thiệp, duyệt lệnh HITL và đàm thoại chẩn đoán được tập trung quản lý tại WebUI Agent Copilot của nhóm.
