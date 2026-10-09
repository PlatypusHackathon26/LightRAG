# DENSO A3 – RAG chatbot chạy local

Mọi thứ của DENSO nằm trong thư mục `denso/`; lõi LightRAG không bị sửa, nên vẫn
kéo được bản cập nhật từ upstream.

```
Nạp:  PDF/DOCX/XLSX/TXT/ảnh ─► pipeline/parse.py (docling-serve :5001)
        ─► [pipeline/ocr_pages.py: trang scan / ảnh chụp, NVIDIA 90B vision, cấp 1] ─► pipeline/clean.py
        (trang + ngôn ngữ) ─► [pipeline/ocr_images.py: chữ trong ảnh] ─► scripts/ingest.py
Hỏi:  UI ─► Agent Gateway :9700 (quyền, trích dẫn) ─► LightRAG :9621 (level_1) / :9631 (lookup)
        ─► reranker ngôn ngữ :7998 ─► proxy :8899 ─► LLM API (NVIDIA)
      Embedding: bge-m3 trên Ollama local (:11434)
```

Dữ liệu rời khỏi máy: câu hỏi và đoạn tài liệu **cấp 1** đi tới LLM API để sinh câu trả lời;
ảnh trong tài liệu **cấp 1** đi tới API thị giác để đọc chữ. Tài liệu cấp 2/3 không được gửi
qua API miễn phí. Mọi service chỉ bind vào localhost (trừ tunnel demo khi bật `-Tunnel`).

## Chạy từ A đến Z (cho thành viên mới)

Kết quả cuối: chatbot ở http://localhost:5173 trả lời từ cùng kho tài liệu với máy demo.
Cần Windows, khoảng 16 GB RAM (RAM trống ít nhất 4 GB khi chạy), mạng Internet.

### 1. Cài phần mềm (một lần)

| Phần mềm | Dùng để | Ghi chú |
|---|---|---|
| Git, Python 3.11 | code, backend | |
| [uv](https://docs.astral.sh/uv/) | cài thư viện Python | |
| [Bun](https://bun.sh) | giao diện web | |
| [Ollama](https://ollama.com) | tạo vector (bge-m3) | chạy nền sau khi cài |
| Docker Desktop | Docling (đọc PDF, OCR) | chỉ cần khi upload tài liệu |
| cloudflared | link công khai | chỉ cần khi cho người ngoài vào |

### 2. Lấy code và cài thư viện

```powershell
git clone https://github.com/PlatypusHackathon26/LightRAG.git
cd LightRAG
git checkout feat/rag-backend
uv sync --extra api
uv pip install --python .venv\Scripts\python.exe -r denso\requirements.txt
ollama pull bge-m3
```

`uv sync` lần sau sẽ gỡ các gói thêm ở dòng thứ năm: chạy lại dòng đó sau mỗi lần `uv sync`.

### 3. Dữ liệu và cấu hình (không có trên GitHub)

| Thứ | Lấy ở đâu | Đặt ở đâu |
|---|---|---|
| Kho tri thức + tài liệu | file `denso_data_bundle_<ngày>.zip` do nhóm gửi | giải nén vào thư mục gốc repo (tạo `rag_storage/` và `denso/data/`) |
| `.env` | tự tạo (dưới đây) hoặc xin nhóm qua kênh kín | thư mục gốc repo |
| API key NVIDIA | đăng ký miễn phí tại https://build.nvidia.com | dòng `NVIDIA_API_KEY=` trong `.env` |
| `users.json` | chép `denso\gateway\users.example.json` | `denso\gateway\users.json`, đổi các token thành chuỗi ngẫu nhiên dài |

Tự tạo `.env` (mọi giá trị DENSO nằm trong `denso/env.denso`, dòng sau ghi đè dòng trước):

```powershell
Copy-Item env.example .env
Get-Content denso\env.denso | Add-Content .env
notepad .env      # thay NVIDIA_API_KEY=nvapi-put-your-own-key-here bằng key của bạn
```

Không có kho dữ liệu thì vẫn chạy được nhưng chatbot chưa có tài liệu: upload ở bước 6.
Kho chỉ dùng được với đúng embedding `bge-m3` (1024 chiều); đổi model là phải nạp lại từ đầu.

### 4. Cấu hình giao diện

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

### 5. Chạy

```powershell
powershell -ExecutionPolicy Bypass -File denso\scripts\serve_chat.ps1 -WithUI
```

Lệnh bật lần lượt proxy NVIDIA (:8899), reranker ngôn ngữ (:7998), LightRAG kho tri thức (:9621)
và kho tra cứu (:9631), Agent Gateway (:9700) và giao diện (:5173), rồi in trạng thái từng dịch vụ.
Mở http://localhost:5173 và hỏi thử: "Mô-men xoắn siết bu-lông SCV là bao nhiêu?" → 6,9–10,8 Nm,
trích hướng dẫn SCV trang 4.

| Tuỳ chọn của `serve_chat.ps1` | Tác dụng |
|---|---|
| `-WithUI` | bật thêm giao diện dev :5173 |
| `-Restart` | khởi động lại LightRAG và gateway (sau khi sửa `.env`, prompt hay code gateway) |
| `-Tunnel` | link công khai qua Cloudflare; dòng `demo link` là link Vercel dùng được ngay |
| `-GuestUpload` | khách (không token) được upload và xoá tài liệu – chỉ dùng khi cả nhóm test |
| `-CorsRegex '<regex>'` | cho phép thêm tên miền giao diện khác (ví dụ project Vercel riêng) |

### 6. Upload tài liệu (cần Docling)

```powershell
powershell -ExecutionPolicy Bypass -File denso\start.ps1 -DoclingOnly
```

Sau đó kéo file vào Knowledge Hub trên giao diện: PDF, DOCX, XLSX, TXT, ảnh. Trang scan và ảnh
chụp của tài liệu cấp 1 được đọc bằng mô hình thị giác NVIDIA (1–4 phút mỗi trang). Docling
chiếm khoảng 2 GB RAM: tắt bằng `docker stop docling-serve` khi không upload.

### 7. Kiểm tra lại độ chính xác

```powershell
.venv\Scripts\python denso\scripts\eval_lookup.py --name thu      # 10 câu tra cứu theo xe
.venv\Scripts\python denso\scripts\eval_language.py --name thu    # trả lời đúng ngôn ngữ
.venv\Scripts\python -m pytest denso\tests -q -o addopts=""       # test tự động
```

Benchmark 30 câu: xem mục Benchmark bên dưới. Kết quả nằm trong `denso/results/`.

### 8. Giao diện trên Vercel

Vercel chỉ chứa giao diện; backend vẫn chạy trên máy có `serve_chat.ps1`. Project Vercel cần
Root Directory `lightrag_webui` và hai biến môi trường `VITE_DEMO_MODE=true`,
`VITE_AGENT_LIVE=true` (thêm biến xong phải Redeploy). Mở link kèm `?gateway=<link tunnel>`.
Tên miền Vercel khác project gốc phải được cho phép bằng `-CorsRegex`, nếu không trình duyệt chặn.

### Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Giao diện Vercel ra dữ liệu mẫu / bản cũ | thiếu `VITE_DEMO_MODE` / `VITE_AGENT_LIVE` hoặc chưa Redeploy; link thiếu `?gateway=` |
| "the answering LLM returned nothing" | hết hạn mức hoặc API chậm: xem `denso/logs/llm_proxy_nvidia_api_key.jsonl`, hỏi lại sau ít phút |
| Upload báo "Docling is not running" | chạy `denso\start.ps1 -DoclingOnly` |
| `start.ps1` báo Docker không lên | mở Docker Desktop xem có hộp thoại cần bấm; sau lần tắt máy đột ngột script tự dời socket hỏng |
| Cổng đã bị chiếm | `serve_chat.ps1 -Restart`, hoặc tắt tiến trình đang giữ cổng |
| Máy chậm / treo | đóng bớt ứng dụng; không chạy LLM trả lời trên máy (xem mục bên dưới) |
| "Tài khoản này không có quyền upload tài liệu" | dùng token có `can_upload` trong `.env.development.local`, hoặc chạy gateway với `-GuestUpload` |

Docker Desktop trên máy này: nếu bị tắt đột ngột, nó để lại socket hỏng và lần sau báo
"The file cannot be accessed by the system". `start.ps1` tự đổi tên `%LOCALAPPDATA%\Docker\run`
(và `docker-secrets-engine`) trước khi bật lại; nên thoát Docker bằng Quit ở khay hệ thống.

## Pipeline xử lý dữ liệu (raw → sạch → kho tri thức)

```
data/raw/[level_N/]*  ─► pipeline/parse.py  ─► data/parsed/<tên>/docling.{md,json}, meta.json
                      ─► pipeline/clean.py  ─► data/cleaned_md/<tên>.md      (nạp vào LightRAG)
                                             ─► data/cleaned_json/<tên>.json  (schema A3 output_format.json)
                                             ─► data/parsed/<tên>/clean_report.json (đã bỏ/sửa gì)
                      ─► scripts/ingest.py  ─► LightRAG workspace level_N … level_3
```

```powershell
.venv\Scripts\python denso\pipeline\parse.py denso\data\raw      # cần docling-serve đang chạy
.venv\Scripts\python denso\pipeline\clean.py
.venv\Scripts\python -m pytest denso\tests -q -o addopts=""
```

`access_level` lấy từ thư mục `level_N` gần nhất (mặc định 1) hoặc `--level`.

### Catalogue lớn và máy bị tắt đột ngột

PDF dài hơn `--chunk-pages` (mặc định 20) được parse theo từng đoạn trang, mỗi
đoạn lưu ngay vào `data/parsed/<tên>/parts/`. File được ghi qua tên tạm rồi
đổi tên; `meta.json` ghi cuối cùng = file đã xong. docling-serve bị giới hạn
6 CPU (`docker-compose.yml`) để giảm nhiệt.

Nếu máy tắt giữa chừng:

```powershell
powershell -ExecutionPolicy Bypass -File denso\start.ps1 -DoclingOnly   # tự dọn socket Docker hỏng
.venv\Scripts\python denso\pipeline\parse.py --chunk-pages 20 --cooldown 15 denso\data\raw   # chạy lại y nguyên lệnh cũ
```

Chỉ mất đoạn trang đang dở; log nằm ở `denso/logs/parse_catalogues.log`.

Quy tắc làm sạch (`clean.py`), rút từ lỗi thật trong output Docling:

| Lỗi | Xử lý |
|---|---|
| `&gt;`, `\_` | unescape HTML / Markdown |
| `<!-- image -->` | bỏ |
| `P r i n t e d i n B`, `D E A` | bỏ dòng chữ tách rời (không tính ký hiệu gạch đầu dòng) |
| `0`, `o`, `审` | bỏ dòng ≤ 2 ký tự chữ/số, ký tự CJK lạc trong trang không phải CJK |
| `Ref ri gerant`, `t ype:`, `comfort able` | ghép từ khi có bằng chứng từ điển (wordfreq), không áp dụng cho tiếng Việt |
| `A /C` | `A/C` |
| header/footer lặp | bỏ dòng ngắn lặp ≥ nửa số trang |
| bảng | chuẩn hoá Markdown gọn, ghi `tables[].page` |

Không lọc ngôn ngữ: benchmark hỏi đối chiếu phần tiếng Nga/Đức/Pháp. Mỗi trang
được gắn `--- [Trang N | ngôn ngữ: xx] ---` trong `.md`; `cleaned_text` của JSON
giữ đúng định dạng `--- [Trang N] ---` của schema.

Hạn chế đã biết: từ IN HOA bị cắt ở mép cột trong lớp text của PDF gốc
(`LEAKAG`, `INSTALLATIO`) chưa được sửa.

### Không chạy LLM trả lời trên máy local

Ba lần tắt nguồn đột ngột ngày 2026-10-07 đều xảy ra khi qwen3:8b trả lời câu hỏi
(prompt ~16K token): runner của Ollama chiếm thêm ~4.75 GB RAM hệ thống ngay lúc bắt đầu
suy luận, RAM trống tụt dưới 1 GB rồi máy tắt cứng. Vai trò QUERY/KEYWORD chỉ chạy qua API
(proxy `tools/llm_rate_proxy.py`); Ollama local chỉ giữ bge-m3 cho embedding. Trước khi
chạy dài: đóng bớt tab trình duyệt và app nặng; không chạy Docling (Docker) cùng lúc.

## Nạp tài liệu

Tài liệu cấp N được nạp vào các workspace `level_N` … `level_3`; người dùng có
quyền K chỉ truy vấn `level_K`.

```powershell
.venv\Scripts\python denso\pipeline\parse.py --level 1 denso\data\raw
.venv\Scripts\python denso\pipeline\clean.py
.venv\Scripts\python denso\scripts\ingest.py --level 1 denso\data\cleaned_md
```

(Upload từ giao diện chạy đúng chuỗi này cho từng file.)

## Benchmark

```powershell
.venv\Scripts\python denso\scripts\run_benchmark.py --server http://127.0.0.1:9621 --name level_1 --modes naive --judge-model z-ai/glm-5.3-flash --judge-reasoning ""
.venv\Scripts\python denso\scripts\score_facts.py --name level_1
```

Kết quả: `denso/results/benchmark_<name>.md` (điểm judge, tỉ lệ trúng nguồn, độ trễ, theo
loại câu hỏi). Benchmark gửi đúng prompt như gateway, nên điểm là điểm của demo. "Trúng nguồn"
chỉ đo tài liệu được truy xuất, không đo trang trích dẫn hiển thị trên giao diện.

## Lưu ý bảo mật

- **Phân quyền nằm ở Agent Gateway**: mỗi cấp là một server LightRAG riêng, gateway chọn
  server theo token trong `gateway/users.json` (không tin cấp do client gửi). Các server
  LightRAG chỉ bind localhost; đặt `LIGHTRAG_API_KEY` nếu có thể bị gọi trực tiếp.
- Image Docker không chứa `denso/data`, log, `users.json` hay file `.env` (`.dockerignore`).
- Không bật MinerU chế độ `official` (gửi file lên cloud).

## Giới hạn phần cứng (laptop 16GB RAM)

- Chạy tuần tự: Docling parse xong rồi mới index. `MAX_ASYNC_LLM=1`,
  `MAX_PARALLEL_INSERT=1` trong `.env`.
- Catalogue vài trăm trang (Spark Plug, Wiper, AC Components) rất lâu trên CPU;
  nên thử với các tài liệu nhỏ trước.

## Agent Gateway (backend cho UI agentic)

`denso/gateway/app.py` (FastAPI, cổng 9700) là backend mà `lightrag_webui/src/api/agent.ts`
gọi tới; UI không bao giờ gọi LightRAG trực tiếp.

| Endpoint | Nguồn |
|---|---|
| `POST /agent/chat` | LightRAG `/query` của server theo cấp quyền (`naive`, đổi bằng `DENSO_KNOWLEDGE_MODE`); câu hỏi tra xe/mã ("fits a 2018 Toyota…", "cross reference", "lắp cho xe nào") → server tra cứu (`naive`). Trả `content`, `citations` (documentName, pages từ dấu trang, excerpt), `events` |
| `GET/POST /agent/documents` | danh sách tài liệu (KnowledgeDocument) / upload cộng dồn level N..3 (cần `can_upload`) |
| `GET /agent/incidents`, `/agent/telemetry/{id}` | `gateway/sample_ops.json` (dữ liệu MẪU) |
| `POST /agent/actions/{id}/approve|reject` | chỉ ghi `logs/actions.jsonl` – **không bao giờ gửi lệnh PLC** |
| `GET /agent/health` | trạng thái các server LightRAG |

Cấp quyền lấy từ `Authorization: Bearer <token>` tra trong `gateway/users.json`
(gitignored; mẫu ở `users.example.json`); không có token → `DENSO_GUEST_LEVEL`.
Client không thể tự chọn cấp quyền.

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python denso\gateway\app.py
```

Phía UI cần: thêm `/agent` vào `VITE_API_ENDPOINTS` (proxy dev tới :9700) và cho
`agenticStore.ts` gọi `api/agent.ts` thay vì mock.

## Benchmark: kết quả và cách chạy lại

Kết quả lượt đầu (`results/benchmark_level_1_knowledge.*`): naive 30/30 câu, mix
dừng ở Q25 vì Cerebras hết quota ngày. Trên 24 câu chạy cả hai mode: naive judge 98% /
dữ kiện 91%, mix 83% / 73% – nhưng mix bị thiệt: với `MAX_TOTAL_TOKENS=16000`, ngân
sách mặc định 6000 (entity) + 8000 (relation) chỉ chừa 2 chunk văn bản gốc.

Chạy lại mix công bằng (naive giữ nguyên trong `benchmark_level_1_budgetfix.json`):

```powershell
# 1. key mới trong .env (EXTRACT_LLM_BINDING_API_KEY=csk-..., không kèm < >)
# 2. proxy với hạn mức mới, không fallback
.venv\Scripts\python denso\tools\llm_rate_proxy.py --fresh-key --fallback-model ""
# 3. khởi động lại server level_1 để nhận MAX_ENTITY_TOKENS=3000 / MAX_RELATION_TOKENS=4000
$env:WORKSPACE="level_1"; $env:PORT="9621"; $env:PYTHONIOENCODING="utf-8"; .venv\Scripts\lightrag-server.exe
# 4. chỉ chạy mix (naive đã có sẵn trong file); --no-rerank giữ đúng cách truy xuất
#    của lượt naive (không reranker, chunk_top_k=10) dù .env đã bật reranker
.venv\Scripts\python denso\scripts\run_benchmark.py --name level_1_budgetfix --modes mix --no-rerank
.venv\Scripts\python denso\scripts\score_facts.py --name level_1_budgetfix
```

Đo hiệu quả reranker đầu-cuối: chạy cả hai mode **không** có `--no-rerank` với tên
khác (ví dụ `level_1_langpref`) rồi so với `level_1_budgetfix`.

Thí nghiệm prompt (`USER_PROMPT_PREFIX_FILE=denso_answer.md`) ảnh hưởng mọi mode nên
chạy riêng với tên khác, cả naive lẫn mix.

## Reranker ưu tiên ngôn ngữ

Catalogue/hướng dẫn đa ngôn ngữ lặp cùng một mục bằng tối đa 17 thứ tiếng; embedding
đa ngôn ngữ xếp bản dịch ngang bản gốc nên đẩy chunk đúng ngôn ngữ ra khỏi ngữ cảnh.
`tools/lang_rerank.py` (endpoint `/rerank` kiểu Cohere, cổng 7998) giữ thứ tự vector
nhưng đưa chunk có `ngôn ngữ: xx` trùng ngôn ngữ câu hỏi lên trước – trừ khi câu hỏi
nhắc tới ngôn ngữ khác ("the Russian section", "tiếng Đức", "other languages"), khi
đó giữ nguyên thứ tự. Không gọi LLM, không cần GPU, ~0 ms/câu.

```powershell
.venv\Scripts\python denso\tools\lang_rerank.py      # start.ps1 tự bật
# .env: RERANK_BINDING=cohere, RERANK_MODEL=denso-lang-pref,
#       RERANK_BINDING_HOST=http://127.0.0.1:7998/rerank, CHUNK_TOP_K=30
```

`CHUNK_TOP_K=30` là tập ứng viên để sắp xếp lại; `MAX_TOTAL_TOKENS` vẫn quyết định số
chunk vào LLM (~10–12). Service tắt thì LightRAG giữ thứ tự vector (chỉ log cảnh báo).

Kết quả trên 28 câu có đáp án (naive, đo trực tiếp qua `/query/data` của server):

| | hit@1 | trích dẫn nằm trong ngữ cảnh | đủ mọi trích dẫn |
|---|---|---|---|
| không reranker (`chunk_top_k=10`) | 68% | 93% | 93% |
| ưu tiên ngôn ngữ | 75% | 100% | 100% |

Q6, Q20 từ ngoài ngữ cảnh lên hạng 7; câu hỏi chéo ngôn ngữ Q11/Q27/Q28 giữ nguyên.
Cross-encoder bge-reranker-v2-m3 trên CPU chậm (~84 s/câu) và kém hơn ở hit@1 nên
không dùng. So sánh offline: `scripts/eval_rerank.py --strategies baseline lang lang-pref`.

## Chạy bằng Docker

> **Chưa dùng được cho demo:** compose còn theo cấu hình cũ (proxy Cerebras, reranker
> Infinity) và chưa có reranker ngôn ngữ, chưa chạy thử trọn vẹn. Dùng `serve_chat.ps1` ở trên.

`denso/docker-compose.yml` (chạy từ thư mục gốc repo). Image LightRAG build từ
`Dockerfile` gốc (đã có WebUI, gồm trang agentic); pipeline/gateway/proxy dùng
`denso/Dockerfile`. Dữ liệu nằm trên host: `rag_storage/` (index có sẵn được dùng lại),
`denso/data`, `denso/results`, `denso/logs`. Mọi cổng chỉ bind `127.0.0.1`.

```powershell
Copy-Item env.example .env; Get-Content denso\env.denso | Add-Content .env   # cấu hình host
Copy-Item denso\compose.env.example denso\compose.env                        # override cho container
docker compose -f denso/docker-compose.yml --profile proxy up -d             # LightRAG level_1 + gateway + proxy
```

| Profile | Thêm gì |
|---|---|
| (mặc định) | `lightrag-level1` :9621, `gateway` :9700 |
| `proxy` | rate proxy free-tier (cần khi EXTRACT/QUERY/KEYWORD dùng API – xem `compose.env`) |
| `parse` | `docling` :5001 + job `pipeline` (parse/clean/check_evidence) |
| `rerank` | Infinity + bge-reranker-v2-m3 :7997 (CPU, chậm ~5 s/chunk) |
| `lookup` | server tầng tra cứu :9631 |
| `levels` | server level_2 :9622, level_3 :9623 |
| `local-llm` | Ollama CPU trong container (máy không có Ollama trên host) |

`.env` giữ giá trị chạy trực tiếp trên máy (localhost); `compose.env` chỉ ghi đè tên
service/đường dẫn container (đúng quy ước AGENTS.md).
