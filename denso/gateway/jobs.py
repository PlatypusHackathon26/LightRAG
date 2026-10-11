"""Upload jobs: parse -> clean -> ingest -> (images), one job at a time.

Each step is a subprocess logged to denso/logs/upload_<job>.log. The document is answerable
after ingest; the image pass only adds to it. A job can be cancelled at any point (an upload made
by mistake): a queued one never starts, a running one has its current step killed.
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

ALLOWED = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".bmp",
    ".webp",
    ".txt",
}
SCANNABLE = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".bmp",
    ".webp",
}  # may hold pages only OCR can read
SAFE_NAME = re.compile(r"[^\w\s().,+-]", re.UNICODE)


class Cancelled(Exception):
    """The job was cancelled; not a RuntimeError, so the steps that tolerate a failure stop too."""


@dataclass
class Job:
    id: str
    name: str  # file name as saved under raw/
    level: int
    size: int
    status: str = "uploading"  # uploading | parsing | chunking | embedding | vectorized | error | cancelled
    progress: int = 0
    stage: str = "queued"  # human-readable step
    images: str = "pending"  # pending | running | done | skipped | error
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    cancelled: bool = False

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
    def __init__(
        self,
        repo: Path,
        level_servers: list[str],
        python: str | None = None,
        docling: str = "http://127.0.0.1:5001",
        read_images: bool = True,
    ):
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
        self.current: str | None = None  # id of the job the worker is running
        self._procs: dict[str, asyncio.subprocess.Process] = {}

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
        return [
            j
            for j in self.jobs.values()
            if j.status != "cancelled"
            and (j.status != "vectorized" or j.images == "running")
        ]

    async def cancel(self, job_id: str, timeout: float = 30) -> Job | None:
        """Stop a job: a queued one never starts, a running one has its step killed.

        Returns once the job has stopped (or after `timeout`), with the status it reached before
        the cancel, so the caller knows whether it already got to the knowledge base.
        """
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job.cancelled = True
        if self.current != job_id:
            if job.finished is None:  # still queued: _work skips it
                job.status, job.stage, job.finished = "cancelled", "Đã huỷ", time.time()
            return job
        proc = self._procs.get(job_id)
        if proc is not None and proc.returncode is None:
            proc.kill()
        deadline = time.monotonic() + timeout
        while self.current == job_id and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        return job

    # ------------------------------------------------------------------ worker
    async def _work(self) -> None:
        while not self.queue.empty():
            job = self.jobs[self.queue.get_nowait()]
            if job.cancelled:
                continue
            self.current = job.id
            try:
                await self._run(job)
            except Cancelled:
                job.status, job.stage, job.finished = "cancelled", "Đã huỷ", time.time()
            except Exception as exc:  # noqa: BLE001 - reported on the job, never kills the worker
                job.status, job.error, job.finished = (
                    "error",
                    str(exc)[:500],
                    time.time(),
                )
            finally:
                self.current = None

    async def _go(self, job: Job, args: list[str], log_name: str) -> None:
        """Run one step unless the job was cancelled before or during it."""
        if job.cancelled:
            raise Cancelled
        await self._step(job, args, log_name)
        if job.cancelled:
            raise Cancelled

    async def _step(self, job: Job, args: list[str], log_name: str) -> None:
        log = self.logs / f"upload_{job.id}.log"
        self.logs.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n$ {' '.join(args)}\n")
            fh.flush()
            proc = await asyncio.create_subprocess_exec(
                self.python,
                *args,
                cwd=self.repo,
                stdout=fh,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self._procs[job.id] = proc
            try:
                code = await proc.wait()
            finally:
                self._procs.pop(job.id, None)
        if job.cancelled:
            raise Cancelled
        if code != 0:
            tail = (
                log.read_text(encoding="utf-8", errors="replace")
                .strip()
                .splitlines()[-3:]
            )
            raise RuntimeError(
                f"{log_name} failed (exit {code}): {' | '.join(tail)[:400]}"
            )

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
            await self._go(
                job,
                [
                    "denso/scripts/ingest.py",
                    "--server",
                    url,
                    "--replace",
                    "--poll",
                    "5",
                    str(hinted),
                ],
                f"{label} (level {lv})",
            )
        if len(skipped) == len(self.level_servers) - job.level + 1:
            raise RuntimeError(
                f"no LightRAG server running for level {job.level} or above"
            )
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
        if raw.suffix.lower() != ".txt" and not await self._healthy(
            self.docling
        ):  # parse.py reads text itself
            raise RuntimeError(
                "Docling is not running on "
                + self.docling
                + " - start it with denso/start.ps1 -DoclingOnly, then upload again"
            ) from None
        job.status, job.stage, job.progress = (
            "parsing",
            "Docling đang đọc bố cục, bảng và trang",
            10,
        )
        # --force: an upload replacing a file of the same name must be read again, not served from
        # the previous parse (parse.py skips files whose meta.json exists).
        await self._go(
            job,
            [
                "denso/pipeline/parse.py",
                "--level",
                str(job.level),
                "--docling",
                self.docling,
                "--cooldown",
                "2",
                "--force",
                str(raw),
            ],
            "parse",
        )
        ocr_note = ""
        if job.level == 1 and raw.suffix.lower() in SCANNABLE:
            # Scanned pages / photos: the vision model reads Vietnamese diacritics Docling's OCR drops.
            # Level 1 only (the page images leave the machine); on failure Docling's text stays.
            job.stage, job.progress = "Đọc trang scan bằng mô hình thị giác", 40
            try:
                await self._go(
                    job,
                    ["denso/pipeline/ocr_pages.py", "--docs", job.stem],
                    "read scanned pages",
                )
            except RuntimeError as exc:
                ocr_note = (
                    f"; đọc trang scan lỗi, dùng OCR của Docling: {str(exc)[:120]}"
                )
        job.status, job.stage, job.progress = (
            "chunking",
            "Làm sạch, gắn dấu trang và ngôn ngữ",
            60,
        )
        await self._go(job, ["denso/pipeline/clean.py", job.stem], "clean")
        job.status, job.stage, job.progress = (
            "embedding",
            "Tạo vector và nạp vào kho tri thức",
            80,
        )
        skipped = await self._ingest(job, self._ingest_copy(job.stem), "ingest")
        note = (
            f" - chưa nạp vào {', '.join(skipped)} (server chưa chạy)"
            if skipped
            else ""
        ) + ocr_note
        job.status, job.stage, job.progress = (
            "vectorized",
            f"Sẵn sàng hỏi đáp (có trích dẫn trang){note}",
            100,
        )
        if not self.read_images or raw.suffix.lower() != ".pdf" or job.level > 1:
            job.images, job.finished = (
                "skipped",
                time.time(),
            )  # images leave the machine: public docs only
            return
        job.images, job.stage = (
            "running",
            "Sẵn sàng hỏi đáp; đang đọc chữ trong ảnh để bổ sung",
        )
        try:
            await self._go(
                job, ["denso/pipeline/ocr_images.py", "--docs", job.stem], "read images"
            )
            await self._go(
                job, ["denso/pipeline/clean.py", job.stem], "clean with images"
            )
            await self._ingest(job, self._ingest_copy(job.stem), "ingest with images")
            job.images, job.stage = (
                "done",
                f"Sẵn sàng hỏi đáp (đã gồm chữ trong ảnh){note}",
            )
        except RuntimeError as exc:
            job.images, job.stage = (
                "error",
                f"Sẵn sàng hỏi đáp; đọc ảnh lỗi: {str(exc)[:160]}",
            )
        job.finished = time.time()
