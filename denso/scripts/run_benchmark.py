"""Run the 30-question benchmark against a LightRAG server and score it.

Scores: source_hit (a correct file is referenced) and an LLM judge (1 / 0.5 / 0). Results are
cached per question, so an interrupted run resumes; it stops before the free quota runs out.

Usage:
    python denso/scripts/run_benchmark.py --server http://127.0.0.1:9621 --name level_1 --modes naive
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from language import language_instruction  # noqa: E402

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


# Retrieval the level_1_knowledge baseline ran with (before the language reranker).
NO_RERANK = {"enable_rerank": False, "chunk_top_k": 10}


def query(client: httpx.Client, question: str, mode: str, overrides: dict | None = None) -> dict:
    t0 = time.time()
    payload = {"query": question, "mode": mode, "include_references": True}
    # The prompt the Agent Gateway sends, so the benchmark measures what the demo answers.
    instruction = language_instruction(question)
    if instruction:
        payload["user_prompt"] = "\n" + instruction
    r = client.post("/query", json={**payload, **(overrides or {})})
    r.raise_for_status()
    body = r.json()
    return {
        "answer": body.get("response", ""),
        "references": [ref.get("file_path", "") for ref in body.get("references") or []],
        "latency_s": round(time.time() - t0, 1),
        "llm_generated": body.get("llm_generated", True),
    }


class BudgetExhausted(RuntimeError):
    pass


def check_budget(proxy: httpx.Client | None, models: list[str], need: int) -> None:
    """Stop before a model's free daily quota runs out (proxy /budget), instead of scoring failures."""
    if proxy is None:
        return
    b = proxy.get("/budget").json()
    for m in models:
        left = b["budget_per_model"] - b["by_model"].get(m, 0)
        if left < need:
            raise BudgetExhausted(f"{m}: only {left} tokens left today (UTC {b['day']}), need ~{need}")


UNPARSABLE = "judge returned unparsable output"


def judge(client: httpx.Client, model: str, q: dict, answer: str, reasoning: str | None) -> dict:
    prompt = JUDGE_PROMPT.format(
        question=q["question"],
        truth=q["ground_truth_answer"],
        answerable=q.get("answerable_from_documents", True),
        answer=answer,
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        # Reasoning judges (GLM, Nemotron) think before the JSON; 512 cut them off mid-answer.
        "max_completion_tokens": 4096,
    }
    if reasoning:
        body["reasoning_effort"] = reasoning
    r = client.post("/chat/completions", json=body)
    if r.status_code == 429 and "budget" in r.text:
        raise BudgetExhausted(f"judge model {model}: daily token budget spent")
    r.raise_for_status()
    try:
        verdict = parse_verdict(r.json()["choices"][0]["message"]["content"])
        score = float(verdict.get("score", 0))
        if score not in (0.0, 0.5, 1.0):
            score = 0.0
        return {"score": score, "reason": verdict.get("reason", "")}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {"score": 0.0, "reason": UNPARSABLE}


def parse_verdict(text: str) -> dict:
    """The judge's JSON verdict, tolerating code fences or text around it."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start:end + 1])


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


def stop(message: str, results: dict, out_json: Path) -> None:
    done = len(results)
    print(f"\nSTOPPED: {message}\n{done} result(s) are saved in {out_json}; re-running the same command resumes.")
    if "budget" in message:
        print("To continue today: put a new key in .env (EXTRACT_LLM_BINDING_API_KEY), restart the proxy with "
              "--fresh-key, then re-run this command.")
    sys.exit(3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="Label for the result files, e.g. level_1 or level_1_rerank")
    ap.add_argument("--modes", nargs="+", default=["naive", "mix"])
    ap.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--server", default="http://127.0.0.1:9621")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--judge-base", default="http://127.0.0.1:8899/v1", help="OpenAI-compatible endpoint for the judge")
    ap.add_argument("--judge-model", default="qwen-3.8-27b")
    ap.add_argument("--judge-reasoning", default="none", help="reasoning_effort for the judge ('' = omit)")
    ap.add_argument("--proxy", default="http://127.0.0.1:8899", help="llm_rate_proxy base for /budget ('' = no check)")
    ap.add_argument("--answer-model", default="gpt-oss-120b", help="Model LightRAG's QUERY/KEYWORD roles use (budget check)")
    ap.add_argument("--tokens-per-question", type=int, default=25000, help="Budget reserve per question")
    ap.add_argument("--ids", type=int, nargs="*", help="Only run these question ids")
    ap.add_argument("--rejudge-failed", action="store_true",
                    help="Score again the saved answers whose verdict was unparsable (no answering-LLM calls)")
    ap.add_argument("--no-rerank", action="store_true",
                    help="Pin the baseline retrieval (no reranker, chunk_top_k=10) so results stay comparable "
                         "with level_1_knowledge whatever RERANK_BINDING / CHUNK_TOP_K the server has")
    args = ap.parse_args()
    # The /query route substitutes this when the answering LLM returned nothing
    # (timeout, 429, spent budget). PROMPTS["fail_response"] is different: it is
    # LightRAG's deliberate refusal when retrieval finds nothing, a valid answer.
    empty_llm_placeholder = "No relevant context found for the query."

    questions = json.loads(args.bench.read_text(encoding="utf-8"))
    if args.ids:
        questions = [q for q in questions if q["id"] in set(args.ids)]
    args.out.mkdir(parents=True, exist_ok=True)
    out_json = args.out / f"benchmark_{args.name}.json"
    results: dict = json.loads(out_json.read_text(encoding="utf-8")) if out_json.exists() else {}

    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    proxy = httpx.Client(base_url=args.proxy, timeout=30) if args.proxy else None
    with (
        httpx.Client(base_url=args.server, headers=headers, timeout=1800) as client,
        httpx.Client(base_url=args.judge_base, timeout=600) as judge_client,
    ):
        for mode in args.modes:
            for q in questions:
                key = f"{mode}:{q['id']}"
                if key in results and not (args.rejudge_failed and results[key]["judge"]["reason"] == UNPARSABLE):
                    continue
                if key in results:
                    # Only the verdict failed: score the saved answer again, do not re-ask the LLM.
                    results[key]["judge"] = judge(judge_client, args.judge_model, q, results[key]["answer"],
                                                  args.judge_reasoning or None)
                    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"[{mode}] Q{q['id']:>2} rejudged={results[key]['judge']['score']:.1f}")
                    continue
                try:
                    check_budget(proxy, [args.answer_model], args.tokens_per_question)
                    check_budget(proxy, [args.judge_model], 3000)
                except BudgetExhausted as exc:
                    stop(f"Free-tier budget exhausted: {exc}.", results, out_json)
                res = query(client, q["question"], mode, NO_RERANK if args.no_rerank else None)
                if res["answer"].strip() == empty_llm_placeholder:
                    # The LLM call failed or returned nothing: never score it as a wrong answer.
                    stop(f"[{mode}] Q{q['id']}: the answering LLM returned nothing "
                         f"({res['latency_s']}s). Check denso/logs/llm_proxy.jsonl and the server log; "
                         "the question is not saved and will be retried on the next run.", results, out_json)
                cited = {norm_name(c["file"]) for c in q.get("citations", [])}
                got = {norm_name(f) for f in res["references"]}
                res["source_hit"] = bool(cited & got) if cited else None
                try:
                    res["judge"] = judge(judge_client, args.judge_model, q, res["answer"], args.judge_reasoning or None)
                except BudgetExhausted as exc:
                    stop(f"Free-tier budget exhausted: {exc}.", results, out_json)
                res["id"] = q["id"]
                results[key] = res
                out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    f"[{mode}] Q{q['id']:>2} judge={res['judge']['score']:.1f} "
                    f"hit={res['source_hit']} {res['latency_s']}s"
                )

    report = summarize(questions, results, args.modes)
    (args.out / f"benchmark_{args.name}.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
