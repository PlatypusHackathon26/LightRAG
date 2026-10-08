"""Upload jobs: a raw file goes through the whole DENSO pipeline before it is searchable.

A file dropped in the Knowledge Hub used to be sent straight to LightRAG, which parsed the
PDF itself: no Docling layout, no cleaning, no page markers - so its answers could not cite
pages. A job runs the same steps as the 11 benchmark documents, one job at a time (Docling
takes the whole CPU):

    parsing    denso/pipeline/parse.py      Docling, resumable page ranges
    chunking   denso/pipeline/clean.py      cleaning + "--- [Trang N | ngôn ngữ: xx] ---"
    embedding  denso/scripts/ingest.py      vector-only upload to the level's servers
    vectorized searchable, pages cited
    images     denso/pipeline/ocr_images.py text inside images, then clean + ingest again

The document is answerable after `embedding`; the image pass only adds to it. Each step
is a subprocess, so a crash in one never takes the gateway down, and its log is kept in
denso/logs/upload_<job>.log.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

ALLOWED = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp", ".txt"}
SAFE_NAME = re.compile(r"[^\w\s().,+-]", re.UNICODE)


@dataclass
class Job:
    id: str
    name: str            # file name as saved under raw/
    level: int
    size: int
    status: str = "uploading"   # uploading | parsing | chunking | embedding | vectorized | error
    progress: int = 0
    stage: str = "queued"       # human-readable step
    images: str = "pending"     # pending | running | done | skipped | error
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    @property
    def stem(self) -> str:
        return Path(self.name).stem

    def public(self) -> dict:
        d = asdict(self)
        d["elapsedSeconds"] = round((self.finished or time.time()) - self.created)
        return d


def safe_filename(name: str) -> str:
    """Keep a readable name but nothing that can escape raw/ or upset a shell."""
    base = Path(name).name
    stem, suffix = Path(base).stem, Path(base).suffix.lower()
    stem = SAFE_NAME.sub("_", stem).strip(" .") or "upload"
    return f"{stem[:120]}{suffix}"


class JobRunner:
    def __init__(self, repo: Path, level_servers: list[str], python: str | None = None,
                 docling: str = "http://127.0.0.1:5001", read_images: bool = True):
        self.repo = repo
        self.data = repo / "denso" / "data"
        self.logs = repo / "denso" / "logs"
        self.level_servers = level_servers
        self.python = python or sys.executable
        self.docling = docling
        self.read_images = read_images
        self.jobs: dict[str, Job] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    # ------------------------------------------------------------------ API
    def submit(self, filename: str, content: bytes, level: int) -> Job:
        name = safe_filename(filename)
        if Path(name).suffix not in ALLOWED:
            raise ValueError(f"unsupported file type {Path(name).suffix or '(none)'}")
        raw_dir = self.data / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / name).write_bytes(content)
        job = Job(id=uuid.uuid4().hex[:12], name=name, level=level, size=len(content))
        self.jobs[job.id] = job
        self.queue.put_nowait(job.id)
        if self.worker is None or self.worker.done():
            self.worker = asyncio.get_running_loop().create_task(self._work())
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status != "vectorized" or j.images == "running"]

    # ------------------------------------------------------------------ worker
    async def _work(self) -> None:
        while not self.queue.empty():
            job = self.jobs[self.queue.get_nowait()]
            try:
                await self._run(job)
            except Exception as exc:  # noqa: BLE001 - reported on the job, never kills the worker
                job.status, job.error, job.finished = "error", str(exc)[:500], time.time()

    async def _step(self, job: Job, args: list[str], log_name: str) -> None:
        log = self.logs / f"upload_{job.id}.log"
        self.logs.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n$ {' '.join(args)}\n")
            fh.flush()
            proc = await asyncio.create_subprocess_exec(
                self.python, *args, cwd=self.repo, stdout=fh, stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            code = await proc.wait()
        if code != 0:
            tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
            raise RuntimeError(f"{log_name} failed (exit {code}): {' | '.join(tail)[:400]}")

    async def _ingest(self, job: Job, hinted: Path, label: str) -> list[str]:
        """Upload to every running server of levels job.level..3; return the levels skipped.

        A level-N document belongs to the servers of levels N..3. One that is not running is
        reported on the job instead of failing it or being skipped silently.
        """
        skipped = []
        for lv in range(job.level, len(self.level_servers) + 1):
            url = self.level_servers[lv - 1]
            if not await self._healthy(url):
                skipped.append(f"level_{lv}")
                continue
            await self._step(job, ["denso/scripts/ingest.py", "--server", url, "--replace", "--poll", "5",
                                   str(hinted)], f"{label} (level {lv})")
        if len(skipped) == len(self.level_servers) - job.level + 1:
            raise RuntimeError(f"no LightRAG server running for level {job.level} or above")
        return skipped

    async def _healthy(self, url: str) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as c:
                return (await c.get(f"{url}/health")).status_code == 200
        except httpx.HTTPError:
            return False

    def _ingest_copy(self, stem: str) -> Path:
        """Vector-only copy of the cleaned document: searchable in seconds, no LLM extraction."""
        cleaned = self.data / "cleaned_md" / f"{stem}.md"
        hinted = self.data / "cleaned_md" / f"{stem}.[native-P!].md"
        shutil.copyfile(cleaned, hinted)
        return hinted

    async def _run(self, job: Job) -> None:
        raw = self.data / "raw" / job.name
        if not await self._healthy(self.docling):
            raise RuntimeError("Docling is not running on " + self.docling +
                               " - start it with denso/start.ps1 -DoclingOnly, then upload again") from None
        job.status, job.stage, job.progress = "parsing", "Docling đang đọc bố cục, bảng và trang", 10
        # --force: an upload replacing a file of the same name must be read again, not served from
        # the previous parse (parse.py skips files whose meta.json exists).
        await self._step(job, ["denso/pipeline/parse.py", "--level", str(job.level), "--docling", self.docling,
                               "--cooldown", "2", "--force", str(raw)], "parse")
        job.status, job.stage, job.progress = "chunking", "Làm sạch, gắn dấu trang và ngôn ngữ", 60
        await self._step(job, ["denso/pipeline/clean.py", job.stem], "clean")
        job.status, job.stage, job.progress = "embedding", "Tạo vector và nạp vào kho tri thức", 80
        skipped = await self._ingest(job, self._ingest_copy(job.stem), "ingest")
        note = f" - chưa nạp vào {', '.join(skipped)} (server chưa chạy)" if skipped else ""
        job.status, job.stage, job.progress = "vectorized", f"Sẵn sàng hỏi đáp (có trích dẫn trang){note}", 100
        if not self.read_images or raw.suffix.lower() != ".pdf" or job.level > 1:
            job.images, job.finished = "skipped", time.time()  # images leave the machine: public docs only
            return
        job.images, job.stage = "running", "Sẵn sàng hỏi đáp; đang đọc chữ trong ảnh để bổ sung"
        try:
            await self._step(job, ["denso/pipeline/ocr_images.py", "--docs", job.stem], "read images")
            await self._step(job, ["denso/pipeline/clean.py", job.stem], "clean with images")
            await self._ingest(job, self._ingest_copy(job.stem), "ingest with images")
            job.images, job.stage = "done", f"Sẵn sàng hỏi đáp (đã gồm chữ trong ảnh){note}"
        except RuntimeError as exc:
            job.images, job.stage = "error", f"Sẵn sàng hỏi đáp; đọc ảnh lỗi: {str(exc)[:160]}"
        job.finished = time.time()
