# DENSO A3 – Knowledge Agent

Dự án cho đề A3 – DENSO Factory Hacks 2026:

- **Chatbot tài liệu kỹ thuật**: đọc tài liệu nhiều định dạng (PDF, bản scan, ảnh chụp, DOCX, XLSX, TXT;
  tiếng Việt, Anh, Nhật), trả lời bằng ngôn ngữ người hỏi, **luôn kèm tài liệu và số trang**, và nói rõ
  khi tài liệu không có câu trả lời.
- **Giám sát nhà xưởng (Long-agent)**: 5 máy mô phỏng, phát hiện bất thường, agent đề xuất lệnh; bảng tester
  để bật lỗi mô phỏng, mở từ nút **Dashboard**. Lệnh chỉ đi tới máy mô phỏng, không tới PLC thật.

## Cấu trúc

```
LightRAG/
├── README.md                    tài liệu này
├── .env                         (gitignored) cấu hình + API key, ghép từ env.example và denso/env.denso
│
├── denso/                       ★ phần chính của dự án – bắt đầu ở denso/README.md
│   ├── scripts/serve_chat.ps1   bật toàn bộ backend (-WithUI giao diện, -WithIoT Long-agent, -Tunnel demo)
│   ├── start.ps1                bật Docker Desktop + Docling
│   ├── pipeline/                xử lý tài liệu: Docling → OCR → làm sạch → nạp vào LightRAG
│   ├── gateway/                 Agent Gateway :9700 – backend của giao diện
│   │   ├── app.py               API, phân quyền, trích dẫn, upload/xoá tài liệu, relay dashboard
│   │   ├── long_agent.py        dựng sự cố + thẻ duyệt HITL từ cảnh báo của Long-agent
│   │   └── jobs.py, language.py, lookup.py
│   ├── tools/                   proxy giới hạn tốc độ LLM, reranker ưu tiên ngôn ngữ
│   ├── prompts/                 quy tắc trả lời, loại thực thể cho đồ thị
│   ├── tests/                   test gateway và pipeline (pytest)
│   ├── docs/                    đặc tả API gateway
│   ├── docling/                 Docling bản CPU (Docker)
│   └── data/ logs/ results/     (gitignored) tài liệu, log, kết quả đo
│
├── long_agent/                  Long-agent – giám sát nhà xưởng mô phỏng (long_agent/README.md)
│   ├── main.py                  ghép 3 tầng + FastAPI :8085
│   ├── machines/                5 máy mô phỏng (CNC, robot, ép nhựa, AOI, AMR) + ngưỡng
│   ├── iot/                     event bus, lọc bất thường, duyệt HITL, gửi lệnh tới máy mô phỏng
│   ├── agent/                   chẩn đoán bằng LLM, đề xuất lệnh sửa gốc
│   ├── dashboard/               bảng tester (bật lỗi mô phỏng), API trạng thái
│   ├── machines_description.md  mô tả máy và lỗi – cũng nạp vào kho tri thức
│   └── tests/
│
├── lightrag_webui/              giao diện web (React + Vite), deploy lên Vercel (vercel.json)
│   ├── agentic.html             trang vào của giao diện DENSO
│   └── src/
│       ├── features/agentic/    ★ giao diện DENSO: chat, Automated Alerts, thẻ duyệt, kho tri thức
│       │   ├── components/      thanh trên (nút Dashboard), sidebar sự cố, khung chat, thẻ HITL
│       │   ├── stores/          trạng thái hội thoại, duyệt / từ chối qua gateway
│       │   ├── liveIncidents.ts gộp sự cố từ gateway vào sidebar, theo thứ tự thời gian
│       │   └── mock/            dữ liệu mẫu khi chạy không có gateway
│       ├── api/agent.ts         client gọi Agent Gateway
│       └── ...                  phần còn lại là WebUI gốc của LightRAG
│
├── lightrag/                    lõi RAG – LightRAG (HKUDS), dùng nguyên, không sửa
├── tests/                       test của lõi LightRAG
├── docs/                        tài liệu LightRAG gốc (docs/LightRAG-README.md) và thiết kế lõi
├── scripts/                     bộ chạy test, bộ cài đặt môi trường của LightRAG
├── prompts/                     mẫu prompt của LightRAG
├── pyproject.toml, uv.lock      phụ thuộc Python (uv sync)
├── Dockerfile, docker-compose-full.yml, Makefile, env.example   từ LightRAG gốc
│
└── rag_storage/                 (gitignored) kho tri thức: level_1/, level_1_lookup/
```

## Chạy nhanh

Chi tiết từng bước (cài đặt, dữ liệu, `.env`, giao diện) ở [denso/README.md](denso/README.md) mục 3.

```powershell
uv sync --extra api
uv pip install --python .venv\Scripts\python.exe -r denso\requirements.txt
powershell -ExecutionPolicy Bypass -File denso\scripts\serve_chat.ps1 -WithUI            # chatbot
powershell -ExecutionPolicy Bypass -File denso\scripts\serve_chat.ps1 -WithUI -WithIoT   # + Long-agent
```

Giao diện: http://localhost:5173 · Bảng tester Long-agent: http://localhost:9700/dashboard/

## Nguồn gốc và giấy phép

Lõi RAG là [LightRAG](https://github.com/HKUDS/LightRAG) (HKUDS, giấy phép MIT – xem [LICENSE](LICENSE)).
Nhánh này bỏ các ví dụ, bộ triển khai Kubernetes/Docker không dùng và tài liệu dịch của bản gốc; test và
tài liệu thiết kế của lõi được giữ để vẫn kiểm tra được LightRAG.
