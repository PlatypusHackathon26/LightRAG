# dashboard/server.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware


def create_app(state_store: Any, machines_dict: Optional[dict] = None) -> FastAPI:
    app = FastAPI(title="Industrial Fleet Monitor")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    html_file = Path(__file__).parent / "index.html"

    @app.get("/", response_class=HTMLResponse)
    def index():
        return html_file.read_text(encoding="utf-8")

    @app.get("/api/machines")
    def get_machines():
        return state_store.get_all_machines()

    @app.get("/api/stream")
    async def stream_telemetry():
        """Đẩy dữ liệu thời gian thực (SSE) xuống Web."""
        async def event_generator():
            while True:
                data = json.dumps(state_store.get_all_machines())
                yield f"data: {data}\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # API hỗ trợ Demo: Bấm nút trên Web để tiêm lỗi trực tiếp
# Bổ sung vào trong create_app() của dashboard/server.py
    @app.post("/api/fault/interval")
    def set_global_fault_interval(seconds: float):
        """Thay đổi tần suất sinh lỗi của tất cả các máy đang chạy."""
        if machines_dict:
            for m in machines_dict.values():
                m.set_fault_interval(seconds)
            state_store.set_fault_interval(seconds)  # Cập nhật snapshot để Web thấy ngay
            return {"success": True, "interval_sec": seconds}
        return {"success": False, "error": "No machines registered"}

    return app