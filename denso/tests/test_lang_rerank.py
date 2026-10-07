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


def test_cross_lingual_question_keeps_vector_order():
    docs = [RU, DE, EN]
    order = [i for i, _ in rank("Does the Russian section give the same torque as the English section?", docs)]
    assert order == [0, 1, 2]


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
