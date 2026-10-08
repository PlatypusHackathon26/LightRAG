"""Step 2 - clean Docling Markdown and export it for the knowledge base.

Input:  <parsed>/<stem>/{docling.md, meta.json}   (written by parse.py)
Output: <out>/cleaned_md/<stem>.md      heading-preserving Markdown for LightRAG
        <out>/cleaned_json/<stem>.json  A3 schema (see output_format.json)
        <parsed>/<stem>/clean_report.json  what was dropped / fixed, per page

Rules are deliberately conservative: a line is only dropped when it matches a
known junk pattern, and OCR word-joining needs dictionary evidence. Every
language is kept (the benchmark compares e.g. the Russian and English sections)
and each page is tagged with its detected language instead.

Usage:
    python denso/pipeline/clean.py                 # every parsed document
    python denso/pipeline/clean.py "AC Compressor Leaflet"
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from langdetect import DetectorFactory, LangDetectException, detect_langs
from wordfreq import zipf_frequency

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textutils import clean_text  # noqa: E402

DetectorFactory.seed = 0  # deterministic language detection

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARSED = ROOT / "data" / "parsed"
DEFAULT_OUT = ROOT / "data"
PAGE_BREAK = "<!-- PAGE_BREAK -->"

# Languages wordfreq knows well enough for OCR word-joining. Vietnamese is
# excluded on purpose: its words are space-separated syllables.
JOINABLE_LANGS = {"en", "de", "fr", "es", "it", "pt", "ro", "pl", "nl", "sv", "da", "ru"}
CJK_LANGS = {"zh-cn", "zh-tw", "ja", "ko"}

HTML_COMMENT = re.compile(r"^\s*<!--.*-->\s*$")
IMAGE_PLACEHOLDER = "<!-- image -->"
IMG_LINE = "\x00IMG\x00"  # marks an image description inlined by inline_captions(); never cleaned
BULLET_GT = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s*>\s*")
BULLET_PREFIX = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?(?:>\s*)?")
TRAILING_PUNCT = re.compile(r"^(.*?)([.,;:!?)\]]*)$")
INLINE_GT_BULLET = re.compile(r"\s+>\s+(?=[A-Z])")
MD_ESCAPE = re.compile(r"\\([_*\[\]()#+\-.!|`])")
SLASH_ACRONYM = re.compile(r"\b([A-Z])\s+/\s*([A-Z])\b")
CJK_CHAR = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class PageReport:
    page: int
    language: str
    dropped: list[str] = field(default_factory=list)
    joined: list[str] = field(default_factory=list)


def detect_lang(text: str) -> str:
    """Page language; 'mixed' when no language clearly dominates (e.g. a multilingual TOC)."""
    sample = " ".join(WORD.findall(text))
    if len(sample) < 20:
        return "unknown"
    try:
        best = detect_langs(sample)[0]
    except LangDetectException:
        return "unknown"
    return best.lang if best.prob >= 0.75 else "mixed"


# ---------------------------------------------------------------- line rules


def is_letter_spaced(line: str) -> bool:
    """'P r i n t e d i n B' - print codes and logos spelled out by OCR."""
    tokens = BULLET_PREFIX.sub("", line).split()
    # A formula is not a spelled-out logo: "Công thức: A - B = C" was dropped from a text upload.
    if len(tokens) < 3 or "=" in tokens:
        return False
    singles = sum(1 for t in tokens if len(t) == 1 and t not in "-+=/×")
    return singles / len(tokens) >= 0.6


def is_junk_line(line: str, page_lang: str) -> str | None:
    """Return the reason a body line should be dropped, or None to keep it."""
    stripped = line.strip()
    if HTML_COMMENT.match(stripped):
        return "html_comment"
    alnum = sum(ch.isalnum() for ch in stripped)
    if alnum <= 2:
        return "too_short"
    if is_letter_spaced(stripped):
        return "letter_spaced"
    if page_lang not in CJK_LANGS and CJK_CHAR.search(stripped) and len(stripped) <= 4:
        return "stray_cjk"
    return None


def _zipf(word: str, lang: str) -> float:
    return zipf_frequency(word.lower(), lang)


def join_ocr_splits(line: str, lang: str, log: list[str]) -> str:
    """Join words OCR split apart ('Ref ri gerant' -> 'Refrigerant').

    A window of 2-3 alphabetic tokens is joined when the joined word exists and
    either one fragment is not a real word ('t ype'), or every fragment is at
    least 3 letters and the joined word is nearly as common as its most common
    fragment ('comfort able'). Short real words stay apart ('a part', pt 'com o').
    Trailing punctuation on the last token is kept ('t ype:' -> 'type:').
    """
    if lang not in JOINABLE_LANGS:
        return line
    tokens = line.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        merged = False
        for width in (3, 2):
            window = tokens[i : i + width]
            if len(window) < width:
                continue
            last, punct = TRAILING_PUNCT.match(window[-1]).groups()
            words = window[:-1] + [last]
            if not all(w.isalpha() for w in words):
                continue
            # Acronyms and capitalised follow-up words are separate on purpose.
            if any(w.isupper() and len(w) > 1 for w in words) or any(w[0].isupper() for w in words[1:]):
                continue
            joined = "".join(words)
            zj = _zipf(joined, lang)
            parts = [_zipf(w, lang) for w in words]
            if zj < 2.0:
                continue
            has_nonword = min(parts) < 2.0
            all_long = min(len(w) for w in words) >= 3
            if has_nonword or (all_long and zj >= max(parts) - 0.8):
                out.append(joined + punct)
                log.append(f"{' '.join(window)} -> {joined}{punct}")
                i += width
                merged = True
                break
        if not merged:
            out.append(tokens[i])
            i += 1
    return " ".join(out)


def clean_inline(text: str, lang: str, log: list[str]) -> str:
    text = html.unescape(text)
    text = MD_ESCAPE.sub(r"\1", text)
    text = SLASH_ACRONYM.sub(r"\1/\2", text)
    text = join_ocr_splits(clean_text(text, keep_newlines=False), lang, log)
    return text


# ---------------------------------------------------------------- tables


def clean_table(lines: list[str], lang: str, log: list[str]) -> str:
    """Re-render a Markdown table compactly with cleaned cell text."""
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue  # separator row, re-created below
        rows.append([clean_inline(c, lang, log) for c in cells])
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


# Tables this big are likely to be split across chunks by LightRAG's P chunker
# (~2000-token chunks; a heading section holding several mid-size tables gets
# split too). Row slices keep the header row but not the page marker, so such
# tables get a per-row page column instead.
SPLIT_TABLE_CHARS = 1500
SPLIT_TABLE_ROWS = 10


def likely_split(table_md: str) -> bool:
    return len(table_md) >= SPLIT_TABLE_CHARS or table_md.count("\n") - 1 >= SPLIT_TABLE_ROWS


def with_page_column(table_md: str, page: int) -> str:
    lines = table_md.split("\n")
    out = [lines[0].replace("| ", "| Trang | ", 1), lines[1].replace("|", "|---|", 1)]
    out += [line.replace("| ", f"| {page} | ", 1) for line in lines[2:]]
    return "\n".join(out)


# ---------------------------------------------------------------- document


# Footnote legends ('*2 No applicable item is available', '※ ...') explain markers
# used inside tables on that page; every chunk needs them, so they are never
# treated as running boilerplate even when printed on every page.
FOOTNOTE_LEGEND = re.compile(r"^(?:[-*+]\s+)?(?:\*\s*\d+|※|\(\s*\d+\s*\)\s|\(Note)")


def repeated_lines(pages: list[str]) -> set[str]:
    """Short lines repeated on at least half of the pages: running headers/footers."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        seen = {
            ln.strip()
            for ln in page.split("\n")
            if 0 < len(ln.strip()) < 80 and not ln.startswith("|") and not FOOTNOTE_LEGEND.match(ln.strip())
        }
        counts.update(seen)
    return {ln for ln, n in counts.items() if n >= max(3, len(pages) // 2)}


def clean_page(
    raw: str, number: int, boilerplate: set[str], emitted: set[str] | None = None
) -> tuple[list[str], list[dict], PageReport]:
    """Clean one page. `emitted` collects boilerplate lines already kept once in this document."""
    emitted = set() if emitted is None else emitted
    # Inlined image descriptions are English model output: keep them out of the page language.
    lang = detect_lang("\n".join(x for x in raw.split("\n") if not x.strip().startswith(IMG_LINE)))
    report = PageReport(page=number, language=lang)
    blocks: list[str] = []
    tables: list[dict] = []
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            table_md = clean_table(table_lines, lang, report.joined)
            if table_md:
                blocks.append(with_page_column(table_md, number) if likely_split(table_md) else table_md)
                tables.append({"page": number, "markdown": table_md})
            continue
        i += 1
        if stripped.startswith(IMG_LINE):
            blocks.append(f"[Ảnh] {stripped[len(IMG_LINE):].strip()}")
            continue
        if stripped in boilerplate:
            if stripped in emitted:
                report.dropped.append(f"boilerplate: {stripped}")
                continue
            emitted.add(stripped)  # keep the first occurrence, run it through the normal rules
        heading = HEADING.match(stripped)
        if heading:
            text = clean_inline(heading.group(2), lang, report.joined)
            if text and not is_letter_spaced(text):
                blocks.append(f"{heading.group(1)} {text}")
            continue
        reason = is_junk_line(stripped, lang)
        if reason:
            report.dropped.append(f"{reason}: {stripped}")
            continue
        bullet = BULLET_GT.match(line)
        if bullet:
            body = line[bullet.end():]
            for item in INLINE_GT_BULLET.split(body.replace("&gt;", ">")):
                item = clean_inline(item.lstrip("> "), lang, report.joined)
                if item:
                    blocks.append(f"- {item}")
            continue
        text = clean_inline(stripped, lang, report.joined)
        if text:
            blocks.append(text)
    return drop_repeats_in_page(blocks, report), tables, report


DUP_MIN_CHARS = 80


def drop_repeats_in_page(blocks: list[str], report: PageReport) -> list[str]:
    """Drop exact repeats of a prose paragraph on the same page (keep the first).

    Layered PDFs make Docling emit the same warning or caption several times on
    one page. Repeats across pages or documents are kept on purpose: the
    brochure reprints whole bulletins and both copies are cited.
    """
    seen: set[str] = set()
    out = []
    for block in blocks:
        if block.startswith(("#", "|")) or len(block) < DUP_MIN_CHARS:
            out.append(block)
            continue
        key = " ".join(block.lower().split())
        if key in seen:
            report.dropped.append(f"duplicate_in_page: {block[:80]}")
            continue
        seen.add(key)
        out.append(block)
    return out


def markdown_page(blocks: list[str], number: int, lang: str) -> str:
    """Render one page, repeating its marker right after every heading.

    LightRAG's native parser splits Markdown into heading-led blocks, and a
    marker placed before a heading ends up at the tail of the previous block.
    Putting the marker after each heading makes every block - and so every
    chunk - start with the page it comes from, which is what citations need.
    """
    marker = page_marker(number, lang)
    out: list[str] = []
    if not blocks or not HEADING.match(blocks[0]):
        out.append(marker)
    for block in blocks:
        out.append(block)
        if HEADING.match(block):
            out.append(marker)
    return "\n\n".join(out)


def page_marker(number: int, lang: str | None = None) -> str:
    return f"--- [Trang {number}] ---" if lang is None else f"--- [Trang {number} | ngôn ngữ: {lang}] ---"


def doc_id_for(source: Path) -> str:
    digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else hashlib.sha256(source.name.encode()).hexdigest()
    return f"DENSO_{digest[:8].upper()}"


TIERS_FILE = Path(__file__).resolve().parent / "tiers.json"
PART_NAME = re.compile(r"^p(\d{4})-(\d{4})\.md$")
LOOKUP_HINT = "[native-P!]"  # LightRAG filename hint: native engine, P chunking, no KG extraction


def load_tiers() -> dict:
    data = json.loads(TIERS_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def compact_caption(text: str, limit: int = 600) -> str:
    """One-line form of a vision-model description: no repeated lines, bullets joined."""
    seen, parts = set(), []
    for line in text.splitlines():
        line = line.strip().lstrip("*-• ").strip().strip('"')
        if line and line.lower() not in seen:
            seen.add(line.lower())
            parts.append(line.rstrip(":"))
    out = "; ".join(parts)
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + " …"


def load_captions(doc_dir: Path) -> dict[int, list[str]]:
    """page -> image descriptions in PDF order, from ocr_images.py (empty when it has not run)."""
    texts_path, order_path = doc_dir / "image_text.json", doc_dir / "image_order.json"
    if not (texts_path.exists() and order_path.exists()):
        return {}
    texts = json.loads(texts_path.read_text(encoding="utf-8"))
    out: dict[int, list[str]] = {}
    for page, keys in json.loads(order_path.read_text(encoding="utf-8")).items():
        captions = []
        for k in keys:
            t = (texts.get(k) or {}).get("text", "").strip()
            if t and not re.fullmatch(r"\W*no text\W*", t, re.IGNORECASE) and len(t) >= 15:
                captions.append(compact_caption(t))
        if captions:
            out[int(page)] = captions
    return out


def inline_captions(raw: str, captions: list[str]) -> str:
    """Put image descriptions where Docling left the pictures.

    One description per `<!-- image -->` placeholder, in order, when the counts match (the
    brochure's shelf-life section: three placeholders, three oil cans). Otherwise - icons were
    filtered out, or a picture was not extracted - every description goes to the end of the
    page, so a description is never attached to the wrong section.
    """
    if not captions:
        return raw
    lines = raw.split("\n")
    slots = [i for i, line in enumerate(lines) if IMAGE_PLACEHOLDER in line]
    if len(slots) == len(captions):
        for i, caption in zip(slots, captions):
            lines[i] = IMG_LINE + caption
        return "\n".join(lines)
    return raw + "\n\n" + "\n".join(IMG_LINE + c for c in captions)


def load_pages(doc_dir: Path) -> tuple[list[str], bool, int]:
    """Return (raw pages, complete?, raw char count).

    A finished parse has docling.md. An unfinished one is assembled from the
    contiguous run of parts/ ranges starting at page 1, so the knowledge tier
    of a long catalogue can be cleaned before the lookup pages are parsed.
    """
    if (doc_dir / "meta.json").exists() and (doc_dir / "docling.md").exists():
        md = (doc_dir / "docling.md").read_text(encoding="utf-8")
        return md.split(PAGE_BREAK), True, len(md)
    parts = sorted(
        (int(m.group(1)), int(m.group(2)), f)
        for f in (doc_dir / "parts").glob("p*.md")
        if (m := PART_NAME.match(f.name))
    ) if (doc_dir / "parts").exists() else []
    pages: list[str] = []
    size = 0
    for start, end, f in parts:
        if start != len(pages) + 1:
            break  # gap: stop at the last contiguous page
        md = f.read_text(encoding="utf-8")
        size += len(md)
        chunk = md.split(PAGE_BREAK)
        chunk += [""] * (end - start + 1 - len(chunk))
        pages += chunk[: end - start + 1]
    return pages, False, size


def write_md(path: Path, title: str, md_parts: list[str]) -> None:
    path.write_text(f"# {title}\n\n" + "\n\n".join(md_parts) + "\n", encoding="utf-8")


def process(doc_dir: Path, out_root: Path, tiers: dict | None = None) -> dict | None:
    """Clean one parsed document. Returns its report, or None if nothing could be written yet."""
    tiers = load_tiers() if tiers is None else tiers
    stem = doc_dir.name
    pages_raw, complete, raw_chars = load_pages(doc_dir)
    tier = tiers.get(stem)
    if not pages_raw:
        return None
    if not complete and (tier is None or len(pages_raw) < tier["knowledge_pages"][1]):
        return None  # nothing publishable until more ranges are parsed
    pages_raw = [html.unescape(p) for p in pages_raw]
    boilerplate = repeated_lines(pages_raw)  # before inlining: descriptions repeat with their images
    captions = load_captions(doc_dir)
    pages_raw = [inline_captions(p, captions.get(n, [])) for n, p in enumerate(pages_raw, 1)]
    emitted: set[str] = set()

    md_parts: list[str] = []
    text_parts: list[str] = []
    all_tables: list[dict] = []
    reports: list[PageReport] = []
    for n, raw in enumerate(pages_raw, 1):
        blocks, tables, report = clean_page(raw, n, boilerplate, emitted)
        reports.append(report)
        all_tables += tables
        md_parts.append(markdown_page(blocks, n, report.language))
        prose = [b for b in blocks if not b.startswith("|")]
        text_parts.append(page_marker(n) + "\n" + "\n".join(b.lstrip("#").strip() for b in prose))

    langs = Counter(r.language for r in reports if r.language not in ("unknown", "mixed"))
    cleaned_text = "\n\n".join(text_parts).strip()
    md_dir = out_root / "cleaned_md"
    md_dir.mkdir(parents=True, exist_ok=True)
    clean_report = {
        "source_file": stem,
        "complete": complete,
        "languages": dict(langs),
        "boilerplate": sorted(boilerplate),
        "pages": [r.__dict__ for r in reports],
        "chars_before": raw_chars,
        "chars_after": len(cleaned_text),
        "outputs": [],
    }
    if tier:
        first, last = tier["knowledge_pages"]
        knowledge = md_parts[first - 1 : last] if last >= first else []
        if knowledge:
            write_md(md_dir / f"{stem}.md", stem, knowledge)
            clean_report["outputs"].append(f"{stem}.md (knowledge pp.{first}-{last})")
        if complete:
            lookup_from = max(last, 0) + 1
            lookup_name = f"{stem} - lookup.{LOOKUP_HINT}.md"
            write_md(md_dir / lookup_name, f"{stem} (lookup tables)", md_parts[lookup_from - 1 :])
            clean_report["outputs"].append(f"{lookup_name} (lookup pp.{lookup_from}-{len(md_parts)})")
    else:
        write_md(md_dir / f"{stem}.md", stem, md_parts)
        clean_report["outputs"].append(f"{stem}.md")
    (doc_dir / "clean_report.json").write_text(json.dumps(clean_report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not complete:
        return clean_report  # the A3 JSON describes the whole document; wait for the full parse

    meta = json.loads((doc_dir / "meta.json").read_text(encoding="utf-8"))
    clean_report["source_file"] = meta["source_file"]
    source = Path(meta["source_path"])
    record = {
        "doc_id": doc_id_for(source),
        "source_file": meta["source_file"],
        "source_type": meta["source_type"],
        "language": langs.most_common(1)[0][0] if langs else "unknown",
        "access_level": meta["access_level"],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cleaned_text": cleaned_text,
        "tables": all_tables,
        "metadata": {
            "total_pages": len(pages_raw),
            "file_size_kb": meta["file_size_kb"],
            "is_corrupted": meta.get("docling_status") != "success" or len(cleaned_text) < 50,
        },
    }
    (out_root / "cleaned_json").mkdir(parents=True, exist_ok=True)
    (out_root / "cleaned_json" / f"{stem}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    clean_report["outputs"].append(f"cleaned_json/{stem}.json")
    (doc_dir / "clean_report.json").write_text(json.dumps(clean_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean_report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="Parsed document folder names (default: all)")
    ap.add_argument("--parsed", type=Path, default=DEFAULT_PARSED)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    dirs = [args.parsed / n for n in args.names] if args.names else sorted(
        d for d in args.parsed.iterdir() if (d / "docling.md").exists() or (d / "parts").exists()
    )
    tiers = load_tiers()
    for d in dirs:
        rep = process(d, args.out, tiers)
        if rep is None:
            print(f"{d.name}: not enough pages parsed yet, skipped")
            continue
        dropped = sum(len(p["dropped"]) for p in rep["pages"])
        joined = sum(len(p["joined"]) for p in rep["pages"])
        state = "" if rep["complete"] else " [PARTIAL parse]"
        print(
            f"{rep['source_file']}{state}: {len(rep['pages'])} pages, languages={rep['languages']}, "
            f"dropped={dropped} lines, joined={joined} OCR splits, "
            f"{rep['chars_before']} -> {rep['chars_after']} chars -> {', '.join(rep['outputs'])}"
        )


if __name__ == "__main__":
    main()
