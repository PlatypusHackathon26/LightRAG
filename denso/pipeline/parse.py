"""Step 1 - parse raw documents with the local docling-serve.

For every file it stores the raw Docling outputs next to each other:
    <out>/<stem>/docling.md     Markdown with a page-break marker between pages
    <out>/<stem>/docling.json   DoclingDocument (page provenance, tables)
    <out>/<stem>/meta.json      source path, access level, size, parse time

Crash safety (the laptop can power off when it overheats):
  * PDFs longer than --chunk-pages are converted in page ranges; each range is
    saved to <stem>/parts/ as soon as it is done, and a re-run skips finished
    ranges, so a crash only loses the range in flight.
  * Every file is written to a temp name and renamed, so a half-written file
    never looks finished. meta.json is written last and marks a file as done.
  * --cooldown pauses between ranges to let the machine cool down.

Already-parsed files are skipped unless --force is given. After a crash just
run the same command again.

Usage:
    python denso/pipeline/parse.py denso/data/raw            # level from folder name
    python denso/pipeline/parse.py --level 1 some/file.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "parsed"
PAGE_BREAK = "<!-- PAGE_BREAK -->"
DOCLING_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
LEVEL_DIR = re.compile(r"level_(\d)")


def access_level_for(path: Path, explicit: int | None) -> int:
    """Explicit --level wins; otherwise the nearest level_N folder; default 1."""
    if explicit is not None:
        return explicit
    for part in reversed(path.parts):
        if m := LEVEL_DIR.fullmatch(part):
            return int(m.group(1))
    return 1


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in DOCLING_SUFFIXES)
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(f"Not found: {p}")
    return files


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def pdf_page_count(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def page_ranges(total: int, size: int) -> list[tuple[int, int]]:
    return [(start, min(start + size - 1, total)) for start in range(1, total + 1, size)]


def convert(
    client: httpx.Client,
    path: Path,
    ocr_lang: list[str] | None,
    page_range: tuple[int, int] | None = None,
    retries: int = 3,
) -> dict:
    """POST one file (or page range) to docling-serve, retrying transient failures."""
    for attempt in range(1, retries + 1):
        try:
            return _convert_once(client, path, ocr_lang, page_range)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if attempt == retries:
                raise
            wait = 30 * attempt
            print(f"    attempt {attempt} failed ({exc.__class__.__name__}: {exc}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def _convert_once(
    client: httpx.Client, path: Path, ocr_lang: list[str] | None, page_range: tuple[int, int] | None
) -> dict:
    data: dict[str, object] = {
        "to_formats": ["md", "json"],
        "image_export_mode": "placeholder",
        "md_page_break_placeholder": PAGE_BREAK,
        "do_ocr": "true",
        "force_ocr": "false",
        "table_mode": "accurate",
        "do_pdf_heading_hierarchy": "true",
        "abort_on_error": "false",
    }
    if ocr_lang:
        data["ocr_lang"] = ocr_lang
    if page_range:
        data["page_range"] = [str(page_range[0]), str(page_range[1])]
    with path.open("rb") as fh:
        r = client.post("/v1/convert/file", data=data, files={"files": (path.name, fh)})
    r.raise_for_status()
    body = r.json()
    if body.get("status") not in ("success", "partial_success"):
        raise RuntimeError(f"docling status={body.get('status')} errors={body.get('errors')}")
    return body


def parse_in_ranges(
    client: httpx.Client, path: Path, out_dir: Path, total: int, args: argparse.Namespace
) -> tuple[str, list[str]]:
    """Convert a long PDF range by range, resuming from parts/ after a crash.

    Returns the merged Markdown and any warnings. A range whose Markdown does
    not contain the expected number of pages is padded at its end so later
    page numbers stay aligned with the PDF; the warning is recorded in meta.
    """
    parts_dir = out_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    ranges = page_ranges(total, args.chunk_pages)
    md_parts: list[str] = []
    warnings: list[str] = []
    for n, (a, b) in enumerate(ranges, 1):
        md_file = parts_dir / f"p{a:04d}-{b:04d}.md"
        if md_file.exists():
            print(f"    pages {a}-{b}: done earlier, skipping", flush=True)
        else:
            t0 = time.time()
            print(f"    pages {a}-{b} ({n}/{len(ranges)}) ...", flush=True)
            body = convert(client, path, args.ocr_lang, (a, b))
            doc = body["document"]
            write_atomic(parts_dir / f"p{a:04d}-{b:04d}.json", json.dumps(doc.get("json_content") or {}, ensure_ascii=False))
            write_atomic(md_file, doc.get("md_content") or "")
            print(f"    pages {a}-{b}: ok in {time.time() - t0:.0f}s", flush=True)
            if args.cooldown and n < len(ranges):
                time.sleep(args.cooldown)
        md = md_file.read_text(encoding="utf-8")
        pages = md.split(PAGE_BREAK)
        expected = b - a + 1
        if len(pages) < expected:
            warnings.append(f"pages {a}-{b}: docling returned {len(pages)} of {expected} pages; padded at end")
            pages += [""] * (expected - len(pages))
        md_parts.append(PAGE_BREAK.join(pages[:expected]))
    return PAGE_BREAK.join(md_parts), warnings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--level", type=int, choices=(1, 2, 3))
    ap.add_argument("--docling", default="http://127.0.0.1:5001")
    ap.add_argument("--ocr-lang", nargs="*", default=None, help="BCP-47 tags, e.g. en vi")
    ap.add_argument("--chunk-pages", type=int, default=20, help="Pages per Docling request for long PDFs")
    ap.add_argument("--cooldown", type=float, default=0, help="Seconds to pause between page ranges")
    ap.add_argument("--force", action="store_true", help="Re-parse files that already have output")
    args = ap.parse_args()

    files = collect(args.paths)
    failed = 0
    with httpx.Client(base_url=args.docling, timeout=httpx.Timeout(3600, connect=10)) as client:
        for i, path in enumerate(files, 1):
            out_dir = args.out / path.stem
            if (out_dir / "meta.json").exists() and not args.force:
                print(f"[{i}/{len(files)}] skip (parsed) {path.name}")
                continue
            if args.force and (out_dir / "parts").exists():
                for f in (out_dir / "parts").iterdir():
                    f.unlink()
            total = pdf_page_count(path)
            chunked = total is not None and total > args.chunk_pages
            label = f"{total} pages, in ranges of {args.chunk_pages}" if chunked else f"{path.stat().st_size / 1024:.0f} KB"
            print(f"[{i}/{len(files)}] parsing {path.name} ({label}) ...", flush=True)
            t0 = time.time()
            out_dir.mkdir(parents=True, exist_ok=True)
            warnings: list[str] = []
            try:
                if chunked:
                    md_content, warnings = parse_in_ranges(client, path, out_dir, total, args)
                    body = {"status": "success", "errors": []}
                else:
                    body = convert(client, path, args.ocr_lang)
                    doc = body["document"]
                    md_content = doc.get("md_content") or ""
                    write_atomic(out_dir / "docling.json", json.dumps(doc.get("json_content") or {}, ensure_ascii=False))
            except Exception as exc:  # keep going; one bad file must not stop the batch
                failed += 1
                print(f"    FAILED: {exc}  (finished page ranges are kept; re-run to resume)")
                continue
            write_atomic(out_dir / "docling.md", md_content)
            meta = {
                "source_file": path.name,
                "source_path": str(path.resolve()),
                "source_type": path.suffix.lower().lstrip("."),
                "access_level": access_level_for(path, args.level),
                "file_size_kb": round(path.stat().st_size / 1024, 1),
                "parsed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "parse_seconds": round(time.time() - t0, 1),
                "docling_status": body.get("status"),
                "docling_errors": body.get("errors") or [],
                "total_pages": total,
                "chunk_pages": args.chunk_pages if chunked else None,
                "warnings": warnings,
            }
            # meta.json last: its presence is what marks the file as finished.
            write_atomic(out_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            for w in warnings:
                print(f"    WARNING: {w}")
            print(f"    ok in {meta['parse_seconds']}s -> {out_dir}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
