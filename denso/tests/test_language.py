"""Answer language (denso/gateway/language.py) and how the gateway passes it to LightRAG."""

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from app import Settings, create_app  # noqa: E402
from language import language_instruction, question_language  # noqa: E402


@pytest.mark.parametrize("text, lang", [
    ("Mô-men xoắn siết bu-lông SCV là bao nhiêu?", "vi"),
    ("Gioăng bị phồng vì sao", "vi"),
    ("What torque must be used for the SCV bolts?", "en"),
    ("ディーゼル用SCVの締め付けトルクは?", "ja"),
    ("Installez la vis et serrez-la à côté du corps de la pompe.", "fr"),  # â/ô are not Vietnamese
    ("Установить болты и затянуть их моментом.", "ru"),
])
def test_question_language(text, lang):
    assert question_language(text) == lang


def test_instructions_name_the_language():
    assert language_instruction("Dầu DENSO nào dùng cho máy nén TV?").startswith("Trả lời HOÀN TOÀN bằng tiếng Việt")
    assert "日本語" in language_instruction("慣らし運転の手順を教えてください。")
    assert "Deutsch" in language_instruction("Welches Öl wird für den TV-Kompressor verwendet?")
    assert language_instruction("?? 12") == ""


def test_the_gateway_sends_the_instruction_with_each_question(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "6,9 – 10,8 Nm.", "references": []})

    settings = Settings(level_servers=["http://l1", "http://l2", "http://l3"], users={},
                        actions_log=tmp_path / "a.jsonl", ops_file=tmp_path / "n.json")
    tc = TestClient(create_app(settings, transport=httpx.MockTransport(handler)))
    tc.post("/agent/chat", json={"conversationId": "c", "message": "Mô-men xoắn siết bu-lông SCV là bao nhiêu?"})
    assert sent[-1]["user_prompt"].startswith("\nTrả lời HOÀN TOÀN bằng tiếng Việt")


def test_a_question_about_a_language_section_cites_that_sections_page():
    # Seen live: "Phần tiếng Nga ... mô-men xoắn" cited pages 4 and 6 (English, German): the
    # torque figure is on every translation's page.
    from app import to_citations
    from language import named_languages

    chunk = ("--- [Trang 4 | ngôn ngữ: en] ---\nTighten the bolts with 6.9 to 10.8 Nm.\n"
             "--- [Trang 6 | ngôn ngữ: de] ---\nSchrauben mit 6,9 bis 10,8 Nm anziehen.\n"
             "--- [Trang 19 | ngôn ngữ: ru] ---\nЗатянуть болты моментом от 6,9 до 10,8 Н-м.")
    ref = {"reference_id": "1", "file_path": "Diesel_SCV.md", "content": [chunk]}
    answer = "Phần tiếng Nga ghi mô-men xoắn từ 6,9 đến 10,8 Nm."
    question = "Phần tiếng Nga của hướng dẫn SCV ghi mô-men xoắn là bao nhiêu?"
    assert named_languages(question) == {"ru"}
    (c,) = to_citations([ref], answer, named_languages(question))
    assert c["pages"] == "19"


def test_a_comparison_of_two_language_sections_cites_a_page_of_each():
    from app import to_citations

    chunk = ("--- [Trang 4 | ngôn ngữ: en] ---\nIt is necessary to use the two guide pins; tighten with 6.9 to 10.8 Nm.\n"
             "--- [Trang 6 | ngôn ngữ: de] ---\nES IST NOTWENDIG, DIE ZWEI FÜHRUNGSSTIFTE ZU VERWENDEN, 6,9 bis 10,8 Nm.\n"
             "--- [Trang 10 | ngôn ngữ: fr] ---\nIL EST NÉCESSAIRE D'UTILISER LES DEUX GOUPILLES DE GUIDAGE, 6,9 à 10,8 Nm.")
    ref = {"reference_id": "1", "file_path": "Diesel_SCV.md", "content": [chunk]}
    answer = "Yes: both require 2 guide pins (zwei Führungsstifte / deux goupilles de guidage), torque 6.9 to 10.8 Nm."
    (c,) = to_citations([ref], answer, {"de", "fr"})
    assert c["pages"] == "6, 10"


def test_a_comparison_keeps_a_source_for_each_language_asked_about():
    # Seen live (Q28): the image-text document (German pages) was kept and the guide holding
    # the French section dropped, though the answer compared both.
    from app import only_cited

    images = {"reference_id": "1", "file_path": "Diesel_SCV - images.md",
              "content": ["--- [Trang 5 | ngôn ngữ: de] ---\nZwei Führungsstifte einsetzen: two guide pins required."]}
    guide = {"reference_id": "3", "file_path": "Diesel_SCV.md",
             "content": ["--- [Trang 7 | ngôn ngữ: fr] ---\nInstaller les 2 goupilles de guidage."]}
    other = {"reference_id": "4", "file_path": "Spark Plug Catalogue 2025.md",
             "content": ["--- [Trang 2 | ngôn ngữ: en] ---\nSpark plug heat range table."]}
    answer = "Yes, both the German and French language sections agree that two guide pins are required [1]."
    kept = only_cited([images, other, guide], answer, {"de", "fr"})
    assert [r["reference_id"] for r in kept] == ["3", "1"]  # the guide's text first


def test_a_comparison_cites_the_document_text_before_its_picture_descriptions():
    # Seen live (Q28): the image-text document carries both German and French tags (OCR of
    # those pages), so it alone "covered" the question and the guide holding the French text
    # was never cited.
    from app import only_cited

    images = {"reference_id": "1", "file_path": "Diesel_SCV - images.md",
              "content": ["--- [Trang 5 | ngôn ngữ: de] ---\nZwei Führungsstifte: two guide pins.\n"
                          "--- [Trang 10 | ngôn ngữ: fr] ---\nDeux goupilles: two guide pins."]}
    guide = {"reference_id": "3", "file_path": "Diesel_SCV.md",
             "content": ["--- [Trang 7 | ngôn ngữ: fr] ---\nInstaller les 2 goupilles de guidage."]}
    answer = "Yes, both the German and French language sections agree that two guide pins are required [1]."
    kept = only_cited([images, guide], answer, {"de", "fr"})
    assert [r["reference_id"] for r in kept] == ["3", "1"]


def test_a_comparison_never_cites_another_document_for_a_language():
    # Seen live (Q28): the wiper catalogue's German pages were cited for the SCV guide's German section.
    from app import only_cited

    images = {"reference_id": "1", "file_path": "Diesel_SCV - images.md",
              "content": ["--- [Trang 5 | ngôn ngữ: de] ---\nZwei Führungsstifte: two guide pins required for installation."]}
    wiper = {"reference_id": "2", "file_path": "WiperBlade-Cat26.md",
             "content": ["--- [Trang 14 | ngôn ngữ: de] ---\nInstallation Type Availability: guide pins required."]}
    guide = {"reference_id": "3", "file_path": "Diesel_SCV.md",
             "content": ["--- [Trang 7 | ngôn ngữ: fr] ---\nInstaller les 2 goupilles de guidage."]}
    answer = "Yes, both the German and French language sections agree that two guide pins are required [1]."
    kept = only_cited([images, wiper, guide], answer, {"de", "fr"})
    assert [r["reference_id"] for r in kept] == ["3", "1"]


def test_a_comparison_drops_another_document_even_when_the_model_cites_it():
    from app import only_cited

    images = {"reference_id": "1", "file_path": "Diesel_SCV - images.md",
              "content": ["--- [Trang 5 | ngôn ngữ: de] ---\nZwei Führungsstifte: two guide pins required for installation."]}
    wiper = {"reference_id": "2", "file_path": "WiperBlade-Cat26.md",
             "content": ["--- [Trang 14 | ngôn ngữ: de] ---\nInstallation: two guide pins required for installation."]}
    guide = {"reference_id": "3", "file_path": "Diesel_SCV.md",
             "content": ["--- [Trang 7 | ngôn ngữ: fr] ---\nInstaller les 2 goupilles de guidage."]}
    answer = "Yes, both the German and French language sections agree that two guide pins are required [2][3]."
    kept = only_cited([images, wiper, guide], answer, {"de", "fr"})
    assert sorted(r["reference_id"] for r in kept) == ["1", "3"]
