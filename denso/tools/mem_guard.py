"""Memory guard for long local runs (benchmark, ingest) on the 16 GB laptop.

Two jobs:

1. Black box. Every sample goes to denso/logs/mem_guard.jsonl (fsynced), so
   after a sudden power-off the last lines show whether RAM, CPU or the
   pagefile was the problem - the Windows event log records none of that for a
   hard power-off.
2. Brake. When available RAM drops it frees memory in escalating steps, never
   touching the user's own apps:
     < --unload-gb    unload every Ollama model (they reload on the next call)
     < --kill-gb      (two samples in a row) terminate resumable DENSO jobs
                      whose command line matches --kill (benchmark, ingest,
                      evals); every one of them resumes or can be re-run

Run it before any heavy job and leave it running:
    python denso/tools/mem_guard.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "logs" / "mem_guard.jsonl"
DEFAULT_KILL = ["run_benchmark.py", "eval_rerank.py", "eval_retrieval.py", "ingest.py", "live_check.py", "ollama_probe.py"]
GB = 1024 ** 3


@dataclass
class GuardState:
    low_streak: int = 0
    unloaded_at: float = 0.0
    killed: list[int] = field(default_factory=list)


def decide(available_gb: float, state: GuardState, unload_gb: float, kill_gb: float,
           now: float, unload_cooldown: float = 60.0) -> list[str]:
    """Pure decision step: which actions to take for this sample."""
    actions = []
    state.low_streak = state.low_streak + 1 if available_gb < kill_gb else 0
    if available_gb < unload_gb and now - state.unloaded_at >= unload_cooldown:
        actions.append("unload_ollama")
        state.unloaded_at = now
    if state.low_streak >= 2:
        actions.append("kill_jobs")
        state.low_streak = 0
    return actions


def unload_ollama(host: str) -> list[str]:
    try:
        with httpx.Client(base_url=host, timeout=10) as c:
            models = [m["name"] for m in c.get("/api/ps").json().get("models", [])]
            for m in models:
                c.post("/api/generate", json={"model": m, "keep_alive": 0})
            return models
    except httpx.HTTPError:
        return []


def matching_jobs(patterns: list[str]) -> list[psutil.Process]:
    me = os.getpid()
    jobs = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if p.info["pid"] != me and "mem_guard" not in cmd and any(pat in cmd for pat in patterns):
            jobs.append(p)
    return jobs


def top_processes(n: int = 5) -> list[list]:
    rows = []
    for p in psutil.process_iter(["name", "memory_info"]):
        mi = p.info.get("memory_info")
        if mi:
            rows.append((p.info["name"], mi.rss))
    totals: dict[str, int] = {}
    for name, rss in rows:
        totals[name] = totals.get(name, 0) + rss
    return [[k, round(v / GB, 2)] for k, v in sorted(totals.items(), key=lambda x: -x[1])[:n]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--unload-gb", type=float, default=1.5, help="Unload Ollama models below this much available RAM")
    ap.add_argument("--kill-gb", type=float, default=0.8, help="Terminate DENSO jobs below this (2 samples in a row)")
    ap.add_argument("--kill", nargs="*", default=DEFAULT_KILL, help="Command-line substrings of killable jobs")
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = ap.parse_args()

    args.log.parent.mkdir(parents=True, exist_ok=True)
    state = GuardState()
    psutil.cpu_percent()
    last_full = 0.0
    with open(args.log, "a", encoding="utf-8") as log:
        def write(rec: dict) -> None:
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()
            os.fsync(log.fileno())

        write({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "start", "unload_gb": args.unload_gb,
               "kill_gb": args.kill_gb})
        while True:
            vm, sw, now = psutil.virtual_memory(), psutil.swap_memory(), time.time()
            avail = vm.available / GB
            rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "avail_gb": round(avail, 2), "ram_pct": vm.percent,
                   "pagefile_pct": sw.percent, "cpu_pct": psutil.cpu_percent()}
            for action in decide(avail, state, args.unload_gb, args.kill_gb, now):
                if action == "unload_ollama":
                    rec["unloaded"] = unload_ollama(args.ollama)
                elif action == "kill_jobs":
                    jobs = matching_jobs(args.kill)
                    for j in jobs:
                        try:
                            j.terminate()
                        except psutil.Error:
                            pass
                    rec["killed"] = [" ".join(j.cmdline()[-3:]) if j.is_running() else j.pid for j in jobs]
            # Full record (with the heaviest apps) every minute, and on every sample once RAM is tight.
            if avail < args.unload_gb * 2 or "unloaded" in rec or "killed" in rec or now - last_full >= 60:
                rec["top"] = top_processes()
                write(rec)
                last_full = now
                if avail < args.unload_gb * 2:
                    print(f"{rec['ts']} LOW RAM {avail:.1f} GB available {rec.get('unloaded', '')} {rec.get('killed', '')}",
                          flush=True)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
