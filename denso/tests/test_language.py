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
    # English questions get none: it flipped a correct table answer (Oil 9 -> ND-oil 8).
    assert language_instruction("What oil is used for a TV compressor with R-134a?") == ""


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


def test_a_procedure_answer_cites_the_pages_of_one_language_not_every_translation():
    # Seen live: a Vietnamese SCV-procedure answer cited "4, 6, 7, 10, 12, 14, ...".
    from app import to_citations

    chunk = ("--- [Trang 4 | ngôn ngữ: en] ---\nInstall 1 new O-ring. Install the SCV Common Rail pump guide pins.\n"
             "--- [Trang 6 | ngôn ngữ: de] ---\nNeuen O-Ring einsetzen. SCV Common Rail Pumpe.\n"
             "--- [Trang 7 | ngôn ngữ: es] ---\nInstalar O-ring nuevo. SCV Common Rail bomba.")
    ref = {"reference_id": "1", "file_path": "Diesel_SCV.md", "content": [chunk]}
    answer = "Quy trình lắp SCV lên bơm Common Rail: 1. Lắp O-ring mới. 2. Lắp chốt dẫn hướng. [1]"
    (c,) = to_citations([ref], answer)
    assert c["pages"] == "4"


def test_a_short_comparison_answer_still_cites_the_document_holding_both_sections():
    # Seen live (Q28): "both say 2 guide pins" shared too few words with any chunk and got no source.
    from app import only_cited

    guide = {"reference_id": "3", "file_path": "Diesel_SCV.md",
             "content": ["--- [Trang 6 | ngôn ngữ: de] ---\nZwei Führungsstifte.\n"
                         "--- [Trang 10 | ngôn ngữ: fr] ---\nDeux goupilles."]}
    plug = {"reference_id": "4", "file_path": "Spark Plug Catalogue 2025.md",
            "content": ["--- [Trang 2 | ngôn ngữ: en] ---\nHeat range table."]}
    kept = only_cited([plug, guide], "Yes, both say two.", {"de", "fr"})
    assert [r["reference_id"] for r in kept] == ["3"]


def test_tied_pages_prefer_the_english_section():
    # Seen live: a Vietnamese procedure answer cited the Spanish page 7 instead of English 3-4.
    from app import to_citations

    chunk = ("--- [Trang 7 | ngôn ngữ: es] ---\nInstalar O-ring nuevo. SCV Common Rail bomba.\n"
             "--- [Trang 4 | ngôn ngữ: en] ---\nInstall 1 new O-ring. SCV Common Rail pump.")
    ref = {"reference_id": "1", "file_path": "Diesel_SCV.md", "content": [chunk]}
    (c,) = to_citations([ref], "Lắp O-ring mới cho SCV trên bơm Common Rail. [1]")
    assert c["pages"] == "4"


def test_fallback_pages_of_a_multilingual_manual_are_the_english_ones():
    # Seen live: a Vietnamese run-in answer cited pages 44-45 (another translation) of the manual.
    from app import pages_from_chunks

    chunks = ["--- [Trang 44 | ngôn ngữ: tr] ---\nRodaj prosedürü.", "--- [Trang 5 | ngôn ngữ: en] ---\nRun in procedure."]
    assert pages_from_chunks(chunks) == "5"


def test_short_plain_ascii_questions_are_english():
    # Seen live: langdetect read "SCV torque?" as Spanish, so the reranker boosted the Spanish section.
    for q in ["SCV torque?", "Oil 9 use?", "ND-oil 8 part number?"]:
        assert question_language(q) == "en"
        assert language_instruction(q) == ""


def test_a_vietnamese_answer_cites_the_vietnamese_slide_that_says_it():
    # Seen live: an alpha-beta answer cited p.40 ("200 million node evaluations ... alpha-beta"),
    # the only page sharing English words with it, not the Vietnamese slides that define it.
    from app import to_citations

    chunk = ("--- [Trang 35 | ngôn ngữ: vi] ---\n- α là giá trị tốt nhất (giá trị cao nhất) tính đến thời điểm hiện "
             "tại cho người chơi MAX.\n- β là giá trị tốt nhất (giá trị thấp nhất) cho người chơi MIN.\n"
             "--- [Trang 40 | ngôn ngữ: en] ---\n- Baseline system: 200 million node evaluations per move, minimax "
             "with alpha-beta pruning.")
    ref = {"reference_id": "1", "file_path": "Bai 5.md", "content": [chunk]}
    answer = ("Alpha-beta pruning dùng hai giá trị: α là giá trị tốt nhất (cao nhất) mà người chơi MAX có được, "
              "β là giá trị tốt nhất (thấp nhất) cho người chơi MIN, để bỏ các nhánh minimax không cần thiết.")
    (c,) = to_citations([ref], answer)
    assert c["pages"] == "35"


def test_a_bare_formula_answer_cites_the_page_it_is_printed_on():
    from app import only_cited, to_citations

    ref = {"reference_id": "1", "file_path": "Bai 5.md", "content": [
        "--- [Trang 26 | ngôn ngữ: en] ---\n- Time complexity? O(b m)\n"
        "--- [Trang 34 | ngôn ngữ: vi] ---\n- Với một \"sắp xếp hoàn hảo\", time complexity = O(b m/2) từ O(b m)."]}
    other = {"reference_id": "2", "file_path": "Spark Plug Catalogue 2025.md", "content": ["--- [Trang 3] ---\nHeat range"]}
    kept = only_cited([ref, other], "O(b m/2)")
    assert [r["reference_id"] for r in kept] == ["1"]
    assert to_citations(kept, "O(b m/2)")[0]["pages"] == "34"


def test_the_chunk_kept_for_pages_is_chosen_in_the_answers_language_too():
    # Seen live: the chunk holding pp. 29-36 lost to chunks naming Kasparov / Minimax in English,
    # and a Vietnamese alpha-beta answer cited pp. 8, 9, 46.
    from app import to_citations

    defining = ("--- [Trang 34 | ngôn ngữ: vi] ---\n- Phương pháp cắt cụt alpha-beta không ảnh hưởng đến kết quả cuối "
                "cùng, chỉ ảnh hưởng đến thời gian tìm kiếm. Thứ tự sắp xếp các bước đi có ảnh hưởng lớn.")
    names = ("--- [Trang 45 | ngôn ngữ: en] ---\n- Chess: Deep Blue defeated Garry Kasparov in 1997, searching "
             "200 million positions with alpha-beta and minimax extensions.")
    ref = {"reference_id": "1", "file_path": "Bai 5.md", "content": [names, defining]}
    answer = ("Cắt cụt alpha-beta không ảnh hưởng đến kết quả cuối cùng của minimax, chỉ ảnh hưởng đến thời gian "
              "tìm kiếm; thứ tự sắp xếp các bước đi có ảnh hưởng lớn. Deep Blue đã thắng Garry Kasparov.")
    (c,) = to_citations([ref], answer)
    assert "34" in c["pages"].split(", ")
