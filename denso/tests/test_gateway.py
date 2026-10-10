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
    pages_from_chunks,
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
    assert c["pages"] == "4"  # the Russian translation (p.20) is not where the answer was read
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
                "response": "Answer [1].\n\n### References\n- [1] x.md",
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
        upload_pipeline=False,  # direct-to-LightRAG uploads; the pipeline route is in test_jobs.py
    )
    return calls, TestClient(create_app(settings, transport=transport)), settings


def test_chat_uses_the_tokens_level_server(client):
    calls, tc, _ = client
    r = tc.post("/agent/chat", json={"conversationId": "c1", "message": "What torque for SCV bolts?"},
                headers={"Authorization": "Bearer tok-admin"})
    assert r.status_code == 200
    assert calls[-1].url.host == "l3"
    body = r.json()
    assert body["content"] == "Answer [1]." and body["citations"][0]["pages"] == "2"
    sent = json.loads(calls[-1].content)
    assert sent["mode"] == "naive" and sent["include_chunk_content"] is True


def test_guest_gets_level_1_and_unknown_token_is_rejected(client):
    calls, tc, _ = client
    tc.post("/agent/chat", json={"conversationId": "c2", "message": "What torque for SCV bolts?"})
    assert calls[-1].url.host == "l1"
    assert tc.post("/agent/chat", json={"conversationId": "c2", "message": "What oil for a TV compressor?"},
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
    assert hist == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "Answer [1]."}]


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
    assert only_cited(refs, "No markers at all.") == []  # nothing points to a source: cite none
    assert [r["file_path"] for r in only_cited(refs, "No markers.", listed={"1"})] == ["catalogue.md"]


def test_without_markers_the_quoted_figures_pick_the_source():
    refs = [{"reference_id": "1", "file_path": "catalogue.md", "content": ["SC20HR11 1.6L 2009-2012"]},
            {"reference_id": "2", "file_path": "guide.md", "content": ["tighten with 6,9 to 10,8 Nm"]}]
    assert [r["file_path"] for r in only_cited(refs, "Tighten to 6.9 - 10.8 Nm.")] == ["guide.md"]
    assert only_cited(refs, "Tighten to 99.9 Nm.") == []  # figure found nowhere: no source supports it


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


def test_pages_follow_the_language_of_the_best_chunk():
    # A multilingual guide: the best-ranked chunk is English, so only English pages count.
    chunks = ["--- [Trang 4 | ngôn ngữ: en] ---\nTighten to 6.9 Nm",
              "--- [Trang 20 | ngôn ngữ: ru] ---\nЗатянуть 6,9 Н-м",
              "--- [Trang 5 | ngôn ngữ: en] ---\nUse guide pins",
              "--- [Trang 6 | ngôn ngữ: de] ---\nAnziehen 6,9 Nm"]
    assert pages_from_chunks(chunks) == "4, 5"


def test_a_chunk_crossing_a_language_boundary_keeps_only_its_first_language():
    chunk = ("--- [Trang 4 | ngôn ngữ: en] ---\nTighten to 6.9 Nm\n"
             "--- [Trang 5 | ngôn ngữ: de] ---\nAnziehen\n--- [Trang 2 | ngôn ngữ: mixed] ---\nNotes")
    assert pages_from_chunks([chunk]) == "2, 4"


def test_long_page_lists_are_cut():
    chunks = [f"--- [Trang {p} | ngôn ngữ: en] ---\nrow" for p in range(1, 15)]
    assert pages_from_chunks(chunks) == "1, 2, 3, 4, 5, 6, …"


@pytest.mark.parametrize("raw, expected", [
    ("<think>We need to find the plug. Let's search.</think>\nUse SC20HR11 [1].", "Use SC20HR11 [1]."),
    ("Let me check the table.</think>Use SC20HR11 [1].", "Use SC20HR11 [1]."),       # orphan closing tag
    ("Use SC20HR11 [1].\n<think>We need to double check", "Use SC20HR11 [1]."),       # unclosed, cut off
    ("<think>We need to find DENSO spark plug for Toyota Corolla", ""),               # only reasoning (seen live)
])
def test_model_reasoning_never_reaches_the_user(raw, expected):
    assert clean_answer(raw) == expected


def _chat_with(handler, tmp_path, **kw):
    settings = Settings(level_servers=SERVERS, users={}, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json", **kw)
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    return tc.post("/agent/chat", json={"conversationId": "c", "message": "torque?"})


def test_reasoning_only_answer_is_an_error(tmp_path):
    r = _chat_with(lambda req: httpx.Response(200, json={"response": "<think>We need to find the torque", "references": []}),
                   tmp_path)
    assert r.status_code == 503 and "only its reasoning" in r.json()["detail"]


def test_slow_llm_gives_a_clear_timeout(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    r = _chat_with(handler, tmp_path, answer_timeout=1)
    assert r.status_code == 504 and "please ask again" in r.json()["detail"]


def test_a_why_answer_without_figures_keeps_only_the_documents_it_draws_on():
    refs = [{"reference_id": "1", "file_path": "brochure.md", "content": [
                "Swollen rubber seals: the system was charged with the wrong refrigerant, or additives, "
                "conditioners or flushing agents were used. Replace the affected components."]},
            {"reference_id": "2", "file_path": "spark plug catalogue.md", "content": [
                "Spark plug replacement: inspect the system and replace worn insulators regularly."]}]
    answer = ("Rubber seals become swollen when the system was charged with the wrong refrigerant, or when "
              "additives, conditioners or unsuitable flushing agents were used. Replace the affected components.")
    assert [r["file_path"] for r in only_cited(refs, answer)] == ["brochure.md"]
    # Too few English words to judge, and no document named, no code quoted: cite none rather than all.
    assert only_cited(refs, "Gioăng bị phồng do dùng sai môi chất lạnh.") == []
    named = "Gioăng bị phồng do dùng sai môi chất lạnh (brochure, p. 3)."
    assert [r["file_path"] for r in only_cited(refs, named)] == ["brochure.md"]


# --- citations follow what the answer was read from (BHT manual upload, seen live) ----------

BHT = {"reference_id": "1", "file_path": "BHT-M60_Manual_demo_40p.md", "content": [
    "--- [Trang 12 | ngôn ngữ: en] ---\nKitting flow: determine and verify the system configuration, prepare "
    "the materials, run automatic kitting with BHTKitting or BHT DMS, then confirm the results.",
    "--- [Trang 30 | ngôn ngữ: en] ---\nPower OFF: press and hold the power key for one second."]}
BROCHURE = {"reference_id": "2", "file_path": "DENSO-AC_brochure_tips-and-tricks_EN.md", "content": [
    "--- [Trang 3 | ngôn ngữ: en] ---\nCompressor replacement: flushing the refrigerant circuit and replacing "
    "the receiver drier."]}
KITTING = ("The kitting flow is: determine and verify the system configuration, prepare the materials, run "
           "automatic kitting with BHTKitting or BHT DMS, then confirm the results [2].")


def test_a_wrongly_cited_document_is_replaced_by_the_one_that_supports_the_answer():
    assert [r["file_path"] for r in only_cited([BHT, BROCHURE], KITTING)] == ["BHT-M60_Manual_demo_40p.md"]


def test_pages_come_from_the_chunks_that_support_the_answer():
    (c,) = to_citations([BHT], KITTING)
    assert c["pages"] == "12" and c["excerpt"].startswith("Kitting flow")


def test_page_markers_copied_into_the_answer_become_plain_page_references():
    assert clean_answer("Confirm the results.\n--- [Trang 14-15 | ngôn ngữ: en] ---") == "Confirm the results.\n(trang 14-15)"


def test_a_not_in_the_documents_answer_lists_no_sources(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "I do not have enough information to answer.",
                                         "references": [BHT, BROCHURE]})

    settings = Settings(level_servers=SERVERS, users={}, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json")
    r = TestClient(create_app(settings, transport=httpx.MockTransport(handler))).post(
        "/agent/chat", json={"conversationId": "c", "message": "What is the battery capacity of the BHT-M60?"})
    assert r.status_code == 200 and r.json()["citations"] == []


def test_a_chunk_spanning_pages_cites_the_page_the_answer_is_on():
    chunk = ("--- [Trang 16 | ngôn ngữ: en] ---\nPower ON: press and hold the power key until the screen lights.\n"
             "--- [Trang 17 | ngôn ngữ: en] ---\nThe home screen shows the launcher and the status bar.\n"
             "--- [Trang 18 | ngôn ngữ: en] ---\nPower OFF: press and hold the power key for one second; a pop-up "
             "menu appears, tap Power off to shut the terminal down.")
    ref = {"reference_id": "1", "file_path": "BHT.md", "content": [chunk]}
    answer = "Press and hold the power key for one second; a pop-up menu appears, then tap Power off to shut down."
    (c,) = to_citations([ref], answer)
    assert c["pages"] == "18"


def test_an_answer_no_retrieved_chunk_supports_cites_nothing_and_is_flagged(tmp_path):
    # Seen live: after the BHT manual was deleted, an answer repeated from the conversation
    # history about Google Play auto-updates cited "Spark Plug Catalogue 2025, page 4".
    spark = {"reference_id": "1", "file_path": "Spark Plug Catalogue 2025.md", "content": [
        "--- [Trang 4 | ngôn ngữ: en] ---\nIridium spark plugs: the fine centre electrode improves ignitability."]}
    answer = ("If you are not using Google Play Store in operation, disable the Google Play Store app; otherwise "
              "open App info, clear storage and select Don't auto-update apps in the Auto-update apps menu [1].")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": answer, "references": [spark]})

    settings = Settings(level_servers=SERVERS, users={}, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json")
    body = TestClient(create_app(settings, transport=httpx.MockTransport(handler))).post(
        "/agent/chat", json={"conversationId": "c", "message": "How do I stop Google Play auto-updates?"}).json()
    assert body["citations"] == [] and body["grounded"] is False
    assert "Không có đoạn tài liệu nào khớp" in body["events"][0]["label"]


# --- Citations for answers no chunk supports (seen live: "xin chào" cited two catalogues) ---

def test_a_greeting_is_answered_without_retrieval_or_sources(tmp_path):
    from language import small_talk_reply

    assert small_talk_reply("xin chào").startswith("Xin chào")
    assert small_talk_reply("Hello!").startswith("Hello")
    assert small_talk_reply("cảm ơn bạn nhé").startswith("Không có gì")
    assert small_talk_reply("Bạn là ai?").startswith("Xin chào")
    assert small_talk_reply("Bạn là ai trong nhóm bảo trì?") is None
    assert small_talk_reply("xin chào, mô-men xoắn SCV là bao nhiêu?") is None
    assert small_talk_reply("Hi, what oil for a TV compressor?") is None


def test_an_answer_that_points_to_nothing_cites_nothing():
    from app import only_cited

    refs = [{"reference_id": "1", "file_path": "Spark Plug Catalogue 2025.md",
             "content": ["--- [Trang 2 | ngôn ngữ: en] ---\nIridium Power IK20, gap 0.8 mm."]},
            {"reference_id": "2", "file_path": "DENSO-AC_brochure_tips-and-tricks_EN.md",
             "content": ["--- [Trang 1 | ngôn ngữ: en] ---\nCompete with the best in the industry."]}]
    assert only_cited(refs, "Xin chào! Bạn có thể giúp tôi gì hôm nay?") == []


def test_a_vietnamese_answer_cites_the_document_it_names_or_whose_codes_it_quotes():
    from app import only_cited

    oil = {"reference_id": "1", "file_path": "AC Compressor Leaflet.md",
           "content": ["--- [Trang 2 | ngôn ngữ: en] ---\nTV compressor, HFC134a: DENSO Oil 9 (DND09250)."]}
    plug = {"reference_id": "2", "file_path": "Spark_Plug Catalogue 2025.md",
            "content": ["--- [Trang 7 | ngôn ngữ: en] ---\nM14 plug: 20-30 N·m."]}
    named = "Máy nén kiểu TV dùng dầu DENSO Oil 9. (AC Compressor Leaflet, p. 2)"
    assert [r["reference_id"] for r in only_cited([oil, plug], named)] == ["1"]
    coded = "Bugi M14 cần siết với lực 20-30 N·m."
    assert [r["reference_id"] for r in only_cited([oil, plug], coded)] == ["2"]
    named_loosely = "Siết 20-30 N·m theo Spark Plug Catalogue 2025."
    assert [r["reference_id"] for r in only_cited([oil, plug], named_loosely)] == ["2"]


def test_a_vietnamese_refusal_is_a_refusal():
    from app import REFUSAL

    for text in ["Tôi không có đủ thông tin để trả lời.", "Tôi không có thông tin về điều này.",
                 "Tài liệu không đủ thông tin."]:
        assert REFUSAL.search(text)


@pytest.mark.parametrize("text", [
    "Based on the provided context, there is no information available about an \"Oil 9\" product from DENSO.",
    "The shelf life of DENSO ND-oil 9 is not specified in the provided context.",
    "Tài liệu không đề cập đến hạn sử dụng của dầu ND-oil 9.",
    "資料には記載されていません。",
])
def test_refusals_are_recognised(text):
    # Seen live: "there is no information available about Oil 9" was shown with three sources.
    from app import is_refusal

    assert is_refusal(text)


@pytest.mark.parametrize("text", [
    "ND-oil 8 has a shelf life of 36 months in its metal can (Brochure, p. 12). " * 4
    + "The shelf life of ND-oil 12 is not specified in the provided context.",
    "Không tăng tốc động cơ trong 5 phút đầu; nếu không tìm thấy nút A/C, dùng bảng điều khiển phụ.",
])
def test_a_real_answer_with_one_gap_is_not_a_refusal(text):
    from app import is_refusal

    assert not is_refusal(text)


def test_one_users_conversation_history_never_reaches_another_user(client):
    calls, tc, _ = client
    tc.post("/agent/chat", json={"conversationId": "shared", "message": "What torque for SCV bolts?"},
            headers={"Authorization": "Bearer tok-admin"})
    tc.post("/agent/chat", json={"conversationId": "shared", "message": "What torque for SCV bolts?"})  # a guest
    assert json.loads(calls[-1].content).get("conversation_history") is None


def test_guests_upload_only_when_the_team_testing_switch_is_on(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "track_id": "t"})

    for allowed, expected in [(False, 403), (True, 200)]:
        settings = Settings(level_servers=SERVERS, users={}, actions_log=tmp_path / "a.jsonl",
                            ops_file=tmp_path / "n.json", upload_pipeline=False, guest_can_upload=allowed)
        tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
        r = tc.post("/agent/documents", files={"file": ("a.md", b"x")}, data={"level": "1"})
        assert r.status_code == expected
        # Still level 1: the switch grants uploads, never a higher access level.
        assert tc.post("/agent/documents", files={"file": ("a.md", b"x")}, data={"level": "2"}).status_code == 403


def test_raw_file_finds_the_upload_behind_a_document(tmp_path):
    from app import raw_file
    (tmp_path / "raw" / "level_3").mkdir(parents=True)
    pdf = tmp_path / "raw" / "Phieu.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "raw" / "level_3" / "Secret.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "parsed" / "Catalogue").mkdir(parents=True)
    (tmp_path / "parsed" / "Catalogue" / "meta.json").write_text('{"source_file": "Phieu.pdf"}', encoding="utf-8")
    assert raw_file("Phieu.md", tmp_path) == pdf.resolve()
    assert raw_file("Phieu - images.[native-P!].md", tmp_path) == pdf.resolve()
    assert raw_file("Catalogue.md", tmp_path) == pdf.resolve()  # through parsed/<stem>/meta.json
    assert raw_file("Secret.md", tmp_path, max_level=1) is None  # raw/level_3 is above the caller
    assert raw_file("Secret.md", tmp_path, max_level=3) is not None
    assert raw_file("../../etc/passwd", tmp_path) is None


def test_raw_file_matches_either_unicode_normal_form(tmp_path):
    import unicodedata
    from app import raw_file
    (tmp_path / "raw").mkdir()
    name = unicodedata.normalize("NFD", "Bài 5 - Tìm kiếm có đối thủ") + ".pdf"
    (tmp_path / "raw" / name).write_bytes(b"%PDF-1.4")
    assert raw_file("Bài 5 - Tìm kiếm có đối thủ.md", tmp_path) is not None


def test_document_file_is_served_only_at_the_callers_level(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "Low.pdf").write_bytes(b"%PDF-1.4 low")

    def handler(request: httpx.Request) -> httpx.Response:
        docs = {"l1": [{"id": "doc-low", "file_path": "Low.md"}],
                "l3": [{"id": "doc-high", "file_path": "High.md"}]}.get(request.url.host, [])
        return httpx.Response(200, json={"documents": docs, "pagination": {"has_next": False}})

    settings = Settings(level_servers=SERVERS, users={"tok-admin": {"name": "admin", "level": 3}},
                        actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "m.json",
                        upload_pipeline=False, data_dir=tmp_path)
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    r = tc.get("/agent/documents/doc-low/file")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 low"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert tc.get("/agent/documents/doc-high/file").status_code == 404  # a guest is level 1
    # Level 3 sees the document, but its original was never uploaded here.
    assert tc.get("/agent/documents/doc-high/file", headers={"Authorization": "Bearer tok-admin"}).status_code == 404


def test_telemetry_is_found_by_incident_id_or_device_id(tmp_path):
    ops_file = tmp_path / "ops.json"
    ops_file.write_text(json.dumps({"telemetry": {"INC-1": {"deviceId": "bench-01", "points": []}}}), encoding="utf-8")
    settings = Settings(level_servers=SERVERS, actions_log=tmp_path / "a.jsonl", ops_file=ops_file, upload_pipeline=False)
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert tc.get("/agent/telemetry/INC-1").json()["deviceId"] == "bench-01"
    assert tc.get("/agent/telemetry/bench-01").json()["deviceId"] == "bench-01"
    assert tc.get("/agent/telemetry/other").status_code == 404


# ---------------------------------------------------------------- iot_service forwarding


def _iot_client(tmp_path, iot_handler, **kw):
    """Gateway with DENSO_IOT_URL=http://iot; LightRAG answers every chat with a fixed reply."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "iot":
            return iot_handler(request)
        if request.url.path == "/query":
            return httpx.Response(200, json={"response": "From the documents.", "references": [], "llm_generated": True})
        return httpx.Response(404)

    settings = Settings(level_servers=SERVERS, actions_log=tmp_path / "actions.jsonl", ops_file=tmp_path / "m.json",
                        upload_pipeline=False, iot_url="http://iot",
                        users={"tok-eng": {"name": "eng", "level": 1, "can_approve": True},
                               "tok-op": {"name": "op", "level": 1}}, **kw)
    return seen, TestClient(create_app(settings, transport=httpx.MockTransport(handler)))


IOT_INCIDENT = {"id": "INC-0001", "conversationId": "CONV-0001", "device": "COMP-TB-01", "alarm": "High discharge",
                "severity": "high", "status": "awaiting_approval", "timestamp": "2026-10-11T00:00:00Z"}


def _iot_ok(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/agent/incidents":
        return httpx.Response(200, json=[IOT_INCIDENT])
    if path == "/agent/telemetry/COMP-TB-01":
        return httpx.Response(200, json={"deviceId": "COMP-TB-01", "points": []})
    if path == "/agent/actions/ACT-0001/approve":
        return httpx.Response(200, json={"ack": "ACK 200"})
    if path == "/agent/actions/ACT-0001/reject":
        return httpx.Response(200, json={"status": "rejected"})
    if path == "/agent/chat":
        return httpx.Response(200, json={"content": "IoT agent: lower the RPM.", "citations": []})
    return httpx.Response(404, json={"detail": "Incident not found"})


def test_incidents_and_telemetry_come_from_the_iot_service(tmp_path):
    _, tc = _iot_client(tmp_path, _iot_ok)
    assert tc.get("/agent/incidents").json() == [IOT_INCIDENT]
    assert tc.get("/agent/telemetry/COMP-TB-01").json()["deviceId"] == "COMP-TB-01"
    r = tc.get("/agent/incidents/INC-9999")
    assert r.status_code == 404 and "IoT service" in r.json()["detail"]


def test_an_unreachable_iot_service_is_a_503_not_sample_data(tmp_path):
    def down(request):
        raise httpx.ConnectError("refused")
    _, tc = _iot_client(tmp_path, down)
    r = tc.get("/agent/incidents")
    assert r.status_code == 503
    assert "not reachable" in r.json()["detail"]


def test_approving_an_iot_action_needs_the_right_and_is_logged(tmp_path):
    seen, tc = _iot_client(tmp_path, _iot_ok)
    assert tc.post("/agent/actions/ACT-0001/approve").status_code == 403  # guest
    assert tc.post("/agent/actions/ACT-0001/approve", headers={"Authorization": "Bearer tok-op"}).status_code == 403
    assert not [r for r in seen if r.url.path.endswith("/approve")]  # refused before reaching the simulator
    r = tc.post("/agent/actions/ACT-0001/approve", headers={"Authorization": "Bearer tok-eng"})
    assert r.json() == {"ack": "ACK 200"}
    assert tc.post("/agent/actions/ACT-0001/reject", headers={"Authorization": "Bearer tok-eng"}).status_code == 200
    rows = [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(x["decision"], x["user"]) for x in rows] == [("approve", "eng"), ("reject", "eng")]


def test_team_testing_mode_lets_guests_approve(tmp_path):
    _, tc = _iot_client(tmp_path, _iot_ok, guest_can_upload=True)
    assert tc.post("/agent/actions/ACT-0001/approve").json() == {"ack": "ACK 200"}


def test_without_the_iot_service_an_approval_is_only_recorded(tmp_path):
    settings = Settings(level_servers=SERVERS, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "m.json",
                        upload_pipeline=False)
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert tc.post("/agent/actions/ACT-1/approve").json()["ack"].startswith("ACK-")


LIVE_INCIDENT = {
    **IOT_INCIDENT,
    "alarm": "CẢNH BÁO NGUY HIỂM: Quạt dàn ngưng hỏng",
    "telemetry": {"deviceId": "COMP-TB-01", "points": [
        {"key": "discharge_temp", "label": "Nhiệt độ đầu xả", "value": 121.8, "unit": "°C", "threshold": 105.0,
         "isAnomalous": True},
        {"key": "compressor_rpm", "label": "Tốc độ máy nén", "value": 1500.0, "unit": "rpm", "threshold": None,
         "isAnomalous": False}]},
    "proposedAction": {"id": "ACT-0001", "titleVi": "Đề xuất: SET_RPM",
                       "subtitleVi": "Hạ tốc độ máy nén xuống 1000 RPM trong khi chờ sửa quạt."},
}


def _iot_live(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/agent/incidents":
        return httpx.Response(200, json=[LIVE_INCIDENT])
    return _iot_ok(request)


def test_a_chat_in_an_incident_is_answered_from_the_documents_with_the_incident_in_the_prompt(tmp_path):
    seen, tc = _iot_client(tmp_path, _iot_live)
    r = tc.post("/agent/chat", json={"conversationId": "CONV-0001", "message": "Cần kiểm tra gì tiếp theo?"})
    assert r.json()["content"].startswith("From the documents")
    assert not [x for x in seen if x.url.host == "iot" and x.url.path == "/agent/chat"]  # not the IoT rule bot
    (query,) = [json.loads(x.content) for x in seen if x.url.path == "/query"]
    # The fault steers retrieval of a vague Vietnamese question...
    assert query["query"] == "Cần kiểm tra gì tiếp theo?\n(Quạt dàn ngưng hỏng)"
    # ...and the live state reaches the answer prompt, marked as not coming from the documents.
    prompt = query["user_prompt"]
    assert "NOT from the documents" in prompt
    assert "COMP-TB-01" in prompt and "Nhiệt độ đầu xả 121.8 °C, limit 105, OUT OF RANGE" in prompt
    assert "Đề xuất: SET_RPM" in prompt and "waiting for approval" in prompt
    assert "tiếng Việt" in prompt or "Vietnamese" in prompt  # the language instruction is kept
    assert r.json()["events"][0]["label"] == "Incident context added (INC-0001, COMP-TB-01)"


def test_an_english_question_in_an_incident_keeps_its_own_retrieval_text(tmp_path):
    seen, tc = _iot_client(tmp_path, _iot_live)
    tc.post("/agent/chat", json={"conversationId": "CONV-0001", "message": "How do I replace the condenser fan?"})
    (query,) = [json.loads(x.content) for x in seen if x.url.path == "/query"]
    assert query["query"] == "How do I replace the condenser fan?"  # a Vietnamese alarm would flip the reranker
    assert "Quạt dàn ngưng hỏng" in query["user_prompt"]


def test_other_conversations_get_no_incident_context(tmp_path):
    seen, tc = _iot_client(tmp_path, _iot_live)
    for conv in ("CONV-LIVE", "iot-rag-abc123"):
        tc.post("/agent/chat", json={"conversationId": conv, "message": "SCV bolt torque?"})
    queries = [json.loads(x.content) for x in seen if x.url.path == "/query"]
    assert [q["query"] for q in queries] == ["SCV bolt torque?", "SCV bolt torque?"]
    assert not any("NOT from the documents" in (q.get("user_prompt") or "") for q in queries)


def test_documents_still_answer_when_the_iot_service_is_down(tmp_path):
    def down(request):
        raise httpx.ConnectError("refused")
    _, tc = _iot_client(tmp_path, down)
    r = tc.post("/agent/chat", json={"conversationId": "CONV-LIVE", "message": "SCV bolt torque?"})
    assert r.status_code == 200
    assert r.json()["content"].startswith("From the documents")


# ---------------------------------------------------------------- iot_service dashboard relay


def _iot_dashboard(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/dashboard/":
        return httpx.Response(200, text="<html>control room</html>", headers={"content-type": "text/html"})
    if path == "/dashboard/app.js":
        return httpx.Response(200, text="console.log(1)", headers={"content-type": "application/javascript"})
    if path == "/api/v1/dashboard/events":
        return httpx.Response(200, json={"query": dict(request.url.params),
                                         "token": request.headers.get("x-dashboard-token")})
    if path == "/api/v1/stream":
        return httpx.Response(200, content=b"event: snapshot\ndata: {}\n\n", headers={"content-type": "text/event-stream"})
    return httpx.Response(404, json={"detail": "Not Found"})


def test_the_dashboard_opens_through_the_gateway(tmp_path):
    _, tc = _iot_client(tmp_path, _iot_dashboard)
    r = tc.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/dashboard/"
    r = tc.get("/dashboard/")
    assert r.text == "<html>control room</html>" and r.headers["content-type"].startswith("text/html")
    assert tc.get("/dashboard/app.js").headers["content-type"].startswith("application/javascript")
    # Query string and the dashboard's own token header reach the IoT service.
    r = tc.get("/api/v1/dashboard/events?limit=50&machine=COMP-TB-01", headers={"X-Dashboard-Token": "t"})
    assert r.json() == {"query": {"limit": "50", "machine": "COMP-TB-01"}, "token": "t"}
    assert tc.get("/dashboard/missing.css").status_code == 404


def test_the_dashboard_event_stream_is_relayed(tmp_path):
    _, tc = _iot_client(tmp_path, _iot_dashboard)
    r = tc.get("/api/v1/stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.content == b"event: snapshot\ndata: {}\n\n"


def test_no_dashboard_without_the_iot_service(tmp_path):
    settings = Settings(level_servers=SERVERS, actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "m.json",
                        upload_pipeline=False)
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert tc.get("/dashboard/").status_code == 404
    assert tc.get("/api/v1/stream").status_code == 404


def test_through_the_tunnel_the_dashboard_is_told_to_poll(tmp_path):
    # A Cloudflare quick tunnel holds the event stream back: refusing it makes the dashboard poll.
    seen, tc = _iot_client(tmp_path, _iot_dashboard)
    r = tc.get("/api/v1/stream", headers={"CF-Ray": "a488d6069b4385c1-HKG"})
    assert r.status_code == 503
    assert not [x for x in seen if x.url.path == "/api/v1/stream"]  # no idle upstream connection left open
    assert tc.get("/api/v1/dashboard/events", headers={"CF-Ray": "x"}).status_code == 200  # polling still works
