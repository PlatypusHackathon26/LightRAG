"""Preview how LightRAG will chunk the cleaned Markdown, without any LLM.

Runs the same path as an upload of a cleaned .md file: the `native` parser
writes a sidecar, then the `P` (paragraph semantic) chunker splits it. For
each document it reports chunk count and token sizes, how many chunks carry a
page marker (needed to cite pages), split tables, and an indexing-time
estimate for the knowledge-graph tier.

Usage:
    python denso/pipeline/preview_chunks.py                     # all cleaned_md files
    python denso/pipeline/preview_chunks.py "AC Compressor Leaflet.md" --show 3
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from lightrag.chunker.paragraph_semantic import chunking_by_paragraph_semantic  # noqa: E402
from lightrag.utils import TiktokenTokenizer  # noqa: E402

DEFAULT_MD = REPO / "denso" / "data" / "cleaned_md"
PAGE_MARK = re.compile(r"--- \[Trang (\d+)")
TABLE_PAGE_COL = re.compile(r'format="json">\[\["Trang"')
# Measured on the laptop: qwen3:8b JSON extraction of a ~2000-token chunk took ~150 s.
SECONDS_PER_KG_CHUNK = 150


def parse_native(md: Path, out_dir: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "lightrag.parser.cli", str(md), "--engine", "native", "-o", str(out_dir), "--preview", "0"],
        check=True,
        cwd=REPO,
        capture_output=True,
    )
    return next((out_dir / f"{md.name}.parsed").glob("*.blocks.jsonl"))


def chunk(md: Path, tokenizer, size: int, overlap: int) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        blocks = parse_native(md, Path(tmp))
        content = md.read_text(encoding="utf-8")
        return chunking_by_paragraph_semantic(
            tokenizer, content, size, blocks_path=str(blocks), chunk_overlap_token_size=overlap
        )


def summarize(name: str, chunks: list[dict]) -> dict:
    tokens = [c["tokens"] for c in chunks]
    # Citable = a page marker, or a slice of a large table that carries clean.py's "Trang" column.
    with_page = sum(bool(PAGE_MARK.search(c["content"]) or TABLE_PAGE_COL.search(c["content"])) for c in chunks)
    tables = sum(c["content"].count("<table") for c in chunks)  # native parser renders tables as <table format="json">
    return {
        "file": name,
        "chunks": len(chunks),
        "tokens_total": sum(tokens),
        "tokens_median": int(statistics.median(tokens)) if tokens else 0,
        "tokens_max": max(tokens, default=0),
        "small_chunks_lt_100": sum(t < 100 for t in tokens),
        "chunks_with_page_marker": with_page,
        "table_fragments": tables,
        "kg": "!" not in name,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="cleaned_md file names (default: all)")
    ap.add_argument("--md", type=Path, default=DEFAULT_MD)
    ap.add_argument("--size", type=int, default=2000, help="CHUNK_P_SIZE")
    ap.add_argument("--overlap", type=int, default=100, help="CHUNK_P_OVERLAP_SIZE")
    ap.add_argument("--show", type=int, default=0, help="Print the first N chunks of each file")
    ap.add_argument("--json", type=Path, help="Also write the summary as JSON")
    args = ap.parse_args()

    files = [args.md / f for f in args.files] if args.files else sorted(args.md.glob("*.md"))
    tokenizer = TiktokenTokenizer()
    rows = []
    for md in files:
        chunks = chunk(md, tokenizer, args.size, args.overlap)
        row = summarize(md.name, chunks)
        rows.append(row)
        print(
            f"{row['file'][:60]:60} chunks={row['chunks']:5} tokens={row['tokens_total']:8} "
            f"median={row['tokens_median']:5} max={row['tokens_max']:5} small={row['small_chunks_lt_100']:3} "
            f"page_marked={row['chunks_with_page_marker']}/{row['chunks']} tables={row['table_fragments']}"
        )
        for c in chunks[: args.show]:
            head = c.get("heading") or {}
            print(f"   --- chunk {c['chunk_order_index']} ({c['tokens']} tok) heading={head.get('heading')!r} parents={head.get('parent_headings')}")
            print("   " + c["content"][:500].replace("\n", "\n   "))

    kg = [r for r in rows if r["kg"]]
    kg_chunks = sum(r["chunks"] for r in kg)
    print(
        f"\nKnowledge tier: {kg_chunks} chunks -> ~{kg_chunks * SECONDS_PER_KG_CHUNK / 3600:.1f} h of qwen3 extraction "
        f"(at ~{SECONDS_PER_KG_CHUNK}s/chunk, before gleaning). Lookup tier: {sum(r['chunks'] for r in rows if not r['kg'])} chunks, embeddings only."
    )
    marked = sum(r["chunks_with_page_marker"] for r in rows)
    total = sum(r["chunks"] for r in rows)
    print(f"Chunks that carry a page marker (citable page): {marked}/{total}")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
