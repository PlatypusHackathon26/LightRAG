# Đặc tả kết nối UI Agentic ↔ DENSO Agent Gateway

> Gửi: Nam (UI agentic, nhánh `nam-web`)
> Nhánh tham chiếu: `feat/rag-backend` – gateway `denso/gateway/app.py`, phần nối UI ở commit `5f8edf5bf`
> Trạng thái: chạy được end-to-end trên máy local (UI → gateway → LightRAG). Ví dụ trong tài liệu
> lấy từ gateway thật, trừ `/agent/chat` (ghi chú ở mục 4.1).

## 1. Kiến trúc

```
UI agentic (Vite :5173 / build trong /webui/agentic.html)
   │  fetch  http://127.0.0.1:9700/agent/*      (CORS cho :5173)
   ▼
DENSO Agent Gateway (FastAPI :9700)  denso/gateway/app.py
   ├─ token → cấp quyền (users.json phía server)   ← UI KHÔNG tự chọn cấp quyền
   ├─ câu hỏi kỹ thuật  → LightRAG level_N  (:9621/9622/9623, mode=mix)
   ├─ câu hỏi tra xe    → LightRAG lookup   (:9631, mode=naive; không có thì về level_N)
   ├─ sự cố / telemetry → denso/gateway/sample_ops.json (dữ liệu MẪU)
   └─ duyệt hành động   → chỉ ghi denso/logs/actions.jsonl, KHÔNG gửi lệnh PLC
```

UI **không bao giờ gọi LightRAG trực tiếp** cho phần agentic.

## 2. Chạy thử

```powershell
# 1. LightRAG level_1 (đã có index trong rag_storage/level_1)
$env:WORKSPACE="level_1"; $env:PORT="9621"; $env:PYTHONIOENCODING="utf-8"; .venv\Scripts\lightrag-server.exe
# 2. Gateway
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python denso\gateway\app.py
# 3. UI: tạo lightrag_webui/.env.development.local (đã gitignore qua *.local)
#      VITE_AGENT_LIVE=true
#      VITE_AGENT_BASE_URL=http://127.0.0.1:9700
cd lightrag_webui; bun run dev      # mở http://localhost:5173/agentic.html
```

Lưu ý khi tạo file env bằng PowerShell 5.1: `Set-Content -Encoding utf8` ghi kèm BOM, làm biến
đầu tiên thành `﻿VITE_AGENT_LIVE` và Vite bỏ qua. Ghi bằng editor hoặc
`[IO.File]::WriteAllText(path, text)`.

## 3. Cấu hình phía UI

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `VITE_AGENT_LIVE` | `false` | `true` = dùng gateway; `false` = mock như cũ |
| `VITE_AGENT_BASE_URL` | rỗng (cùng origin) | origin của gateway, ví dụ `http://127.0.0.1:9700` |
| `VITE_AGENT_TOKEN` | rỗng | bearer token chỉ để demo (biến `VITE_` bị đóng gói vào bundle – không phải bí mật) |
| `VITE_DEMO_MODE` | `true` (dev) | **không đổi ý nghĩa**: chỉ quyết định trang chính có bị thay bằng agentic hay không |

`VITE_AGENT_LIVE` tách khỏi `VITE_DEMO_MODE` để không phá luồng demo hiện có.

## 4. Hợp đồng API

Mọi request có thể kèm `Authorization: Bearer <token>`. Không có token → cấp quyền khách
(`DENSO_GUEST_LEVEL`, mặc định 1). Token sai → `401`. Lỗi có dạng `{"detail": "<thông báo>"}`.

### 4.1 `POST /agent/chat`

Request:
```json
{ "conversationId": "CONV-LIVE", "message": "What torque range must be used to tighten the SCV mounting bolts?" }
```

Response `200` (khớp `AgentChatResponse` trong `src/api/agent.ts`):
```json
{
  "content": "The English portion of the Diesel Common Rail System installation guide specifies that the SCV mounting bolts must be tightened to a torque between 6.9 Nm and 10.8 Nm.",
  "citations": [
    {
      "id": "cit-1",
      "documentId": "Diesel_SCV Kit_DCRS300260_installation guide (đa ngôn ngữ)",
      "documentName": "Diesel_SCV Kit_DCRS300260_installation guide (đa ngôn ngữ)",
      "pages": "4",
      "excerpt": "Install the SCV by carefully pushing it into the housing (to avoid O-ring damage). When the SCV is in position, remove the guide pins. Fit the bolts and tighten them with 6.9 to 10.8 [Nm]. …"
    }
  ],
  "events": [
    { "id": "ev-1a2b3c4d", "timestamp": "2026-10-07T05:00:00+00:00", "type": "knowledge_retrieved",
      "label": "Retrieved 1 source document(s) (knowledge, mix, level 1)", "citations": [ "…như trên…" ] },
    { "id": "ev-5e6f7a8b", "timestamp": "2026-10-07T05:00:09+00:00", "type": "response_generated",
      "label": "Answer generated", "detail": "9.8 s" }
  ],
  "target": "knowledge",
  "llmGenerated": true
}
```
*`content` là câu trả lời thật của câu Q3 trong lần benchmark; hôm viết tài liệu quota LLM đã hết
nên không chụp được một response `/agent/chat` mới. Cấu trúc đúng theo code và test của gateway.*

- `content`: Markdown; gateway đã **cắt khối `### References`** của LightRAG vì UI hiển thị citations riêng.
- `citations[].pages`: lấy từ dấu trang trong dữ liệu đã làm sạch (`--- [Trang N] ---`), dạng `"4, 20"`.
- `events`: đúng kiểu `AgentEvent`, dùng cho `AgentActivityTrace`. `timestamp` là ISO; store đổi sang giờ hiển thị.
- `target`: `"knowledge"` hoặc `"lookup"`. Có thể ép bằng trường tùy chọn `"target"` trong request.
- Lịch sử hội thoại do gateway giữ theo `conversationId` (6 lượt gần nhất) – UI không cần gửi lại.

Lỗi:

| Mã | Khi nào |
|---|---|
| `401` | token không có trong `users.json` |
| `502` | LightRAG trả lỗi |
| `503` | server LightRAG của cấp quyền đó không chạy, **hoặc** LLM không sinh được câu trả lời (hết quota / rate limit / timeout) |

Trường hợp 503 thứ hai quan trọng: LightRAG khi đó trả chuỗi *"No relevant context found for the query."* –
nếu chuyển thẳng lên UI, người dùng sẽ hiểu nhầm là "tài liệu không có thông tin".

### 4.2 `GET /agent/documents` → `KnowledgeDocument[]`

Response thật (2/10 phần tử):
```json
[
  { "id": "doc-8fcb87cadb93cd531318f4a565c41ec0", "name": "Spark Plug Catalogue 2025",
    "tags": ["knowledge", "level_1"], "sizeBytes": 138766,
    "importedAt": "2026-10-06T21:34:07.090608+00:00", "indexStatus": "vectorized", "progress": 100 },
  { "id": "doc-e3640ac814b46510723fc1b351ceba90", "name": "WiperBlade-Cat26_Full-Version",
    "tags": ["knowledge", "level_1"], "sizeBytes": 21730,
    "importedAt": "2026-10-06T21:34:07.118734+00:00", "indexStatus": "vectorized", "progress": 100 }
]
```

Ánh xạ trạng thái LightRAG → `indexStatus`: `pending→uploading`, `parsing→parsing`,
`analyzing→chunking`, `processing→embedding`, `processed→vectorized`, `failed→error`.
`tags` gồm tầng (`knowledge` / `lookup`) và cấp quyền. `extractedText` chưa được trả.

### 4.3 `POST /agent/documents` (upload)

`multipart/form-data`: `file`, `level` (1–3). Chỉ user có `can_upload: true`; không được upload tài liệu
cấp cao hơn cấp của mình (`403`). Tài liệu cấp N được nạp vào các server N..3 (cộng dồn).
Response: `{ "status": "accepted", "trackIds": { "level_2": "…", "level_3": "…" } }`.

### 4.4 `GET /agent/incidents`, `GET /agent/incidents/{id}`, `GET /agent/telemetry/{id}`

Đọc từ `denso/gateway/sample_ops.json` (dữ liệu mẫu, đúng kiểu `Incident` / `TelemetrySnapshot`).
Response thật của `/agent/incidents`:
```json
[{ "id": "INC-DEMO-01", "conversationId": "conv-inc-demo-01", "device": "A/C compressor test bench 01",
   "alarm": "Compressor discharge pressure high", "severity": "high", "status": "active",
   "timestamp": "2026-10-07T08:00:00Z", "tags": ["demo", "ac-compressor"] }]
```
Không tìm thấy → `404` (client trả `undefined`, không ném lỗi).

### 4.5 `POST /agent/actions/{id}/approve` | `/reject`

Response thật: `{"ack": "ACK-888057"}` / `{"status": "rejected"}`. Gateway **chỉ ghi log**:
```json
{"action": "ACT-DEMO", "decision": "approve", "user": "guest", "ack": "ACK-888057", "executed": false,
 "note": "recorded only - the gateway never sends PLC commands"}
```

### 4.6 `GET /agent/health`

```json
{"status": "ok", "backends": {"level_1": {"url": "http://127.0.0.1:9621", "ok": true, "workspace": "level_1"},
 "level_2": {"url": "http://127.0.0.1:9622", "ok": false}, "level_3": {"url": "http://127.0.0.1:9623", "ok": false}}}
```

## 5. Những gì đã sửa trong UI (commit `5f8edf5bf`)

| File | Thay đổi |
|---|---|
| `src/features/agentic/agentConfig.ts` (mới) | đọc `VITE_AGENT_LIVE`, `VITE_AGENT_BASE_URL`, `VITE_AGENT_TOKEN` |
| `src/api/agent.ts` | `createAgentClient(config, fetch)`; giữ nguyên các named export cũ; thêm `fetchDocuments`, `AgentApiError` (có `status`), header bearer, 404 → `undefined` |
| `src/api/agent.test.ts` (mới) | 5 test cho client (mock không gọi mạng, đường dẫn, token, lỗi 503, 404) |
| `stores/agenticStore.ts` | `isLive`, `liveError`, `loadLiveData`, `addAgentEvents`; live mode khởi đầu bằng một phiên Q&A trống thay vì hội thoại CNC mẫu |
| `components/ChatWorkspace.tsx` | live: gửi qua gateway, trạng thái `investigating`, gắn citations + events, hiện lỗi gateway; mock: giữ `DEMO_RESPONSES` cũ |
| `AgenticWorkspace.tsx` | live: tải documents + incidents khi mở trang |
| `src/vite-env.d.ts`, `.env.development` | khai báo / ghi chú 3 biến mới (`VITE_AGENT_LIVE=false`) |

Kiểm tra: `bun test` 622 pass / 19 fail (đúng 19 test này cũng fail trên nhánh gốc chưa sửa, không liên
quan agentic), `tsc --noEmit` sạch, `lint` 0 lỗi.

## 6. Việc còn lại phía UI (chưa nối)

1. **Upload trong Knowledge Hub** vẫn giả lập (`simulateUploadPipeline`) → gọi `POST /agent/documents` rồi
   poll `/agent/documents` để cập nhật `indexStatus`.
2. **Nút duyệt / từ chối HITL** vẫn dùng timer giả trong store → gọi `approveAction` / `rejectAction` của `api/agent.ts`.
3. Sự cố từ gateway có `conversationId` chưa tồn tại trong `conversations` → cần tạo hội thoại tương ứng khi chọn sự cố.
4. Dòng chữ cố định "DEMO MODE" dưới ô chat nên phụ thuộc `isLive`.
5. `useLiveTelemetry` vẫn sinh số ngẫu nhiên → dùng `fetchTelemetry` khi live.
6. Streaming câu trả lời (`/query/stream` của LightRAG) chưa hỗ trợ; hiện trả cả câu một lần.

## 7. Góp ý thêm cho nhánh `nam-web`

1. `env.example` có dòng `AUTH_ACCOUNTS='admin:admin123'` (commit `26c45f07e`) – repo đang public; nên xóa
   và đặt tài khoản trong `.env` cá nhân.
2. Cờ demo bị kiểm tra ngược chiều: `AppRouter.tsx` dùng `=== 'true'`, còn `api/agent.ts` /
   `agenticStore.ts` (bản gốc) dùng `!== 'false'`. Phần live giờ dùng cờ riêng `VITE_AGENT_LIVE`, nhưng nên
   thống nhất `VITE_DEMO_MODE`.
3. `lightrag_webui/package-lock.json` (npm) nằm cạnh `bun.lock` – repo dùng bun, hai lockfile sẽ lệch nhau.
4. Code agentic chưa có test (số test pass không đổi so với upstream trước commit nối gateway).
