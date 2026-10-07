"""Tests for the crash-safe helpers in parse.py (no docling-serve needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from parse import access_level_for, align_segments, page_ranges, write_atomic  # noqa: E402


def _doc(body_pages, furniture_pages=()):
    texts = [{"content_layer": "body", "prov": [{"page_no": p}]} for p in body_pages]
    texts += [{"content_layer": "furniture", "prov": [{"page_no": p}]} for p in furniture_pages]
    return {"texts": texts, "tables": [], "pictures": []}


def test_blank_pages_do_not_shift_later_pages():
    # Real case: Spark Plug pp.444-450 are blank "MEMO" pages; Docling's Markdown
    # had 5 segments for 12 pages, and padding at the end put p.451 on p.444.
    segs = ["p441", "p442", "p443", "p451", "p452"]
    pages, warning = align_segments(segs, 441, 452, _doc([441, 442, 443, 451, 452], furniture_pages=range(441, 453)))
    assert pages[0] == "p441" and pages[10] == "p451" and pages[11] == "p452"
    assert pages[3:10] == [""] * 7
    assert "aligned by page" in warning


def test_full_range_is_unchanged():
    assert align_segments(["a", "b"], 1, 2, None) == (["a", "b"], None)


def test_unexplained_gap_is_padded_and_flagged():
    pages, warning = align_segments(["a"], 1, 3, _doc([1, 2]))
    assert pages == ["a", "", ""] and "may be off" in warning


def test_page_ranges_cover_every_page_once():
    ranges = page_ranges(452, 20)
    assert ranges[0] == (1, 20)
    assert ranges[-1] == (441, 452)
    covered = [p for a, b in ranges for p in range(a, b + 1)]
    assert covered == list(range(1, 453))


def test_page_ranges_short_document():
    assert page_ranges(4, 20) == [(1, 4)]


def test_write_atomic_leaves_no_temp_file(tmp_path):
    target = tmp_path / "meta.json"
    write_atomic(target, "{}")
    write_atomic(target, '{"ok": true}')
    assert target.read_text(encoding="utf-8") == '{"ok": true}'
    assert list(tmp_path.iterdir()) == [target]


def test_access_level_from_folder_or_flag():
    assert access_level_for(Path("data/raw/level_3/sop.pdf"), None) == 3
    assert access_level_for(Path("data/raw/sop.pdf"), None) == 1
    assert access_level_for(Path("data/raw/level_3/sop.pdf"), 2) == 2
