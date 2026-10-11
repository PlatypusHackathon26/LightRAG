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
        │  triệu chứng xuất hiện khi bộ phận hỏng hoạt động, chỉ số trôi dần về giá trị lỗi
        ▼
TelemetryReceiver — ngưỡng tĩnh + ROC + cooldown 60 s/chỉ số, theo trạng thái máy
        │  "alert" (kèm danh sách anomaly)
        ▼
AgentBrain.handle_alert           (bỏ qua máy đang có quy trình / vé chờ; chẩn đoán lại khi có chỉ số MỚI)
        │  RAGEngine.query_with_schema:
        │    • tra SOP trong LightRAG (agent/retriever.py, LONG_AGENT_RAG_URL)
        │    • LLM chọn MỘT lệnh sửa trong danh sách máy khai báo (+ lệnh tạm thời tuỳ chọn), kèm nguồn
        │    • chuẩn hoá tên lệnh; sai hoặc đã thử thất bại → hỏi lại 1 lần; vẫn sai → không đề xuất
        ▼
agent/procedures.py:  SAFE_STOP → LOCKOUT → <lệnh sửa> → UNLOCK   (lập từ đồ thị trạng thái của máy)
        ▼
ActionApproval — vé 1 "Sửa"  ── kỹ sư duyệt trên web UI → gateway → POST /api/decision
        ▼
ProcedureRunner chạy từng bước (chờ máy dừng hẳn trước LOCKOUT, chờ hết thời gian sửa)
        ▼
ActionApproval — vé 2 "Khởi động lại" ── kỹ sư duyệt → START (liên động có thể bắt chờ)
        ▼
Theo dõi LONG_AGENT_VERIFY_S giây: không cảnh báo → đã xác minh; cảnh báo quay lại → thất bại, chẩn đoán lại
```

### Trạng thái máy và lệnh

Mọi máy dùng chung các trạng thái `RUNNING`, `HOLD`, `STARTING`, `STOPPED`, `LOCKED_OUT`, `MAINTENANCE`, `E_STOP`
(AMR thêm `CHARGING`). Mỗi máy **tự khai báo lệnh** trong `command_specs()` (`machines/commands.py`): loại
(control / repair / setpoint), tham số và khoảng giá trị, trạng thái được phép, mức rủi ro, lỗi mà lệnh sửa và thời
gian sửa, các tên gọi khác. Danh mục của agent, mức rủi ro khi duyệt và kiểm tra của dispatcher đều lấy từ đây.

- Dừng máy đưa tốc độ, tải, dòng về 0 và để nhiệt nguội dần. Dừng không sửa lỗi: chạy lại mà chưa sửa thì triệu chứng quay lại.
- Lệnh sửa chỉ chạy khi `LOCKED_OUT` (riêng `PURGE_BARREL`: `STOPPED` và nòng còn nóng), mất thời gian, chỉ gỡ đúng
  lỗi của bộ phận đó và **không đổi số đo** – số đo hồi phục theo vật lý sau `START`.
- `LOCKOUT` chờ bộ phận chuyển động đứng yên; `START` kiểm liên động (quá nhiệt, pin cạn); máy ép phun chỉ vào
  `RUNNING` khi đầu phun ≥ 195°C; `E_STOP` phải `RESET_ESTOP` trước mọi thao tác.

## ⚙️ 5. Năm dòng máy mô phỏng (`machines/`)

| Machine ID | Loại | Model | Vị trí | Thông số giám sát chính |
|---|---|---|---|---|
| `MC-MILL-01` | CNC_MILLING | DMG MORI NVX 5080 | Cell-01 | `Spindle_Temp_C`, `Vibration_RMS_mm_s`, `Spindle_Load_Pct`, `Coolant_Pressure_Bar` |
| `MC-ROBOT-01` | ROBOT_ARM | DENSO VS-068 | Cell-01_Handling | `Joint_3_Current_A`, `Motor_Temp_C` |
| `MC-INJ-01` | INJECTION_MOLDING | FANUC ROBOSHOT S2000i | Cell-02 | `Nozzle_Temp_Zone1`, `Clamping_Pressure_Bar` |
| `MC-AOI-01` | AOI_INSPECTION | KOH YOUNG ZENITH 3D | Cell-03_SMT | `False_Reject_Rate_Pct` |
| `MC-AMR-01` | AMR_VEHICLE | OMRON LD90 (VDA5050) | Floor_Transit | `Battery_Pct` (sàn 20%) |

Mỗi máy mô hình hóa **phản hồi vật lý thật** (ví dụ CNC: dao mòn → tải tăng → nhiệt tăng → rung theo hàm phi tuyến chuẩn ISO 10816) và **nhận lệnh PLC** qua `receive_plc_command()`.

**Chọn lỗi thủ công:** bấm thẻ máy trên Dashboard để mở danh sách lỗi của máy đó, chọn lỗi rồi bấm **Áp dụng**. Máy không tự sinh lỗi theo thời gian. Lỗi được sửa thật qua agent và quy trình hai lần duyệt. **Reset mô phỏng (tester)** rồi **Áp dụng** xoá mọi lỗi ngay – chỉ để tester dọn máy giữa các kịch bản, không phải sửa chữa; số đo vẫn hồi phục dần.

API chọn lỗi: `GET /api/machines/{machine_id}/faults` trả danh mục và lỗi đang bật; `POST` cùng đường dẫn nhận `{"active_faults": ["FAULT_CODE", ...]}` để áp dụng toàn bộ lựa chọn. Danh sách rỗng hủy tất cả lỗi trên máy.

Dashboard kiểm chứng dùng mức danh nghĩa, nhiễu, đơn vị và ngưỡng chung từ `machines/specifications.py`, hiển thị đầy đủ chỉ số trong `machines_description.md`. Các chỉ số hội tụ theo thời gian hoặc theo giới hạn tốc độ khi bật/hủy lỗi, không nhảy thẳng sang giá trị đích. Agent chỉ đề xuất; mọi lệnh tới máy đi qua HITL, kể cả lệnh kỹ sư gửi qua `/api/plc/fix`.

## 🌟 6. Điểm nhấn kỹ thuật

- **Một nguồn lệnh duy nhất** – máy tự khai báo lệnh; không có danh sách chép tay để lệch nhau.
- **Câu trả lời → lệnh chính xác** – LLM chỉ chọn tên trong danh sách; tên được chuẩn hoá; sai thì hỏi lại; văn bản tự do không bao giờ thành lệnh.
- **Agent chọn "sửa gì", code quyết định "làm thế nào"** – cùng một lệnh sửa luôn ra cùng một quy trình.
- **Mô phỏng không gian lận** – sửa chữa cần máy dừng và khoá an toàn, mất thời gian, không reset số đo; sửa sai thì lỗi còn.
- **Chẩn đoán có tài liệu** – SOP bảo trì (`docs/maintenance_sop.md`) nạp vào LightRAG, agent tra theo triệu chứng và trích nguồn.
- **Hai lần duyệt + kiểm chứng** – duyệt sửa, duyệt khởi động lại, rồi theo dõi; thất bại thì chẩn đoán lại và không lặp lệnh đã thử.
- **Edge filter theo trạng thái** – không báo áp suất 0 khi máy đang dừng, không coi việc ấm máy sau khởi động là sự cố.

---

## 📁 7. Cấu trúc

```text
long_agent/
├── main.py                     # Ghép 3 tầng + FastAPI (uvicorn) tại LONG_AGENT_HOST:LONG_AGENT_PORT
├── machines_description.md     # Mô tả máy, chỉ số, lỗi — cũng được nạp vào kho tri thức của gateway
├── requirements.txt            # fastapi, uvicorn, pydantic, httpx
├── docs/maintenance_sop.md     # SOP bảo trì 5 máy – nạp vào LightRAG cho agent tra
├── machines/                   # TẦNG 1 — 5 máy mô phỏng
│   ├── commands.py             #   trạng thái chung, CommandSpec, chuẩn hoá tên lệnh, kiểm tham số
│   ├── base_machine.py         #   máy trạng thái, thực thi lệnh, hoàn tất sửa chữa / khởi động
│   └── specifications.py       #   danh nghĩa, nhiễu, đơn vị, ngưỡng
├── iot/                        # TẦNG 2 — event_bus, telemetry_receiver, actuator_dispatcher
│   ├── action_approval.py      #   vé chờ duyệt (một lệnh hoặc một quy trình), lịch sử quyết định
│   └── procedure_runner.py     #   chạy quy trình đã duyệt, xin duyệt khởi động lại, kiểm chứng
├── agent/                      # TẦNG 3
│   ├── brain.py                #   alert → chẩn đoán → đề xuất, chặn chẩn đoán lặp / khi máy đang bận
│   ├── rag_engine.py           #   tra tài liệu, prompt, chọn một lệnh sửa máy khai báo
│   ├── procedures.py           #   lập quy trình sửa / khởi động lại từ đồ thị trạng thái
│   ├── retriever.py            #   lấy đoạn tài liệu từ LightRAG (LONG_AGENT_RAG_URL)
│   └── llm_client.py           #   gọi LLM từ biến môi trường LONG_AGENT_LLM_*
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
| `LONG_AGENT_RAG_URL` | trống | LightRAG để agent tra SOP (serve_chat đặt `http://127.0.0.1:9621`); trống thì chẩn đoán không có tài liệu |
| `LONG_AGENT_PROPOSE` | `1` | `0` = chỉ chẩn đoán, không đề xuất lệnh |
| `LONG_AGENT_APPROVAL_TTL_S` | `1800` | Vé chờ duyệt hết hạn sau bấy nhiêu giây (ghi vào lịch sử) |
| `LONG_AGENT_VERIFY_S` | `120` | Thời gian theo dõi sau khi khởi động lại để xác minh sửa chữa |
| `LONG_AGENT_AUTO_LOW` | — | `1` = lệnh máy khai báo rủi ro thấp chạy ngay; mặc định mọi lệnh chờ duyệt |
| `LONG_AGENT_REPEAT_S` | `120` | Cửa sổ chặn chẩn đoán lặp cho cùng một máy (giây) |

## 🔌 9. API (`dashboard/server.py`)

| Method | Route | Mô tả | Qua gateway |
|---|---|---|---|
| `GET` | `/` | Bảng tester | relay tại `/dashboard/` |
| `GET` | `/api/machines` | Trạng thái + chỉ số từng máy | relay |
| `GET` / `POST` | `/api/machines/{id}/faults` | Danh mục lỗi / áp dụng `{"active_faults": [...]}` | relay |
| `GET` | `/api/stream` | SSE trạng thái máy | relay (503 sau Cloudflare tunnel) |
| `GET` | `/api/state` | Snapshot: máy (kèm `state`, `procedure_phase`), cảnh báo, hội thoại, `pending_approvals`, `history` | gateway đọc để dựng incident |
| `POST` | `/api/decision` | `{action_id, decision}` — duyệt/từ chối; 404 vé hết hạn, 409 máy từ chối | gateway gọi khi kỹ sư bấm |
| `POST` | `/api/actions/{id}/approve` | Duyệt (chỉ cùng origin) | không |
| `POST` | `/api/chat`, `/api/upload`, `/api/plc/fix` | Chat, tải file, lệnh sửa trực tiếp | không |

## 🧪 10. Kiểm thử

```powershell
cd long_agent
..\.venv\Scripts\python -m pytest tests -q
```

Toàn bộ test chạy offline trên đồng hồ giả (FastAPI `TestClient`, LLM giả, LightRAG giả):

- `test_commands.py` – chuẩn hoá tên lệnh, kiểm tham số; SOP và `machines_description.md` khớp với lệnh máy khai báo.
- `test_realistic_states.py` – dừng máy, khoá an toàn, sửa cần thời gian, không reset số đo, sửa sai thì lỗi còn, liên động khởi động.
- `test_procedures.py` – lập quy trình từ mọi trạng thái; vòng kín sửa → khởi động lại → xác minh / thất bại.
- `test_rag_schema_formatter.py` – câu trả lời viết khác nhau ra cùng một lệnh; hỏi lại; tài liệu vào prompt.
- `test_fault_semantics.py`, `test_machine_dynamics.py`, `test_smooth_telemetry.py` – vật lý của 16 lỗi và hồi phục qua quy trình thật.

Phía gateway có test riêng trong `denso/tests/test_gateway.py`.

## ⚠️ 11. Giới hạn & lưu ý

- **Mô phỏng thuần** — không kết nối PLC/phần cứng thật; lệnh đã duyệt chỉ tới máy mô phỏng. Không dùng làm giao diện điều khiển sản xuất.
- **Trạng thái in-memory** — cảnh báo, hội thoại, vé chờ duyệt mất khi tắt `main.py`.
- **Không có xác thực ở cổng 8085** — quyền duyệt do gateway kiểm (`can_approve`); chỉ mở 8085 ra ngoài localhost khi thật cần.
- **AMR** — pin giảm dần theo mô phỏng nên cảnh báo `Battery_Pct` có thể xuất hiện mà không cần bật lỗi.

## 📄 12. License

[MIT](LICENSE) © DENSO Factory Hacks 2026 — Team Long-agent
