# dashboard/server.py
from __future__ import annotations

import json
import os
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Tuple
from urllib.parse import urlparse

# Thư mục lưu file tri thức upload lên RAG (nằm cạnh server.py)
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge_uploads")


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        # 1. Trả về giao diện chính
        if parsed.path in ("/", "/index.html"):
            # index.html nằm NGANG HÀNG với server.py
            tmpl_path = os.path.join(os.path.dirname(__file__), "index.html")

            if not os.path.exists(tmpl_path):
                self.send_error(404, f"File index.html không tồn tại tại: {tmpl_path}")
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

        # 1. Quyết định APPROVE / REJECT (HITL)
        if parsed.path == "/api/decision":
            data = self._read_json_body()
            action_id = data.get("action_id", "")
            decision = data.get("decision", "REJECT")

            result = {"status": "FAILED"}
            if self.server.on_decision and action_id:
                result = self.server.on_decision(action_id, decision)
                self.server.state_store.remove_approval(action_id)

            self._send_json(result)

        # 2. User gửi tin nhắn chat với AI Agent
        elif parsed.path == "/api/chat":
            data = self._read_json_body()
            text = str(data.get("text", "")).strip()
            if not text:
                self._send_json({"error": "Thiếu nội dung tin nhắn"}, status=400)
                return

            state = self.server.state_store
            session_id = str(data.get("session_id", "")).strip()
            conv = None
            for c in state.conversations:
                if c["session_id"] == session_id:
                    conv = c
                    break

            if conv is None:
                # User mở thread mới (hoặc thread hệ thống không còn tồn tại)
                session_id = state.create_user_session(text)
            state.add_message(session_id, "user", text)

            reply = "Agent hiện chưa phản hồi. Vui lòng thử lại."
            if self.server.on_chat:
                try:
                    reply = self.server.on_chat(text) or reply
                except Exception as exc:  # noqa: BLE001 - không để lỗi chat sập server
                    reply = f"Lỗi khi xử lý truy vấn: {exc}"
            state.add_message(session_id, "assistant", reply, source="AI_AGENT")

            self._send_json({"session_id": session_id, "reply": reply})

        # 3. Upload file tri thức lên kho RAG
        elif parsed.path == "/api/upload":
            self._handle_upload()
        else:
            self.send_error(404)

    # -------------------------------------------------------------------------
    # Helper
    # -------------------------------------------------------------------------
    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        return json.loads(body) if body else {}

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _handle_upload(self) -> None:
        """Nhận multipart/form-data, lưu file vào knowledge_uploads/.

        Python 3.13+ đã bỏ module cgi -> dùng email.parser.BytesParser để
        tách phần attachment khỏi body multipart.
        """
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""

        if not ctype.startswith("multipart/form-data") or not raw_body:
            self._send_json({"status": "ERROR", "error": "Cần multipart/form-data"}, status=400)
            return

        # Dựng lại 1 message MIME đầy đủ để parser của email xử lý
        mime_raw = (
            f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
            + raw_body
        )
        msg = BytesParser(policy=email_policy).parsebytes(mime_raw)

        saved = []
        for part in msg.iter_parts():
            filename = part.get_filename()
            if not filename:
                continue
            # Chống path traversal: chỉ giữ tên file gốc
            filename = os.path.basename(filename.replace("\\", "/")).strip()
            if not filename:
                continue
            data = part.get_payload(decode=True) or b""

            os.makedirs(UPLOAD_DIR, exist_ok=True)
            safe_path = os.path.join(UPLOAD_DIR, filename)
            with open(safe_path, "wb") as f:
                f.write(data)

            self.server.state_store.record_upload(filename, len(data), status="OK")
            saved.append({"filename": filename, "size": len(data)})

        if not saved:
            self._send_json({"status": "ERROR", "error": "Không tìm thấy file trong form"}, status=400)
            return

        self._send_json({"status": "OK", "files": saved})


class DashboardServer(HTTPServer):
    def __init__(
        self,
        server_address: Tuple[str, int],
        state_store: Any,
        action_approval: Any = None,
        on_decision: Callable[[str, str], Dict[str, Any]] | None = None,
        on_chat: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(server_address, DashboardHandler)
        self.state_store = state_store
        self.action_approval = action_approval
        self.on_decision = on_decision
        # Callback tra cứu tri thức: text của user -> câu trả lời của Agent
        self.on_chat = on_chat