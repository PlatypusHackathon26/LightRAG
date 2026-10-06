"""Upload documents to a running LightRAG server and wait until they are indexed.

Access levels map to cumulative workspaces: a level-N document is uploaded to
workspaces level_N .. level_3, so a user cleared for level K queries only
workspace level_K and never sees documents above K.

Usage:
    python denso/scripts/ingest.py --level 1 denso/data/raw
    python denso/scripts/ingest.py --workspace bench denso/data/raw/*.pdf
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

MAX_LEVEL = 3
SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".md", ".txt"}
TERMINAL = {"processed", "failed"}


def collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(f"Not found: {p}")
    return files


def upload(client: httpx.Client, workspace: str, path: Path) -> str:
    with path.open("rb") as fh:
        r = client.post(
            "/documents/upload",
            headers={"LIGHTRAG-WORKSPACE": workspace},
            files={"file": (path.name, fh)},
        )
    r.raise_for_status()
    body = r.json()
    print(f"  [{workspace}] {path.name}: {body.get('status')} - {body.get('message')}")
    return body["track_id"]


def wait(client: httpx.Client, workspace: str, track_ids: dict[str, str], poll: float) -> int:
    pending = dict(track_ids)
    failed = 0
    started = time.time()
    while pending:
        time.sleep(poll)
        for name, tid in list(pending.items()):
            r = client.get(
                f"/documents/track_status/{tid}",
                headers={"LIGHTRAG-WORKSPACE": workspace},
            )
            r.raise_for_status()
            docs = r.json().get("documents", [])
            statuses = {d["status"] for d in docs}
            if docs and statuses <= TERMINAL:
                for d in docs:
                    if d["status"] == "failed":
                        failed += 1
                        print(f"  FAILED {name}: {d.get('error_msg')}")
                    else:
                        print(f"  done   {name} ({d.get('chunks_count')} chunks)")
                del pending[name]
        if pending:
            mins = (time.time() - started) / 60
            print(f"  ... {len(pending)} still processing ({mins:.1f} min elapsed)")
    return failed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="Files or directories to upload")
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--level", type=int, choices=range(1, MAX_LEVEL + 1), help="Access level of the documents")
    target.add_argument("--workspace", help="Upload to a single explicit workspace")
    ap.add_argument("--server", default="http://127.0.0.1:9621")
    ap.add_argument("--api-key", default=None, help="LIGHTRAG_API_KEY if the server requires one")
    ap.add_argument("--poll", type=float, default=30.0, help="Seconds between status polls")
    ap.add_argument("--no-wait", action="store_true", help="Upload only, do not wait for indexing")
    args = ap.parse_args()

    files = collect_files(args.paths)
    if not files:
        sys.exit("No supported files found.")
    workspaces = (
        [args.workspace]
        if args.workspace
        else [f"level_{n}" for n in range(args.level, MAX_LEVEL + 1)]
    )
    headers = {"X-API-Key": args.api_key} if args.api_key else {}

    total_failed = 0
    with httpx.Client(base_url=args.server, headers=headers, timeout=120) as client:
        for ws in workspaces:
            print(f"Workspace {ws}: uploading {len(files)} file(s)")
            track_ids = {f.name: upload(client, ws, f) for f in files}
            if not args.no_wait:
                total_failed += wait(client, ws, track_ids, args.poll)
    sys.exit(1 if total_failed else 0)


if __name__ == "__main__":
    main()
