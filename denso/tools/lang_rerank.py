"""Reranker that puts chunks in the question's language first (Cohere-compatible /rerank).

Order: question language > English > other translations; picture descriptions last. A question
about named language sections ("the Russian section") boosts those languages instead.

Run:  python denso/tools/lang_rerank.py      (.env: RERANK_BINDING_HOST=http://127.0.0.1:7998/rerank)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

# The gateway's detector, so both agree on a question's language (langdetect alone read
# "SCV torque?" as Spanish here while the gateway's heuristics did not).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
from language import question_language  # noqa: E402

CHUNK_LANG = re.compile(r"ngôn ngữ: ([a-z]{2}(?:-[a-z]{2})?)")
# Language names (English and Vietnamese) -> langdetect codes. A question naming a language
# other than its own ("the Russian section", "tiếng Đức") is cross-lingual: keep vector order.
LANGUAGE_CODES = {
    "english": "en", "russian": "ru", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
    "polish": "pl", "portuguese": "pt", "romanian": "ro", "dutch": "nl", "greek": "el", "czech": "cs",
    "slovak": "sk", "hungarian": "hu", "swedish": "sv", "bulgarian": "bg", "croatian": "hr", "serbian": "sr",
    "turkish": "tr", "chinese": "zh-cn", "japanese": "ja", "korean": "ko", "vietnamese": "vi",
    "tiếng anh": "en", "tiếng nga": "ru", "tiếng đức": "de", "tiếng pháp": "fr", "tiếng tây ban nha": "es",
    "tiếng ý": "it", "tiếng ba lan": "pl", "tiếng bồ đào nha": "pt", "tiếng rumani": "ro",
    "tiếng hà lan": "nl", "tiếng hy lạp": "el", "tiếng séc": "cs", "tiếng hungary": "hu",
    "tiếng thụy điển": "sv", "tiếng bulgaria": "bg", "tiếng thổ nhĩ kỳ": "tr", "tiếng trung": "zh-cn",
    "tiếng nhật": "ja", "tiếng hàn": "ko", "tiếng việt": "vi",
}
LANGUAGE_NAMES = re.compile(r"\b(" + "|".join(sorted(map(re.escape, LANGUAGE_CODES), key=len, reverse=True)) + r")\b",
                            re.IGNORECASE)
# Wording that asks about several languages at once, whatever language is named.
MULTI_LANGUAGE = re.compile(r"\b(multilingual|translations?|language versions?|other languages?)\b|"
                            r"ngôn ngữ (khác|nào)|đa ngôn ngữ", re.IGNORECASE)
LANG_BOOST = 2.0  # tiers: question language > English (FALLBACK_BOOST) > other translations
FALLBACK_BOOST = 1.0
TEXT_FLOOR = 1.0
MAX_SCORE = TEXT_FLOOR + 1.0 + LANG_BOOST
IMAGE_CHUNK = re.compile(r"^#{2,3} Ảnh |^# Chữ và hình trong ảnh", re.MULTILINE)
FALLBACK_LANG = "en"


def chunk_languages(text: str) -> set[str]:
    return set(CHUNK_LANG.findall(text))


def is_cross_lingual(query: str, lang: str | None = None) -> bool:
    """True when the question asks about a language other than its own (or several)."""
    if MULTI_LANGUAGE.search(query):
        return True
    lang = lang or question_language(query)
    named = {LANGUAGE_CODES[m.group(1).lower()] for m in LANGUAGE_NAMES.finditer(query)}
    return bool(named - {lang})


def is_image_text(text: str) -> bool:
    """A chunk of an ocr_images.py document (descriptions of pictures, not the document's text)."""
    return bool(IMAGE_CHUNK.search(text))


def rank(query: str, documents: list[str]) -> list[tuple[int, float]]:
    """Return (index, score) sorted best first; scores in [0, MAX_SCORE].

    Base score keeps the incoming (vector) order: 1 - i/n. Chunks tagged with the
    question's language get +1; untagged chunks keep their base score. A
    cross-lingual question boosts the languages it names instead (none named, e.g.
    "other languages": plain vector order). Document text always ranks
    above picture descriptions (+TEXT_FLOOR): sixteen SCV-guide image captions pushed
    the French section out of the context and the model invented its pin count.
    Scores stay positive - LightRAG drops chunks below MIN_RERANK_SCORE (0).
    """
    n = max(len(documents), 1)
    lang = question_language(query)
    wanted: set[str] = set()
    if is_cross_lingual(query, lang):
        # "Do the German and French sections agree?": the named sections, in vector order.
        # English is left out: every catalogue is English, and boosting it pushed the Russian
        # section of "Russian vs English" out of the context.
        wanted = {LANGUAGE_CODES[m.group(1).lower()] for m in LANGUAGE_NAMES.finditer(query)} - {FALLBACK_LANG}
        lang = None
    elif lang and not any(lang in chunk_languages(d) for d in documents):
        # No section in the question's language (a Vietnamese question over English/multilingual
        # manuals): prefer English, the manuals' source language, over its translations.
        lang = FALLBACK_LANG
    scored = []
    for i, doc in enumerate(documents):
        score = 1.0 - i / n
        if is_image_text(doc):
            score *= 0.5  # in [0, 0.5]: below every text chunk, still usable if room is left
            if wanted & chunk_languages(doc):
                # The SCV guide's Russian section reaches the pool only as its pages' OCR text.
                score += TEXT_FLOOR + LANG_BOOST
        else:
            score += TEXT_FLOOR
            langs = chunk_languages(doc)
            if (lang and lang in langs) or (wanted & langs):
                score += LANG_BOOST
            elif lang and lang != FALLBACK_LANG and FALLBACK_LANG in langs:
                # English (the source language) second, above the other translations: with one
                # Vietnamese upload in the pool, a Vietnamese question's context was filled with
                # the Romanian, Spanish, Croatian... run-in sections and the English one left out.
                score += FALLBACK_BOOST
        scored.append((i, round(score, 6)))
    return sorted(scored, key=lambda x: -x[1])


class RerankRequest(BaseModel):
    query: str
    documents: list[Any]
    model: str | None = None
    top_n: int | None = None


def doc_text(doc: Any) -> str:
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return str(doc.get("text") or doc.get("content") or "")
    return str(doc)


def create_app() -> FastAPI:
    app = FastAPI(title="DENSO language-preference reranker")

    @app.post("/rerank")
    def rerank(req: RerankRequest) -> dict:
        order = rank(req.query, [doc_text(d) for d in req.documents])
        if req.top_n:
            order = order[: req.top_n]
        return {
            "id": "denso-lang-pref",
            "results": [{"index": i, "relevance_score": s / MAX_SCORE} for i, s in order],  # scale to [0, 1]
            "meta": {"model": req.model or "denso-lang-pref", "cross_lingual": is_cross_lingual(req.query)},
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7998)
    args = ap.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
