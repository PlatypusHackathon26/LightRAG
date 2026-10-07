"""DENSO Agent Gateway: the backend the agentic UI calls (lightrag_webui/src/api/agent.ts).

The UI never talks to LightRAG directly. The gateway:
  * resolves the caller's access level from a server-side token table
    (users.json); a level sent by the client is never trusted
  * routes knowledge questions to that level's LightRAG server (cumulative
    workspaces level_1..level_3, one server each) and part-number / vehicle
    lookups to the lookup server, then maps LightRAG references to the UI's
    Citation shape (documentName, pages, excerpt)
  * lists and uploads knowledge documents for the Knowledge Hub
  * serves incidents / telemetry from a sample file and records HITL
    approvals in a log only - it never sends a command to a PLC

Run:  python denso/gateway/app.py            (http://127.0.0.1:9700)
Env:  DENSO_LEVEL_SERVERS="http://127.0.0.1:9621,http://127.0.0.1:9622,http://127.0.0.1:9623"
      DENSO_LOOKUP_SERVER="http://127.0.0.1:9631"   (optional)
      DENSO_GATEWAY_USERS=denso/gateway/users.json  DENSO_GUEST_LEVEL=1
      DENSO_GATEWAY_CORS="http://localhost:5173"    LIGHTRAG_API_KEY (if the servers need it)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MAX_LEVEL = 3
HISTORY_TURNS = 6
PAGE_MARK = re.compile(r"--- \[Trang (\d+)[^\]]*\] ---")
LOOKUP_HINT = re.compile(r"\s*-\s*lookup\.\[[^\]]*\]$|\.\[[^\]]*\]$")
# Vehicle-application lookups go to the lookup tier. Only the *intent* counts: a
# part number alone is not enough, because the knowledge tier is full of them too
# (benchmark Q1 asks about DCRS300260, Q10 about DCP32045).
LOOKUP_QUESTION = re.compile(
    r"\b(fit|fits|fitting|suitable for|compatible with|applicable to)\b.{0,60}\b(car|vehicle|model|engine|motorcycle|my)\b|"
    r"\bfits? (?:a |an |the |my )?(?:\d{4} )?[A-Z][a-z]+|"
    r"\b(which|what)\b.{0,50}\b(plug|blade|wiper|part)\b.{0,50}\bfor (?:a |an |the |my )?(?:\d{4} )?[A-Z][a-z]+|"
    r"\b(vehicle )?applications? (list|table|for)\b|\bcross[- ]reference\b|\bequivalent (of|to)\b|"
    r"\bxe nào\b|\blắp (cho|được)\b|\bdùng cho xe\b",
    re.IGNORECASE,
)
# Placeholder the LightRAG /query route returns when the LLM produced no text. Not the same
# as PROMPTS["fail_response"], which is a deliberate refusal when retrieval finds nothing.
EMPTY_LLM_PLACEHOLDER = "No relevant context found for the query."
# LightRAG doc_status -> UI DocumentIndexStatus
STATUS_MAP = {
    "pending": "uploading",
    "parsing": "parsing",
    "analyzing": "chunking",
    "preprocessed": "chunking",
    "processing": "embedding",
    "processed": "vectorized",
    "failed": "error",
}


# ---------------------------------------------------------------- pure helpers


def display_name(file_path: str) -> str:
    """'Spark Plug Catalogue 2025 - lookup.[native-P!].md' -> 'Spark Plug Catalogue 2025'."""
    name = Path(file_path.replace("\\", "/")).name
    if name.lower().endswith(".md"):
        name = name[:-3]
    return LOOKUP_HINT.sub("", name).strip()


def pages_from_chunks(chunks: list[str]) -> str | None:
    pages = sorted({int(p) for c in chunks for p in PAGE_MARK.findall(c)})
    return ", ".join(map(str, pages)) or None


def excerpt_from_chunks(chunks: list[str], limit: int = 300) -> str | None:
    for c in chunks:
        text = re.sub(r"\s+", " ", PAGE_MARK.sub(" ", re.sub(r"<[^>]+>", " ", c))).strip(" #-")
        if text:
            return text[:limit] + ("…" if len(text) > limit else "")
    return None


def to_citations(references: list[dict]) -> list[dict]:
    """LightRAG references (with include_chunk_content) -> UI Citation objects."""
    out = []
    for ref in references:
        chunks = ref.get("content") or []
        if isinstance(chunks, str):
            chunks = [chunks]
        out.append({
            "id": f"cit-{ref.get('reference_id', len(out) + 1)}",
            "documentId": display_name(ref.get("file_path", "")),
            "documentName": display_name(ref.get("file_path", "")),
            "pages": pages_from_chunks(chunks),
            "excerpt": excerpt_from_chunks(chunks),
        })
    return out


def strip_reference_section(answer: str) -> str:
    """The UI renders citations itself; drop LightRAG's trailing '### References' block."""
    return re.split(r"\n#{2,4}\s*References\s*\n", answer, maxsplit=1)[0].rstrip()


def classify_target(message: str) -> str:
    return "lookup" if LOOKUP_QUESTION.search(message) else "knowledge"


def to_knowledge_document(doc: dict, level: int) -> dict:
    name = doc.get("file_path", "")
    tier = "lookup" if "lookup.[" in name else "knowledge"
    status = STATUS_MAP.get(doc.get("status", ""), "error")
    return {
        "id": doc.get("id"),
        "name": display_name(name),
        "tags": [tier, f"level_{level}"],
        "sizeBytes": int(doc.get("content_length") or 0),
        "importedAt": doc.get("created_at"),
        "indexStatus": status,
        "progress": 100 if status == "vectorized" else None,
    }


# ---------------------------------------------------------------- config / auth


@dataclass
class Settings:
    level_servers: list[str]
    lookup_server: str | None = None
    users: dict[str, dict] = field(default_factory=dict)
    guest_level: int = 1
    api_key: str | None = None
    cors: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    ops_file: Path = HERE / "sample_ops.json"
    actions_log: Path = REPO / "denso" / "logs" / "actions.jsonl"
    knowledge_mode: str = "mix"
    lookup_mode: str = "naive"

    @classmethod
    def from_env(cls) -> "Settings":
        servers = os.environ.get(
            "DENSO_LEVEL_SERVERS", "http://127.0.0.1:9621,http://127.0.0.1:9622,http://127.0.0.1:9623"
        ).split(",")
        users_file = Path(os.environ.get("DENSO_GATEWAY_USERS", HERE / "users.json"))
        users = json.loads(users_file.read_text(encoding="utf-8")) if users_file.exists() else {}
        return cls(
            level_servers=[s.strip() for s in servers if s.strip()],
            lookup_server=os.environ.get("DENSO_LOOKUP_SERVER") or None,
            users={k: v for k, v in users.items() if not k.startswith("_")},
            guest_level=int(os.environ.get("DENSO_GUEST_LEVEL", "1")),
            api_key=os.environ.get("LIGHTRAG_API_KEY") or None,
            cors=[o.strip() for o in os.environ.get("DENSO_GATEWAY_CORS", "http://localhost:5173").split(",")],
        )


@dataclass
class User:
    name: str
    level: int
    can_upload: bool = False


class ChatRequest(BaseModel):
    conversationId: str
    message: str
    target: str | None = None  # optional override: "knowledge" | "lookup"


def create_app(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    if len(settings.level_servers) != MAX_LEVEL:
        raise ValueError(f"need {MAX_LEVEL} level servers, got {len(settings.level_servers)}")
    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    client = httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10), headers=headers, transport=transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await client.aclose()

    app = FastAPI(title="DENSO Agent Gateway", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors, allow_methods=["*"], allow_headers=["*"])
    history: dict[str, deque] = defaultdict(lambda: deque(maxlen=HISTORY_TURNS * 2))

    def current_user(authorization: str | None = Header(default=None)) -> User:
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not token:
            return User(name="guest", level=settings.guest_level)
        info = settings.users.get(token)
        if info is None:
            raise HTTPException(status_code=401, detail="unknown token")
        level = int(info.get("level", 1))
        if not 1 <= level <= MAX_LEVEL:
            raise HTTPException(status_code=500, detail="misconfigured user level")
        return User(name=info.get("name", "user"), level=level, can_upload=bool(info.get("can_upload")))

    def ops() -> dict:
        if settings.ops_file.exists():
            return json.loads(settings.ops_file.read_text(encoding="utf-8"))
        return {"incidents": [], "telemetry": {}}

    def log_action(row: dict) -> None:
        settings.actions_log.parent.mkdir(parents=True, exist_ok=True)
        with settings.actions_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    @app.get("/agent/health")
    async def health() -> dict:
        async def probe(url: str) -> dict:
            try:
                r = await client.get(f"{url}/health", timeout=5)
                cfg = r.json().get("configuration", {})
                return {"url": url, "ok": r.status_code == 200, "workspace": cfg.get("workspace")}
            except (httpx.HTTPError, ValueError):
                return {"url": url, "ok": False}
        backends = {f"level_{i + 1}": await probe(u) for i, u in enumerate(settings.level_servers)}
        if settings.lookup_server:
            backends["lookup"] = await probe(settings.lookup_server)
        return {"status": "ok", "backends": backends}

    @app.post("/agent/chat")
    async def chat(req: ChatRequest, user: User = Depends(current_user)) -> dict:
        target = req.target or classify_target(req.message)
        if target == "lookup" and settings.lookup_server:
            url, mode = settings.lookup_server, settings.lookup_mode
        else:
            target, url, mode = "knowledge", settings.level_servers[user.level - 1], settings.knowledge_mode
        past = list(history[req.conversationId])
        payload = {
            "query": req.message,
            "mode": mode,
            "include_references": True,
            "include_chunk_content": True,
            "conversation_history": past or None,
        }
        try:
            r = await client.post(f"{url}/query", json=payload)
        except httpx.ConnectError:
            if target != "lookup":
                raise HTTPException(status_code=503, detail=f"LightRAG level_{user.level} server is not running")
            # Lookup server not deployed (compose profile off): answer from the knowledge tier.
            target, url, mode = "knowledge", settings.level_servers[user.level - 1], settings.knowledge_mode
            r = await client.post(f"{url}/query", json={**payload, "mode": mode})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"LightRAG {target} server returned {r.status_code}")
        body = r.json()
        if body.get("response", "").strip() == EMPTY_LLM_PLACEHOLDER:
            # LightRAG substitutes this when the answering LLM returned nothing (timeout,
            # 429, spent quota). Passing it on would read as "the documents have no answer".
            raise HTTPException(status_code=503, detail="the answering LLM returned nothing (quota, rate limit or "
                                                       "timeout) - see denso/logs/llm_proxy.jsonl and the server log")
        content = strip_reference_section(body.get("response", ""))
        citations = to_citations(body.get("references") or [])
        history[req.conversationId].extend(
            [{"role": "user", "content": req.message}, {"role": "assistant", "content": content}]
        )
        now = datetime.now(timezone.utc).isoformat()
        events = [
            {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "knowledge_retrieved",
             "label": f"Retrieved {len(citations)} source document(s) ({target}, {mode}, level {user.level})",
             "citations": citations},
            {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "response_generated",
             "label": "Answer generated", "detail": f"{body.get('response_time', '?')} s"},
        ]
        return {"content": content, "citations": citations, "events": events,
                "target": target, "llmGenerated": body.get("llm_generated", True)}

    @app.get("/agent/documents")
    async def documents(user: User = Depends(current_user)) -> list[dict]:
        url = settings.level_servers[user.level - 1]
        out, page = [], 1
        while True:
            r = await client.post(f"{url}/documents/paginated", json={"page": page, "page_size": 100})
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail="LightRAG documents listing failed")
            data = r.json()
            out += [to_knowledge_document(d, user.level) for d in data.get("documents", [])]
            if not data.get("pagination", {}).get("has_next"):
                return out
            page += 1

    @app.post("/agent/documents")
    async def upload(
        file: UploadFile = File(...), level: int = Form(1), user: User = Depends(current_user)
    ) -> dict:
        if not user.can_upload:
            raise HTTPException(status_code=403, detail="this user may not upload documents")
        if not 1 <= level <= user.level:
            raise HTTPException(status_code=403, detail=f"cannot upload a level-{level} document as level {user.level}")
        data = await file.read()
        tracks = {}
        for lv in range(level, MAX_LEVEL + 1):  # cumulative: a level-N document is visible to N..3
            r = await client.post(f"{settings.level_servers[lv - 1]}/documents/upload",
                                  files={"file": (file.filename, data)})
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"upload to level_{lv} failed ({r.status_code})")
            tracks[f"level_{lv}"] = r.json().get("track_id")
        return {"status": "accepted", "trackIds": tracks}

    @app.get("/agent/incidents")
    async def incidents(user: User = Depends(current_user)) -> list[dict]:
        return ops().get("incidents", [])

    @app.get("/agent/incidents/{incident_id}")
    async def incident(incident_id: str, user: User = Depends(current_user)) -> dict:
        for inc in ops().get("incidents", []):
            if inc.get("id") == incident_id:
                return inc
        raise HTTPException(status_code=404, detail="incident not found")

    @app.get("/agent/telemetry/{device_id}")
    async def telemetry(device_id: str, user: User = Depends(current_user)) -> dict:
        snap = ops().get("telemetry", {}).get(device_id)
        if snap is None:
            raise HTTPException(status_code=404, detail="no telemetry for this device")
        return snap

    @app.post("/agent/actions/{action_id}/approve")
    async def approve(action_id: str, user: User = Depends(current_user)) -> dict:
        ack = f"ACK-{uuid.uuid4().hex[:6].upper()}"
        log_action({"ts": datetime.now(timezone.utc).isoformat(), "action": action_id, "decision": "approve",
                    "user": user.name, "ack": ack, "executed": False,
                    "note": "recorded only - the gateway never sends PLC commands"})
        return {"ack": ack}

    @app.post("/agent/actions/{action_id}/reject")
    async def reject(action_id: str, user: User = Depends(current_user)) -> dict:
        log_action({"ts": datetime.now(timezone.utc).isoformat(), "action": action_id, "decision": "reject",
                    "user": user.name, "executed": False})
        return {"status": "rejected"}

    return app


def main() -> None:
    import uvicorn

    port = int(os.environ.get("DENSO_GATEWAY_PORT", "9700"))
    host = os.environ.get("DENSO_GATEWAY_HOST", "127.0.0.1")  # 0.0.0.0 inside a container only
    uvicorn.run(create_app(Settings.from_env()), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
