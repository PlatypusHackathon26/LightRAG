# dashboard/server.py
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Tuple
from urllib.parse import parse_qs, urlparse


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Tắt bớt log HTTP để đỡ rối terminal
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        # 1. Trả về giao diện chính
        if parsed.path in ("/", "/index.html"):
            tmpl_path = os.path.join(
                os.path.dirname(__file__), "templates", "index.html"
            )
            if not os.path.exists(tmpl_path):
                self.send_error(404, "Template index.html not found")
                return

            with open(tmpl_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        # 2. API Polling lấy dữ liệu live
        elif parsed.path == "/api/state":
            state = self.server.state_store.get_snapshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state).encode("utf-8"))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        # API xử lý bấm nút DUYỆT hoặc TỪ CHỐI
        if parsed.path == "/api/decision":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body) if body else {}

            action_id = data.get("action_id", "")
            decision = data.get("decision", "REJECT")  # APPROVE hoặc REJECT

            result = {"status": "FAILED"}
            if self.server.on_decision and action_id:
                result = self.server.on_decision(action_id, decision)
                self.server.state_store.remove_approval(action_id)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))
        else:
            self.send_error(404)


class DashboardServer(HTTPServer):
    """Máy chủ Dashboard phục vụ Web UI và API."""

    def __init__(
        self,
        server_address: Tuple[str, int],
        state_store: Any,
        action_approval: Any = None,
        on_decision: Callable[[str, str], Dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(server_address, DashboardHandler)
        self.state_store = state_store
        self.action_approval = action_approval
        self.on_decision = on_decision