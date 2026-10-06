"""Find duplicated content in the cleaned Markdown (no LLM).

Two signals, both within a document and across documents:
  * exact duplicate paragraphs/table rows after normalisation (>= --min-chars)
  * near-duplicate pages: Jaccard similarity of 8-word shingles >= --page-sim

Duplicates waste qwen3 extraction time and crowd the retrieval top-k with
copies of the same text. This script only reports; clean.py decides what to drop.

Usage:
    python denso/pipeline/find_duplicates.py
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_evidence import split_pages, tokens  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MD = ROOT / "data" / "cleaned_md"
MARKER = re.compile(r"^--- \[Trang .*\] ---$")


def paragraphs(page_text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", page_text):
        block = block.strip()
        if not block or MARKER.match(block) or block.startswith("#"):
            continue
        out.append(block)
    return out


def norm(text: str) -> str:
    return " ".join(tokens(text))


def shingles(text: str, k: int = 8) -> set[tuple[str, ...]]:
    t = tokens(text)
    return {tuple(t[i : i + k]) for i in range(max(0, len(t) - k + 1))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--md", type=Path, default=DEFAULT_MD)
    ap.add_argument("--min-chars", type=int, default=80, help="Ignore paragraphs shorter than this")
    ap.add_argument("--page-sim", type=float, default=0.8)
    ap.add_argument("--include-lookup", action="store_true", help="Also scan '- lookup' files (slow)")
    args = ap.parse_args()

    files = [f for f in sorted(args.md.glob("*.md")) if args.include_lookup or " - lookup." not in f.name]
    para_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
    page_shingles: dict[tuple[str, int], set] = {}
    total_chars = 0
    for f in files:
        pages = split_pages(f.read_text(encoding="utf-8"))
        for n, text in pages.items():
            page_shingles[(f.stem, n)] = shingles(text)
            for p in paragraphs(text):
                if len(p) >= args.min_chars:
                    para_index[norm(p)].append((f.stem, n))
                    total_chars += len(p)

    dups = {k: v for k, v in para_index.items() if len(v) > 1}
    wasted = sum(len(k) * (len(v) - 1) for k, v in dups.items())
    print(f"Exact duplicate paragraphs: {len(dups)} distinct, {sum(len(v) - 1 for v in dups.values())} extra copies, "
          f"~{wasted} chars ({wasted / max(total_chars, 1):.1%} of paragraph text)")
    for k, v in sorted(dups.items(), key=lambda kv: -len(kv[0]) * (len(kv[1]) - 1))[:12]:
        where = ", ".join(f"{d[:18]} p{n}" for d, n in v[:4]) + (" ..." if len(v) > 4 else "")
        print(f"  x{len(v)} {len(k):5} chars  [{where}]  {k[:70]}")

    print(f"\nNear-duplicate pages (shingle Jaccard >= {args.page_sim:.0%}):")
    keys = [k for k, s in page_shingles.items() if len(s) >= 20]
    found = 0
    for a, b in combinations(keys, 2):
        sa, sb = page_shingles[a], page_shingles[b]
        # cheap size filter before the full Jaccard
        if min(len(sa), len(sb)) / max(len(sa), len(sb)) < args.page_sim:
            continue
        j = len(sa & sb) / len(sa | sb)
        if j >= args.page_sim:
            found += 1
            print(f"  {j:.0%}  {a[0][:30]} p{a[1]}  ~  {b[0][:30]} p{b[1]}")
    if not found:
        print("  none")


if __name__ == "__main__":
    main()
