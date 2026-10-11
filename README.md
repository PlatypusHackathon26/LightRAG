# DENSO A3 – Knowledge Agent

Dự án cho đề A3 – DENSO Factory Hacks 2026:

- **Chatbot tài liệu kỹ thuật**: đọc tài liệu nhiều định dạng (PDF, bản scan, ảnh chụp, DOCX, XLSX, TXT;
  tiếng Việt, Anh, Nhật), trả lời bằng ngôn ngữ người hỏi, **luôn kèm tài liệu và số trang**, và nói rõ
  khi tài liệu không có câu trả lời.
- **Giám sát nhà xưởng (Long-agent)**: 5 máy mô phỏng, phát hiện bất thường, agent đề xuất lệnh; bảng tester
  để bật lỗi mô phỏng, mở từ nút **Dashboard**. Lệnh chỉ đi tới máy mô phỏng, không tới PLC thật.

## Cấu trúc

| Thư mục | Nội dung | Hướng dẫn |
|---|---|---|
| [`denso/`](denso/) | Pipeline xử lý tài liệu, Agent Gateway (backend của giao diện), đánh giá độ chính xác, kịch bản chạy | [denso/README.md](denso/README.md) – **bắt đầu ở đây** |
| [`long_agent/`](long_agent/) | Long-agent: 5 máy nhà xưởng mô phỏng, edge IoT gateway, agent, dashboard tester | [long_agent/README.md](long_agent/README.md) |
| [`lightrag_webui/`](lightrag_webui/) | Giao diện web (React); phần của dự án nằm trong `src/features/agentic/` | |
| [`lightrag/`](lightrag/) | Lõi RAG – [LightRAG](https://github.com/HKUDS/LightRAG), dùng nguyên, không sửa | [docs/LightRAG-README.md](docs/LightRAG-README.md) |
| `tests/`, `docs/`, `scripts/` | Test, tài liệu thiết kế và bộ cài đặt của LightRAG gốc | |

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
