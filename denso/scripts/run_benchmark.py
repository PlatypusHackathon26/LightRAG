"""Run the DENSO QA benchmark against a LightRAG server and compare query modes.

For every question and mode it records the answer, the referenced files and the
latency, then scores two things:
  * source_hit - at least one ground-truth citation file appears in references
  * judge      - a local Ollama LLM grades the answer vs the ground truth:
                 1.0 correct, 0.5 partially correct, 0.0 wrong
                 (abstention questions are correct when the answer declines)

Results are cached per (mode, id) in the output JSON, so an interrupted run
resumes where it stopped.

Usage:
    python denso/scripts/run_benchmark.py --workspace level_3 --modes naive mix
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH = ROOT / "data" / "evaluation" / "Benchmark_30_QA.json"
DEFAULT_OUT = ROOT / "results"

JUDGE_PROMPT = """You grade answers from a technical document QA system.

Question: {question}
Ground-truth answer: {truth}
Answerable from the documents: {answerable}
System answer: {answer}

Rules:
- If the question is answerable, grade factual agreement with the ground truth.
  Numbers, part numbers, units and ranges must match. Extra correct detail is fine.
- If the question is NOT answerable, the answer is correct only if it says the
  information is not available instead of inventing one.
Reply with JSON only: {{"score": 1 | 0.5 | 0, "reason": "<one short sentence>"}}
score 1 = correct, 0.5 = partially correct or incomplete, 0 = wrong or hallucinated."""


def norm_name(name: str) -> str:
    """Normalize file names so 'AC Compressor Leaflet.pdf' == 'AC_Compressor_Leaflet.pdf'."""
    stem = Path(name.replace("\\", "/")).name.rsplit(".", 1)[0]
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def query(client: httpx.Client, workspace: str, question: str, mode: str) -> dict:
    t0 = time.time()
    r = client.post(
        "/query",
        headers={"LIGHTRAG-WORKSPACE": workspace},
        json={"query": question, "mode": mode, "include_references": True},
    )
    r.raise_for_status()
    body = r.json()
    return {
        "answer": body.get("response", ""),
        "references": [ref.get("file_path", "") for ref in body.get("references") or []],
        "latency_s": round(time.time() - t0, 1),
    }


def judge(ollama: httpx.Client, model: str, q: dict, answer: str) -> dict:
    prompt = JUDGE_PROMPT.format(
        question=q["question"],
        truth=q["ground_truth_answer"],
        answerable=q.get("answerable_from_documents", True),
        answer=answer,
    )
    r = ollama.post(
        "/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "think": False,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 8192},
        },
    )
    r.raise_for_status()
    try:
        verdict = json.loads(r.json()["message"]["content"])
        score = float(verdict.get("score", 0))
        if score not in (0.0, 0.5, 1.0):
            score = 0.0
        return {"score": score, "reason": verdict.get("reason", "")}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {"score": 0.0, "reason": "judge returned unparsable output"}


def summarize(questions: list[dict], results: dict, modes: list[str]) -> str:
    by_id = {q["id"]: q for q in questions}
    lines = ["# DENSO benchmark results", ""]
    lines += ["| Mode | Judge score | Source hit | Avg latency (s) | N |", "|---|---|---|---|---|"]
    per_cat: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for mode in modes:
        rows = [v for k, v in results.items() if k.startswith(f"{mode}:")]
        if not rows:
            continue
        judge_avg = sum(r["judge"]["score"] for r in rows) / len(rows)
        hits = [r["source_hit"] for r in rows if r["source_hit"] is not None]
        hit_rate = sum(hits) / len(hits) if hits else 0.0
        lat = sum(r["latency_s"] for r in rows) / len(rows)
        lines.append(f"| {mode} | {judge_avg:.0%} | {hit_rate:.0%} | {lat:.1f} | {len(rows)} |")
        for r in rows:
            per_cat[by_id[r["id"]]["category"]][mode].append(r["judge"]["score"])
    lines += ["", "## Judge score by category", ""]
    lines += ["| Category | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
    for cat, scores in sorted(per_cat.items()):
        cells = [f"{sum(s) / len(s):.0%} ({len(s)})" if (s := scores.get(m)) else "-" for m in modes]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--modes", nargs="+", default=["naive", "mix"])
    ap.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--server", default="http://127.0.0.1:9621")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--judge-model", default="qwen3:8b")
    ap.add_argument("--ids", type=int, nargs="*", help="Only run these question ids")
    args = ap.parse_args()

    questions = json.loads(args.bench.read_text(encoding="utf-8"))
    if args.ids:
        questions = [q for q in questions if q["id"] in set(args.ids)]
    args.out.mkdir(parents=True, exist_ok=True)
    out_json = args.out / f"benchmark_{args.workspace}.json"
    results: dict = json.loads(out_json.read_text(encoding="utf-8")) if out_json.exists() else {}

    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    with (
        httpx.Client(base_url=args.server, headers=headers, timeout=1800) as client,
        httpx.Client(base_url=args.ollama, timeout=900) as ollama,
    ):
        for mode in args.modes:
            for q in questions:
                key = f"{mode}:{q['id']}"
                if key in results:
                    continue
                res = query(client, args.workspace, q["question"], mode)
                cited = {norm_name(c["file"]) for c in q.get("citations", [])}
                got = {norm_name(f) for f in res["references"]}
                res["source_hit"] = bool(cited & got) if cited else None
                res["judge"] = judge(ollama, args.judge_model, q, res["answer"])
                res["id"] = q["id"]
                results[key] = res
                out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    f"[{mode}] Q{q['id']:>2} judge={res['judge']['score']:.1f} "
                    f"hit={res['source_hit']} {res['latency_s']}s"
                )

    report = summarize(questions, results, args.modes)
    (args.out / f"benchmark_{args.workspace}.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
