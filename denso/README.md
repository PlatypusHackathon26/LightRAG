# DENSO A3 – RAG chatbot chạy local

Mọi thứ của DENSO nằm trong thư mục `denso/`; lõi LightRAG không bị sửa, nên vẫn
kéo được bản cập nhật từ upstream.

```
PDF/DOCX/ảnh ─► docling-serve (Docker, CPU, 127.0.0.1:5001)   đọc file, OCR, bảng
                      │  LIGHTRAG_PARSER=pdf:docling-P,...
                      ▼
               LightRAG server (127.0.0.1:9621)  WebUI + REST API
                 ├─ workspace level_1 / level_2 / level_3 (cộng dồn theo quyền)
                 └─ Ollama (localhost:11434): qwen3:8b (LLM) + bge-m3 (embedding)
```

Không có dữ liệu nào rời khỏi máy: mọi service chỉ bind vào localhost.

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `docling/docker-compose.yml` | docling-serve bản CPU |
| `scripts/ingest.py` | Upload tài liệu theo cấp quyền và chờ index xong |
| `scripts/run_benchmark.py` | Chạy bộ 30 câu QA, so sánh các mode (`naive`, `mix`, …) |
| `start.ps1` | Khởi động Docling → Ollama → LightRAG |
| `data/raw/`, `data/evaluation/` | Tài liệu và benchmark (gitignored) |
| `results/` | Kết quả benchmark |
| `../.env` | Cấu hình LightRAG (gitignored) |

## Cài đặt lần đầu

1. Docker Desktop đang chạy; Ollama đã cài.
2. Kéo model và image:
   ```powershell
   ollama pull qwen3:8b
   ollama pull bge-m3
   docker compose -f denso/docling/docker-compose.yml pull
   ```
3. Môi trường Python (Python 3.11):
   ```powershell
   uv sync --extra api --python 3.11
   uv pip install --python .venv\Scripts\python.exe "ollama>=0.5.4,<1.0.0"
   ```
   Gói `ollama` không nằm trong extra `api`; LightRAG cố tự cài bằng pip nhưng
   venv của uv không có pip nên server sẽ crash nếu thiếu. (`uv sync` lần sau sẽ
   gỡ nó — cài lại bằng lệnh trên.)
4. Ollama: bật flash attention + nén KV cache để context 32K vừa 8GB VRAM
   (biến môi trường user `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`).
   Trên máy này app Ollama hay báo "server not ready" vì dò GPU Vulkan mất ~13s;
   `start.ps1` tự chạy `ollama serve` nếu API chưa lên.
5. WebUI: `cd lightrag_webui; bun install --frozen-lockfile; bun run build`

### Sự cố Docker Desktop trên máy này

Nếu Docker bị tắt đột ngột, nó để lại socket hỏng và lần sau báo
"initializing Inference manager … The file cannot be accessed by the system".
Cách sửa: thoát Docker, đổi tên `%LOCALAPPDATA%\Docker\run` (và
`%LOCALAPPDATA%\docker-secrets-engine` nếu lỗi nhắc tới nó), rồi mở lại Docker.
Luôn thoát Docker bằng Quit ở khay hệ thống.

6. Cấu hình: `.env` không được commit, các giá trị DENSO nằm ở `denso/env.denso`:
   ```powershell
   Copy-Item env.example .env
   Get-Content denso\env.denso | Add-Content .env
   ```
   Quan trọng nhất: `OLLAMA_LLM_NUM_PREDICT=8192`. Mặc định của LightRAG cho
   Ollama là 128 token output, cắt JSON trích xuất thực thể sau ~2 entity →
   log báo "JSON extraction result is empty or unrecoverable" và đồ thị rỗng.

## Chạy

```powershell
powershell -ExecutionPolicy Bypass -File denso\start.ps1
```

Mở http://127.0.0.1:9621. Chọn workspace ở góc WebUI (hoặc gửi header
`LIGHTRAG-WORKSPACE`).

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

## Nạp tài liệu

Tài liệu cấp N được nạp vào các workspace `level_N` … `level_3`; người dùng có
quyền K chỉ truy vấn `level_K`.

```powershell
.venv\Scripts\python denso\scripts\ingest.py --level 1 denso\data\raw
```

## Benchmark

```powershell
.venv\Scripts\python denso\scripts\run_benchmark.py --workspace level_3 --modes naive mix
```

Kết quả: `denso/results/benchmark_<workspace>.md` (điểm judge, tỉ lệ trúng nguồn,
độ trễ, điểm theo từng loại câu hỏi). Judge là chính qwen3:8b chạy local nên chỉ
dùng để so sánh tương đối giữa các mode, không phải điểm tuyệt đối.

## Lưu ý bảo mật

- **Workspace không phải phân quyền.** Ai gọi được API đều tự đặt được header
  `LIGHTRAG-WORKSPACE`. Khi triển khai cho người dùng thật cần một gateway xác
  thực người dùng rồi tự gắn header theo `access_level`; đặt `LIGHTRAG_API_KEY`
  để chặn truy cập trực tiếp.
- Không bật MinerU chế độ `official` (gửi file lên cloud).

## Giới hạn phần cứng (laptop 16GB RAM)

- Chạy tuần tự: Docling parse xong rồi mới index. `MAX_ASYNC_LLM=1`,
  `MAX_PARALLEL_INSERT=1` trong `.env`.
- Catalogue vài trăm trang (Spark Plug, Wiper, AC Components) rất lâu trên CPU;
  nên thử với các tài liệu nhỏ trước.
