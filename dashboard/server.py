from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], state: Any, approvals: Any, on_decision: Any = None) -> None:
        self.state = state
        self.approvals = approvals
        self.on_decision = on_decision
        super().__init__(server_address, self._make_handler())

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        state = self.state
        approvals = self.approvals
        on_decision = self.on_decision
        index_path = Path(__file__).with_name("index.html")

        class DashboardHandler(BaseHTTPRequestHandler):
            def _send_json(self, status: int, data: Dict[str, Any]) -> None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                route = urlparse(self.path).path
                if route == "/api/state":
                    snapshot = state.snapshot()
                    snapshot["actions"] = approvals.snapshot()
                    self._send_json(200, snapshot)
                    return

                if route in ("/", "/index.html"):
                    body = index_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_error(404, "Not found")

            def do_POST(self) -> None:
                parts = urlparse(self.path).path.strip("/").split("/")
                if len(parts) != 4 or parts[:2] != ["api", "actions"]:
                    self.send_error(404, "Not found")
                    return

                expected_origin = f"http://{self.headers.get('Host', '')}"
                if self.headers.get("Origin") != expected_origin:
                    self._send_json(403, {"error": "Approval requests must come from this dashboard origin"})
                    return

                action_id, decision = parts[2], parts[3]
                if decision not in {"approve", "reject"}:
                    self._send_json(400, {"error": "decision must be approve or reject"})
                    return

                try:
                    result = (
                        on_decision(action_id, decision)
                        if on_decision is not None
                        else approvals.decide(action_id, decision)
                    )
                except KeyError as exc:
                    self._send_json(404, {"error": str(exc)})
                    return
                except RuntimeError as exc:
                    self._send_json(409, {"error": str(exc)})
                    return
                except Exception as exc:
                    self._send_json(502, {"error": f"Dispatch failed: {exc}"})
                    return

                self._send_json(200, {"action": result})

            def log_message(self, format: str, *args: Any) -> None:
                return

        return DashboardHandler
