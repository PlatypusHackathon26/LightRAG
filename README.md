# 🏭 DENSO Smart Maintenance Agent

### IIoT Real-time Monitoring · RAG Knowledge AI · Human-in-the-Loop

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Zero Dependency](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 🏁 Dự án tham dự **DENSO Factory Hacks 2026**
> Hệ thống AI Agent chủ động giám sát IIoT thời gian thực, chẩn đoán sự cố dựa trên **RAG** tri thức nhà xưởng và điều phối can thiệp máy móc an toàn với cơ chế **Human-in-the-Loop (HITL)** — toàn bộ giao diện theo phong cách chat kiểu ChatGPT/Gemini.

---

## 📌 1. Bối cảnh & Bài toán đặt ra

Trong môi trường sản xuất linh kiện ô tô chính xác của DENSO (bugi, kim phun, cụm HVAC...):

- **Downtime tốn kém** — mỗi phút dừng dây chuyền đột ngột (*Unplanned Downtime*) gây thiệt hại lớn về sản lượng và tiến độ giao hàng Just-In-Time.
- **Tra cứu cẩm nang mất thời gian** — tài liệu kỹ thuật (SOP, cẩm nang máy) đồ sộ khiến kỹ thuật viên mất nhiều thời gian tra cứu mã lỗi khi máy gặp sự cố.
- **Mất mát tri thức chuyên gia** — kinh nghiệm xử lý lỗi của các thợ bậc cao thường nằm ở dạng ghi chép rời rạc hoặc truyền miệng, chưa được số hóa.

## 💡 2. Giải pháp: Kiến trúc 3 lớp

```text
┌─────────────────────────────┐
│ 1. FACTORY FLOOR            │  5 máy mô phỏng DENSO (CNC, Robot, Ép nhựa, AOI, AMR)
│    (Telemetry & Act)        │  Bắn thông số chu kỳ: rung, nhiệt, áp suất, pin...
└────────────┬────────────────┘
             │ Event Bus (in-memory, async)
             ▼
┌─────────────────────────────┐
│ 2. EDGE IOT GATEWAY         │  Lọc ngưỡng bất thường + Rate-of-Change (ROC)
│    (Rule & Protection)      │  Cooldown chống spam · Sanity check trước khi nhận lệnh
└────────────┬────────────────┘
             │  event: "normal" / "alert" / "action_command"
             ▼
┌─────────────────────────────┐
│ 3. AUTONOMOUS AI AGENT      │  Nhận alert ➜ Tra cứu cẩm nang (RAG) ➜ Dịch thành lệnh
│    (Reasoning & HITL)       │  Lệnh LOW  ➜ thực thi ngay
│                             │  Lệnh HIGH ➜ thẻ DUYỆT trong khung chat (chờ kỹ sư)
└─────────────────────────────┘
```

---

## 🖥️ 3. Giao diện — kiểu ChatGPT, 3 cột

```text
┌──────────────────────────────────────────────────────────────────────┐
│  🔴 DENSO AI-AGENT 2026   TRỰC TUYẾN   12:00:00   [📤 Upfile lên RAG]│
├───────────────┬──────────────────────────────────┬───────────────────┤
│ 👤 USER       │  ⚠ CẢNH BÁO THIẾT BỊ (bubble)  │ 🏭 MÁY MÓC       │
│  CHỦ ĐỘNG    │  ✦ AI_RAG: Khuyến nghị...       │  MC-MILL-01  ●    │
│  - Chat #1    │  [user bubble]                   │  MC-ROBOT-01 ●    │
│               │  ┌ ⏳ LỆNH CHỜ DUYỆT ─────┐     │  ...  LIVE 1s     │
│ ⚠ SYSTEM      │  │ [MC-MILL-01] SAFE_STOP  │     │                   │
│  ALERT        │  │ [✔ Duyệt] [✖ Từ chối]   │     │                   │
│  - MC-MILL..  │  └─────────────────────────┘     │                   │
│               │  [ô nhập · Enter gửi]            │                   │
└───────────────┴──────────────────────────────────┴───────────────────┘
```

- **Cột trái** — danh sách hội thoại chia 2 nhóm: **User chủ động** (bạn hỏi Agent) và **System Alert** (hệ thống tự tạo thread khi máy phát hiện bất thường, kèm tóm tắt anomaly + khuyến nghị RAG). Thread có lệnh chờ hiển thị badge **DUYỆT** nhấp nháy.
- **Cột giữa** — khung chat chính: gửi tin nhắn (Enter gửi, Shift+Enter xuống dòng), Agent trả lời theo cẩm nang RAG. Lệnh rủi ro cao hiện **ngay trong khung chat** dạng thẻ **Duyệt thực thi / Từ chối** — sau quyết định, thẻ chuyển ✔ ĐÃ DUYỆT / ✖ ĐÃ TỪ CHỐI và lưu lại trong hội thoại.
- **Cột phải** — trạng thái 5 máy thời gian thực (cập nhật mỗi 1s, viền đỏ nhấp nháy khi alert).
- **Nút 📤 Upfile lên RAG** (góc trên phải) — modal upload file (PDF/MD/TXT...) vào `knowledge_uploads/`, danh sách file đã nạp hiển thị ngay trong modal.

---

## 🔄 4. Luồng xử lý sự cố (end-to-end)

```text
Máy mô phỏng sinh telemetry (mỗi 1s)
        │  EventBus("telemetry")
        ▼
TelemetryReceiver — Edge Filtering
        │  • Ngưỡng tĩnh (min/max)  • Tốc độ biến thiên ROC/phút (cửa sổ trượt)
        │  • Cooldown 60s/chỉ số    • Heartbeat "normal" mỗi 10s
        ├─ bình thường ──► nhãn "normal" ──► AgentBrain cập nhật trạng thái máy
        │
        └─ bất thường ───► nhãn "alert" (gửi ngay)
                │
                ▼
        AgentBrain.handle_alert
          ① RAGEngine.query(tình trạng)      ──► bubble trả lời RAG trong chat
          ② AgentTools.translate_advice()    ──► so khớp keyword → lệnh + risk_level
          ③ publish "action_command"
                │
                ▼
        ActionApproval (HITL)
          ├─ risk LOW  ──► thực thi NGAY
          └─ risk HIGH ──► thẻ DUYỆT trong khung chat → kỹ sư bấm ✔ / ✖
                │
                ▼
        ActuatorDispatcher ──► machine.receive_plc_command()
                └──► "command_response" (audit log tối đa 200 lệnh)
```

## ⚙️ 5. Năm dòng máy mô phỏng (`machines/`)

| Machine ID | Loại | Model | Vị trí | Thông số giám sát chính |
|---|---|---|---|---|
| `MC-MILL-01` | CNC_MILLING | DMG MORI NVX 5080 | Cell-01 | `Spindle_Temp_C`, `Vibration_RMS_mm_s`, `Spindle_Load_Pct`, `Coolant_Pressure_Bar` |
| `MC-ROBOT-01` | ROBOT_ARM | DENSO VS-068 | Cell-01_Handling | `Joint_3_Current_A`, `Motor_Temp_C` |
| `MC-INJ-01` | INJECTION_MOLDING | FANUC ROBOSHOT S2000i | Cell-02 | `Nozzle_Temp_Zone1`, `Clamping_Pressure_Bar` |
| `MC-AOI-01` | AOI_INSPECTION | KOH YOUNG ZENITH 3D | Cell-03_SMT | `False_Reject_Rate_Pct` |
| `MC-AMR-01` | AMR_VEHICLE | OMRON LD90 (VDA5050) | Floor_Transit | `Battery_Pct` (sàn 20%) |

Mỗi máy mô hình hóa **phản hồi vật lý thật** (ví dụ CNC: dao mòn → tải tăng → nhiệt tăng → rung theo hàm phi tuyến chuẩn ISO 10816) và **nhận lệnh PLC** qua `receive_plc_command()`.

## 🌟 6. Điểm nhấn kỹ thuật

- **Edge Anomaly Filtering** — chỉ telemetry vượt ngưỡng hoặc *tăng nhanh bất thường* (ROC) mới kích hoạt Agent; cooldown 60s chống spam LLM/API.
- **Event Bus bất đồng bộ** — pub/sub in-memory chạy qua `ThreadPoolExecutor`, bọc try-except từng handler để lỗi một bên không làm sập hệ thống.
- **RAG domain-specific** — `agent/rag_engine.py` trả lời theo cẩm nang DENSO theo từ khóa; **là bản giả lập có chuẩn bị sẵn interface** để thay LightRAG thật (chỉ cần thay nội dung `query()`).
- **HITL trong khung chat** — lệnh `LOW` chạy ngay, lệnh `HIGH` tạo thẻ duyệt ngay trong hội thoại của máy; quyết định được lưu lại làm lịch sử.
- **Chat với Agent** — người dùng hỏi trực tiếp qua ô nhập (`POST /api/chat`), hội thoại lưu thành thread riêng.
- **Kho tri thức upload được** — nút 📤 nhận file `multipart/form-data`, parse bằng `email.parser` (stdlib, không cần `cgi` — đã bị xóa ở Python 3.13+), lưu vào `knowledge_uploads/`.
- **Zero dependency** — backend 100% thư viện Python chuẩn; frontend HTML + Tailwind CDN, không cần Node/build step.
- **Render diff phía client** — card máy cập nhật giá trị *tại chỗ*, sidebar/chat chỉ re-render khi dữ liệu đổi → không nhấp nháy, không reset vị trí cuộn.

---

## 📁 7. Cấu trúc dự án

```text
Long-agent/
├── main.py                     # Điểm khởi chạy: ghép 3 tầng + DashboardServer
├── machines/                   # TẦNG 1 — 5 máy mô phỏng
│   ├── base_machine.py         #   Lớp cơ sở (state, generate_telemetry, receive_plc_command)
│   ├── cnc_milling.py          #   MC-MILL-01  — máy phay CNC
│   ├── robot_arm.py            #   MC-ROBOT-01 — robot 6 trục DENSO
│   ├── injection_molding.py    #   MC-INJ-01   — máy ép nhựa
│   ├── aoi_inspection.py       #   MC-AOI-01   — soi quang học 3D
│   └── amr_vehicle.py          #   MC-AMR-01   — xe tự hành
├── iot/                        # TẦNG 2 — Edge IoT Gateway
│   ├── event_bus.py            #   Pub/Sub bất đồng bộ (ThreadPool)
│   ├── telemetry_receiver.py   #   Lọc bất thường: ngưỡng + ROC + cooldown 60s
│   ├── actuator_dispatcher.py  #   Định tuyến lệnh xuống máy + audit log
│   └── action_approval.py      #   Chốt HITL: phân loại rủi ro / chờ duyệt
├── agent/                      # TẦNG 3 — AI Agent
│   ├── brain.py                #   Bộ não: alert → RAG → dịch lệnh → publish
│   ├── rag_engine.py           #   RAG engine (giả lập, chờ LightRAG)
│   ├── tools.py                #   Bảng khả năng máy + so khớp keyword → lệnh
│   └── knowledge_base.py       #   Mock knowledge store
├── dashboard/                  # Web UI (stdlib http.server)
│   ├── server.py               #   Routes: /, /api/state, /api/chat, /api/upload, /api/decision
│   ├── state_store.py          #   State tập trung: máy, hội thoại 2 nhánh, HITL, uploads
│   └── index.html              #   Giao diện Chat-GPT 3 cột (viết lại hoàn toàn)
├── tests/                      # Bộ kiểm thử unittest
│   ├── test_api_chat.py        #   11 test: state, chat API, upload API, thẻ HITL
│   ├── test_hitl.py            #   ⚠ bản cũ — chưa theo API hiện tại
│   └── test_dashboard.py       #   ⚠ bản cũ — chưa theo API hiện tại
├── knowledge_uploads/          # Kho file upload lên RAG (tự tạo, nằm trong .gitignore)
└── README.md
```

## 🚀 8. Chạy dự án

**Yêu cầu:** Python 3.10+ (đã kiểm chứng trên 3.14) — không cần cài thêm thư viện nào.

```powershell
# Chạy từ thư mục gốc dự án
python main.py
```

Mở trình duyệt tại **http://localhost:8000**.

```powershell
# Tùy chọn: đổi cổng / địa chỉ / chu kỳ telemetry (giây)
python main.py --host 127.0.0.1 --port 8080 --interval 0.5
```

## 🔌 9. API

| Method | Route | Mô tả |
|---|---|---|
| `GET` | `/` | Phục vụ giao diện `index.html` |
| `GET` | `/api/state` | Snapshot JSON: `machines`, `conversations` (2 nhánh), `pending_approvals`, `alerts`, `uploads` |
| `POST` | `/api/chat` | `{session_id?, text}` → tạo/chọn thread, trả `{session_id, reply}` |
| `POST` | `/api/upload` | `multipart/form-data` (field `file`) → lưu vào `knowledge_uploads/`, trả `{status, files}` |
| `POST` | `/api/decision` | `{action_id, decision: "APPROVE"\|"REJECT"}` → duyệt HITL, cập nhật thẻ trong chat |

## 🧪 10. Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

- ✅ **`tests/test_api_chat.py` — 11/11 PASS**: cấu trúc hội thoại 2 nhánh, alert → thread System Alert, chat API (tạo thread/tiếp tục thread/từ chối text rỗng), upload multipart (lưu file + đăng ký), thẻ HITL (tạo pending → approve/reject cập nhật trạng thái), endpoint `/api/decision`.
- ⚠ `test_hitl.py` & `test_dashboard.py` là **bản viết cho API phiên bản cũ** (import `ActionDispatchError`, `record_agent_result` không còn tồn tại) — đang có lỗi sẵn từ trước khi refactor, cần viết lại theo API hiện tại.

## ⚠️ 11. Giới hạn & lưu ý

- **RAG là giả lập** — `RAGEngine.query()` trả văn bản mẫu theo từ khóa; giao diện/luồng đã sẵn sàng để thay LightRAG thật (kèm vector DB) mà không đổi code khác.
- **Trạng thái in-memory** — hội thoại, lệnh chờ, danh sách upload lưu trong RAM, reset khi tắt simulator.
- **Mô phỏng thuần** — không kết nối PLC/hardware thật; nút Duyệt chỉ gửi lệnh tới máy mô phỏng. **Không sử dụng server này như giao diện điều khiển sản xuất.**
- **Chưa có xác thực** — không có đăng nhập/phân quyền (phù hợp demo nội bộ).

## 📄 12. License

[MIT](LICENSE) © DENSO Factory Hacks 2026 — Team Long-agent


