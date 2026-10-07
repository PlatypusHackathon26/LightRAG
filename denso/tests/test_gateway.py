"""Gateway tests against a mocked LightRAG backend (no live servers)."""

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from app import (  # noqa: E402
    Settings,
    classify_target,
    clean_answer,
    create_app,
    display_name,
    only_cited,
    strip_reference_section,
    to_citations,
)

BENCH = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "Benchmark_30_QA.json"
SERVERS = ["http://l1", "http://l2", "http://l3"]


def test_display_name_strips_extension_and_lookup_hint():
    assert display_name("Spark Plug Catalogue 2025 - lookup.[native-P!].md") == "Spark Plug Catalogue 2025"
    assert display_name("AC Compressor Leaflet.md") == "AC Compressor Leaflet"


def test_citations_carry_pages_and_excerpt():
    refs = [{
        "reference_id": "1",
        "file_path": "Diesel_SCV Kit_DCRS300260_installation guide (đa ngôn ngữ).md",
        "content": ["--- [Trang 4 | ngôn ngữ: en] ---\n\nFit the bolts and tighten them with 6.9 to 10.8 [Nm].",
                    "--- [Trang 20 | ngôn ngữ: ru] ---\n\nУстановить болты"],
    }]
    (c,) = to_citations(refs)
    assert c["pages"] == "4, 20"
    assert c["documentName"] == "Diesel_SCV Kit_DCRS300260_installation guide (đa ngôn ngữ)"
    assert c["excerpt"].startswith("Fit the bolts and tighten them with 6.9 to 10.8")


def test_reference_block_is_removed_from_answer():
    answer = "Tighten to **6.9 - 10.8 Nm**.\n\n### References\n- [1] Diesel_SCV.md"
    assert strip_reference_section(answer) == "Tighten to **6.9 - 10.8 Nm**."


@pytest.mark.skipif(not BENCH.exists(), reason="benchmark data not present")
def test_every_benchmark_question_routes_to_the_knowledge_tier():
    # Regression: an early version routed any part-number-like token to the lookup
    # tier, which would have sent Q1 (DCRS300260) and Q10 (DCP32045) to the wrong server.
    for q in json.loads(BENCH.read_text(encoding="utf-8")):
        assert classify_target(q["question"]) == "knowledge", q["id"]


@pytest.mark.parametrize("question", [
    "Which DENSO spark plug fits a 2018 Toyota Corolla?",
    "What wiper blade is suitable for my car, a Honda City?",
    "NGK BKR6E cross reference to DENSO",
    "Bugi nào lắp cho xe Vios 2020?",
])
def test_vehicle_application_questions_route_to_lookup(question):
    assert classify_target(question) == "lookup"


@pytest.fixture
def backend():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/query":
            return httpx.Response(200, json={
                "response": "Answer.\n\n### References\n- [1] x.md",
                "references": [{"reference_id": "1", "file_path": "x.md", "content": ["--- [Trang 2] ---\nBody"]}],
                "llm_generated": True,
            })
        if request.url.path == "/documents/upload":
            return httpx.Response(200, json={"status": "success", "track_id": f"t-{request.url.host}"})
        if request.url.path == "/documents/paginated":
            return httpx.Response(200, json={"documents": [{
                "id": "doc-1", "file_path": "WiperBlade-Cat26_Full-Version - lookup.[native-P!].md",
                "status": "processed", "content_length": 1234, "created_at": "2026-10-07T00:00:00Z"}],
                "pagination": {"has_next": False}})
        return httpx.Response(404)

    return calls, httpx.MockTransport(handler)


@pytest.fixture
def client(backend, tmp_path):
    calls, transport = backend
    settings = Settings(
        level_servers=SERVERS,
        lookup_server="http://lookup",
        users={"tok-op": {"name": "op", "level": 1}, "tok-admin": {"name": "admin", "level": 3, "can_upload": True}},
        actions_log=tmp_path / "actions.jsonl",
        ops_file=tmp_path / "missing.json",
    )
    return calls, TestClient(create_app(settings, transport=transport)), settings


def test_chat_uses_the_tokens_level_server(client):
    calls, tc, _ = client
    r = tc.post("/agent/chat", json={"conversationId": "c1", "message": "What torque for SCV bolts?"},
                headers={"Authorization": "Bearer tok-admin"})
    assert r.status_code == 200
    assert calls[-1].url.host == "l3"
    body = r.json()
    assert body["content"] == "Answer." and body["citations"][0]["pages"] == "2"
    sent = json.loads(calls[-1].content)
    assert sent["mode"] == "naive" and sent["include_chunk_content"] is True


def test_guest_gets_level_1_and_unknown_token_is_rejected(client):
    calls, tc, _ = client
    tc.post("/agent/chat", json={"conversationId": "c2", "message": "hello"})
    assert calls[-1].url.host == "l1"
    assert tc.post("/agent/chat", json={"conversationId": "c2", "message": "hi"},
                   headers={"Authorization": "Bearer forged"}).status_code == 401


def test_client_cannot_raise_its_own_level(client):
    calls, tc, _ = client
    tc.post("/agent/chat", json={"conversationId": "c3", "message": "x", "level": 3},
            headers={"Authorization": "Bearer tok-op"})
    assert calls[-1].url.host == "l1"


def test_history_is_sent_on_the_next_turn(client):
    calls, tc, _ = client
    h = {"Authorization": "Bearer tok-op"}
    tc.post("/agent/chat", json={"conversationId": "c4", "message": "first"}, headers=h)
    tc.post("/agent/chat", json={"conversationId": "c4", "message": "second"}, headers=h)
    hist = json.loads(calls[-1].content)["conversation_history"]
    assert hist == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "Answer."}]


def test_lookup_questions_go_to_the_lookup_server_in_naive_mode(client):
    calls, tc, _ = client
    tc.post("/agent/chat", json={"conversationId": "c5", "message": "Which DENSO spark plug fits a 2018 Toyota Corolla?"})
    assert calls[-1].url.host == "lookup" and json.loads(calls[-1].content)["mode"] == "naive"


def test_upload_is_cumulative_and_permission_checked(client):
    calls, tc, _ = client
    files = {"file": ("sop.md", b"# SOP")}
    assert tc.post("/agent/documents", files=files, data={"level": "1"},
                   headers={"Authorization": "Bearer tok-op"}).status_code == 403
    r = tc.post("/agent/documents", files=files, data={"level": "2"}, headers={"Authorization": "Bearer tok-admin"})
    assert r.status_code == 200 and set(r.json()["trackIds"]) == {"level_2", "level_3"}
    assert [c.url.host for c in calls if c.url.path == "/documents/upload"] == ["l2", "l3"]


def test_documents_map_status_and_tier(client):
    _, tc, _ = client
    (doc,) = tc.get("/agent/documents").json()
    assert doc["indexStatus"] == "vectorized" and doc["name"] == "WiperBlade-Cat26_Full-Version"
    assert "lookup" in doc["tags"]


def test_approval_is_logged_and_never_executed(client):
    _, tc, settings = client
    ack = tc.post("/agent/actions/act-1/approve").json()["ack"]
    row = json.loads(settings.actions_log.read_text(encoding="utf-8").splitlines()[-1])
    assert row["action"] == "act-1" and row["ack"] == ack and row["executed"] is False


def test_lookup_falls_back_to_knowledge_when_lookup_server_is_down(backend, tmp_path):
    calls, transport = backend

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lookup":
            raise httpx.ConnectError("lookup profile not running", request=request)
        return transport.handle_request(request)

    settings = Settings(level_servers=SERVERS, lookup_server="http://lookup", users={},
                        actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "none.json")
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    r = tc.post("/agent/chat", json={"conversationId": "c9", "message": "Which DENSO spark plug fits a 2018 Toyota Corolla?"})
    assert r.status_code == 200 and r.json()["target"] == "knowledge"
    assert calls[-1].url.host == "l1" and json.loads(calls[-1].content)["mode"] == "naive"


def test_empty_llm_answer_is_an_error_not_a_no_context_reply(tmp_path):
    # Regression (seen live): with the API quota spent, LightRAG answered the
    # placeholder "No relevant context found for the query." and the UI showed it
    # as if the documents had no answer.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "No relevant context found for the query.",
                                         "references": [], "llm_generated": False})

    settings = Settings(level_servers=SERVERS, users={}, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json")
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    r = tc.post("/agent/chat", json={"conversationId": "c", "message": "torque?"})
    assert r.status_code == 503 and "LLM returned nothing" in r.json()["detail"]


def test_knowledge_mode_can_be_set_from_env(monkeypatch):
    monkeypatch.setenv("DENSO_KNOWLEDGE_MODE", "mix")
    assert Settings.from_env().knowledge_mode == "mix"
    monkeypatch.delenv("DENSO_KNOWLEDGE_MODE")
    assert Settings.from_env().knowledge_mode == "naive"


def test_nemotron_citation_markers_become_plain_ids():
    raw = "Tighten to **6.9 - 10.8 Nm**【2†L4-L5】 and check【file.md】.\n\n### References\n- [2] guide.md"
    assert clean_answer(raw) == "Tighten to **6.9 - 10.8 Nm** [2] and check."


def test_only_cited_references_are_kept():
    refs = [{"reference_id": "1", "file_path": "catalogue.md"}, {"reference_id": "2", "file_path": "guide.md"}]
    assert [r["file_path"] for r in only_cited(refs, "Torque is 6.9 Nm [2].")] == ["guide.md"]
    assert [r["file_path"] for r in only_cited(refs, "See [1, 2].")] == ["catalogue.md", "guide.md"]
    assert len(only_cited(refs, "No markers at all.")) == 2  # nothing cited: keep everything


def test_cors_regex_allows_every_deployment_of_the_vercel_project(tmp_path):
    settings = Settings(level_servers=SERVERS, users={}, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "x.json",
                        cors_regex=r"^https://denso-copilot(-[a-z0-9-]+)?\.vercel\.app$")
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))

    def allowed(origin: str) -> bool:
        r = tc.options("/agent/chat", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        return r.headers.get("access-control-allow-origin") == origin

    assert allowed("https://denso-copilot.vercel.app")
    assert allowed("https://denso-copilot-git-feat-rag-backend-team.vercel.app")
    assert not allowed("https://evil-copilot.vercel.app")
    assert allowed("http://localhost:5173")  # the explicit list still applies
