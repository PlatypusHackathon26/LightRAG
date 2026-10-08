"""DELETE /agent/documents/{id} (denso/gateway/app.py): a real removal, not just the UI row."""

import json
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from app import Settings, create_app  # noqa: E402

SERVERS = ["http://l1", "http://l2", "http://l3"]
USERS = {"tok-admin": {"name": "admin", "level": 3, "can_upload": True},
         "tok-l1": {"name": "uploader", "level": 1, "can_upload": True},
         "tok-op": {"name": "op", "level": 3}}
DOC = {"id": "doc-bht", "file_path": "BHT-M60_Manual_demo_40p.md", "status": "processed",
       "metadata": {"source_file": "BHT-M60_Manual_demo_40p.[native-P!].md"}}


def fake_lightrag(holders: set[str], down: set[str] = frozenset(), busy: bool = False):
    """Servers in `holders` list DOC until it is deleted; `down` servers refuse connections."""
    state = {"docs": {h: [dict(DOC)] for h in holders}, "deletes": []}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in down:
            raise httpx.ConnectError("down", request=request)
        if request.url.path == "/documents/paginated":
            return httpx.Response(200, json={"documents": state["docs"].get(host, []), "pagination": {"has_next": False}})
        if request.url.path == "/documents/delete_document":
            if busy:
                return httpx.Response(200, json={"status": "busy"})
            ids = json.loads(request.content)["doc_ids"]
            assert len(ids) == len(set(ids))
            state["deletes"].append((host, ids))
            state["docs"][host] = []
            return httpx.Response(200, json={"status": "deletion_started"})
        return httpx.Response(404)
    return state, httpx.MockTransport(handler)


def client(tmp_path, transport):
    data = tmp_path / "data"
    settings = Settings(level_servers=SERVERS, users=USERS, actions_log=tmp_path / "a.jsonl",
                        ops_file=tmp_path / "n.json", upload_pipeline=False, data_dir=data)
    return TestClient(create_app(settings, transport=transport)), data


def make_outputs(data: Path) -> None:
    (data / "cleaned_md").mkdir(parents=True)
    (data / "cleaned_md" / "BHT-M60_Manual_demo_40p.md").write_text("x", encoding="utf-8")
    (data / "cleaned_md" / "BHT-M60_Manual_demo_40p.[native-P!].md").write_text("x", encoding="utf-8")
    (data / "parsed" / "BHT-M60_Manual_demo_40p").mkdir(parents=True)
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "BHT-M60_Manual_demo_40p.pdf").write_bytes(b"%PDF")


def test_delete_removes_the_document_from_every_server_holding_it(tmp_path):
    state, transport = fake_lightrag({"l1", "l2"}, down={"l3"})
    tc, data = client(tmp_path, transport)
    make_outputs(data)
    r = tc.delete("/agent/documents/doc-bht", headers={"Authorization": "Bearer tok-admin"})
    assert r.status_code == 200 and r.json()["levels"] == ["level_1", "level_2"]
    assert sorted(h for h, _ in state["deletes"]) == ["l1", "l2"]
    assert not (data / "cleaned_md" / "BHT-M60_Manual_demo_40p.md").exists()
    assert not (data / "parsed" / "BHT-M60_Manual_demo_40p").exists()
    assert (data / "raw" / "BHT-M60_Manual_demo_40p.pdf").exists()  # kept: upload it again to undo


def test_only_uploaders_may_delete(tmp_path):
    _, transport = fake_lightrag({"l1"})
    tc, _ = client(tmp_path, transport)
    assert tc.delete("/agent/documents/doc-bht", headers={"Authorization": "Bearer tok-op"}).status_code == 403
    assert tc.delete("/agent/documents/doc-bht").status_code == 403  # guest


def test_a_document_held_only_above_the_users_level_cannot_be_deleted(tmp_path):
    _, transport = fake_lightrag({"l2", "l3"})  # a level-2 document
    tc, _ = client(tmp_path, transport)
    # A level-1 uploader does not even see it on the level_1 server.
    assert tc.delete("/agent/documents/doc-bht", headers={"Authorization": "Bearer tok-l1"}).status_code == 404


def test_a_busy_knowledge_base_is_reported_and_nothing_is_removed(tmp_path):
    state, transport = fake_lightrag({"l1"}, busy=True)
    tc, data = client(tmp_path, transport)
    make_outputs(data)
    r = tc.delete("/agent/documents/doc-bht", headers={"Authorization": "Bearer tok-admin"})
    assert r.status_code == 409 and "busy" in r.json()["detail"]
    assert (data / "cleaned_md" / "BHT-M60_Manual_demo_40p.md").exists()


def test_an_upload_still_in_the_pipeline_cannot_be_deleted_yet(tmp_path):
    _, transport = fake_lightrag({"l1"})
    tc, _ = client(tmp_path, transport)
    assert tc.delete("/agent/documents/job-abc123", headers={"Authorization": "Bearer tok-admin"}).status_code == 409


def test_a_dot_dot_name_never_reaches_the_data_folder(tmp_path):
    evil = dict(DOC, file_path="..", metadata={"source_file": ".."})
    state = {"docs": [evil]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/documents/paginated":
            return httpx.Response(200, json={"documents": state["docs"], "pagination": {"has_next": False}})
        state["docs"] = []
        return httpx.Response(200, json={"status": "deletion_started"})

    tc, data = client(tmp_path, httpx.MockTransport(handler))
    make_outputs(data)
    tc.delete("/agent/documents/doc-bht", headers={"Authorization": "Bearer tok-admin"})
    assert (data / "raw" / "BHT-M60_Manual_demo_40p.pdf").exists() and (data / "cleaned_md").exists()
