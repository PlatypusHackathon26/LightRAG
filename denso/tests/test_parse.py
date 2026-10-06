"""Tests for the crash-safe helpers in parse.py (no docling-serve needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from parse import access_level_for, page_ranges, write_atomic  # noqa: E402


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
