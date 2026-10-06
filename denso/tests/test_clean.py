"""Regression tests for the cleaning rules, built from real Docling output."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from clean import clean_page, detect_lang, is_junk_line, is_letter_spaced, join_ocr_splits, repeated_lines  # noqa: E402


def joined(line: str, lang: str = "en") -> str:
    return join_ocr_splits(line, lang, [])


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Ref ri gerant Type", "Refrigerant Type"),
        ("a comfort able cabin", "a comfortable cabin"),
        ("fixed displacement t ype: 10PA", "fixed displacement type: 10PA"),
    ],
)
def test_joins_ocr_splits(raw, expected):
    assert joined(raw) == expected


@pytest.mark.parametrize(
    "raw, lang",
    [
        ("take a part of it", "en"),  # 'apart' is a word, but 'a part' is too
        ("com o motor", "pt"),  # Portuguese 'with the'
        ("Dual Swash Plate", "en"),  # capitalised follow-up words
        ("DENSO Oil 8", "en"),  # acronym
        ("bảo trì máy dập", "vi"),  # Vietnamese syllables are never joined
    ],
)
def test_keeps_real_word_pairs(raw, lang):
    assert joined(raw, lang) == raw


def test_letter_spaced_print_codes_are_junk():
    assert is_letter_spaced("www.denso-am.eu P r i n t e d i n B")
    assert is_letter_spaced("D E A")


def test_bullet_marker_is_not_counted_as_letter_spacing():
    # Regression: '- > Condensers' was dropped as letter-spaced.
    assert not is_letter_spaced("- > Condensers")
    assert is_junk_line("- > Condensers", "en") is None


@pytest.mark.parametrize("line", ["0", "o", "审", "<!-- image -->"])
def test_short_and_placeholder_lines_are_junk(line):
    assert is_junk_line(line, "en") is not None


def test_page_keeps_every_bullet_and_cleans_entities():
    raw = "- &gt; Condensers\n- &gt; Receiver Driers\n\n<!-- image -->\n\n申\n"
    import html

    blocks, tables, report = clean_page(html.unescape(raw), 2, set())
    assert blocks == ["- Condensers", "- Receiver Driers"]
    assert tables == []
    assert len(report.dropped) == 2


def test_tables_are_recompacted_with_page_number():
    raw = (
        "Intro text for the oil table on this page.\n\n"
        "| Compressor Type   | Ref ri gerant Type |\n"
        "|-------------------|--------------------|\n"
        "| Vane-type (TV)    | HFC134a (R-134a)   |\n"
    )
    blocks, tables, _ = clean_page(raw, 2, set())
    assert tables == [
        {"page": 2, "markdown": "| Compressor Type | Refrigerant Type |\n|---|---|\n| Vane-type (TV) | HFC134a (R-134a) |"}
    ]
    assert tables[0]["markdown"] in blocks


def test_large_tables_get_a_page_column_but_json_tables_do_not():
    # Regression: split slices of big tables (NGK cross reference, pp.10-15)
    # lost their page marker, so 42/74 Spark Plug chunks could not cite a page.
    rows = "".join(f"| BKR{i}ES | K{i}TT |\n" for i in range(400))
    raw = "| NGK TYPE | DENSO |\n|---|---|\n" + rows
    blocks, tables, _ = clean_page(raw, 11, set())
    assert blocks[0].startswith("| Trang | NGK TYPE | DENSO |\n|---|---|---|\n| 11 | BKR0ES | K0TT |")
    assert all(line.startswith("| 11 | ") for line in blocks[0].split("\n")[2:])
    assert tables[0]["markdown"].startswith("| NGK TYPE | DENSO |")  # A3 JSON keeps the original table


def test_repeated_paragraph_on_same_page_is_dropped_once():
    # Real case: Spark Plug p.32 repeats one 127-char sentence 4 times.
    para = "Both electrodes are needle shaped for better ignitability and wider heat range, and the gap stays stable."
    raw = f"{para}\n\n{para}\n\nShort line here.\n\nShort line here.\n\n{para}\n"
    blocks, _, report = clean_page(raw, 32, set())
    assert blocks == [para, "Short line here.", "Short line here."]  # short lines are never deduplicated
    assert sum(d.startswith("duplicate_in_page") for d in report.dropped) == 2


def test_small_tables_are_left_alone():
    blocks, _, _ = clean_page("| A | B |\n|---|---|\n| 1 | 2 |\n", 3, set())
    assert blocks == ["| A | B |\n|---|---|\n| 1 | 2 |"]


def test_multilingual_toc_page_is_mixed_not_guessed():
    # Regression: the Installation Manual TOC (17 languages) was tagged 'ca'.
    toc = (
        "EN A/C Compressor Installation Guide RU Компрессор кондиционера "
        "PL Sprężarka klimatyzacji przewodnik DE Klimakompressor Einbauanleitung "
        "FR Compresseur de climatisation Guide d'installation HU Klímakompresszor beépítési útmutató"
    )
    assert detect_lang(toc) == "mixed"
    assert detect_lang("Fit the bolts and tighten them with the torque given in the table below.") == "en"


def test_footnote_legends_are_never_boilerplate():
    # Regression: the Wiper catalogue legend ('*2 No applicable item is available')
    # printed under every application table was removed from all 151 pages,
    # leaving '*2' markers in table cells unexplained.
    legend = "- *2 No applicable item is available"
    pages = [f"| Car | *2 |\n{legend}\n*7 Shorter than OEM wiper\nNotes footer {i % 1}" for i in range(6)]
    found = repeated_lines(pages)
    assert legend not in found and "*7 Shorter than OEM wiper" not in found
    assert "Notes footer 0" in found


def test_boilerplate_keeps_its_first_occurrence():
    boiler = {"Please take off the plastic part put on the wiper arm"}
    emitted: set[str] = set()
    first, _, _ = clean_page("Please take off the plastic part put on the wiper arm\nBody one.", 26, boiler, emitted)
    later, _, rep = clean_page("Please take off the plastic part put on the wiper arm\nBody two.", 27, boiler, emitted)
    assert first == ["Please take off the plastic part put on the wiper arm", "Body one."]
    assert later == ["Body two."] and rep.dropped == ["boilerplate: Please take off the plastic part put on the wiper arm"]


def test_running_headers_detected_only_when_repeated():
    pages = ["Diesel Common Rail System\nbody one", "Diesel Common Rail System\nbody two", "Diesel Common Rail System\nbody three"]
    assert repeated_lines(pages) == {"Diesel Common Rail System"}
    assert repeated_lines(pages[:2]) == set()
