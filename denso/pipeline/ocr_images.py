"""Step 2b - transcribe the text inside PDF images with a vision LLM (public documents only).

Writes "<stem> - images.[native-P!].md" with the usual page markers, so answers drawn from a
picture still cite its page. Results are cached per image.

Usage:
    python denso/pipeline/ocr_images.py [--docs "DENSO-AC_brochure_tips-and-tricks_EN"]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path

import httpx
import pypdf
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PAGE_MARK = re.compile(r"^--- \[Trang (\d+)(?: \| ngôn ngữ: ([a-z-]+))?[^\]]*\] ---$")
HEADING = re.compile(r"^#{1,7}\s+(.+)$")
NO_TEXT = re.compile(r"^\W*no text\W*$", re.IGNORECASE)
PROMPT = (
    "This image comes from a DENSO automotive technical document. In one sentence, say what the image "
    "shows (product, part, diagram, table, photo of a label...). Then transcribe every legible word, number "
    "and code exactly as printed, keeping the original language (English, Japanese, Vietnamese...), and add "
    "'English: ...' for any non-English text. Do not guess unreadable text. If the image holds no meaningful "
    "text and no product or part (a decorative photo, a logo), answer exactly: NO TEXT"
)


def image_key(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def collect_images(pdf: Path, pages: tuple[int, int] | None, min_px: int, min_bytes: int,
                   max_repeat: int) -> dict[str, dict]:
    """key -> {"pages": [...], "data": bytes, "mime": str} for the images worth reading."""
    found: dict[str, dict] = {}
    for no, page in enumerate(pypdf.PdfReader(str(pdf)).pages, 1):
        if pages and not pages[0] <= no <= pages[1]:
            continue
        try:
            images = page.images
        except Exception:  # noqa: BLE001 - a broken image stream must not stop the document
            continue
        for im in images:
            try:
                width, height = im.image.size
            except Exception:  # noqa: BLE001
                continue
            if width < min_px or height < min_px or len(im.data) < min_bytes:
                continue
            key = image_key(im.data)
            entry = found.setdefault(key, {"pages": [], "data": im.data,
                                           "mime": "image/png" if im.name.lower().endswith(".png") else "image/jpeg"})
            if no not in entry["pages"]:
                entry["pages"].append(no)
    # A picture on many pages is a frame, logo or decoration, not content.
    return {k: v for k, v in found.items() if len(v["pages"]) <= max_repeat}


def page_context(cleaned_md: Path) -> dict[int, dict]:
    """page -> {"lang": xx, "headings": [...]} from the cleaned Markdown of the same document."""
    ctx: dict[int, dict] = defaultdict(lambda: {"lang": "en", "headings": []})
    if not cleaned_md.exists():
        return ctx
    page = None
    for line in cleaned_md.read_text(encoding="utf-8").splitlines():
        m = PAGE_MARK.match(line.strip())
        if m:
            page = int(m.group(1))
            if m.group(2):
                ctx[page]["lang"] = m.group(2)
            continue
        h = HEADING.match(line.strip())
        if h and page is not None and h.group(1) not in ctx[page]["headings"]:
            ctx[page]["headings"].append(h.group(1).strip())
    return ctx


async def read_images(todo: dict[str, dict], cache: dict, cache_path: Path, args, key: str) -> None:
    sem = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()

    async with httpx.AsyncClient(base_url=args.base, timeout=args.timeout,
                                 headers={"Authorization": f"Bearer {key}"}) as client:
        async def one(k: str, item: dict) -> None:
            body = {"model": args.model, "temperature": 0, "max_tokens": 600, "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{item['mime']};base64,{base64.b64encode(item['data']).decode()}"}},
            ]}]}
            async with sem:
                for attempt in range(1, 5):
                    try:
                        r = await client.post("/chat/completions", json=body)
                        if r.status_code == 200:
                            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
                            break
                        print(f"  {k} p{item['pages']} HTTP {r.status_code} (attempt {attempt})", flush=True)
                    except httpx.HTTPError as exc:
                        print(f"  {k} p{item['pages']} {type(exc).__name__} (attempt {attempt})", flush=True)
                    await asyncio.sleep(10 * attempt)
                else:
                    return  # left out of the cache: the next run retries it
            async with lock:
                cache[k] = {"pages": item["pages"], "text": text, "model": args.model,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                tmp = cache_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, cache_path)
                print(f"  read {k} p{item['pages']}: {text[:80]!r}", flush=True)

        await asyncio.gather(*(one(k, v) for k, v in todo.items()))


def sections_with_images(docling_md: Path) -> dict[str, int]:
    """heading text -> number of `<!-- image -->` placeholders directly under it in Docling's Markdown.

    Docling keeps where each picture sat. Knowing that the three oil cans sit under "Shelf life"
    (not just "somewhere on page 12") is what lets an answer read them as the shelf-life list.
    """
    counts: dict[str, int] = defaultdict(int)
    if not docling_md.exists():
        return counts
    heading = None
    for line in docling_md.read_text(encoding="utf-8").splitlines():
        h = HEADING.match(line.strip())
        if h:
            heading = h.group(1).strip()
        elif "<!-- image -->" in line and heading:
            counts[heading] += 1
    return counts


def dedupe_lines(text: str) -> str:
    """Drop repeated lines: the small vision model sometimes loops ("* ND-OIL 11" x 60)."""
    seen, out = set(), []
    for line in text.splitlines():
        key = line.strip().lower()
        if key and key in seen:
            continue
        seen.add(key)
        out.append(line)
    return "\n".join(out).strip()


def write_markdown(stem: str, cache: dict, cleaned_dir: Path, docling_md: Path | None = None) -> Path | None:
    ctx = page_context(cleaned_dir / f"{stem}.md")
    with_images = sections_with_images(docling_md) if docling_md else {}
    by_page: dict[int, list[str]] = defaultdict(list)
    for entry in cache.values():
        text = dedupe_lines(entry["text"].strip())
        if not text or NO_TEXT.match(text) or len(text) < 15:
            continue
        # Under every page it is on: the brochure shows the same three oil cans on pages 11, 12
        # and 15, and only page 12 is the shelf-life section the question is about.
        for page in entry["pages"]:
            by_page[page].append(text)
    if not by_page:
        return None
    lines = [f"# Chữ và hình trong ảnh – {stem}", "",
             "Nội dung đọc từ ảnh của tài liệu gốc bằng mô hình thị giác (có thể sai ở chữ nhỏ; đối chiếu bản gốc).", ""]
    for page in sorted(by_page):
        c = ctx[page]
        texts = by_page[page]
        owners = [h for h in c["headings"] if with_images.get(h)]
        if len(owners) == 1:
            title = f"Ảnh trong mục «{owners[0]}» (trang {page}) – {stem}"
        elif owners:
            title = f"Ảnh trong các mục {', '.join(f'«{h}»' for h in owners)} (trang {page}) – {stem}"
        else:
            title = f"Ảnh trên trang {page} – {stem}"
        lines += [f"--- [Trang {page} | ngôn ngữ: {c['lang']}] ---", "", f"## {title}", ""]
        if not owners and c["headings"]:
            lines += [f"Các mục trên trang này: {'; '.join(c['headings'][:8])}.", ""]
        # One line naming every picture, so the set reads as a list ("the shelf life of ND-oils
        # is: [ND-OIL 8] [ND-OIL 11] [ND-OIL 12]") rather than as separate photos.
        summary = "; ".join(t.splitlines()[0].rstrip(".") for t in texts)
        where = f"mục «{owners[0]}»" if len(owners) == 1 else "trang này"
        lines += [f"Các ảnh trong {where} cho thấy: {summary}.", ""]
        for i, text in enumerate(texts, 1):
            lines += [f"### Ảnh {i}", "", text, ""]
    out = cleaned_dir / f"{stem} - images.[native-P!].md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=DATA / "raw")
    ap.add_argument("--parsed", type=Path, default=DATA / "parsed")
    ap.add_argument("--cleaned", type=Path, default=DATA / "cleaned_md")
    ap.add_argument("--docs", nargs="*", help="Only these document stems")
    ap.add_argument("--skip", nargs="*", default=["AC Components Catalogue_2020"], help="Stems to leave out")
    ap.add_argument("--base", default="https://integrate.api.nvidia.com/v1")
    ap.add_argument("--key-var", default="NVIDIA_API_KEY", help="Variable in .env holding the API key")
    ap.add_argument("--model", default="meta/llama-3.2-11b-vision-instruct",
                    help="11b reads labels as well as 90b at ~21 vs ~6 tokens/s on the free tier")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--min-px", type=int, default=120)
    ap.add_argument("--min-bytes", type=int, default=8000)
    ap.add_argument("--max-repeat", type=int, default=3, help="Images on more pages than this are decoration")
    ap.add_argument("--dry-run", action="store_true", help="Count images only, no API calls")
    args = ap.parse_args()

    key = (dotenv_values(ROOT.parent / ".env").get(args.key_var) or "").strip()
    if not key and not args.dry_run:
        raise SystemExit(f"{args.key_var} is not set in .env")
    tiers = json.loads((ROOT / "pipeline" / "tiers.json").read_text(encoding="utf-8"))
    pdfs = [p for p in sorted(args.raw.glob("*.pdf"))
            if (not args.docs or p.stem in args.docs) and p.stem not in (args.skip or [])]
    for pdf in pdfs:
        # The images leave the machine: only documents parse.py recorded as level 1. Uploads of every
        # level share raw/, so the folder alone says nothing; no meta.json (not parsed) is a skip too.
        meta_path = args.parsed / pdf.stem / "meta.json"
        level = json.loads(meta_path.read_text(encoding="utf-8")).get("access_level") if meta_path.exists() else None
        if level != 1:
            print(f"{pdf.stem}: skipped (access level {level or 'unknown'} - images are sent only for level 1)")
            continue
        rng = tiers.get(pdf.stem, {}).get("knowledge_pages")
        images = collect_images(pdf, tuple(rng) if rng else None, args.min_px, args.min_bytes, args.max_repeat)
        # Scanned pages were transcribed whole by ocr_pages.py; describing the scan again as a picture
        # added "[Ảnh] The image shows a technical document in Vietnamese..." next to the real text.
        scan_file = args.parsed / pdf.stem / "scan_pages.json"
        scanned = set(json.loads(scan_file.read_text(encoding="utf-8"))) if scan_file.exists() else set()
        images = {k: v for k, v in images.items() if not set(v["pages"]) <= scanned}
        cache_path = args.parsed / pdf.stem / "image_text.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Page -> image keys in PDF order, so clean.py can put each description where Docling
        # left the picture's `<!-- image -->` placeholder.
        order: dict[int, list[str]] = defaultdict(list)
        for k, v in images.items():
            for page in v["pages"]:
                order[page].append(k)
        (cache_path.parent / "image_order.json").write_text(json.dumps(order, indent=1), encoding="utf-8")
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        todo = {k: v for k, v in images.items() if k not in cache}
        print(f"{pdf.stem}: {len(images)} images, {len(todo)} to read", flush=True)
        if args.dry_run:
            continue
        if todo:
            asyncio.run(read_images(todo, cache, cache_path, args, key))
        # Pages from this parse, not the cache: a re-uploaded file can move a picture.
        out = write_markdown(pdf.stem, {k: {**v, "pages": images[k]["pages"]} for k, v in cache.items() if k in images},
                             args.cleaned,
                             args.parsed / pdf.stem / "docling.md")
        print(f"  -> {out.name if out else 'no image text'}", flush=True)


if __name__ == "__main__":
    main()
