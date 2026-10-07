"""Score vehicle-application (lookup tier) questions end to end through the Agent Gateway.

For each question in denso/data/evaluation/Lookup_10_QA.json it asks POST /agent/chat,
like the UI does, and checks without any judge LLM:
  * facts  - every fact group has at least one accepted part number in the answer
  * page   - a citation points at one of the accepted catalogue pages
  * abstain - for vehicles not in the catalogues, the answer declines

Usage:
    python denso/scripts/eval_lookup.py --name keyword_v1
    python denso/scripts/eval_lookup.py --gateway http://127.0.0.1:9700 --ids L1 L6
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from score_facts import REFUSAL  # noqa: E402

DEFAULT_BENCH = ROOT / "data" / "evaluation" / "Lookup_10_QA.json"
NOT_LISTED = re.compile(r"not (?:listed|found|included|covered|in the catalogue)|no (?:matching|row|entry|listing)|"
                        r"không (?:có|tìm thấy|được liệt kê)", re.IGNORECASE)


def norm(text: str) -> str:
    return re.sub(r"[‐-―−]", "-", text).upper()


def score(q: dict, answer: str, citations: list[dict]) -> dict:
    a = norm(answer)
    if not q["answerable"]:
        declined = bool(REFUSAL.search(answer) or NOT_LISTED.search(answer))
        return {"ok": declined, "facts": None, "page": None, "declined": declined}
    groups = [any(alt.upper() in a for alt in g) for g in q["facts"]]
    pages = {int(p) for c in citations for p in re.findall(r"\d+", str(c.get("pages") or ""))}
    page_ok = bool(pages & set(q["pages"]))
    return {"ok": all(groups) and page_ok, "facts": sum(groups) / len(groups), "page": page_ok,
            "cited_pages": sorted(pages)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", default="http://127.0.0.1:9700")
    ap.add_argument("--name", required=True)
    ap.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    args = ap.parse_args()

    questions = [q for q in json.loads(args.bench.read_text(encoding="utf-8")) if not args.ids or q["id"] in args.ids]
    rows = []
    with httpx.Client(base_url=args.gateway, timeout=400) as client:
        for q in questions:
            t0 = time.time()
            r = client.post("/agent/chat", json={"conversationId": f"eval-{q['id']}-{time.time()}", "message": q["question"]})
            body = r.json() if r.status_code == 200 else {"content": f"HTTP {r.status_code}: {r.text[:200]}", "citations": []}
            s = score(q, body["content"], body.get("citations") or [])
            route = next((e["label"] for e in body.get("events", []) if e.get("type") == "knowledge_retrieved"), "")
            rows.append({**q, **s, "answer": body["content"], "seconds": round(time.time() - t0, 1), "route": route})
            print(f"{q['id']:>4} {'OK ' if s['ok'] else 'BAD'} facts={s['facts']} page={s['page']} "
                  f"{rows[-1]['seconds']}s | {route} | {body['content'][:110]!r}", flush=True)

    n = len(rows)
    lines = [f"# Lookup-tier evaluation ({args.name})", "",
             f"Correct (all part numbers + a right page, or a decline when not listed): "
             f"**{sum(r['ok'] for r in rows)}/{n}**", "",
             "| Q | OK | facts | page | s | route | answer |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        ans = r["answer"].replace("\n", " ").replace("|", "/")[:160]
        lines.append(f"| {r['id']} | {'✅' if r['ok'] else '❌'} | {r['facts']} | {r['page']} | {r['seconds']} | {r['route']} | {ans} |")
    report = "\n".join(lines) + "\n"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"lookup_{args.name}.md").write_text(report, encoding="utf-8")
    (args.out / f"lookup_{args.name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
