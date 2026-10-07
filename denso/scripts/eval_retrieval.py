"""Retrieval-only evaluation: does LightRAG fetch the evidence chunk at all?

For every answerable benchmark question it calls /query/data (naive mode =
embedding search only, no LLM tokens) and finds the first rank at which a
retrieved chunk comes from the cited file AND contains the citation's evidence
(token recall >= --min-recall). Reports hit@k and lists the misses with what
was retrieved instead, which separates "retrieval missed it" from "the LLM
answered badly".

Usage:
    python denso/scripts/eval_retrieval.py --server http://127.0.0.1:9621 --name level_1_knowledge
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from check_evidence import norm_name, recall  # noqa: E402

DEFAULT_BENCH = ROOT / "data" / "evaluation" / "Benchmark_30_QA.json"
DEFAULT_OUT = ROOT / "results"
KS = (1, 3, 5, 10, 20)


def first_hit(chunks: list[dict], citation: dict, min_recall: float) -> int | None:
    """1-based rank of the first chunk from the cited file that holds the evidence."""
    want = norm_name(citation["file"])
    for rank, c in enumerate(chunks, 1):
        if norm_name(c.get("file_path", "")) == want and recall(citation["evidence"], c.get("content", "")) >= min_recall:
            return rank
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:9621")
    ap.add_argument("--name", required=True, help="Label for the result files")
    ap.add_argument("--mode", default="naive", help="naive needs no LLM; other modes spend keyword-extraction tokens")
    ap.add_argument("--top-k", type=int, default=max(KS))
    ap.add_argument("--min-recall", type=float, default=0.6, help="Evidence token recall needed inside one chunk")
    ap.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    questions = [q for q in json.loads(args.bench.read_text(encoding="utf-8")) if q.get("answerable_from_documents", True)]
    rows = []
    with httpx.Client(base_url=args.server, timeout=300) as client:
        for q in questions:
            r = client.post("/query/data", json={"query": q["question"], "mode": args.mode, "chunk_top_k": args.top_k})
            r.raise_for_status()
            chunks = (r.json().get("data") or {}).get("chunks") or []
            ranks = [first_hit(chunks, c, args.min_recall) for c in q["citations"]]
            found = [x for x in ranks if x is not None]
            rows.append({
                "id": q["id"], "category": q["category"], "citations": len(ranks), "ranks": ranks,
                "best": min(found) if found else None,  # any citation retrieved
                "all": max(ranks) if found and len(found) == len(ranks) else None,  # every citation retrieved
                "top3_files": [c.get("file_path", "")[:45] for c in chunks[:3]],
            })
            print(f"Q{q['id']:<2} ranks={ranks}", flush=True)

    def rate(key: str, k: int, subset: list[dict]) -> float:
        return sum(1 for x in subset if x[key] is not None and x[key] <= k) / len(subset)

    lines = [f"# Retrieval evaluation ({args.name}, mode={args.mode}, min evidence recall {args.min_recall:.0%})", "",
             "| | " + " | ".join(f"hit@{k}" for k in KS) + " |", "|---|" + "---|" * len(KS)]
    lines.append("| any citation | " + " | ".join(f"{rate('best', k, rows):.0%}" for k in KS) + " |")
    lines.append("| all citations | " + " | ".join(f"{rate('all', k, rows):.0%}" for k in KS) + " |")
    cats: dict[str, list[dict]] = defaultdict(list)
    for x in rows:
        cats[x["category"]].append(x)
    lines += ["", "## hit@10 (any citation) by category", "", "| Category | hit@10 | N |", "|---|---|---|"]
    for cat, sub in sorted(cats.items()):
        lines.append(f"| {cat} | {rate('best', 10, sub):.0%} | {len(sub)} |")
    lines += ["", "## Not retrieved within top 10", ""]
    for x in rows:
        if x["best"] is None or x["best"] > 10:
            lines.append(f"- Q{x['id']} ({x['category']}): ranks {x['ranks']}; top-3 retrieved: {x['top3_files']}")
    args.out.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines) + "\n"
    (args.out / f"retrieval_{args.name}_{args.mode}.md").write_text(report, encoding="utf-8")
    (args.out / f"retrieval_{args.name}_{args.mode}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
