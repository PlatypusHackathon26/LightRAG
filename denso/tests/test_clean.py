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


def test_multilingual_toc_page_is_mixed_not_guessed():
    # Regression: the Installation Manual TOC (17 languages) was tagged 'ca'.
    toc = (
        "EN A/C Compressor Installation Guide RU Компрессор кондиционера "
        "PL Sprężarka klimatyzacji przewodnik DE Klimakompressor Einbauanleitung "
        "FR Compresseur de climatisation Guide d'installation HU Klímakompresszor beépítési útmutató"
    )
    assert detect_lang(toc) == "mixed"
    assert detect_lang("Fit the bolts and tighten them with the torque given in the table below.") == "en"


def test_running_headers_detected_only_when_repeated():
    pages = ["Diesel Common Rail System\nbody one", "Diesel Common Rail System\nbody two", "Diesel Common Rail System\nbody three"]
    assert repeated_lines(pages) == {"Diesel Common Rail System"}
    assert repeated_lines(pages[:2]) == set()
