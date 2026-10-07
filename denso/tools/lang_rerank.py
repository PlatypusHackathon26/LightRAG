"""Query-language-aware "reranker" with a Cohere-compatible /rerank endpoint.

The cleaned Markdown tags every page with "ngôn ngữ: xx". Multilingual manuals
repeat the same section in up to 17 languages, and the multilingual embedding
model ranks the translations about as high as the section in the question's
language, crowding it out of the context (benchmark Q6). This service keeps
LightRAG's vector order but moves chunks whose language matches the question
to the front - EXCEPT when the question names another language ("the Russian
section", "tiếng Đức"), where it keeps the vector order untouched (Q27/Q28).

Offline on the 28 answerable benchmark questions (pool 30, eval_rerank.py
strategy "lang-pref"): hit@1 68% -> 75%, hit@10 93% -> 100%, every citation in
the top 10 93% -> 100%. Plain language preference without the cross-lingual
exception pushed Q11/Q27/Q28 down to rank 19-30. The cross-encoder on CPU was
slower (84 s per question) and worse at hit@1. See denso/results/rerank_*.md.

LightRAG wiring (.env):
    RERANK_BINDING=cohere
    RERANK_BINDING_HOST=http://127.0.0.1:7998/rerank
    RERANK_MODEL=denso-lang-pref
    CHUNK_TOP_K=30        # candidate pool; MAX_TOTAL_TOKENS then keeps the best ~12

Run:  python denso/tools/lang_rerank.py
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from fastapi import FastAPI
from langdetect import DetectorFactory, LangDetectException, detect
from pydantic import BaseModel

DetectorFactory.seed = 0
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
LANG_BOOST = 1.0
FALLBACK_LANG = "en"


def question_language(query: str) -> str | None:
    try:
        return detect(query)
    except LangDetectException:
        return None


def chunk_languages(text: str) -> set[str]:
    return set(CHUNK_LANG.findall(text))


def is_cross_lingual(query: str, lang: str | None = None) -> bool:
    """True when the question asks about a language other than its own (or several)."""
    if MULTI_LANGUAGE.search(query):
        return True
    lang = lang or question_language(query)
    named = {LANGUAGE_CODES[m.group(1).lower()] for m in LANGUAGE_NAMES.finditer(query)}
    return bool(named - {lang})


def rank(query: str, documents: list[str]) -> list[tuple[int, float]]:
    """Return (index, score) sorted best first; scores in [0, 2].

    Base score keeps the incoming (vector) order: 1 - i/n. Chunks tagged with the
    question's language get +1; untagged chunks keep their base score. A
    cross-lingual question gets the plain vector order.
    """
    n = max(len(documents), 1)
    lang = question_language(query)
    if is_cross_lingual(query, lang):
        lang = None
    elif lang and not any(lang in chunk_languages(d) for d in documents):
        # No section in the question's language (a Vietnamese question over English/multilingual
        # manuals): prefer English, the manuals' source language, over its translations.
        lang = FALLBACK_LANG
    scored = []
    for i, doc in enumerate(documents):
        score = 1.0 - i / n
        if lang and lang in chunk_languages(doc):
            score += LANG_BOOST
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
            "results": [{"index": i, "relevance_score": s / 2.0} for i, s in order],  # scale to [0, 1]
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
