"""Scanned-page transcription (denso/pipeline/ocr_pages.py), with the vision model mocked."""

import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import ocr_pages  # noqa: E402
from ocr_pages import PAGE_BREAK, replace_pages, scan_pages  # noqa: E402


def scan_image(text: str = "Đánh dấu vị trí giắc nối") -> Image.Image:
    img = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(img).text((20, 20), text, fill="black")
    return img


def test_an_image_upload_is_one_scanned_page(tmp_path):
    f = tmp_path / "ghi chu.png"
    scan_image().save(f)
    assert list(scan_pages(f)) == [1]


def test_only_pdf_pages_without_a_text_layer_are_scanned(tmp_path):
    # Page 1: an image-only scan. Page 2 is the same scan: both are pages only OCR can read.
    pdf = tmp_path / "phieu.pdf"
    scan_image().save(pdf, save_all=True, append_images=[scan_image("Siết 6,9 – 10,8 Nm")])
    assert sorted(scan_pages(pdf)) == [1, 2]
    assert scan_pages(tmp_path / "notes.docx") == {}


def test_replace_pages_swaps_only_the_scanned_pages():
    md = f"page one{PAGE_BREAK}page two{PAGE_BREAK}page three"
    out = replace_pages(md, {2: "Lắp 2 chốt dẫn hướng"}).split(PAGE_BREAK)
    assert out[0] == "page one" and out[1].strip() == "Lắp 2 chốt dẫn hướng" and out[2] == "page three"
    assert len(replace_pages("only", {3: "x"}, total=3).split(PAGE_BREAK)) == 3


def _doc(tmp_path, level: int) -> tuple[argparse.Namespace, Path]:
    raw = tmp_path / "raw" / "scan.png"
    raw.parent.mkdir()
    scan_image().save(raw)
    doc = tmp_path / "parsed" / "scan"
    doc.mkdir(parents=True)
    (doc / "meta.json").write_text(json.dumps({"access_level": level, "source_path": str(raw),
                                               "source_file": "scan.png"}), encoding="utf-8")
    (doc / "docling.md").write_text("Đánh du vi trí gic ni", encoding="utf-8")
    args = argparse.Namespace(parsed=tmp_path / "parsed", raw=tmp_path / "raw", model="m")
    return args, doc


def test_the_transcription_replaces_doclings_text_and_keeps_the_original(tmp_path, monkeypatch):
    args, doc = _doc(tmp_path, 1)

    async def fake(pages, cache, cache_path, args, key):
        return {1: "Đánh dấu vị trí giắc nối"}

    monkeypatch.setattr(ocr_pages, "transcribe", fake)
    assert ocr_pages.process("scan", args, "key") == 1
    assert (doc / "docling.md").read_text(encoding="utf-8").strip() == "Đánh dấu vị trí giắc nối"
    assert (doc / "docling_ocr.md").read_text(encoding="utf-8") == "Đánh du vi trí gic ni"
    # A re-upload parses again: its fresh docling.md becomes the original, not the old one.
    (doc / "docling.md").write_text("Bản mới của Docling", encoding="utf-8")
    ocr_pages.process("scan", args, "key")
    assert (doc / "docling_ocr.md").read_text(encoding="utf-8") == "Bản mới của Docling"


def test_page_images_of_a_document_above_level_1_never_leave_the_machine(tmp_path, monkeypatch):
    args, doc = _doc(tmp_path, 2)

    async def fail(*a, **k):
        raise AssertionError("a level-2 page was sent")

    monkeypatch.setattr(ocr_pages, "transcribe", fail)
    assert ocr_pages.process("scan", args, "key") == 0
    assert (doc / "docling.md").read_text(encoding="utf-8") == "Đánh du vi trí gic ni"


def test_the_models_framing_is_not_part_of_the_page():
    # Seen live: "The text in the scanned page is transcribed as follows:" opened the photo's page.
    from ocr_pages import clean_transcription

    text = "The text in the scanned page is transcribed as follows:\n\n```\n| Oil | Code |\n```"
    assert clean_transcription(text) == "| Oil | Code |"
    assert clean_transcription("Here is the transcription:\nĐánh dấu") == "Đánh dấu"
    assert clean_transcription("The text below says 2 pins.") == "The text below says 2 pins."  # no colon: content


def test_unusual_image_formats_are_sent_as_png():
    buf = io.BytesIO()
    scan_image().save(buf, format="TIFF")
    assert ocr_pages.as_png(buf.getvalue()).startswith(b"\x89PNG")
