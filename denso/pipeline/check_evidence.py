"""Check that benchmark evidence survives parsing + cleaning, without any LLM.

For every citation in the benchmark it looks up the cleaned Markdown of the
cited file and measures how many evidence tokens appear on the cited page
(and, as a fallback, anywhere in the document). A citation passes when token
recall on the cited page is >= --threshold.

A failing citation means the answer cannot be retrieved no matter how good the
RAG layer is: either the parser lost it, a cleaning rule dropped it, or the page
numbering is off.

Usage:
    python denso/pipeline/check_evidence.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH = ROOT / "data" / "evaluation" / "Benchmark_30_QA.json"
DEFAULT_MD = ROOT / "data" / "cleaned_md"
PAGE_MARK = re.compile(r"^--- \[Trang (\d+)(?: \|[^\]]*)?\] ---$", re.M)
TOKEN = re.compile(r"\w+", re.UNICODE)


def norm_name(name: str) -> str:
    stem = Path(name.replace("\\", "/")).name.rsplit(".", 1)[0]
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    return TOKEN.findall(text)


def split_pages(md: str) -> dict[int, str]:
    """Map page number -> text. A page's marker repeats after each heading, so join its segments."""
    pages: dict[int, str] = {}
    marks = list(PAGE_MARK.finditer(md))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        n = int(m.group(1))
        pages[n] = pages.get(n, "") + md[m.end() : end]
    return pages


def recall(evidence: str, text: str) -> float:
    ev = tokens(evidence)
    if not ev:
        return 1.0
    have = set(tokens(text))
    return sum(t in have for t in ev) / len(ev)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--md", type=Path, default=DEFAULT_MD)
    ap.add_argument("--threshold", type=float, default=0.8)
    args = ap.parse_args()

    docs = {norm_name(p.name): p for p in args.md.glob("*.md")}
    questions = json.loads(args.bench.read_text(encoding="utf-8"))
    rows, missing_docs = [], set()
    for q in questions:
        for c in q.get("citations", []):
            key = norm_name(c["file"])
            if key not in docs:
                missing_docs.add(c["file"])
                continue
            pages = split_pages(docs[key].read_text(encoding="utf-8"))
            page = c.get("pdf_page")
            on_page = recall(c["evidence"], pages.get(page, "")) if page else 0.0
            anywhere = recall(c["evidence"], "\n".join(pages.values()))
            rows.append((q["id"], c["file"], page, on_page, anywhere, c["evidence"]))

    ok = sum(r[3] >= args.threshold for r in rows)
    print(f"Evidence check: {ok}/{len(rows)} citations found on the cited page (recall >= {args.threshold:.0%})\n")
    for qid, file, page, on_page, anywhere, evidence in rows:
        flag = "ok  " if on_page >= args.threshold else ("PAGE" if anywhere >= args.threshold else "MISS")
        print(f"{flag} Q{qid:<2} p{page!s:<3} page={on_page:4.0%} doc={anywhere:4.0%}  {file[:38]:38}  {evidence[:70]}")
    if missing_docs:
        print("\nNot cleaned yet (skipped):", ", ".join(sorted(missing_docs)))
    sys.exit(0 if ok == len(rows) else 1)


if __name__ == "__main__":
    main()
