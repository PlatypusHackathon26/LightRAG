# DENSO A3 – Knowledge Agent (RAG chatbot)

Agent đọc tài liệu kỹ thuật đa định dạng (PDF, bản scan, ảnh chụp, DOCX, XLSX, TXT; tiếng Việt,
Anh, Nhật) và chatbot trả lời bằng ngôn ngữ người hỏi, **luôn kèm tài liệu và số trang**, nói rõ
khi tài liệu không có câu trả lời. Đề A3 – DENSO Factory Hacks 2026.

Mọi phần riêng của DENSO nằm trong `denso/`; lõi LightRAG (`lightrag/`) không bị sửa.

## Mục lục

- [DENSO A3 – Knowledge Agent (RAG chatbot)](#denso-a3--knowledge-agent-rag-chatbot)
  - [Mục lục](#mục-lục)
  - [1. Kiến trúc](#1-kiến-trúc)
  - [2. Cây thư mục](#2-cây-thư-mục)
  - [3. Hướng dẫn chạy](#3-hướng-dẫn-chạy)
    - [3.1. Cài phần mềm (một lần)](#31-cài-phần-mềm-một-lần)
    - [3.2. Lấy code và cài thư viện](#32-lấy-code-và-cài-thư-viện)
    - [3.3. Dữ liệu và cấu hình (không có trên GitHub)](#33-dữ-liệu-và-cấu-hình-không-có-trên-github)
    - [3.4. Cấu hình giao diện](#34-cấu-hình-giao-diện)
    - [3.5. Chạy](#35-chạy)
  - [4. Sử dụng hằng ngày](#4-sử-dụng-hằng-ngày)
    - [4.1. Bật, tắt, khởi động lại](#41-bật-tắt-khởi-động-lại)
    - [4.2. Upload và xoá tài liệu](#42-upload-và-xoá-tài-liệu)
    - [4.3. Giao diện trên Vercel](#43-giao-diện-trên-vercel)
  - [5. Pipeline xử lý tài liệu](#5-pipeline-xử-lý-tài-liệu)
  - [6. Đánh giá độ chính xác](#6-đánh-giá-độ-chính-xác)
  - [7. Agent Gateway (API cho giao diện)](#7-agent-gateway-api-cho-giao-diện)
  - [8. Bảo mật và phân quyền](#8-bảo-mật-và-phân-quyền)
  - [9. Giới hạn và lưu ý](#9-giới-hạn-và-lưu-ý)
  - [10. Sự cố thường gặp](#10-sự-cố-thường-gặp)
  - [11. Docker (chưa dùng cho demo)](#11-docker-chưa-dùng-cho-demo)

---

## 1. Kiến trúc

```
NẠP TÀI LIỆU (một lần, khi upload)
  PDF/DOCX/XLSX/TXT/ảnh ─► parse.py ─► ocr_pages.py ─► clean.py ─► [ocr_images.py] ─► ingest.py ─► LightRAG
                           Docling      trang scan,     gắn trang    chữ trong ảnh                kho theo cấp
                           :5001        Vision 90B      + ngôn ngữ   của PDF (cấp 1)
                                        (chỉ cấp 1)

HỎI ĐÁP (mỗi câu hỏi)
  Giao diện ─► Agent Gateway :9700 ─► LightRAG :9621 (tri thức) / :9631 (tra cứu theo xe)
  :5173 /       phân quyền,            │
  Vercel        chỉ dẫn ngôn ngữ,      ├─► embedding bge-m3 (Ollama :11434, trên máy)
                chọn trích dẫn          ├─► reranker ngôn ngữ :7998
                                        └─► proxy :8899 ─► LLM NVIDIA Nemotron 120B (API)
```

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Đọc tài liệu | Docling (Docker) | bố cục, bảng, OCR cơ bản |
| Đọc trang scan, ảnh chụp | NVIDIA Llama 3.2 Vision 90B | giữ dấu tiếng Việt (98% ký tự so với 89% của OCR thường) |
| Kho tri thức | LightRAG, chế độ `naive` | mỗi cấp quyền một kho riêng |
| Embedding | bge-m3 qua Ollama, chạy trên máy | 1024 chiều, đa ngôn ngữ |
| Reranker | `tools/lang_rerank.py` | ưu tiên đoạn cùng ngôn ngữ câu hỏi, rồi tiếng Anh |
| Trả lời | NVIDIA Nemotron 120B (API miễn phí) | qua proxy giới hạn tốc độ |
| Gateway | FastAPI `gateway/app.py` | phân quyền, chọn tài liệu + trang để trích, từ chối khi thiếu dữ liệu |

**Dữ liệu rời khỏi máy:** câu hỏi và đoạn tài liệu **cấp 1** đi tới API NVIDIA để sinh câu trả
lời; ảnh và trang scan của tài liệu **cấp 1** đi tới API thị giác. Tài liệu cấp 2/3 không bao giờ
đi qua API miễn phí. Mọi dịch vụ chỉ nghe trên `127.0.0.1`, trừ khi bật tunnel (`-Tunnel`).

---

## 2. Cây thư mục

```
denso/
├── README.md                    tài liệu này
├── env.denso                    mẫu cấu hình DENSO, ghép vào .env (không chứa key)
├── requirements.txt             thư viện Python thêm cho denso (cài sau uv sync)
├── start.ps1                    bật Docker Desktop + Docling (dùng -DoclingOnly)
│
├── scripts/
│   ├── serve_chat.ps1           ★ bật toàn bộ backend (+ giao diện, + tunnel)
│   ├── ingest.py                nạp tài liệu đã làm sạch vào LightRAG theo cấp
│   ├── run_benchmark.py         benchmark 30 câu (LLM giám khảo)
│   ├── score_facts.py           chấm benchmark theo dữ kiện (không dùng LLM)
│   ├── eval_lookup.py           10 câu tra cứu theo xe
│   ├── eval_language.py         trả lời đúng ngôn ngữ câu hỏi
│   ├── eval_retrieval.py        đo tìm kiếm (hit@k), không gọi LLM
│   ├── eval_rerank.py           so sánh các chiến lược rerank
│   ├── make_test_docs.py        tạo file DOCX/XLSX/TXT thử
│   └── make_scan_samples.py     tạo bản scan / ảnh chụp thử
│
├── pipeline/                    xử lý tài liệu: raw → sạch → kho
│   ├── parse.py                 bước 1: Docling (TXT đọc trực tiếp, XLSX mỗi sheet một trang)
│   ├── ocr_pages.py             bước 1b: đọc trang scan / ảnh bằng Vision 90B (cấp 1)
│   ├── clean.py                 bước 2: làm sạch, gắn "--- [Trang N | ngôn ngữ: xx] ---"
│   ├── ocr_images.py            bước 2b: chữ trong ảnh của PDF (cấp 1)
│   ├── textutils.py             hàm làm sạch dùng chung
│   ├── tiers.json               catalogue nào tách tầng tri thức / tầng tra cứu
│   ├── check_evidence.py        kiểm tra bằng chứng benchmark còn sau làm sạch
│   ├── find_duplicates.py       báo đoạn trùng lặp
│   └── preview_chunks.py        xem trước cách LightRAG chia đoạn
│
├── gateway/                     backend của giao diện agentic
│   ├── app.py                   API, phân quyền, trích dẫn, xoá tài liệu
│   ├── jobs.py                  hàng đợi upload: parse → clean → ingest → ảnh
│   ├── language.py              nhận diện ngôn ngữ, chỉ dẫn trả lời, câu chào
│   ├── lookup.py                tra cứu từ khoá trong catalogue theo xe
│   ├── users.example.json       mẫu token → cấp quyền (chép thành users.json)
│   └── sample_ops.json          sự cố / telemetry MẪU cho giao diện
│
├── tools/
│   ├── llm_rate_proxy.py        proxy API: giới hạn tốc độ, chèn key, đếm hạn mức
│   └── lang_rerank.py           reranker ưu tiên ngôn ngữ (:7998)
│
├── prompts/
│   ├── user_prompt/denso_answer.md   quy tắc trả lời (trích nguồn, giữ nguyên mã, đọc bảng)
│   └── entity_type/denso.yml         loại thực thể cho trích xuất đồ thị
│
├── tests/                       test tự động (pytest)
├── docs/AGENT_GATEWAY_SPEC.md   đặc tả API gateway
├── docling/docker-compose.yml   Docling bản CPU
├── docker-compose.yml, Dockerfile, compose.env.example, requirements.docker.txt,
├── reranker/docker-compose.yml  Docker – chưa cập nhật (xem mục 11)
│
├── data/            (gitignored) raw/ parsed/ cleaned_md/ cleaned_json/ evaluation/ samples/
├── logs/            (gitignored) log dịch vụ, log upload, log proxy
└── results/         (gitignored) kết quả các bài đo

../rag_storage/      (gitignored) kho LightRAG: level_1/, level_1_lookup/
../.env              (gitignored) cấu hình + API key
../iot_service/      dịch vụ IoT: mô phỏng bệ thử, theo dõi ngưỡng, agent IoT, dashboard (mục 4.4)
```

---

## 3. Hướng dẫn chạy

Kết quả cuối: chatbot ở http://localhost:5173 trả lời từ cùng kho tài liệu với máy demo.
Cần Windows, khoảng 16 GB RAM (còn trống ít nhất 4 GB khi chạy) và mạng Internet.

### 3.1. Cài phần mềm (một lần)

| Phần mềm | Dùng để | Ghi chú |
|---|---|---|
| Git, Python 3.11 | code, backend | |
| [uv](https://docs.astral.sh/uv/) | cài thư viện Python | |
| [Bun](https://bun.sh) | giao diện web | |
| [Ollama](https://ollama.com) | tạo vector (bge-m3) | chạy nền sau khi cài |
| Docker Desktop | Docling | chỉ cần khi upload tài liệu |
| cloudflared | link công khai | chỉ cần khi cho người ngoài vào |

### 3.2. Lấy code và cài thư viện

```powershell
git clone https://github.com/PlatypusHackathon26/LightRAG.git
cd LightRAG
git checkout feat/rag-backend
uv sync --extra api
uv pip install --python .venv\Scripts\python.exe -r denso\requirements.txt
ollama pull bge-m3
```

`uv sync` lần sau sẽ gỡ các gói thêm ở dòng thứ năm: chạy lại dòng đó sau mỗi lần `uv sync`.

### 3.3. Dữ liệu và cấu hình (không có trên GitHub)

| Thứ | Lấy ở đâu | Đặt ở đâu |
|---|---|---|
| Kho tri thức + tài liệu | file `denso_data_bundle_<ngày>.zip` do nhóm gửi | giải nén vào thư mục gốc repo (tạo `rag_storage/` và `denso/data/`) |
| `.env` | tự tạo (dưới đây) | thư mục gốc repo |
| API key NVIDIA | đăng ký miễn phí tại https://build.nvidia.com | dòng `NVIDIA_API_KEY=` trong `.env` |
| `users.json` | chép `denso\gateway\users.example.json` | `denso\gateway\users.json`, đổi token thành chuỗi ngẫu nhiên dài |

```powershell
Copy-Item env.example .env
Get-Content denso\env.denso | Add-Content .env    # dòng sau ghi đè dòng trước
notepad .env                                      # thay NVIDIA_API_KEY=nvapi-put-your-own-key-here
```

Không có kho dữ liệu thì vẫn chạy được nhưng chatbot chưa có tài liệu nào (upload ở mục 4.2).
Kho chỉ dùng được với đúng embedding `bge-m3`; đổi model là phải nạp lại từ đầu.

### 3.4. Cấu hình giao diện

```powershell
cd lightrag_webui
bun install --frozen-lockfile
cd ..
```

Tạo `lightrag_webui\.env.development.local` (gitignored):

```
VITE_AGENT_LIVE=true
VITE_AGENT_BASE_URL=http://127.0.0.1:9700
VITE_AGENT_TOKEN=<token có "can_upload": true trong users.json>
```

### 3.5. Chạy

```powershell
powershell -ExecutionPolicy Bypass -File denso\scripts\serve_chat.ps1 -WithUI
```

Mở http://localhost:5173 và hỏi thử: *"Mô-men xoắn siết bu-lông SCV là bao nhiêu?"* → 6,9–10,8 Nm,
trích hướng dẫn SCV trang 4.

---

## 4. Sử dụng hằng ngày

### 4.1. Bật, tắt, khởi động lại

| Việc | Lệnh |
|---|---|
| Bật backend + giao diện | `serve_chat.ps1 -WithUI` |
| Khởi động lại sau khi sửa `.env`, prompt hay code gateway | `serve_chat.ps1 -Restart` |
| Cho người ngoài vào (link công khai) | `serve_chat.ps1 -Tunnel` – dòng `demo link` dùng được ngay |
| Cho khách upload / xoá (cả nhóm test) | thêm `-GuestUpload` – **ai có link cũng xoá được tài liệu và duyệt lệnh** |
| Bật dịch vụ IoT (mô phỏng bệ thử, sự cố thật, duyệt lệnh) | thêm `-WithIoT` (lần đầu thêm cả `-Restart`) – xem mục 4.4 |
| Cho phép tên miền giao diện khác | thêm `-CorsRegex '<regex>'` |
| Bật Docling (cần khi upload) | `denso\start.ps1 -DoclingOnly` |
| Tắt Docling (trả lại ~2 GB RAM) | `docker stop docling-serve` |

Các lệnh `.ps1` chạy bằng `powershell -ExecutionPolicy Bypass -File denso\scripts\<tên>.ps1 …`.
Dịch vụ đang chạy thì `serve_chat.ps1` giữ nguyên, chỉ bật những gì chưa chạy.

| Cổng | Dịch vụ |
|---|---|
| 5173 | giao diện dev |
| 9700 | Agent Gateway |
| 9621 / 9631 | LightRAG kho tri thức / kho tra cứu theo xe |
| 8899 | proxy API NVIDIA |
| 7998 | reranker ngôn ngữ |
| 5001 | Docling |
| 11434 | Ollama |
| 9710 | dịch vụ IoT (`-WithIoT`); dashboard phòng điều khiển mở qua gateway: http://localhost:9700/dashboard/ (cả qua tunnel) |
| 1883 / 5433 | MQTT / TimescaleDB (`iot_service/docker-compose.yml`) |

### 4.2. Upload và xoá tài liệu

Kéo file vào **Knowledge Hub**: PDF, DOCX, PPTX, XLSX, HTML, MD, TXT, ảnh. Một PDF 40 trang hỏi
được sau khoảng 2–3 phút; trang scan và ảnh chụp (cấp 1) thêm 1–4 phút mỗi trang. Xoá trong
Knowledge Hub gỡ tài liệu khỏi mọi kho đang chạy; file gốc trong `data/raw/` được giữ lại.

### 4.3. Giao diện trên Vercel

Vercel chỉ chứa giao diện; backend vẫn chạy trên máy có `serve_chat.ps1`. Project Vercel cần
Root Directory `lightrag_webui` và hai biến `VITE_DEMO_MODE=true`, `VITE_AGENT_LIVE=true`
(thêm biến xong phải **Redeploy**). Mở link kèm `?gateway=<link tunnel>`; tên miền Vercel ngoài
project gốc phải được cho phép bằng `-CorsRegex`.

### 4.4. Dịch vụ IoT (`iot_service/`)

Mô phỏng bệ thử máy nén, theo dõi ngưỡng và agent IoT đề xuất lệnh (`SET_RPM`, `STOP_TEST`) chờ
người duyệt. Giao diện vẫn chỉ nói chuyện với gateway :9700; gateway chuyển tiếp sự cố, telemetry và
quyết định duyệt / từ chối sang IoT :9710, còn agent IoT tra tài liệu qua `POST /agent/chat` nên có
phân quyền và trích dẫn theo trang như giao diện. Lệnh chỉ đi tới **máy mô phỏng**, không tới PLC.

Cài một lần (venv riêng: IoT ghim fastapi/pydantic cũ hơn LightRAG):

```powershell
uv venv iot_service\.venv --python 3.11
uv pip install --python iot_service\.venv\Scripts\python.exe -r iot_service\requirements.txt
```

Chạy: `serve_chat.ps1 -WithIoT -Restart` (thêm `-WithUI` nếu cần). Khi Docker đang chạy, kịch bản bật
`iot_service/docker-compose.yml` – Mosquitto (:1883) và TimescaleDB (:5433), chỉ nghe trên máy; lần đầu tải
image `eclipse-mosquitto:2` và `timescale/timescaledb:2.17.2-pg16` – rồi bật máy mô phỏng. Sự cố, lệnh và
lịch sử cảm biến nằm trong TimescaleDB (volume `denso-iot_timescale-data`), còn lại sau khi tắt máy.
Không có Docker thì không có MQTT và IoT lưu trong RAM. Bơm sự cố thử:

```powershell
cd iot_service
.venv\Scripts\python -m simulator.cli set COMP-TB-01 condenser_fan_failure
```

Duyệt lệnh cần `"can_approve": true` trong `users.json` (hoặc `-GuestUpload`). LLM của agent IoT
(`AGENT_MODE=llm`) được trỏ sang proxy NVIDIA; mặc định `rules` không gọi LLM.

---

## 5. Pipeline xử lý tài liệu

Upload trên giao diện tự chạy chuỗi này cho từng file. Chạy tay cho cả thư mục:

```powershell
.venv\Scripts\python denso\pipeline\parse.py --level 1 denso\data\raw      # cần Docling
.venv\Scripts\python denso\pipeline\ocr_pages.py --docs "<tên file không đuôi>"   # trang scan (cấp 1)
.venv\Scripts\python denso\pipeline\clean.py
.venv\Scripts\python denso\scripts\ingest.py --level 1 denso\data\cleaned_md
```

| Bước | Đầu vào → đầu ra | Ghi chú |
|---|---|---|
| `parse.py` | `data/raw/*` → `data/parsed/<tên>/docling.md, docling.json, meta.json` | PDF dài chia đoạn 20 trang, chạy lại tiếp được sau khi máy tắt đột ngột |
| `ocr_pages.py` | trang không có lớp chữ → thay chữ Docling bằng chữ Vision 90B | bản Docling giữ ở `docling_ocr.md`; chỉ tài liệu cấp 1 |
| `clean.py` | → `data/cleaned_md/<tên>.md` (nạp LightRAG), `cleaned_json/<tên>.json` (schema A3), `clean_report.json` | mỗi trang gắn `--- [Trang N \| ngôn ngữ: xx] ---` |
| `ocr_images.py` | ảnh trong PDF → mô tả + chữ trong ảnh | chỉ tài liệu cấp 1 |
| `ingest.py` | → kho LightRAG `level_N … level_3` | `--replace` thay bản cũ cùng tên |

Cấp quyền lấy từ `--level`, hoặc thư mục `level_N` gần nhất (mặc định 1). Tài liệu cấp N được nạp
vào kho cấp N đến 3; người dùng cấp K chỉ hỏi được kho cấp K.

Quy tắc làm sạch (`clean.py`), rút từ lỗi thật trong output Docling:

| Lỗi | Xử lý |
|---|---|
| `&gt;`, `\_` | bỏ escape HTML / Markdown |
| `P r i n t e d i n B` | bỏ dòng chữ tách rời (công thức có `=` được giữ) |
| dòng ≤ 2 ký tự, ký tự CJK lạc | bỏ |
| `Ref ri gerant`, `comfort able` | ghép từ khi có bằng chứng từ điển; không áp dụng tiếng Việt |
| header/footer lặp | bỏ dòng ngắn lặp ở ≥ nửa số trang |
| bảng | chuẩn hoá Markdown, giữ `\|` trong ô |

Không lọc ngôn ngữ: hướng dẫn đa ngôn ngữ giữ mọi phần, mỗi trang được gắn ngôn ngữ của nó.

---

## 6. Đánh giá độ chính xác

| Bài đo | Lệnh | Kết quả gần nhất |
|---|---|---|
| Benchmark 30 câu (tiếng Anh) | `run_benchmark.py --name <tên> --modes naive` (model giám khảo: `--judge-model`, xem `--help`) | LLM giám khảo 98%, tìm đúng tài liệu 100% |
| Chấm benchmark theo dữ kiện | `score_facts.py --name <tên>` | đủ dữ kiện 84% |
| Tra cứu theo xe (10 câu) | `eval_lookup.py --name <tên>` | 10/10 |
| Đúng ngôn ngữ (10 câu Việt/Anh/Nhật) | `eval_language.py --name <tên>` | 9–10/10 |
| Tìm kiếm, không gọi LLM | `eval_retrieval.py`, `eval_rerank.py` | reranker ngôn ngữ: hit@1 68% → 75% |
| Test tự động | `.venv\Scripts\python -m pytest denso\tests -q -o addopts=""` | |

Các script nằm trong `denso\scripts\` và chạy bằng `.venv\Scripts\python`. Kết quả ghi vào
`denso/results/`. Benchmark gửi đúng prompt như gateway, nên điểm là điểm của demo; "tìm đúng tài
liệu" chỉ đo tài liệu được truy xuất, không đo trang trích dẫn trên giao diện. Bộ 30 câu đã dùng
để chọn cấu hình, nên con số trên một bộ câu chưa từng dùng (lần chạy đầu: 89% đủ dữ kiện, 87%
đúng trang) phản ánh thực tế hơn.

---

## 7. Agent Gateway (API cho giao diện)

`gateway/app.py` (FastAPI, :9700) là backend mà `lightrag_webui/src/api/agent.ts` gọi; giao diện
không bao giờ gọi LightRAG trực tiếp. Đặc tả đầy đủ: `docs/AGENT_GATEWAY_SPEC.md`.

| Endpoint | Tác dụng |
|---|---|
| `POST /agent/chat` | hỏi đáp: chọn kho theo cấp, câu hỏi tra xe sang tầng tra cứu; trả `content`, `citations` (tài liệu, trang, trích đoạn), `events`, `grounded` |
| `GET /agent/documents` | danh sách tài liệu, kể cả upload đang xử lý |
| `POST /agent/documents` | upload qua pipeline (cần `can_upload`); `GET /agent/documents/jobs/{id}` theo dõi |
| `GET /agent/documents/{id}/file` | file gốc cho cửa sổ xem trước (chỉ tài liệu ở cấp của người gọi) |
| `DELETE /agent/documents/{id}` | xoá khỏi mọi kho đang chạy; báo cấp nào chưa kiểm tra được |
| `GET /agent/incidents`, `/agent/telemetry/{id}` | từ dịch vụ IoT khi bật `-WithIoT`, nếu không là dữ liệu MẪU (`sample_ops.json`) |
| `POST /agent/actions/{id}/approve\|reject` | có IoT: chuyển sang IoT (cần `can_approve`), lệnh chạy trên máy mô phỏng; không có IoT: chỉ ghi log. **Không bao giờ gửi lệnh PLC** |
| `POST /agent/chat` trong hội thoại của một sự cố IoT | trả lời từ tài liệu như thường, kèm ngữ cảnh sự cố (máy, cảnh báo, số liệu cảm biến, lệnh đề xuất) trong prompt; trích dẫn và ngôn ngữ như phiên hỏi đáp |
| `GET /agent/health` | trạng thái các kho LightRAG (và IoT) |

---

## 8. Bảo mật và phân quyền

- **Phân quyền ở gateway:** cấp lấy từ `Authorization: Bearer <token>` tra trong
  `gateway/users.json`; không có token là khách (`DENSO_GUEST_LEVEL`, mặc định 1). Trình duyệt
  không tự chọn được cấp. Mỗi cấp là một kho LightRAG riêng.
- **Duyệt lệnh IoT** cần `can_approve` (hoặc `-GuestUpload`). Dịch vụ IoT chỉ nghe trên `127.0.0.1`
  vì các route `/agent/*` của nó không có xác thực: mọi thao tác phải đi qua gateway.
- **Lịch sử hội thoại** tách theo người dùng; xoá tài liệu xoá luôn lịch sử có thể trích nó.
- **API miễn phí chỉ cho cấp 1:** trả lời, đọc ảnh và trang scan; cấp 2/3 không gửi ra ngoài.
- **Không commit bí mật:** `.env`, `users.json`, `data/`, `rag_storage/` đều gitignored;
  `.dockerignore` loại chúng khỏi image.

---

## 9. Giới hạn và lưu ý

- **Không chạy LLM trả lời trên laptop:** ba lần máy tắt đột ngột (2026-10-07) khi Ollama chạy
  qwen3:8b với prompt khoảng 16K token – RAM trống tụt dưới 1 GB. Ollama chỉ giữ bge-m3.
- **RAM:** Docling khoảng 2 GB; giữ RAM trống trên 2 GB, đóng bớt trình duyệt khi upload nhiều.
- **API miễn phí:** khoảng 20–25 giây một câu qua giao diện, có lúc 1–3 phút.
- **Câu trả lời có thể ghép sai** hai dữ kiện đúng thành một ý sai; luôn kiểm tra trang được trích.
- **Chưa có:** chữ viết tay (chưa có mẫu đo), âm thanh, kho cấp 2/3 đang chạy.

---

## 10. Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Giao diện Vercel ra dữ liệu mẫu / bản cũ | thiếu `VITE_DEMO_MODE` / `VITE_AGENT_LIVE` hoặc chưa Redeploy; link thiếu `?gateway=` |
| "the answering LLM returned nothing" | hết hạn mức hoặc API chậm: xem `denso/logs/llm_proxy_nvidia_api_key.jsonl`, hỏi lại sau ít phút |
| Upload báo "Docling is not running" | `denso\start.ps1 -DoclingOnly` |
| Docker Desktop không lên | mở Docker Desktop xem hộp thoại cần bấm; sau lần tắt máy đột ngột `start.ps1` tự dời socket hỏng (`%LOCALAPPDATA%\Docker\run`) |
| Cổng đã bị chiếm | `serve_chat.ps1 -Restart`, hoặc tắt tiến trình đang giữ cổng |
| "Tài khoản này không có quyền upload tài liệu" | token có `can_upload` trong `.env.development.local`, hoặc gateway chạy `-GuestUpload` |
| Trình duyệt báo lỗi CORS | tên miền giao diện chưa được cho phép: `-CorsRegex` |
| Máy chậm / treo | đóng bớt ứng dụng, tắt Docling khi không upload |
| `-WithIoT` báo `mqtt=MISSING` | bật Docker Desktop rồi chạy lại; không có MQTT thì không có telemetry và sự cố |
| Xoá sạch dữ liệu IoT (sự cố, lịch sử cảm biến) | `docker compose -f iot_service/docker-compose.yml down -v` |
| Sự cố IoT không hiện trên giao diện | gateway chạy trước khi có `-WithIoT`: chạy lại với `-WithIoT -Restart` |
| Duyệt lệnh báo "may not approve" | token cần `"can_approve": true` trong `users.json` |

Nên thoát Docker bằng **Quit** ở khay hệ thống, không tắt ngang.

---

## 11. Docker (chưa dùng cho demo)

`docker-compose.yml`, `Dockerfile`, `compose.env.example` dựng LightRAG + gateway + proxy trong
container, dữ liệu để trên máy (`rag_storage/`, `denso/data`). **Bộ này còn theo cấu hình cũ**
(proxy Cerebras, reranker Infinity), chưa có reranker ngôn ngữ và chưa chạy thử trọn vẹn – dùng
`serve_chat.ps1` cho demo. Cập nhật Docker là việc cần làm cho yêu cầu "tài liệu tái lập" và chạy
trên máy chủ.

```powershell
Copy-Item denso\compose.env.example denso\compose.env
docker compose -f denso/docker-compose.yml --profile proxy up -d
```
