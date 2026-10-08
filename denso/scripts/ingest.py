"""Upload cleaned documents to the LightRAG servers of their access level and wait for indexing.

One server per level, cumulative: a level-N document goes to the servers of levels N..3.

Usage:
    python denso/scripts/ingest.py --level 1 denso/data/cleaned_md
    python denso/scripts/ingest.py --server http://127.0.0.1:9621 --replace some.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import httpx

MAX_LEVEL = 3
DEFAULT_SERVERS = "http://127.0.0.1:9621,http://127.0.0.1:9622,http://127.0.0.1:9623"
SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".md", ".txt"}
TERMINAL = {"processed", "failed"}


def level_servers() -> list[str]:
    urls = [u.strip() for u in os.environ.get("DENSO_LEVEL_SERVERS", DEFAULT_SERVERS).split(",") if u.strip()]
    if len(urls) != MAX_LEVEL:
        sys.exit(f"DENSO_LEVEL_SERVERS must list {MAX_LEVEL} URLs, got {len(urls)}")
    return urls


def collect_files(paths: list[str], include_lookup: bool) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(f"Not found: {p}")
    if not include_lookup:
        files = [f for f in files if " - lookup." not in f.name]
    return files


def upload(client: httpx.Client, path: Path) -> str:
    with path.open("rb") as fh:
        r = client.post("/documents/upload", files={"file": (path.name, fh)})
    r.raise_for_status()
    body = r.json()
    print(f"  {path.name}: {body.get('status')} - {body.get('message')}")
    return body["track_id"]


def doc_ids_by_name(client: httpx.Client) -> dict[str, list[str]]:
    """file name -> document ids currently on the server."""
    out: dict[str, list[str]] = {}
    page = 1
    while True:
        r = client.post("/documents/paginated", json={"page": page, "page_size": 100})
        r.raise_for_status()
        body = r.json()
        for d in body.get("documents", []):
            # file_path is the canonical name ("x - images.md", parser hint stripped); the uploaded
            # name ("x - images.[native-P!].md") is kept in metadata.source_file.
            names = {Path(d.get("file_path") or "").name, (d.get("metadata") or {}).get("source_file") or ""}
            for name in names - {""}:
                out.setdefault(name, []).append(d["id"])
        if page >= (body.get("pagination") or {}).get("total_pages", 1):
            return out
        page += 1


def delete_existing(client: httpx.Client, names: list[str], poll: float) -> None:
    """Delete the server's copies of these files and wait until they are gone (for --replace)."""
    # Also the canonical name: "x.[native-P!].md" and an earlier "x.md" are the same document to LightRAG.
    names = list(dict.fromkeys([*names, *(re.sub(r"\.\[[^\]]*\](?=\.[^.]+$)", "", n) for n in names)]))
    found = doc_ids_by_name(client)
    # One document is listed under both its canonical and its uploaded name: dedupe, LightRAG
    # refuses a delete with repeated ids (422 "Document IDs must be unique").
    ids = list(dict.fromkeys(i for n in names for i in found.get(n, [])))
    if not ids:
        return
    r = client.request("DELETE", "/documents/delete_document", json={"doc_ids": ids, "delete_file": False})
    r.raise_for_status()
    print(f"  deleting {len(ids)} existing document(s): {r.json().get('status')}")
    while any(i for n in names for i in doc_ids_by_name(client).get(n, [])):
        time.sleep(poll)


def wait(client: httpx.Client, track_ids: dict[str, str], poll: float) -> int:
    pending = dict(track_ids)
    failed = 0
    started = time.time()
    while pending:
        time.sleep(poll)
        for name, tid in list(pending.items()):
            r = client.get(f"/documents/track_status/{tid}")
            r.raise_for_status()
            docs = r.json().get("documents", [])
            if docs and {d["status"] for d in docs} <= TERMINAL:
                for d in docs:
                    if d["status"] == "failed":
                        failed += 1
                        print(f"  FAILED {name}: {d.get('error_msg')}")
                    else:
                        print(f"  done   {name} ({d.get('chunks_count')} chunks)")
                del pending[name]
        if pending:
            print(f"  ... {len(pending)} still processing ({(time.time() - started) / 60:.1f} min elapsed)", flush=True)
    return failed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="Files or directories to upload")
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--level", type=int, choices=range(1, MAX_LEVEL + 1), help="Access level of the documents")
    target.add_argument("--server", help="Upload to this single server only")
    ap.add_argument("--include-lookup", action="store_true", help="Also upload '<doc> - lookup.[native-P!].md' files")
    ap.add_argument("--api-key", default=None, help="LIGHTRAG_API_KEY if the servers require one")
    ap.add_argument("--poll", type=float, default=30.0, help="Seconds between status polls")
    ap.add_argument("--no-wait", action="store_true", help="Upload only, do not wait for indexing")
    ap.add_argument("--replace", action="store_true",
                    help="Delete documents with the same file name first (an updated file is otherwise a duplicate)")
    args = ap.parse_args()

    files = collect_files(args.paths, args.include_lookup)
    if not files:
        sys.exit("No supported files found.")
    servers = [args.server] if args.server else level_servers()[args.level - 1 :]
    headers = {"X-API-Key": args.api_key} if args.api_key else {}

    total_failed = 0
    for url in servers:
        with httpx.Client(base_url=url, headers=headers, timeout=120) as client:
            try:
                ws = client.get("/health").json().get("configuration", {}).get("workspace") or "(default)"
            except httpx.HTTPError as exc:
                sys.exit(f"Server {url} is not reachable ({exc}); start it or use --server")
            if args.replace:
                delete_existing(client, [f.name for f in files], min(args.poll, 10))
            print(f"{url} [workspace {ws}]: uploading {len(files)} file(s)")
            track_ids = {f.name: upload(client, f) for f in files}
            if not args.no_wait:
                total_failed += wait(client, track_ids, args.poll)
    sys.exit(1 if total_failed else 0)


if __name__ == "__main__":
    main()
