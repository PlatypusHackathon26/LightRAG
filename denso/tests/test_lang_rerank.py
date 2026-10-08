"""Tests for the language-preference reranker (denso/tools/lang_rerank.py)."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from lang_rerank import create_app, is_cross_lingual, rank  # noqa: E402

EN = "--- [Trang 4 | ngôn ngữ: en] ---\nFit the bolts and tighten them with 6.9 to 10.8 Nm."
RU = "--- [Trang 20 | ngôn ngữ: ru] ---\nУстановить болты и затянуть их моментом от 6,9 до 10,8 Н-м."
DE = "--- [Trang 6 | ngôn ngữ: de] ---\nSchrauben einsetzen und mit 6,9 bis 10,8 Nm anziehen."


@pytest.mark.parametrize("question, expected", [
    ("In the English section of the installation guide, what torque must be used?", False),  # own language
    ("What DENSO compressor oil may be used?", False),
    ("Does the value in the Russian-language section match the English section?", True),
    ("Do the German and French language sections agree on the guide pins?", True),
    ("Mô-men xoắn trong phần tiếng Nga là bao nhiêu?", True),
    ("Is the warning repeated in the other language versions?", True),
])
def test_cross_lingual_detection(question, expected):
    # Regression: an escaped "\\b" written through a non-raw string became a
    # backspace character and silently disabled the detection.
    assert is_cross_lingual(question) is expected


def test_same_language_chunks_move_up_keeping_vector_order_within_groups():
    docs = [RU, DE, EN, RU + " (second)"]
    order = [i for i, _ in rank("What torque must be used for the SCV bolts?", docs)]
    assert order == [2, 0, 1, 3]


def test_cross_lingual_question_prefers_the_sections_it_names():
    docs = [RU, DE, EN]
    order = [i for i, _ in rank("Does the Russian section give the same torque as the English section?", docs)]
    assert order == [0, 1, 2]  # Russian first; English is never boosted (every catalogue is English)
    order = [i for i, _ in rank("Does the Russian section give the same torque as the English section?", [DE, EN, RU])]
    assert order == [2, 0, 1]


def test_endpoint_is_cohere_compatible():
    tc = TestClient(create_app())
    r = tc.post("/rerank", json={"model": "x", "query": "What torque for the SCV bolts?",
                                 "documents": [RU, {"text": EN}], "top_n": 1})
    body = r.json()
    assert r.status_code == 200 and body["results"] == [{"index": 1, "relevance_score": body["results"][0]["relevance_score"]}]
    assert 0.0 <= body["results"][0]["relevance_score"] <= 1.0


def test_question_language_absent_from_the_manuals_prefers_english():
    # Seen live: a Vietnamese question quoted the Romanian and Russian sections and
    # cited their pages, because no chunk was tagged "vi".
    docs = [RU, DE, EN]
    order = [i for i, _ in rank("Mô-men xoắn siết bu-lông SCV trên bơm Common Rail diesel là bao nhiêu?", docs)]
    assert order == [2, 0, 1]


def test_cross_lingual_vietnamese_question_still_keeps_vector_order():
    docs = [RU, DE, EN]
    order = [i for i, _ in rank("Mô-men xoắn trong phần tiếng Nga là bao nhiêu?", docs)]
    assert order == [0, 1, 2]


IMAGE = "## Ảnh trên trang 3 – SCV\n\n### Ảnh 1\nA hand pressing two guide pins into the pump body."
FR = "--- trang 7 · ngôn ngữ: fr ---\nInstaller les 2 goupilles de guidage avant de monter la SCV."


def test_picture_descriptions_rank_below_every_document_text_chunk():
    # Seen live (Q28): image-caption chunks pushed the French section out of the context
    # and the model invented "3 guide pins" for it.
    docs = [IMAGE, IMAGE, FR, DE]
    ranked = rank("Do the German and French language sections agree on the number of guide pins?", docs)
    assert [i for i, _ in ranked][:2] == [2, 3]
    assert all(s > 0 for _, s in ranked)  # LightRAG drops chunks scored below 0


def test_endpoint_scores_stay_within_zero_and_one():
    tc = TestClient(create_app())
    r = tc.post("/rerank", json={"query": "What torque for the SCV bolts?", "documents": [EN, IMAGE, RU]})
    scores = [x["relevance_score"] for x in r.json()["results"]]
    assert all(0.0 < s <= 1.0 for s in scores)


def test_picture_text_in_a_named_language_still_ranks_with_the_named_sections():
    # Seen live (Q27): the Russian section reached the pool only as the OCR text of its pages.
    ru_image = "## Ảnh trong mục «Инструкции» (trang 17)\n--- [Trang 19 | ngôn ngữ: ru] ---\nЗатянуть 6,9-10,8 Н-м."
    docs = [EN, DE, IMAGE, ru_image]
    order = [i for i, _ in rank("Does the SCV torque in the Russian-language section match the English section?", docs)]
    assert order[0] == 3 and order[-1] == 2
