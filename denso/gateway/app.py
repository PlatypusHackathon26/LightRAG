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

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import lookup as catalogue  # noqa: E402  (sibling module; app.py runs as a script)
from jobs import JobRunner  # noqa: E402

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


CHUNK_LANG = re.compile(r"--- \[Trang \d+ \| ngôn ngữ: ([a-z-]+)\] ---")
PAGE_LANG = re.compile(r"--- \[Trang (\d+)(?: \| ngôn ngữ: ([a-z-]+))?[^\]]*\] ---")
MAX_PAGES_SHOWN = 6


def pages_from_chunks(chunks: list[str]) -> str | None:
    """Pages of the chunks in the language of the best-ranked chunk.

    A multilingual guide repeats each section once per language, so the context holds
    the same paragraph from many pages; listing all of them ("Pages 1-20") is noise.
    The language reranker ranks the question's language first, so the first chunk's
    language is the one the answer was read from.
    """
    first_lang = next((m.group(1) for c in chunks for m in [CHUNK_LANG.search(c)] if m), None)
    marks = [(int(p), lang) for c in chunks for p, lang in PAGE_LANG.findall(c)]
    # A chunk can run across a language boundary (en p.4 -> de p.5): filter page by page.
    pages = sorted({p for p, lang in marks if not first_lang or lang in (first_lang, "mixed", "")})
    if len(pages) > MAX_PAGES_SHOWN:
        return ", ".join(map(str, pages[:MAX_PAGES_SHOWN])) + ", …"
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


# Nemotron cites as 【2†L4-L5】 or 【1†file.md】 instead of LightRAG's [2].
BRACKET_CITATION = re.compile(r"\s*【\s*(\d+)[^】]*】")
OTHER_BRACKET = re.compile(r"\s*【[^】]*】")
CITED_ID = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Decimal figures (6.9, 10,8) or long part numbers (DND08250, 294009-2150): specific enough to locate a source.
# Distinctive words (7+ letters) to match an answer with no figures to its sources; short words
# ("system", "seal", "with") appear in every document. English only: the sources are English.
CONTENT_WORD = re.compile(r"\b[A-Za-z][A-Za-z-]{6,}\b")
ANSWER_FIGURE = re.compile(r"\b\d+[.,]\d+\b|\b[A-Z]{2,}\d{4,}\b|\b\d{5,}(?:-\d+)?\b")


def strip_reasoning(answer: str) -> str:
    """Drop the model's scratch reasoning (<think>...</think>) that must never reach the user.

    Nemotron sometimes emits it inside the content: as a closed block, as an unclosed
    <think> (cut off, nothing usable after it), or as a stray </think> after leading notes.
    """
    text = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
    if "</think>" in text:          # notes before an orphan closing tag
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:           # unclosed: everything after it is reasoning
        text = text.split("<think>", 1)[0]
    return text.strip()


def clean_answer(answer: str) -> str:
    """Strip reasoning and the references block; normalise model-specific citation markers to [n]."""
    text = strip_reference_section(strip_reasoning(answer))
    text = BRACKET_CITATION.sub(lambda m: f" [{m.group(1)}]", text)
    return OTHER_BRACKET.sub("", text)


def only_cited(references: list[dict], answer: str) -> list[dict]:
    """Keep the references the answer cites; all of them when it cites none.

    LightRAG returns every document that contributed a context chunk, which lists a
    whole catalogue next to the one guide the answer came from.
    """
    ids = {i for m in CITED_ID.finditer(answer) for i in re.findall(r"\d+", m.group(1))}
    kept = [r for r in references if str(r.get("reference_id")) in ids]
    if kept:
        return kept
    def text(r: dict) -> str:
        c = r.get("content") or ""
        return (" ".join(c) if isinstance(c, list) else str(c)).replace(",", ".")

    # No [n] in the answer: keep the documents that contain the figures the answer quotes.
    figures = {f.replace(",", ".") for f in ANSWER_FIGURE.findall(CITED_ID.sub(" ", answer))}
    if figures:
        kept = [r for r in references if any(f in text(r) for f in figures)]
        if kept:
            return kept
    # No figures either (a "why" answer): keep the documents sharing most of the answer's
    # distinctive words; a catalogue that only shares "system" and "seal" drops out.
    words = {w.lower() for w in CONTENT_WORD.findall(answer)}
    if len(words) >= 5 and len(references) > 1:
        overlap = [(r, len(words & {w.lower() for w in CONTENT_WORD.findall(text(r))})) for r in references]
        best = max(n for _, n in overlap)
        kept = [r for r, n in overlap if n >= max(3, best * 0.5)]
    return kept or references


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
    # Hosted UI whose URL changes per deployment, e.g. ^https://denso-copilot(-[a-z0-9-]+)?\.vercel\.app$
    cors_regex: str | None = None
    ops_file: Path = HERE / "sample_ops.json"
    actions_log: Path = REPO / "denso" / "logs" / "actions.jsonl"
    # naive beat mix on the benchmark (100% vs 87% with denso_answer.md, half the latency):
    # mix keeps only ~6 text chunks next to the entities, and the answers sit verbatim in tables.
    knowledge_mode: str = "naive"
    # Seconds a chat waits for LightRAG (retrieval + LLM) before answering 504.
    answer_timeout: float = 150.0
    lookup_mode: str = "naive"
    # Keyword search over the lookup catalogues (gateway/lookup.py); empty = LightRAG lookup server only.
    lookup_files: list[Path] = field(default_factory=list)
    lookup_llm_base: str = "http://127.0.0.1:8899/v1"   # OpenAI-compatible; the proxy adds the API key
    lookup_llm_model: str = "nvidia/nemotron-3-super-120b-a12b"
    # Uploads go through the DENSO pipeline (gateway/jobs.py) so their answers cite pages;
    # False sends the raw file straight to LightRAG (no Docling available, e.g. a server).
    upload_pipeline: bool = True
    docling_url: str = "http://127.0.0.1:5001"
    # Extra request fields, e.g. {"chat_template_kwargs": {"enable_thinking": false}} for Nemotron.
    lookup_llm_extra_body: dict = field(default_factory=dict)

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
            cors_regex=os.environ.get("DENSO_GATEWAY_CORS_REGEX") or None,
            knowledge_mode=os.environ.get("DENSO_KNOWLEDGE_MODE", "naive"),
            answer_timeout=float(os.environ.get("DENSO_ANSWER_TIMEOUT", "150")),
            lookup_files=sorted(Path(os.environ.get("DENSO_LOOKUP_DIR", REPO / "denso" / "data" / "cleaned_md"))
                                .glob("* - lookup.*.md")),
            lookup_llm_base=os.environ.get("DENSO_LOOKUP_LLM_BASE", "http://127.0.0.1:8899/v1"),
            lookup_llm_model=os.environ.get("DENSO_LOOKUP_LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
            lookup_llm_extra_body=json.loads(os.environ.get("DENSO_LOOKUP_LLM_EXTRA_BODY") or "{}"),
            upload_pipeline=os.environ.get("DENSO_UPLOAD_PIPELINE", "1") != "0",
            docling_url=os.environ.get("DENSO_DOCLING_URL", "http://127.0.0.1:5001"),
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
    # A user waiting in the chat gets a clear 504 instead of a spinner for up to 15 minutes.
    client = httpx.AsyncClient(timeout=httpx.Timeout(settings.answer_timeout, connect=10), headers=headers,
                               transport=transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await client.aclose()

    app = FastAPI(title="DENSO Agent Gateway", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors, allow_origin_regex=settings.cors_regex,
                       allow_methods=["*"], allow_headers=["*"])
    history: dict[str, deque] = defaultdict(lambda: deque(maxlen=HISTORY_TURNS * 2))
    lookup_rows = catalogue.load_rows(settings.lookup_files)
    runner = JobRunner(REPO, settings.level_servers, docling=settings.docling_url) if settings.upload_pipeline else None

    def job_document(job) -> dict:
        return {"id": f"job-{job.id}", "name": Path(job.name).stem, "tags": ["#Uploaded", f"level_{job.level}"],
                "sizeBytes": job.size, "importedAt": datetime.fromtimestamp(job.created, timezone.utc).isoformat(),
                "indexStatus": job.status, "progress": job.progress, "extractedText": job.error or job.stage}

    async def answer_from_rows(question: str, hits: list, past: list[dict]) -> tuple[str, list[dict]]:
        """Ask the LLM with the keyword-matched catalogue rows; cite the rows it used."""
        body = {
            **settings.lookup_llm_extra_body,
            "model": settings.lookup_llm_model,
            "temperature": 0,
            "reasoning_effort": "low",
            "max_tokens": 2000,
            "messages": [{"role": "system", "content": catalogue.ANSWER_INSTRUCTIONS}, *past,
                         {"role": "user", "content": f"Catalogue rows:\n{catalogue.rows_context(hits)}\n\nQuestion: {question}"}],
        }
        try:
            r = await client.post(f"{settings.lookup_llm_base}/chat/completions", json=body)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"the answering LLM did not reply within "
                                                        f"{settings.answer_timeout:.0f} s (free API overloaded) - please ask again")
        if r.status_code != 200:
            raise HTTPException(status_code=503, detail=f"the answering LLM failed ({r.status_code}) - please ask again")
        content = clean_answer((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "")
        if not content:
            raise HTTPException(status_code=503, detail="the answering LLM returned no answer - please ask again")
        cited = {int(i) for m in CITED_ID.finditer(content) for i in re.findall(r"\d+", m.group(1))}
        used = [row for i, (row, _) in enumerate(hits, 1) if i in cited] or [row for row, _ in hits]
        citations = []
        for source in dict.fromkeys(row.source for row in used):
            rows = [row for row in used if row.source == source]
            pages = sorted({row.page for row in rows})
            shown = ", ".join(map(str, pages[:MAX_PAGES_SHOWN])) + (", …" if len(pages) > MAX_PAGES_SHOWN else "")
            citations.append({"id": f"cit-{len(citations) + 1}", "documentId": display_name(source),
                              "documentName": display_name(source), "pages": shown,
                              "excerpt": rows[0].text.strip(" |")[:300]})
        return content, citations

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
        hits = catalogue.search(lookup_rows, req.message) if target == "lookup" and lookup_rows else []
        if hits:
            # Vehicle-application rows look alike to vector search; keyword matching finds the row.
            content, citations = await answer_from_rows(req.message, hits, list(history[req.conversationId]))
            history[req.conversationId].extend(
                [{"role": "user", "content": req.message}, {"role": "assistant", "content": content}])
            now = datetime.now(timezone.utc).isoformat()
            return {"content": content, "citations": citations, "target": "lookup", "llmGenerated": True,
                    "events": [
                        {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "knowledge_retrieved",
                         "label": f"Matched {len(hits)} catalogue row(s) (lookup, keyword, level {user.level})",
                         "citations": citations},
                        {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "response_generated",
                         "label": "Answer generated"}]}
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
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"the answering LLM did not reply within "
                                                        f"{settings.answer_timeout:.0f} s (free API overloaded) - please ask again")
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
        content = clean_answer(body.get("response", ""))
        if not content:
            # Only reasoning came back (cut off before the answer): an LLM failure, not an empty answer.
            raise HTTPException(status_code=503, detail="the answering LLM returned only its reasoning, no answer "
                                                        "- please ask again")
        citations = to_citations(only_cited(body.get("references") or [], content))
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

    @app.get("/agent/documents/jobs/{job_id}")
    async def upload_job(job_id: str, user: User = Depends(current_user)) -> dict:
        job = runner.get(job_id) if runner else None
        if job is None:
            raise HTTPException(status_code=404, detail="upload job not found")
        return job.public()

    @app.get("/agent/documents")
    async def documents(user: User = Depends(current_user)) -> list[dict]:
        url = settings.level_servers[user.level - 1]
        # Uploads still in the pipeline first, so the Knowledge Hub shows their progress.
        out = [job_document(j) for j in (runner.active() if runner else []) if j.level <= user.level]
        page = 1
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
        if runner:
            try:
                job = runner.submit(file.filename or "upload", data, level)
            except ValueError as exc:
                raise HTTPException(status_code=415, detail=str(exc)) from None
            return {"status": "accepted", "jobId": job.id, "job": job.public()}
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
