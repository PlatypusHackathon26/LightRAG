"""Generic text cleaning helpers.

Copied from denso-a3-data-pipeline/utils/text_cleaner.py (team repo) so the
LightRAG pipeline does not depend on that checkout. Keep the two in sync.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List

# Ký tự điều khiển / zero-width thường xuất hiện khi extract PDF hoặc audio transcript.
_CONTROL_CHARS_RE = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff]")
_INLINE_SPACE_RE = re.compile(r"[ \t\u00a0\u2000-\u200a]+")
_MULTI_BLANK_LINE_RE = re.compile(r"\n{3,}")
# Nối từ bị ngắt dòng bằng gạch nối ở cuối dòng: "compres-\nsor" -> "compressor"
_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\s*\n\s*(\w)")
# Khoảng trắng trước dấu câu: " ," -> ","
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?%)\]}])")


def normalize_unicode(text: str, form: str = "NFC") -> str:
    """Chuẩn hoá Unicode (mặc định NFC) để so khớp/khử trùng lặp ổn định."""
    return unicodedata.normalize(form, text)


def strip_control_chars(text: str) -> str:
    """Loại bỏ ký tự điều khiển và ký tự zero-width giữ lại ``\\n``/``\\t``."""
    return _ZERO_WIDTH_RE.sub("", _CONTROL_CHARS_RE.sub("", text))


def dehyphenate(text: str) -> str:
    """Ghép lại các từ bị ngắt dòng bằng gạch nối (lỗi rất phổ biến ở PDF)."""
    return _HYPHEN_LINEBREAK_RE.sub(r"\1\2", text)


def collapse_whitespace(text: str, *, keep_newlines: bool = True) -> str:
    """Gộp khoảng trắng thừa; nếu ``keep_newlines=False`` thì gộp cả xuống dòng."""
    if not keep_newlines:
        return _INLINE_SPACE_RE.sub(" ", text.replace("\n", " ")).strip()

    lines = [_INLINE_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return _MULTI_BLANK_LINE_RE.sub("\n\n", "\n".join(lines)).strip()


def clean_text(
    text: str,
    *,
    keep_newlines: bool = True,
    fix_hyphenation: bool = True,
) -> str:
    """Pipeline làm sạch chuẩn cho 1 khối văn bản.

    Thứ tự xử lý: Unicode -> control chars -> dehyphenate -> whitespace -> dấu câu.
    """
    if not text:
        return ""

    cleaned = normalize_unicode(text)
    cleaned = strip_control_chars(cleaned)
    if fix_hyphenation:
        cleaned = dehyphenate(cleaned)
    cleaned = collapse_whitespace(cleaned, keep_newlines=keep_newlines)
    return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)


def clean_blocks(
    blocks: Iterable[str],
    *,
    drop_empty: bool = True,
    **clean_kwargs: object,
) -> List[str]:
    """Làm sạch từng phần tử của danh sách khối (page/paragraph/segment)."""
    cleaned: List[str] = []
    for block in blocks:
        value = clean_text(block, **clean_kwargs)  # type: ignore[arg-type]
        if value or not drop_empty:
            cleaned.append(value)
    return cleaned


def drop_short_blocks(blocks: Iterable[str], min_chars: int = 2) -> List[str]:
    """Bỏ các khối quá ngắn (header/footer/số trang lẻ) trước khi detect ngôn ngữ."""
    return [block for block in blocks if len(block.strip()) >= min_chars]
