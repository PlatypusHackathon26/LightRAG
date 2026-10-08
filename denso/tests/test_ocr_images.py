"""Tests for reading text inside PDF images (denso/pipeline/ocr_images.py), no API calls."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from ocr_images import collect_images, page_context, write_markdown  # noqa: E402


def _picture(seed: int, size=(300, 400)) -> Image.Image:
    # Noisy content so JPEG stays above the size threshold and each picture hashes differently.
    img = Image.new("RGB", size, (seed * 40 % 255, 120, 200))
    d = ImageDraw.Draw(img)
    for i in range(0, size[0], 7):
        d.line([(i, 0), (size[0] - i, size[1])], fill=((i * seed) % 255, (i * 3) % 255, (i * 7) % 255), width=2)
    return img


def test_decorations_icons_and_untiered_pages_are_skipped(tmp_path):
    logo, can = _picture(1), _picture(2)
    icon = _picture(3, size=(40, 40))
    pages = [logo, logo, logo, logo, can, icon]  # logo on 4 pages = decoration
    pdf = tmp_path / "doc.pdf"
    Image.init()  # registers the JPEG writer the PDF plugin embeds pictures with
    pages[0].save(pdf, save_all=True, append_images=pages[1:])
    found = collect_images(pdf, None, min_px=120, min_bytes=2000, max_repeat=3)
    assert [v["pages"] for v in found.values()] == [[5]]
    assert collect_images(pdf, (1, 4), min_px=120, min_bytes=2000, max_repeat=3) == {}


def test_page_context_reads_language_and_headings(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("--- [Trang 12 | ngôn ngữ: en] ---\n\n####### Storage\n\ntext\n\n####### Shelf life\n\n"
                  "--- [Trang 13 | ngôn ngữ: de] ---\n\n## Lagerung\n", encoding="utf-8")
    ctx = page_context(md)
    assert ctx[12] == {"lang": "en", "headings": ["Storage", "Shelf life"]}
    assert ctx[13]["lang"] == "de"


def test_markdown_keeps_page_markers_and_drops_empty_reads(tmp_path):
    (tmp_path / "doc.md").write_text("--- [Trang 12 | ngôn ngữ: en] ---\n\n####### Shelf life\n", encoding="utf-8")
    cache = {
        "a": {"pages": [12], "text": "A can of DENSO ND-OIL 11 compressor oil for HFC-134a / HFO-1234yf."},
        "b": {"pages": [12], "text": "NO TEXT"},
        "c": {"pages": [3], "text": "ok"},  # too short to carry information
    }
    out = write_markdown("doc", cache, tmp_path)
    text = out.read_text(encoding="utf-8")
    assert out.name == "doc - images.[native-P!].md"  # vector-only hint: no entity extraction
    assert "--- [Trang 12 | ngôn ngữ: en] ---" in text and "Các mục trên trang này: Shelf life." in text
    assert "ND-OIL 11" in text and "NO TEXT" not in text and "Trang 3 " not in text


def test_nothing_readable_writes_no_file(tmp_path):
    assert write_markdown("doc", {"a": {"pages": [1], "text": "NO TEXT"}}, tmp_path) is None


def test_an_image_on_several_pages_is_listed_under_each(tmp_path):
    cache = {"a": {"pages": [11, 12, 15], "text": "A can of DENSO ND-OIL 8 compressor oil, 250 ml, DND08250."}}
    text = write_markdown("doc", cache, tmp_path).read_text(encoding="utf-8")
    assert all(f"--- [Trang {p} | " in text for p in (11, 12, 15))


def test_looping_transcriptions_are_collapsed(tmp_path):
    looped = "A can of ND-OIL 11 compressor oil.\n" + "* ND-OIL 11\n" * 60 + "* HFC-134a"
    text = write_markdown("doc", {"a": {"pages": [12], "text": looped}}, tmp_path).read_text(encoding="utf-8")
    assert text.count("* ND-OIL 11") == 1 and "* HFC-134a" in text


def test_images_of_a_document_not_recorded_as_level_1_never_leave_the_machine(tmp_path, monkeypatch, capsys):
    import json

    import ocr_images

    raw, parsed = tmp_path / "raw", tmp_path / "parsed"
    for stem, level in [("secret", 2), ("unparsed", None)]:
        raw.mkdir(exist_ok=True)
        (raw / f"{stem}.pdf").write_bytes(b"%PDF-1.7")
        if level:
            (parsed / stem).mkdir(parents=True)
            (parsed / stem / "meta.json").write_text(json.dumps({"access_level": level}), encoding="utf-8")
    monkeypatch.setattr(ocr_images, "collect_images", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read")))
    monkeypatch.setattr("sys.argv", ["ocr_images.py", "--raw", str(raw), "--parsed", str(parsed),
                                     "--cleaned", str(tmp_path), "--dry-run"])
    ocr_images.main()
    out = capsys.readouterr().out
    assert "secret: skipped (access level 2" in out and "unparsed: skipped (access level unknown" in out
