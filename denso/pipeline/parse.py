"""Step 1 - convert raw documents with docling-serve into <out>/<stem>/{docling.md, docling.json, meta.json}.

Long PDFs are converted in page ranges and every file is written atomically, so after a crash
the same command resumes. TXT is read directly; XLSX becomes one page per sheet.

Usage:
    python denso/pipeline/parse.py denso/data/raw            # level from folder name
    python denso/pipeline/parse.py --level 1 --force some/file.pdf
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
# Plain text is read here: Docling's convert API does not take .txt.
TEXT_SUFFIXES = {".txt"}
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
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in DOCLING_SUFFIXES | TEXT_SUFFIXES)
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(f"Not found: {p}")
    return files


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_text_file(path: Path) -> str:
    """A .txt upload as Markdown text: UTF-8 (with or without BOM), UTF-16, else Windows Vietnamese."""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1258"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _md_table(grid: list[list[dict]]) -> str:
    rows = [[" ".join((c.get("text") or "").split()).replace("|", "\\|") for c in row] for row in grid]
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows[1:]])


def sheets_markdown(doc_json: dict) -> str | None:
    """A workbook as one page per sheet, each headed by its sheet name; None if it has no sheets.

    Docling's own Markdown put both sheets' tables before the first page break and dropped the
    sheet names, so a torque from sheet "Mô-men xoắn" was cited as page 1 with no sheet.
    """
    sheets = [g for g in doc_json.get("groups") or [] if g.get("label") == "sheet"]
    if not sheets:
        return None
    pages = []
    for sheet in sheets:
        parts = [f"## Sheet: {sheet.get('name') or len(pages) + 1}"]
        for child in sheet.get("children") or []:
            _, kind, idx = (child.get("$ref") or "#//").split("/")[:3]
            item = (doc_json.get(kind) or [])[int(idx)] if idx.isdigit() else {}
            if kind == "tables":
                parts.append(_md_table(item.get("data", {}).get("grid") or []))
            elif kind == "texts" and item.get("text"):
                parts.append(item["text"])
        pages.append("\n\n".join(p for p in parts if p))
    return f"\n\n{PAGE_BREAK}\n\n".join(pages)


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
        md_parts.append(merge_range(parts_dir, a, b, warnings))
    return PAGE_BREAK.join(md_parts), warnings


def body_pages(doc_json: dict) -> list[int]:
    """Pages that hold body content (not just headers/footers) in a DoclingDocument."""
    items = doc_json.get("texts", []) + doc_json.get("tables", []) + doc_json.get("pictures", [])
    return sorted({p["page_no"] for it in items if it.get("content_layer", "body") == "body" for p in it.get("prov", [])})


def align_segments(segments: list[str], first: int, last: int, doc_json: dict | None) -> tuple[list[str], str | None]:
    """Place Markdown page segments on the right page numbers.

    Docling's Markdown export emits no page-break placeholder for pages without
    body content (e.g. blank "MEMO" pages), so a range can come back with fewer
    segments than pages. The DoclingDocument JSON says which pages have body
    content; when its count matches the segments, map them one-to-one and leave
    the other pages empty. Otherwise pad at the end and report it.
    """
    expected = last - first + 1
    if len(segments) >= expected:
        return segments[:expected], None
    pages = [p for p in body_pages(doc_json or {}) if first <= p <= last]
    if len(pages) == len(segments):
        out = [""] * expected
        for seg, p in zip(segments, pages):
            out[p - first] = seg
        empty = [p for p in range(first, last + 1) if p not in pages]
        return out, f"pages {first}-{last}: no body content on {empty}; segments aligned by page"
    return segments + [""] * (expected - len(segments)), (
        f"pages {first}-{last}: docling returned {len(segments)} of {expected} pages and the JSON "
        f"lists {len(pages)} body pages; padded at end - page numbers in this range may be off"
    )


def merge_range(parts_dir: Path, a: int, b: int, warnings: list[str]) -> str:
    md = (parts_dir / f"p{a:04d}-{b:04d}.md").read_text(encoding="utf-8")
    json_file = parts_dir / f"p{a:04d}-{b:04d}.json"
    doc_json = json.loads(json_file.read_text(encoding="utf-8")) if json_file.exists() else None
    pages, warning = align_segments(md.split(PAGE_BREAK), a, b, doc_json)
    if warning:
        warnings.append(warning)
    return PAGE_BREAK.join(pages)


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
    ap.add_argument("--remerge", action="store_true", help="Rebuild docling.md from saved parts/ without calling Docling")
    args = ap.parse_args()

    if args.remerge:
        for path in collect(args.paths):
            out_dir = args.out / path.stem
            parts = sorted((out_dir / "parts").glob("p*-*.md")) if (out_dir / "parts").exists() else []
            if not parts:
                print(f"{path.name}: no parts/ to re-merge")
                continue
            warnings: list[str] = []
            ranges = [tuple(int(x) for x in f.stem[1:].split("-")) for f in parts]
            md = PAGE_BREAK.join(merge_range(out_dir / "parts", a, b, warnings) for a, b in ranges)
            write_atomic(out_dir / "docling.md", md)
            meta_file = out_dir / "meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["warnings"] = warnings
                write_atomic(meta_file, json.dumps(meta, ensure_ascii=False, indent=2))
            print(f"{path.name}: re-merged {len(ranges)} ranges, {md.count(PAGE_BREAK) + 1} pages")
            for w in warnings:
                print(f"    {w}")
        return

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
                if path.suffix.lower() in TEXT_SUFFIXES:
                    md_content = read_text_file(path).replace("\r\n", "\n")
                    body = {"status": "success", "errors": []}
                elif chunked:
                    md_content, warnings = parse_in_ranges(client, path, out_dir, total, args)
                    body = {"status": "success", "errors": []}
                else:
                    body = convert(client, path, args.ocr_lang)
                    doc = body["document"]
                    md_content = doc.get("md_content") or ""
                    if path.suffix.lower() == ".xlsx":
                        md_content = sheets_markdown(doc.get("json_content") or {}) or md_content
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
