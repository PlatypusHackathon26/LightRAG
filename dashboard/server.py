# dashboard/server.py
"""FastAPI dashboard: SSE telemetry + chat + upload + HITL decision + PLC fix."""
from __future__ import annotations

import asyncio
import json
import os
from email.parser import BytesParser
from email import policy
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

UPLOAD_DIR = str(Path(__file__).parent.parent / "knowledge_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_multipart(body: bytes, content_type: str) -> list[Dict[str, Any]]:
    """Parse multipart/form-data bang email.parser (stdlib)."""
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    saved: list[Dict[str, Any]] = []
    if msg.is_multipart():
        for part in msg.iter_parts():
            filename = part.get_filename()
            if not filename:
                continue
            safe = os.path.basename(filename)
            data = part.get_payload(decode=True) or b""
            with open(os.path.join(UPLOAD_DIR, safe), "wb") as f:
                f.write(data)
            saved.append({"filename": safe, "size": len(data)})
    return saved


def create_app(
    state_store: Any,
    machines_dict: Optional[dict] = None,
    approval: Any = None,
    on_chat: Optional[Callable[[str], str]] = None,
    on_decision: Optional[Callable[[str, str], Dict[str, Any]]] = None,
) -> FastAPI:
    app = FastAPI(title="Industrial Fleet Monitor")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    html_file = Path(__file__).parent / "index.html"

    @app.get("/", response_class=HTMLResponse)
    def index():
        return html_file.read_text(encoding="utf-8")

    @app.get("/api/state")
    def api_state():
        snap = state_store.get_snapshot() if hasattr(state_store, "get_snapshot") else {}
        if approval is not None and hasattr(approval, "get_pending_actions"):
            snap["actions"] = [
                {"action_id": a.get("approval_id", a.get("action_id")),
                 "status": "pending", **a}
                for a in approval.get_pending_actions()
            ]
            snap["pending_approvals"] = approval.get_pending_actions()
        return snap

    @app.get("/api/machines")
    def get_machines():
        return state_store.get_all_machines()

    @app.get("/api/stream")
    async def stream_telemetry():
        async def event_generator():
            while True:
                data = json.dumps(state_store.get_all_machines())
                yield f"data: {data}\n\n"
                await asyncio.sleep(1.0)
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/api/fault/interval")
    def set_global_fault_interval(seconds: float):
        if machines_dict:
            for m in machines_dict.values():
                m.set_fault_interval(seconds)
            if hasattr(state_store, "set_fault_interval"):
                first_machine = list(machines_dict.values())[0]
                state_store.set_fault_interval(first_machine.fault_interval_sec)
            target_sec = list(machines_dict.values())[0].fault_interval_sec
            return {"success": True, "interval_sec": target_sec}
        return {"success": False, "error": "No machines registered"}

    @app.post("/api/chat")
    async def api_chat(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Body phai la JSON"}, status_code=400)
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "Text rong"}, status_code=400)
        session_id = body.get("session_id")
        if session_id:
            state_store.add_message(session_id, "user", text)
        else:
            session_id = state_store.create_user_session(text[:60])
            state_store.add_message(session_id, "user", text)
        reply = on_chat(text) if on_chat else f"Agent da nhan: {text}"
        state_store.add_message(session_id, "assistant", reply)
        return {"session_id": session_id, "reply": reply}

    @app.post("/api/upload")
    async def api_upload(request: Request):
        ctype = request.headers.get("content-type", "")
        body = await request.body()
        try:
            saved = _save_multipart(body, ctype)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        for f in saved:
            if hasattr(state_store, "register_upload"):
                state_store.register_upload(f["filename"])
        return {"status": "ok", "files": saved}

    @app.post("/api/decision")
    async def api_decision(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Body phai la JSON"}, status_code=400)
        action_id = body.get("action_id", "")
        decision = body.get("decision", "")
        if on_decision is not None:
            result = on_decision(action_id, decision)
            status = result.get("status", "")
            mapped = "approved" if status == "APPROVED" else (
                "rejected" if status == "REJECTED" else status.lower())
            if hasattr(state_store, "remove_approval"):
                state_store.remove_approval(action_id, status=decision)
            return {"status": status, "action_id": action_id}
        if approval is None:
            return JSONResponse({"error": "Khong co Approval service"}, status_code=500)
        try:
            result = approval.decide(action_id, decision)
        except (KeyError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        if hasattr(state_store, "remove_approval"):
            state_store.remove_approval(action_id, status=decision)
        st = result.get("status", "")
        mapped = "approved" if st in ("approved", "EXECUTED") else (
            "rejected" if st in ("rejected", "REJECTED") else st)
        return {"status": mapped.upper() if mapped in ("approved", "rejected") else st,
                "action_id": action_id, "detail": result}

    @app.post("/api/actions/{action_id}/approve")
    def api_approve_action(action_id: str, request: Request):
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if origin and host not in origin:
            return JSONResponse({"error": "Forbidden origin"}, status_code=403)
        if approval is None:
            return JSONResponse({"error": "Khong co Approval service"}, status_code=500)
        try:
            result = approval.decide(action_id, "APPROVE")
        except (KeyError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        if hasattr(state_store, "remove_approval"):
            state_store.remove_approval(action_id, status="APPROVE")
        return {"action": {"action_id": action_id, "status": "approved"},
                "detail": result}

    @app.post("/api/plc/fix")
    async def api_plc_fix(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Body phai la JSON"}, status_code=400)
        machine_id = body.get("machine_id", "")
        command = body.get("command", "")
        params = body.get("params") or body.get("payload") or {}
        if approval is None:
            return JSONResponse({"error": "Khong co Approval service"}, status_code=500)
        result = approval.process_action_request({
            "machine_id": machine_id, "command": command,
            "params": params, "payload": params,
            "risk_level": body.get("risk_level", ""),
            "reason": body.get("reason", "Ky su bam nut sua loi tren Dashboard"),
        })
        return result

    return app


class DashboardServer:
    """Wrapper tuong thich test cu: DashboardServer((host, port), state, approval)."""

    def __init__(self, addr, state_store=None, approval=None,
                 on_decision=None, on_chat=None) -> None:
        import uvicorn as _uvicorn
        host, port = addr
        self.app = create_app(state_store, None, approval, on_chat, on_decision)
        self.server = _uvicorn.Server(
            _uvicorn.Config(self.app, host=host, port=port, log_level="error"))
        self.server_address = (host, port)
        self.server_port = port

    def serve_forever(self) -> None:
        import anyio
        anyio.run(self.server.serve)

    def shutdown(self) -> None:
        self.server.should_exit = True

    def server_close(self) -> None:
        pass