"""Step 1b - transcribe scanned pages (image uploads, PDF pages without a text layer) with a vision LLM.

Docling's OCR dropped Vietnamese diacritics ("Đánh du vi trí gic ni"); NVIDIA's 90B vision model read
the same scan at 98%. The transcription replaces that page in docling.md (the original is kept as
docling_ocr.md); clean.py then runs as usual. Level-1 documents only: the page images leave the machine.

Usage:
    python denso/pipeline/ocr_pages.py --docs "Phieu_bao_tri_SCV_scan"
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

import httpx
import pypdf
from dotenv import dotenv_values
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PAGE_BREAK = "<!-- PAGE_BREAK -->"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
MAX_SIDE = 2048
PROMPT = ("Transcribe all text in this scanned page exactly as printed, line by line, in its original language "
          "(Vietnamese, Japanese, English...). Keep every diacritic, number, code, dash and unit exactly. Render "
          "tables as Markdown tables and headings as Markdown headings. Do not translate, summarise or add "
          "anything. If a word is unreadable write [?]. Output only the transcription.")


def as_png(data: bytes) -> bytes:
    """Any page image as a PNG of at most MAX_SIDE pixels (TIFF/BMP/WebP are not accepted upstream)."""
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def scan_pages(raw: Path) -> dict[int, bytes]:
    """page number -> page image, for the pages only OCR can read."""
    if raw.suffix.lower() in IMAGE_SUFFIXES:
        return {1: raw.read_bytes()}
    if raw.suffix.lower() != ".pdf":
        return {}
    pages = {}
    for no, page in enumerate(pypdf.PdfReader(str(raw)).pages, 1):
        if len((page.extract_text() or "").strip()) >= 20:
            continue  # a real text layer: Docling reads it exactly
        try:
            images = page.images
        except Exception:  # noqa: BLE001 - a broken image stream must not stop the document
            continue
        if images:
            pages[no] = max(images, key=lambda im: len(im.data)).data  # the scan is the page's biggest image
    return pages


PREAMBLE = re.compile(r"^\s*(?:here is|here's|the text|below is|transcription)\b[^\n]*:\s*$", re.IGNORECASE)


NO_TEXT = re.compile(r"^\W*(?:there is |there's )?no (?:legible |readable |visible )?text\b[^\n]{0,60}$", re.IGNORECASE)


def clean_transcription(text: str) -> str:
    """The page text without the model's framing: "The text ... is transcribed as follows:" and ``` fences."""
    lines = [ln for ln in text.strip().splitlines() if not ln.strip().startswith("```")]
    while lines and (PREAMBLE.match(lines[0]) or not lines[0].strip()):
        lines.pop(0)
    text = "\n".join(lines).strip()
    # A picture-only page: "There is no text on the scanned page." is not the page's content.
    return "" if NO_TEXT.match(text) else text


def replace_pages(docling_md: str, texts: dict[int, str], total: int | None = None) -> str:
    """docling.md with the given pages' text replaced (pages are 1-based, split on PAGE_BREAK)."""
    segments = docling_md.split(PAGE_BREAK)
    need = max([total or 0, len(segments), *texts])
    segments += [""] * (need - len(segments))
    for page, text in texts.items():
        segments[page - 1] = f"\n\n{clean_transcription(text)}\n\n"
    return PAGE_BREAK.join(segments)


async def transcribe(pages: dict[int, bytes], cache: dict, cache_path: Path, args, key: str) -> dict[int, str]:
    sem = asyncio.Semaphore(args.concurrency)
    out: dict[int, str] = {}
    async with httpx.AsyncClient(base_url=args.base, timeout=args.timeout,
                                 headers={"Authorization": f"Bearer {key}"}) as client:
        async def one(page: int, data: bytes) -> None:
            png = as_png(data)
            k = hashlib.sha1(png).hexdigest()[:16]
            if k in cache:
                out[page] = cache[k]["text"]
                return
            body = {"model": args.model, "temperature": 0, "max_tokens": 3000, "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}
            async with sem:
                for attempt in range(1, 5):
                    try:
                        r = await client.post("/chat/completions", json=body)
                        if r.status_code == 200:
                            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
                            if text:
                                break
                        print(f"  page {page}: HTTP {r.status_code} (attempt {attempt})", flush=True)
                    except httpx.HTTPError as exc:
                        print(f"  page {page}: {type(exc).__name__} (attempt {attempt})", flush=True)
                    await asyncio.sleep(10 * attempt)
                else:
                    raise RuntimeError(f"page {page}: the vision model gave no transcription after 4 attempts")
            cache[k] = {"page": page, "text": text, "model": args.model}
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, cache_path)
            out[page] = text
            print(f"  page {page}: {len(text)} chars", flush=True)

        await asyncio.gather(*(one(p, d) for p, d in sorted(pages.items())))
    return out


def process(stem: str, args, key: str) -> int:
    doc_dir = args.parsed / stem
    meta_path = doc_dir / "meta.json"
    if not meta_path.exists():
        print(f"{stem}: not parsed yet, skipped")
        return 0
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("access_level") != 1:
        print(f"{stem}: skipped (access level {meta.get('access_level')} - page images are sent only for level 1)")
        return 0
    raw = Path(meta.get("source_path") or "")
    if not raw.exists():
        raw = args.raw / meta["source_file"]
    pages = scan_pages(raw)
    (doc_dir / "scan_pages.json").write_text(json.dumps(sorted(pages)), encoding="utf-8")
    if not pages:
        print(f"{stem}: no scanned pages")
        return 0
    cache_path = doc_dir / "page_text.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    texts = asyncio.run(transcribe(pages, cache, cache_path, args, key))
    docling_md, original, state = doc_dir / "docling.md", doc_dir / "docling_ocr.md", doc_dir / "ocr_pages.json"
    current = docling_md.read_text(encoding="utf-8")
    merged_sha = json.loads(state.read_text(encoding="utf-8")).get("merged_sha") if state.exists() else None
    # docling.md is either our last merge (keep the saved Docling original) or a fresh parse - a
    # re-upload of the same name - which becomes the new original.
    if not original.exists() or hashlib.sha1(current.encode()).hexdigest() != merged_sha:
        original.write_text(current, encoding="utf-8")
    merged = replace_pages(original.read_text(encoding="utf-8"), texts, meta.get("total_pages"))
    tmp = docling_md.with_suffix(".tmp")
    tmp.write_text(merged, encoding="utf-8")
    os.replace(tmp, docling_md)
    state.write_text(json.dumps({"merged_sha": hashlib.sha1(merged.encode()).hexdigest(), "pages": sorted(texts),
                                 "model": args.model}), encoding="utf-8")
    print(f"{stem}: {len(texts)} scanned page(s) transcribed with {args.model}")
    return len(texts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", nargs="+", required=True, help="Parsed document stems")
    ap.add_argument("--raw", type=Path, default=DATA / "raw")
    ap.add_argument("--parsed", type=Path, default=DATA / "parsed")
    ap.add_argument("--base", default="https://integrate.api.nvidia.com/v1")
    ap.add_argument("--key-var", default="NVIDIA_API_KEY")
    ap.add_argument("--model", default="meta/llama-3.2-90b-vision-instruct",
                    help="90b read a Vietnamese scan at 98%% (all 10 key facts); 11b at 79%%, Docling OCR 89%%")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()
    key = (dotenv_values(ROOT.parent / ".env").get(args.key_var) or "").strip()
    if not key:
        raise SystemExit(f"{args.key_var} is not set in .env")
    for stem in args.docs:
        process(stem, args, key)
    sys.exit(0)


if __name__ == "__main__":
    main()
