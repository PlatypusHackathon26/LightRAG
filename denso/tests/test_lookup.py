"""Keyword search over the lookup catalogues (denso/gateway/lookup.py) and its gateway route."""

import json
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from app import Settings, create_app  # noqa: E402
from lookup import load_rows, parse_query, search  # noqa: E402

# Real rows from the Spark Plug Catalogue 2025 lookup tier (OCR'd, columns drift).
SPARK = """| Trang | Model | Engine Size Engine Code | Specification | Year DENSO |
|---|---|---|---|---|
| 139 | TOYOTA COROLLA | 1.33L 4Cyl 16V 1NR-FE 1ZR-FAE | 1.33 Dual-VVTi (NRE150_) | 2009-2012 SC20HR11 | - IXEH22TT - | VCH20 4 |
| 139 | TOYOTA COROLLA | 1.3L 4Cyl 16V 1NR-FE | 1.3 (NRE180_) | 2012-2018 SC20HR11 | - IXEH22TT - | VCH20 4 |
| 139 | TOYOTA COROLLA | 1.5L 4Cyl 16V 1NZ-FE,2NR-FKE | 1.5 (NZE161G) | 2012-2017 FK16HR11 | - IKH16TT - | - 4 |
| 207 | VIOS 1.5J, 1.5E, 1.5G (DUAL VVTI) | 2010-2016 2016 |  | IXEH20TT | - | - | VCH16 |
| 43 | GIULIA GIULIETTA | 3.2L 6Cyl 24V 939 A.000 | 2005- | K20TXR |
"""
WIPER = """| 30 | CIVIC SEDAN (INCL. HYBRID) | 2017-2020 | FC1 | DDP-026R/L | DDP-018R/L |
"""


def rows(tmp_path):
    (tmp_path / "Spark Plug Catalogue 2025 - lookup.[native-P!].md").write_text(SPARK, encoding="utf-8")
    (tmp_path / "WiperBlade-Cat26_Full-Version - lookup.[native-P!].md").write_text(WIPER, encoding="utf-8")
    return load_rows(sorted(tmp_path.glob("* - lookup.*.md")))


def test_query_keeps_model_code_year_and_displacement():
    q = parse_query("Bugi DENSO nào lắp cho Toyota Corolla 1.3L đời 2015?")
    assert q.words == {"COROLLA"} and q.makes == {"TOYOTA"}
    assert q.years == (2015,) and q.displacements == ("1.3",) and q.product == "spark"


def test_displacement_is_not_split_into_a_stray_word():
    # Regression: "1.3L" became the word "3L" and matched "3.2L" Alfa Romeo rows.
    assert "3L" not in parse_query("Toyota Corolla 1.3L 2015").words


def test_the_row_for_the_asked_model_engine_and_year_ranks_first(tmp_path):
    hits = search(rows(tmp_path), "Bugi DENSO nào lắp cho Toyota Corolla 1.3L đời 2015?")
    assert hits[0][0].page == 139 and "NRE180" in hits[0][0].text and "SC20HR11" in hits[0][0].text
    assert all("GIULIA" not in r.text for r, _ in hits)


def test_a_year_outside_the_row_range_ranks_below_one_inside(tmp_path):
    hits = search(rows(tmp_path), "Which DENSO spark plug fits a 2011 Toyota Corolla 1.33?")
    assert "NRE150" in hits[0][0].text  # 2009-2012, not the 2012-2018 NRE180 row


def test_the_product_named_selects_the_catalogue(tmp_path):
    hits = search(rows(tmp_path), "Which DENSO wiper blade fits a Honda Civic 2019?")
    assert hits and all("WiperBlade" in r.source for r, _ in hits)


def test_no_vehicle_words_means_no_keyword_answer(tmp_path):
    assert search(rows(tmp_path), "Which DENSO spark plug is best?") == []


def test_gateway_answers_lookup_questions_from_the_matched_rows(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            sent = json.loads(request.content)
            seen["prompt"] = sent["messages"][-1]["content"]
            seen["thinking"] = sent.get("chat_template_kwargs")
            return httpx.Response(200, json={"choices": [{"message": {"content":
                "<think>check rows</think>The 1.3L Corolla (NRE180, 2012-2018) uses **SC20HR11** [1]."}}]})
        raise AssertionError(f"LightRAG must not be called: {request.url}")

    rows(tmp_path)
    settings = Settings(level_servers=["http://l1", "http://l2", "http://l3"], lookup_server="http://lookup", users={},
                        actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json", lookup_llm_base="http://llm/v1",
                        lookup_files=sorted(tmp_path.glob("* - lookup.*.md")),
                        lookup_llm_extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    r = tc.post("/agent/chat", json={"conversationId": "c", "message": "Bugi DENSO nào lắp cho Toyota Corolla 1.3L đời 2015?"})
    body = r.json()
    assert r.status_code == 200 and body["target"] == "lookup"
    assert body["content"] == "The 1.3L Corolla (NRE180, 2012-2018) uses **SC20HR11** [1]."
    assert "NRE180" in seen["prompt"] and "page 139" in seen["prompt"]
    assert body["citations"][0]["pages"] == "139" and "Spark Plug" in body["citations"][0]["documentName"]
    assert "keyword" in body["events"][0]["label"]
    assert seen["thinking"] == {"enable_thinking": False}  # extra body reaches the LLM request


def test_gateway_falls_back_to_the_lookup_server_without_a_match(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, json={"response": "Not listed.", "references": []})

    rows(tmp_path)
    settings = Settings(level_servers=["http://l1", "http://l2", "http://l3"], lookup_server="http://lookup", users={},
                        actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json",
                        lookup_files=sorted(tmp_path.glob("* - lookup.*.md")))
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    # Lower case: no capitalised model name, so no "not listed" short-cut; no row matches either.
    r = tc.post("/agent/chat", json={"conversationId": "c", "message": "which denso spark plug fits a 2015 lada niva?"})
    assert r.status_code == 200 and calls == ["lookup"]


def _lookup_answer(tmp_path, reply: str) -> dict:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    rows(tmp_path)
    settings = Settings(level_servers=["http://l1", "http://l2", "http://l3"], lookup_server="http://lookup", users={},
                        actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json", lookup_llm_base="http://llm/v1",
                        lookup_files=sorted(tmp_path.glob("* - lookup.*.md")))
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    return tc.post("/agent/chat", json={"conversationId": "c", "message": "Which spark plug fits a Toyota Corolla 2015?"}).json()


def test_a_lookup_refusal_cites_no_rows(tmp_path):
    # Every matched row used to be cited when the answer had no [n] - even "not in the catalogue".
    body = _lookup_answer(tmp_path, "I do not have enough information: no row lists a 2015 Corolla 2.0L.")
    assert body["citations"] == []


def test_a_lookup_answer_without_markers_cites_only_rows_with_its_part_numbers(tmp_path):
    body = _lookup_answer(tmp_path, "The 1.5L Corolla (2012-2017) uses FK16HR11.")
    assert len(body["citations"]) == 1 and "FK16HR11" in body["citations"][0]["excerpt"]


def test_a_named_vehicle_no_row_mentions_gets_no_keyword_rows(tmp_path):
    # Seen in review: "Lada Niva" matched a Lada G4FA row on LADA alone and its plugs were offered.
    extra = "| 90 | LADA | G4FA 1.6L 4CYL 16V | 2015- VXUHC22G |\n"
    (tmp_path / "x - lookup.[native-P!].md").write_text(extra, encoding="utf-8")
    all_rows = rows(tmp_path) + load_rows([tmp_path / "x - lookup.[native-P!].md"])
    assert search(all_rows, "Bugi nào lắp cho xe Lada Niva 2015?") == []
    assert search(all_rows, "Which DENSO spark plug fits a 2015 Lada Niva?") == []
    assert search(all_rows, "Which spark plug fits a Toyota Corolla 1.3L 2015?")  # known models still match


def test_a_vehicle_no_catalogue_mentions_is_declined_without_any_llm(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"nothing may be asked: {request.url}")

    rows(tmp_path)
    settings = Settings(level_servers=["http://l1", "http://l2", "http://l3"], lookup_server="http://lookup", users={},
                        actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json",
                        lookup_files=sorted(tmp_path.glob("* - lookup.*.md")))
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    body = tc.post("/agent/chat", json={"conversationId": "c", "message": "Bugi nào lắp cho xe Lada Niva 2015?"}).json()
    assert body["citations"] == [] and "Không tìm thấy xe" in body["content"] and "Niva" in body["content"]


def test_rows_showing_the_asked_code_are_the_only_rows_given(tmp_path):
    # Seen live (L9): given a "CR-V 2008" row without RE3 too, the model chose it and said it covers RE3.
    wiper = ("| 83 | CR-V (INCL. HYBRID) | 2006-2011 | RE3, RE4 | DCP-026R/L | DCP-017R/L |\n"
             "| 83 | CR-V | 2008 |  |  | DCS-G024 | DCS-G017 |\n")
    (tmp_path / "Wiper - lookup.[native-P!].md").write_text(wiper, encoding="utf-8")
    hits = search(load_rows([tmp_path / "Wiper - lookup.[native-P!].md"]), "Which DENSO wiper blades fit a 2008 Honda CR-V (RE3)?")
    assert [r.text for r, _ in hits] == [" CR-V (INCL. HYBRID) | 2006-2011 | RE3, RE4 | DCP-026R/L | DCP-017R/L "]


def test_a_listed_model_outside_the_asked_year_still_gives_its_rows(tmp_path):
    # "Lada Niva 2015": the catalogue lists the Niva for 2006-2013 only; that row lets the answer say so.
    spark = ("| 90 | LADA | G4FA 1.6L 4Cyl 16V |  | 2015- VXUHC22G |\n"
             "| 90 | NIVA | 21114 11194 | 1600 1600 4x4 | 2006-2013 W20EP-U | W20TT |\n")
    (tmp_path / "Spark - lookup.[native-P!].md").write_text(spark, encoding="utf-8")
    hits = search(load_rows([tmp_path / "Spark - lookup.[native-P!].md"]), "Bugi nào lắp cho xe Lada Niva 2015?")
    assert [r.text.split("|")[0].strip() for r, _ in hits] == ["NIVA"]
