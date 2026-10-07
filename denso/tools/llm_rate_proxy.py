"""Local rate-limiting proxy for a free-tier OpenAI-compatible API (e.g. Cerebras).

LightRAG retries a 429 only 3 times with a 4-10 s back-off, which is not
enough against a 5 requests/minute free tier: chunks run out of retries and
whole documents end up FAILED. This proxy sits between LightRAG and the API:

  * spaces request starts to stay under --rpm and an estimated --tpm budget
  * on 429 waits (Retry-After header, else 20 s) and retries, up to --retries
  * injects the upstream API key from .env (EXTRACT_LLM_BINDING_API_KEY), so
    LightRAG can send any placeholder key
  * appends one JSON line per call to --log (tokens, status, running totals)
  * tracks the daily token budget PER MODEL (free quotas are per model); once
    the requested model's --daily-token-budget is spent it switches to
    --fallback-model (with --fallback-reasoning), and refuses calls (HTTP 429)
    only when the fallback is spent too, so the free quota is never exceeded

Point the LightRAG EXTRACT role at it:
    EXTRACT_LLM_BINDING=openai
    EXTRACT_LLM_BINDING_HOST=http://127.0.0.1:8899/v1

Run:
    python denso/tools/llm_rate_proxy.py --upstream https://api.cerebras.ai/v1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn
from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

REPO = Path(__file__).resolve().parents[2]


class Pacer:
    """Allow a request start only when both the RPM and the token-per-minute budgets permit."""

    def __init__(self, rpm: int, tpm: int) -> None:
        self.min_interval = 60.0 / rpm
        self.tpm = tpm
        self.lock = asyncio.Lock()
        self.last_start = 0.0
        self.window: list[tuple[float, int]] = []  # (time, estimated tokens)

    async def acquire(self, est_tokens: int) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                self.window = [(t, n) for t, n in self.window if now - t < 60]
                wait_rpm = self.last_start + self.min_interval - now
                used = sum(n for _, n in self.window)
                wait_tpm = (self.window[0][0] + 60 - now) if self.window and used + est_tokens > self.tpm else 0
                wait = max(wait_rpm, wait_tpm, 0)
                if wait <= 0:
                    self.last_start = now
                    self.window.append((now, est_tokens))
                    return
                await asyncio.sleep(wait)


def build_app(args: argparse.Namespace) -> FastAPI:
    key = dotenv_values(REPO / ".env").get(args.key_var) or ""
    if not key:
        raise SystemExit(f"{args.key_var} is not set in {REPO / '.env'}")
    app = FastAPI()
    pacer = Pacer(args.rpm, args.tpm)
    client = httpx.AsyncClient(base_url=args.upstream.rstrip("/"), timeout=httpx.Timeout(600, connect=20))
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    state = {"day": datetime.now(timezone.utc).date().isoformat(), "tokens": 0, "calls": 0, "by_model": {}}

    # Resume today's running total after a restart. A "fresh_key" marker (written
    # by --fresh-key when the API key was replaced) resets the count from there on.
    if args.fresh_key:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "fresh_key", "day": state["day"],
                                 "ts": datetime.now(timezone.utc).isoformat()}) + "\n")
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") == "fresh_key" and row.get("day") == state["day"]:
                state.update(tokens=0, calls=0, by_model={})
                continue
            if row.get("event") == "upstream_quota_spent" and row.get("day") == state["day"]:
                state["by_model"][row.get("model")] = args.daily_token_budget
                continue
            if row.get("day") == state["day"] and row.get("status") == 200:
                state["tokens"] = max(state["tokens"], row.get("day_tokens", 0))
                state["calls"] += 1
                m = row.get("model")
                state["by_model"][m] = state["by_model"].get(m, 0) + (row.get("prompt_tokens") or 0) + (row.get("completion_tokens") or 0)

    def log(row: dict) -> None:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    @app.get("/budget")
    async def budget() -> dict:
        """Today's (UTC) usage per model, so callers can stop before the quota runs out."""
        today = datetime.now(timezone.utc).date().isoformat()
        by_model = state["by_model"] if state["day"] == today else {}
        return {"day": today, "budget_per_model": args.daily_token_budget, "by_model": by_model,
                "fallback_model": args.fallback_model or None}

    @app.get("/v1/models")
    async def models() -> Response:
        r = await client.get("/models", headers={"Authorization": f"Bearer {key}"})
        return Response(r.content, status_code=r.status_code, media_type="application/json")

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        body = await request.json()
        if body.get("stream"):
            return JSONResponse({"error": "streaming is not supported by this proxy"}, status_code=400)
        today = datetime.now(timezone.utc).date().isoformat()
        if today != state["day"]:
            state.update(day=today, tokens=0, calls=0, by_model={})
        fallback_used = False
        if state["by_model"].get(body.get("model"), 0) >= args.daily_token_budget:
            fb = args.fallback_model
            if not fb or state["by_model"].get(fb, 0) >= args.daily_token_budget:
                return JSONResponse(
                    {"error": {"message": f"daily token budget {args.daily_token_budget} spent", "type": "budget"}},
                    status_code=429,
                )
            body["model"] = fb
            if args.fallback_reasoning:
                body["reasoning_effort"] = args.fallback_reasoning
            fallback_used = True
        prompt_chars = sum(len(str(m.get("content", ""))) for m in body.get("messages", []))
        est = prompt_chars // 3 + int(body.get("max_completion_tokens") or body.get("max_tokens") or 4000) // 2
        for attempt in range(1, args.retries + 1):
            await pacer.acquire(est)
            t0 = time.time()
            r = await client.post("/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
            if r.status_code != 429:
                break
            wait = float(r.headers.get("retry-after") or 20)
            log({"ts": datetime.now(timezone.utc).isoformat(), "status": 429, "attempt": attempt, "wait": wait})
            if wait > args.max_wait:
                # A long Retry-After (Cerebras sends 86400 s) means the upstream quota is spent,
                # whatever our own counter says: mark the model spent and fail fast instead of
                # sleeping for a day while every client times out.
                state["by_model"][body.get("model")] = args.daily_token_budget
                log({"ts": datetime.now(timezone.utc).isoformat(), "event": "upstream_quota_spent",
                     "model": body.get("model"), "retry_after": wait, "day": state["day"]})
                return JSONResponse(
                    {"error": {"message": f"upstream daily quota spent for {body.get('model')} "
                                          f"(Retry-After {wait:.0f}s); daily token budget spent", "type": "budget"}},
                    status_code=429,
                )
            await asyncio.sleep(wait)
        usage = {}
        if r.status_code == 200:
            usage = r.json().get("usage") or {}
            used = int(usage.get("total_tokens") or 0)
            state["tokens"] += used
            state["calls"] += 1
            state["by_model"][body.get("model")] = state["by_model"].get(body.get("model"), 0) + used
        log({
            "ts": datetime.now(timezone.utc).isoformat(), "day": state["day"], "status": r.status_code,
            "model": body.get("model"), "seconds": round(time.time() - t0, 1),
            "req_max_tokens": body.get("max_completion_tokens") or body.get("max_tokens"),
            "req_reasoning": body.get("reasoning_effort"), "req_format": (body.get("response_format") or {}).get("type"),
            "finish": ((r.json().get("choices") or [{}])[0].get("finish_reason") if r.status_code == 200 else None),
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "day_tokens": state["tokens"], "day_calls": state["calls"], "fallback": fallback_used,
            "model_day_tokens": state["by_model"].get(body.get("model"), 0),
        })
        return Response(r.content, status_code=r.status_code, media_type="application/json")

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", default="https://api.cerebras.ai/v1")
    ap.add_argument("--key-var", default="EXTRACT_LLM_BINDING_API_KEY")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside a container only")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--rpm", type=int, default=4, help="Request starts per minute (Cerebras free: 5)")
    ap.add_argument("--tpm", type=int, default=28000, help="Estimated tokens per minute (Cerebras free: 30K uncached)")
    ap.add_argument("--retries", type=int, default=8)
    ap.add_argument("--daily-token-budget", type=int, default=950_000, help="Per-model stop before the 1M/day free quota")
    ap.add_argument("--fallback-model", default="qwen-3.8-27b", help="Model to use once the requested one is spent ('' = none)")
    ap.add_argument("--fallback-reasoning", default="none", help="reasoning_effort for the fallback model ('' = keep)")
    ap.add_argument("--log", default=str(REPO / "denso" / "logs" / "llm_proxy.jsonl"))
    ap.add_argument("--fresh-key", action="store_true", help="The API key was replaced: start today's budget from zero")
    ap.add_argument("--max-wait", type=float, default=300,
                    help="A 429 asking to wait longer than this (s) means the upstream quota is spent")
    args = ap.parse_args()
    uvicorn.run(build_app(args), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
