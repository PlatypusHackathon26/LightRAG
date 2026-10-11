# 🏭 DENSO Smart Maintenance Agent

### IIoT Real-time Monitoring · RAG Knowledge AI · Human-in-the-Loop

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-uvicorn-009688?logo=fastapi&logoColor=white)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 🏁 Dự án tham dự **DENSO Factory Hacks 2026**
> Hệ thống AI Agent chủ động giám sát IIoT thời gian thực, chẩn đoán sự cố dựa trên **RAG** tri thức nhà xưởng và điều phối can thiệp máy móc an toàn với cơ chế **Human-in-the-Loop (HITL)** — chạy cùng DENSO Agent Gateway của repo này (`denso/`); cảnh báo và chẩn đoán hiện trong mục **Automated Alerts** của web UI.

---

## 📌 1. Bối cảnh & Bài toán đặt ra

Trong môi trường sản xuất linh kiện ô tô chính xác của DENSO (bugi, kim phun, cụm HVAC...):

- **Downtime tốn kém** — mỗi phút dừng dây chuyền đột ngột (*Unplanned Downtime*) gây thiệt hại lớn về sản lượng và tiến độ giao hàng Just-In-Time.
- **Tra cứu cẩm nang mất thời gian** — tài liệu kỹ thuật (SOP, cẩm nang máy) đồ sộ khiến kỹ thuật viên mất nhiều thời gian tra cứu mã lỗi khi máy gặp sự cố.
- **Mất mát tri thức chuyên gia** — kinh nghiệm xử lý lỗi của các thợ bậc cao thường nằm ở dạng ghi chép rời rạc hoặc truyền miệng, chưa được số hóa.

## 💡 2. Kiến trúc

```text
┌─────────────────────────────┐
│ 1. FACTORY FLOOR            │  5 máy mô phỏng DENSO (CNC, Robot, Ép nhựa, AOI, AMR)
│    machines/                │  Telemetry mỗi giây; lỗi do tester bật/tắt thủ công
└────────────┬────────────────┘
             │ Event Bus (in-memory, ThreadPool)
             ▼
┌─────────────────────────────┐
│ 2. EDGE IOT GATEWAY         │  Lọc ngưỡng (machines/specifications.py) + Rate-of-Change
│    iot/                     │  Cooldown chống spam · HITL trước mọi lệnh tới máy
└────────────┬────────────────┘
             │ event "alert" / "normal"
             ▼
┌─────────────────────────────┐
│ 3. AI AGENT                 │  Alert ➜ LLM chẩn đoán trên các chỉ số đang vượt ngưỡng
│    agent/                   │  ➜ đề xuất lệnh sửa gốc trong whitelist ➜ chờ kỹ sư duyệt
└────────────┬────────────────┘
             │ /api/state, /api/decision (127.0.0.1:8085)
             ▼
┌─────────────────────────────┐
│ DENSO Agent Gateway :9700   │  Dựng incident từ alert, thẻ duyệt HITL, hỏi đáp theo tài liệu
│ (denso/gateway)             │  Relay bảng tester tại /dashboard/ → nút Dashboard của web UI
└─────────────────────────────┘
```

## 🖥️ 3. Hai giao diện

- **Bảng tester** (`dashboard/index.html`, phục vụ tại `/`) — lưới 5 thẻ máy với đầy đủ chỉ số trong `machines_description.md`, cập nhật qua SSE `/api/stream` (tự chuyển sang polling `/api/machines` mỗi 1.5 s khi SSE không tới được, ví dụ sau Cloudflare tunnel). Bấm thẻ máy để chọn lỗi cần mô phỏng. Bảng này **không** có khung chat hay thẻ duyệt.
- **Web UI DENSO** (`lightrag_webui`, qua gateway) — mỗi máy đang có cảnh báo là một hội thoại trong **Automated Alerts**: cảnh báo của edge filter, chẩn đoán mới nhất của agent, thẻ duyệt lệnh, và hỏi đáp tiếp trong cùng hội thoại (trả lời theo tài liệu đã nạp vào kho tri thức). Nút **Dashboard** mở bảng tester qua relay `/dashboard/`.

---

## 🔄 4. Luồng xử lý sự cố

```text
Tester bật lỗi trên bảng (POST /api/machines/{id}/faults)
        │  chỉ số trôi dần về giá trị lỗi
        ▼
TelemetryReceiver — ngưỡng tĩnh + ROC + cooldown 60 s/chỉ số
        │  "alert" (kèm danh sách anomaly)
        ▼
AgentBrain.handle_alert
        │  • trong một đợt sự cố, máy chỉ được chẩn đoán lại khi có chỉ số MỚI vượt ngưỡng
        │  • RAGEngine.query_with_schema: prompt gồm giới hạn, mục "CHỈ SỐ ĐANG VƯỢT NGƯỠNG",
        │    danh mục lệnh của loại máy; lệnh đầu tiên phải sửa nguyên nhân gốc
        │    (REPAIR_*, REPLACE_*, REFILL_*...), tối đa 2 lệnh; lệnh ngoài whitelist bị loại
        ▼
ActionApproval (HITL) — mọi lệnh agent đề xuất đều chờ duyệt (lệnh trùng đang chờ thì bỏ qua)
        │  kỹ sư Duyệt / Từ chối trên web UI → gateway → POST /api/decision
        ▼
ActuatorDispatcher ──► machine.receive_plc_command()  (máy mô phỏng, không có PLC thật)
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

**Chọn lỗi thủ công:** bấm thẻ máy trên Dashboard để mở danh sách lỗi của máy đó. Chọn/bỏ chọn một hoặc nhiều lỗi rồi bấm **Áp dụng**; **Bỏ chọn tất cả** rồi **Áp dụng** hủy mọi lỗi trên máy. **Đóng** bỏ các thay đổi chưa áp dụng. Máy không tự sinh lỗi theo thời gian. Hủy lỗi giữ nguyên trạng thái vật lý để các chỉ số hồi phục theo mô phỏng.

API chọn lỗi: `GET /api/machines/{machine_id}/faults` trả danh mục và lỗi đang bật; `POST` cùng đường dẫn nhận `{"active_faults": ["FAULT_CODE", ...]}` để áp dụng toàn bộ lựa chọn. Danh sách rỗng hủy tất cả lỗi trên máy.

Dashboard kiểm chứng dùng mức danh nghĩa, nhiễu, đơn vị và ngưỡng chung từ `machines/specifications.py`, hiển thị đầy đủ chỉ số trong `machines_description.md`. Các chỉ số hội tụ theo thời gian hoặc theo giới hạn tốc độ khi bật/hủy lỗi, không nhảy thẳng sang giá trị đích. Agent trong `main.py` phân tích và đề xuất, không tự thực thi lệnh làm thay đổi kịch bản lỗi thủ công. Lệnh do kỹ sư chủ động gửi vẫn đi qua HITL.

## 🌟 6. Điểm nhấn kỹ thuật

- **Edge Anomaly Filtering** — chỉ telemetry vượt ngưỡng hoặc tăng nhanh bất thường (ROC) mới kích hoạt agent; cooldown chống spam LLM.
- **Chẩn đoán bằng LLM thật** — `agent/llm_client.py` gọi một endpoint OpenAI-compatible; không cấu hình thì `RAGEngine` dùng chẩn đoán giả lập theo từ khóa (đủ cho test offline).
- **Một chẩn đoán cho một sự cố** — chặn lặp theo từng máy; chỉ chẩn đoán lại khi xuất hiện chỉ số lệch mới.
- **Sửa gốc trước, giảm thiểu sau** — prompt buộc lệnh đầu là sửa nguyên nhân gốc, không chỉ tăng bơm hay giảm tốc.
- **HITL cho mọi đề xuất** — không lệnh nào của agent tự chạy; vé chờ duyệt hết hạn nếu bị bỏ quên; lệnh lạ coi là rủi ro cao.
- **Event Bus bất đồng bộ** — pub/sub in-memory qua `ThreadPoolExecutor`, lỗi một handler không làm sập hệ thống.

---

## 📁 7. Cấu trúc

```text
long_agent/
├── main.py                     # Ghép 3 tầng + FastAPI (uvicorn) tại LONG_AGENT_HOST:LONG_AGENT_PORT
├── machines_description.md     # Mô tả máy, chỉ số, lỗi — cũng được nạp vào kho tri thức của gateway
├── requirements.txt            # fastapi, uvicorn, pydantic, httpx
├── machines/                   # TẦNG 1 — 5 máy mô phỏng + specifications.py (ngưỡng, nhiễu, đơn vị)
├── iot/                        # TẦNG 2 — event_bus, telemetry_receiver, action_approval, actuator_dispatcher
├── agent/                      # TẦNG 3
│   ├── brain.py                #   alert → chẩn đoán → đề xuất lệnh, chặn chẩn đoán lặp
│   ├── rag_engine.py           #   prompt, danh mục lệnh (COMMAND_CATALOG), parse + whitelist
│   ├── llm_client.py           #   gọi LLM từ biến môi trường LONG_AGENT_LLM_*
│   └── tools.py, knowledge_base.py
├── dashboard/
│   ├── server.py               #   create_app(): các route ở mục 9
│   ├── state_store.py          #   trạng thái máy, cảnh báo, hội thoại, vé chờ duyệt
│   └── index.html              #   bảng tester
├── tests/                      # pytest/unittest, chạy offline
└── knowledge_uploads/          # file tải lên qua /api/upload (gitignore)
```

## 🚀 8. Chạy

**Yêu cầu:** Python 3.10+, `pip install -r requirements.txt` (venv của repo đã có sẵn các gói này).

Cách thường dùng — chạy cùng gateway và web UI từ thư mục gốc repo:

```powershell
powershell -ExecutionPolicy Bypass -File denso\scripts\serve_chat.ps1 -WithIoT -WithUI
```

`-WithIoT` khởi động `long_agent/main.py` với các biến `LONG_AGENT_*` và đặt `DENSO_IOT_URL=http://127.0.0.1:8085` cho gateway. Thêm `-GuestUpload` nếu khách cần quyền duyệt lệnh.

Chạy riêng:

```powershell
cd long_agent
python main.py          # bảng tester tại http://127.0.0.1:8085
```

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `LONG_AGENT_HOST` / `LONG_AGENT_PORT` | `127.0.0.1` / `8085` | Địa chỉ nghe. Các route lỗi, duyệt, PLC không có xác thực — chỉ mở `0.0.0.0` trong mạng tin cậy |
| `LONG_AGENT_LLM_BASE`, `LONG_AGENT_LLM_MODEL` | trống | Endpoint OpenAI-compatible và model; trống thì dùng chẩn đoán giả lập |
| `LONG_AGENT_LLM_KEY` | trống | Khóa API nếu gọi thẳng nhà cung cấp (để trong `.env`, không commit) |
| `LONG_AGENT_LLM_EXTRA_BODY` | `{}` | JSON thêm vào request (ví dụ tắt thinking) |
| `LONG_AGENT_PROPOSE` | `1` | `0` = chỉ chẩn đoán, không đề xuất lệnh |
| `LONG_AGENT_AUTO_LOW` | — | `1` = lệnh rủi ro thấp chạy ngay (hành vi gốc); mặc định mọi lệnh chờ duyệt |
| `LONG_AGENT_REPEAT_S` | `120` | Khác 0: trong một đợt sự cố chỉ chẩn đoán lại khi có chỉ số mới; 0 = chẩn đoán mọi cảnh báo |
| `LONG_AGENT_RECOVERY_S` | `20` | Máy bình thường liên tục bấy nhiêu giây thì đợt sự cố đóng: các lệnh còn chờ của máy được rút, lần cảnh báo sau là sự cố mới |

## 🔌 9. API (`dashboard/server.py`)

| Method | Route | Mô tả | Qua gateway |
|---|---|---|---|
| `GET` | `/` | Bảng tester | relay tại `/dashboard/` |
| `GET` | `/api/machines` | Trạng thái + chỉ số từng máy | relay |
| `GET` / `POST` | `/api/machines/{id}/faults` | Danh mục lỗi / áp dụng `{"active_faults": [...]}` | relay |
| `GET` | `/api/stream` | SSE trạng thái máy | relay (503 sau Cloudflare tunnel) |
| `GET` | `/api/state` | Snapshot: máy, cảnh báo, hội thoại, `pending_approvals` | gateway đọc để dựng incident |
| `POST` | `/api/decision` | `{action_id, decision}` — duyệt/từ chối | gateway gọi khi kỹ sư bấm |
| `POST` | `/api/actions/{id}/approve` | Duyệt (chỉ cùng origin) | không |
| `POST` | `/api/chat`, `/api/upload`, `/api/plc/fix` | Chat, tải file, lệnh sửa trực tiếp | không |

## 🧪 10. Kiểm thử

```powershell
cd long_agent
..\.venv\Scripts\python -m pytest tests -q
```

Toàn bộ test chạy offline (FastAPI `TestClient`, LLM giả). `tests/test_denso_integration.py` kiểm phần tích hợp với gateway: LLM client, HITL cho mọi lệnh, chặn chẩn đoán lặp, prompt yêu cầu sửa gốc trước. Phía gateway có test riêng trong `denso/tests/test_gateway.py`.

## ⚠️ 11. Giới hạn & lưu ý

- **Mô phỏng thuần** — không kết nối PLC/phần cứng thật; lệnh đã duyệt chỉ tới máy mô phỏng. Không dùng làm giao diện điều khiển sản xuất.
- **Trạng thái in-memory** — cảnh báo, hội thoại, vé chờ duyệt mất khi tắt `main.py`.
- **Không có xác thực ở cổng 8085** — quyền duyệt do gateway kiểm (`can_approve`); chỉ mở 8085 ra ngoài localhost khi thật cần.
- **AMR** — pin giảm dần theo mô phỏng nên cảnh báo `Battery_Pct` có thể xuất hiện mà không cần bật lỗi.

## 📄 12. License

[MIT](LICENSE) © DENSO Factory Hacks 2026 — Team Long-agent
