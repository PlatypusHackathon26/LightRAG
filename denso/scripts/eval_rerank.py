"""Offline re-ranking experiment on top of LightRAG's naive retrieval (no LLM tokens).

For each answerable benchmark question it fetches a deep candidate pool from
/query/data (naive), then re-orders it with several strategies and measures
hit@k exactly like eval_retrieval.py:

  baseline     LightRAG's own vector order
  lang         stable re-order: chunks whose page language matches the
               question's language first (the cleaned Markdown tags every page
               with "ngôn ngữ: xx")
  rerank       a cross-encoder (Infinity /rerank, Cohere-compatible) scores
               every candidate
  rerank+lang  rerank order, then language-matching chunks first
  lang-pref    the deployed service (denso/tools/lang_rerank.py): like "lang",
               but questions about another language keep the vector order

Nothing on the LightRAG servers changes, so it can run next to a benchmark.

Usage:
    python denso/scripts/eval_rerank.py --name level_1_knowledge --strategies baseline lang
    python denso/scripts/eval_rerank.py --name level_1_knowledge --reranker http://127.0.0.1:7997
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
from langdetect import DetectorFactory, LangDetectException, detect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from eval_retrieval import first_hit  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
import lang_rerank  # noqa: E402

DetectorFactory.seed = 0
DEFAULT_BENCH = ROOT / "data" / "evaluation" / "Benchmark_30_QA.json"
DEFAULT_OUT = ROOT / "results"
KS = (1, 3, 5, 10)
CHUNK_LANG = re.compile(r"ngôn ngữ: (\w+)")


def chunk_language(content: str) -> str | None:
    langs = Counter(CHUNK_LANG.findall(content))
    return langs.most_common(1)[0][0] if langs else None


def question_language(question: str) -> str:
    try:
        return detect(question)
    except LangDetectException:
        return "en"


def by_language(chunks: list[dict], lang: str) -> list[dict]:
    # Stable: keeps the incoming order inside each group. Unknown-language chunks stay with the matches.
    return sorted(chunks, key=lambda c: chunk_language(c.get("content", "")) not in (lang, None))


def rerank(client: httpx.Client, model: str, question: str, chunks: list[dict], max_chars: int) -> list[dict]:
    docs = [c.get("content", "")[:max_chars] for c in chunks]
    r = client.post("/rerank", json={"model": model, "query": question, "documents": docs, "top_n": len(docs)})
    r.raise_for_status()
    order = [x["index"] for x in sorted(r.json()["results"], key=lambda x: -x["relevance_score"])]
    return [chunks[i] for i in order]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:9621")
    ap.add_argument("--name", required=True)
    ap.add_argument("--pool", type=int, default=40, help="Candidates fetched from LightRAG and re-ordered")
    ap.add_argument("--pool-tokens", type=int, default=200_000,
                    help="max_total_tokens for the candidate request; the server's MAX_TOTAL_TOKENS would cap the pool")
    ap.add_argument("--strategies", nargs="+", default=["baseline", "lang", "rerank", "rerank+lang"])
    ap.add_argument("--reranker", default="http://127.0.0.1:7997")
    ap.add_argument("--rerank-model", default="BAAI/bge-reranker-v2-m3")
    ap.add_argument("--max-chars", type=int, default=4000, help="Truncate candidates sent to the cross-encoder")
    ap.add_argument("--min-recall", type=float, default=0.6)
    ap.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    questions = [q for q in json.loads(args.bench.read_text(encoding="utf-8")) if q.get("answerable_from_documents", True)]
    ranks: dict[str, dict[int, tuple]] = {s: {} for s in args.strategies}
    seconds: dict[str, float] = {s: 0.0 for s in args.strategies}
    with httpx.Client(base_url=args.server, timeout=300) as lr, httpx.Client(base_url=args.reranker, timeout=900) as rr:
        for q in questions:
            pool = lr.post("/query/data", json={"query": q["question"], "mode": "naive", "chunk_top_k": args.pool,
                                                     "max_total_tokens": args.pool_tokens})
            pool.raise_for_status()
            chunks = (pool.json().get("data") or {}).get("chunks") or []
            lang = question_language(q["question"])
            cache_rr = None
            for s in args.strategies:
                t0 = time.time()
                if s == "baseline":
                    order = chunks
                elif s == "lang":
                    order = by_language(chunks, lang)
                elif s == "lang-pref":
                    order = [chunks[i] for i, _ in lang_rerank.rank(q["question"], [c.get("content", "") for c in chunks])]
                else:
                    cache_rr = cache_rr or rerank(rr, args.rerank_model, q["question"], chunks, args.max_chars)
                    order = by_language(cache_rr, lang) if s == "rerank+lang" else cache_rr
                seconds[s] += time.time() - t0
                ranks[s][q["id"]] = tuple(first_hit(order, c, args.min_recall) for c in q["citations"])
            print(f"Q{q['id']:<2} lang={lang} " + " ".join(f"{s}={list(ranks[s][q['id']])}" for s in args.strategies), flush=True)

    def rate(s: str, k: int, need_all: bool) -> float:
        hits = 0
        for rs in ranks[s].values():
            ok = [r is not None and r <= k for r in rs]
            hits += all(ok) if need_all else any(ok)
        return hits / len(ranks[s])

    lines = [f"# Re-ranking experiment ({args.name}, pool={args.pool}, naive candidates)", "",
             "| Strategy | " + " | ".join(f"hit@{k}" for k in KS) + " | all-citations hit@10 | s/question |",
             "|---|" + "---|" * (len(KS) + 2)]
    for s in args.strategies:
        lines.append(f"| {s} | " + " | ".join(f"{rate(s, k, False):.0%}" for k in KS)
                     + f" | {rate(s, 10, True):.0%} | {seconds[s] / len(questions):.1f} |")
    lines += ["", "## Per question (rank of each citation; - = not in pool)", "",
              "| Q | " + " | ".join(args.strategies) + " |", "|---|" + "---|" * len(args.strategies)]
    for q in questions:
        cells = [",".join("-" if r is None else str(r) for r in ranks[s][q["id"]]) for s in args.strategies]
        lines.append(f"| {q['id']} | " + " | ".join(cells) + " |")
    report = "\n".join(lines) + "\n"
    args.out.mkdir(parents=True, exist_ok=True)
    tag = "_".join(x.replace("+", "").replace("-", "") for x in args.strategies)
    (args.out / f"rerank_{args.name}_{tag}.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
