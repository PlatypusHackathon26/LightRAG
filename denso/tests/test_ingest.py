"""ingest.py --replace (denso/scripts/ingest.py) against a fake LightRAG server."""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest import delete_existing  # noqa: E402


def test_replace_deletes_each_document_once_under_either_name():
    # Regression (upload job, image pass): the document is listed as "manual.md" (canonical)
    # and "manual.[native-P!].md" (uploaded); both names gave the same id, the delete sent it
    # twice and LightRAG answered 422 "Document IDs must be unique".
    state = {"docs": [{"id": "doc-1", "file_path": "manual.md",
                       "metadata": {"source_file": "manual.[native-P!].md"}}], "deleted": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/documents/paginated":
            return httpx.Response(200, json={"documents": state["docs"], "pagination": {"total_pages": 1}})
        if request.url.path == "/documents/delete_document":
            ids = json.loads(request.content)["doc_ids"]
            if len(ids) != len(set(ids)):
                return httpx.Response(422, json={"detail": "Document IDs must be unique"})
            state["deleted"], state["docs"] = ids, []
            return httpx.Response(200, json={"status": "deletion_started"})
        return httpx.Response(404)

    with httpx.Client(base_url="http://lightrag", transport=httpx.MockTransport(handler)) as client:
        delete_existing(client, ["manual.[native-P!].md"], poll=0)
    assert state["deleted"] == ["doc-1"]


def test_replace_with_nothing_to_delete_is_a_no_op():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"documents": [], "pagination": {"total_pages": 1}})

    with httpx.Client(base_url="http://lightrag", transport=httpx.MockTransport(handler)) as client:
        delete_existing(client, ["new.[native-P!].md"], poll=0)
    assert "/documents/delete_document" not in calls


def _busy_server(busy_times: int):
    state = {"docs": [{"id": "doc-1", "file_path": "manual.md", "metadata": {}}], "busy": busy_times}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/documents/paginated":
            return httpx.Response(200, json={"documents": state["docs"], "pagination": {"total_pages": 1}})
        if state["busy"] > 0:
            state["busy"] -= 1
            return httpx.Response(200, json={"status": "busy"})
        state["docs"] = []
        return httpx.Response(200, json={"status": "deletion_started"})
    return state, httpx.MockTransport(handler)


def test_a_busy_server_is_retried_until_it_deletes():
    state, transport = _busy_server(2)
    with httpx.Client(base_url="http://lightrag", transport=transport) as client:
        delete_existing(client, ["manual.md"], poll=0)
    assert state["docs"] == []


def test_a_server_that_stays_busy_fails_loud_instead_of_hanging():
    # Seen in review: "busy" deleted nothing and the wait for the old copy never ended.
    import pytest

    _, transport = _busy_server(10**6)
    with httpx.Client(base_url="http://lightrag", transport=transport) as client, pytest.raises(SystemExit):
        delete_existing(client, ["manual.md"], poll=0, timeout=0.05)
