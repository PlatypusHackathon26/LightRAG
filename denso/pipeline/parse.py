"""Step 1 - parse raw documents with the local docling-serve.

For every file it stores the raw Docling outputs next to each other:
    <out>/<stem>/docling.md     Markdown with a page-break marker between pages
    <out>/<stem>/docling.json   DoclingDocument (page provenance, tables)
    <out>/<stem>/meta.json      source path, access level, size, parse time

Already-parsed files are skipped unless --force is given, because parsing a
large catalogue on CPU takes many minutes.

Usage:
    python denso/pipeline/parse.py denso/data/raw            # level from folder name
    python denso/pipeline/parse.py --level 1 some/file.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

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


def convert(client: httpx.Client, path: Path, ocr_lang: list[str] | None) -> dict:
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
    with path.open("rb") as fh:
        r = client.post("/v1/convert/file", data=data, files={"files": (path.name, fh)})
    r.raise_for_status()
    body = r.json()
    if body.get("status") not in ("success", "partial_success"):
        raise RuntimeError(f"docling status={body.get('status')} errors={body.get('errors')}")
    return body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--level", type=int, choices=(1, 2, 3))
    ap.add_argument("--docling", default="http://127.0.0.1:5001")
    ap.add_argument("--ocr-lang", nargs="*", default=None, help="BCP-47 tags, e.g. en vi")
    ap.add_argument("--force", action="store_true", help="Re-parse files that already have output")
    args = ap.parse_args()

    files = collect(args.paths)
    failed = 0
    with httpx.Client(base_url=args.docling, timeout=httpx.Timeout(3600, connect=10)) as client:
        for i, path in enumerate(files, 1):
            out_dir = args.out / path.stem
            if (out_dir / "docling.json").exists() and not args.force:
                print(f"[{i}/{len(files)}] skip (parsed) {path.name}")
                continue
            print(f"[{i}/{len(files)}] parsing {path.name} ({path.stat().st_size / 1024:.0f} KB) ...", flush=True)
            t0 = time.time()
            try:
                body = convert(client, path, args.ocr_lang)
            except Exception as exc:  # keep going; one bad file must not stop the batch
                failed += 1
                print(f"    FAILED: {exc}")
                continue
            doc = body["document"]
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "docling.md").write_text(doc.get("md_content") or "", encoding="utf-8")
            (out_dir / "docling.json").write_text(
                json.dumps(doc.get("json_content") or {}, ensure_ascii=False), encoding="utf-8"
            )
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
            }
            (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    ok in {meta['parse_seconds']}s -> {out_dir}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
