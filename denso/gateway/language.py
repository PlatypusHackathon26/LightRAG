"""Question language and the per-request instruction that keeps the answer in it.

LightRAG's answer prompt already says "same language as the user query", yet answers mixed
languages: a Vietnamese answer quoted the Romanian and Russian sections, or kept English
sentences from the source. The gateway names the language explicitly for every question.
"""

from __future__ import annotations

import re

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

# Letters only Vietnamese uses among the languages we see (not French / Portuguese accents).
VIETNAMESE = re.compile(r"[ăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.IGNORECASE)
KANA = re.compile(r"[぀-ヿ]")
HAN = re.compile(r"[一-鿿]")
HANGUL = re.compile(r"[가-힯]")

NAMES = {
    "vi": "tiếng Việt", "en": "English", "ja": "日本語", "zh-cn": "中文", "ko": "한국어",
    "de": "Deutsch", "fr": "français", "es": "español", "ru": "русский", "th": "ภาษาไทย",
}

INSTRUCTION = {
    "vi": ("Trả lời HOÀN TOÀN bằng tiếng Việt. Dịch mọi nội dung lấy từ tài liệu tiếng Anh hay tiếng khác "
           "sang tiếng Việt; không chép nguyên câu tiếng nước ngoài. Chỉ giữ nguyên mã sản phẩm, số hiệu, "
           "môi chất lạnh, đơn vị và tên tài liệu. Không trộn hai ngôn ngữ trong cùng một câu. "
           # The example carries no value: a model must never copy a figure from the instruction.
           "Trả lời thành câu tiếng Việt hoàn chỉnh: nhắc lại đúng điều câu hỏi hỏi, rồi nêu điều tài liệu "
           "ghi cho chính điều đó; không chỉ ghi con số (ví dụ: \"Phần tiếng Nga ghi mô-men xoắn siết "
           "bu-lông là … Nm.\")."),
    "ja": ("回答はすべて日本語で書いてください。英語など他の言語の資料の内容は日本語に訳し、外国語の文をそのまま"
           "引用しないでください。製品コード・型番・冷媒・単位・資料名だけは原文のままにしてください。"),
}


# Language sections a question can ask about ("the Russian section", "phần tiếng Đức").
NAMED = {
    "english": "en", "russian": "ru", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
    "polish": "pl", "portuguese": "pt", "romanian": "ro", "japanese": "ja", "vietnamese": "vi",
    "tiếng anh": "en", "tiếng nga": "ru", "tiếng đức": "de", "tiếng pháp": "fr", "tiếng tây ban nha": "es",
    "tiếng ý": "it", "tiếng ba lan": "pl", "tiếng bồ đào nha": "pt", "tiếng rumani": "ro", "tiếng romania": "ro",
    "tiếng nhật": "ja", "tiếng việt": "vi", "英語": "en", "ロシア語": "ru", "ドイツ語": "de", "フランス語": "fr",
}


def named_languages(question: str) -> set[str]:
    """Languages whose section the question asks about, e.g. {"ru", "en"} for Q27."""
    q = question.lower()
    return {code for name, code in NAMED.items() if name in q}


def question_language(text: str) -> str | None:
    """ISO code of the question's language: script heuristics first, then langdetect."""
    if VIETNAMESE.search(text):
        return "vi"
    if KANA.search(text):
        return "ja"
    if HANGUL.search(text):
        return "ko"
    if HAN.search(text):
        return "zh-cn"
    letters = re.sub(r"[\W\d_]", "", text)
    if len(letters) < 3:
        return None
    try:
        return detect(text)
    except LangDetectException:
        return None


def language_instruction(question: str) -> str:
    """Instruction appended to the answer prompt for this question (empty if undetectable)."""
    lang = question_language(question)
    if not lang:
        return ""
    if lang in INSTRUCTION:
        return INSTRUCTION[lang]
    name = NAMES.get(lang, lang)
    return (f"Write the whole answer in {name} (the language of the question). Translate any content taken "
            f"from documents in other languages; do not copy foreign-language sentences. Keep only part "
            f"numbers, codes, refrigerants, units and document names verbatim. Never mix languages in a sentence.")
