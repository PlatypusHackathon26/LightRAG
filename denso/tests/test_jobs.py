"""Upload jobs (denso/gateway/jobs.py): pipeline order, status, skipped levels, failures."""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from jobs import JobRunner, safe_filename  # noqa: E402

SERVERS = ["http://l1", "http://l2", "http://l3"]


class FakeRunner(JobRunner):
    """Records the steps instead of running them; servers listed in `up` answer /health."""

    def __init__(self, repo: Path, up: set[str], fail: str | None = None):
        super().__init__(repo, SERVERS, docling="http://docling")
        self.up, self.fail, self.steps = up, fail, []

    async def _healthy(self, url: str) -> bool:
        return url in self.up

    async def _step(self, job, args, log_name):
        self.steps.append((log_name, args))
        if self.fail and log_name.startswith(self.fail):
            raise RuntimeError(f"{log_name} failed (exit 1): boom")
        if args[0].endswith("clean.py"):  # what clean.py would have written
            out = self.data / "cleaned_md"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{job.stem}.md").write_text("--- [Trang 1 | ngôn ngữ: en] ---\ntext", encoding="utf-8")


def run(runner: FakeRunner, name="Manual E5.pdf", level=1):
    async def go():
        job = runner.submit(name, b"%PDF-1.7", level)
        await runner.worker
        return job
    return asyncio.run(go())


def test_pipeline_order_and_final_status(tmp_path):
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1"})
    job = run(r)
    assert [s[0] for s in r.steps] == ["parse", "read scanned pages", "clean", "ingest (level 1)", "read images",
                                       "clean with images", "ingest with images (level 1)"]
    assert job.status == "vectorized" and job.images == "done" and job.progress == 100
    assert "level_2, level_3" in job.stage  # not running: reported, not silently skipped
    ingest_args = r.steps[3][1]
    assert ingest_args[ingest_args.index("--server") + 1] == "http://l1" and ingest_args[-1].endswith(".[native-P!].md")


def test_docling_down_fails_the_job_with_a_fix(tmp_path):
    job = run(FakeRunner(tmp_path, up={"http://l1"}))
    assert job.status == "error" and "start.ps1 -DoclingOnly" in job.error


def test_a_failed_image_pass_leaves_the_document_answerable(tmp_path):
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1"}, fail="read images")
    job = run(r)
    assert job.status == "vectorized" and job.images == "error" and "đọc ảnh lỗi" in job.stage


def test_confidential_documents_never_go_to_the_vision_api(tmp_path):
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1", "http://l2", "http://l3"})
    job = run(r, level=2)
    assert job.images == "skipped" and not any(s[0] == "read images" for s in r.steps)
    assert [s[0] for s in r.steps if s[0].startswith("ingest")] == ["ingest (level 2)", "ingest (level 3)"]


def test_no_running_server_for_the_level_is_an_error(tmp_path):
    job = run(FakeRunner(tmp_path, up={"http://docling", "http://l1"}), level=2)
    assert job.status == "error" and "no LightRAG server" in job.error


@pytest.mark.parametrize("name, expected", [
    ("../../etc/passwd.pdf", "passwd.pdf"),
    ("BHT-M60_70_80 Manual E5.PDF", "BHT-M60_70_80 Manual E5.pdf"),
    ("a;rm -rf *.pdf", "a_rm -rf _.pdf"),
])
def test_uploaded_names_cannot_escape_raw(name, expected):
    assert safe_filename(name) == expected


def test_unsupported_types_are_refused(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(_submit(FakeRunner(tmp_path, up=set()), "virus.exe"))


async def _submit(r, name):
    return r.submit(name, b"x", 1)


def test_gateway_route_returns_the_job_and_lists_it(tmp_path, monkeypatch):
    from app import Settings, create_app
    import app as gateway

    monkeypatch.setattr(gateway, "JobRunner", lambda repo, servers, docling: FakeRunner(tmp_path, up={"http://docling", "http://l1"}))
    users = {"tok-admin": {"name": "admin", "level": 3, "can_upload": True}}
    settings = Settings(level_servers=SERVERS, users=users, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"documents": [], "pagination": {"has_next": False}}))
    tc = TestClient(create_app(settings, transport=transport))
    h = {"Authorization": "Bearer tok-admin"}
    r = tc.post("/agent/documents", files={"file": ("manual.pdf", b"%PDF")}, data={"level": "1"}, headers=h)
    assert r.status_code == 200 and r.json()["jobId"]
    job = tc.get(f"/agent/documents/jobs/{r.json()['jobId']}", headers=h).json()
    assert job["name"] == "manual.pdf" and job["status"] in {"uploading", "parsing", "vectorized"}
    assert tc.post("/agent/documents", files={"file": ("x.exe", b"MZ")}, data={"level": "1"}, headers=h).status_code == 415


def test_a_replacing_upload_is_parsed_again_not_served_from_the_old_parse(tmp_path):
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1"})
    run(r, name="Bang_tra.xlsx")
    assert "--force" in r.steps[0][1]


def test_text_files_are_accepted(tmp_path):
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1"})
    job = run(r, name="Ghi chu.txt")
    assert job.status == "vectorized"


def test_a_text_file_does_not_need_docling(tmp_path):
    r = FakeRunner(tmp_path, up={"http://l1"})  # Docling down
    assert run(r, name="Ghi chu.txt").status == "vectorized"


def test_scanned_pages_are_read_by_the_vision_model_for_public_documents_only(tmp_path):
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1", "http://l2"})
    run(r, name="Phieu scan.pdf", level=2)
    assert "read scanned pages" not in [s[0] for s in r.steps]  # level 2: nothing leaves the machine
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1"})
    run(r, name="notes.docx")
    assert "read scanned pages" not in [s[0] for s in r.steps]  # a DOCX has no scanned pages
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1"})
    run(r, name="photo.jpg")
    assert [s[0] for s in r.steps][:2] == ["parse", "read scanned pages"]


def test_a_failed_scan_reading_keeps_doclings_text_and_says_so(tmp_path):
    r = FakeRunner(tmp_path, up={"http://docling", "http://l1"}, fail="read scanned")
    job = run(r, name="photo.jpg")
    assert job.status == "vectorized" and "dùng OCR của Docling" in job.stage
