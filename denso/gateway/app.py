"""DENSO Agent Gateway: the backend of the agentic UI (lightrag_webui/src/api/agent.ts).

Resolves the caller's access level from users.json, sends questions to that level's LightRAG
server, picks the citations the answer really uses, and runs document upload / delete jobs.
It never sends a command to a PLC. With DENSO_IOT_URL set, incidents, telemetry and HITL decisions
are forwarded to iot_service, whose commands go to the test-bench simulator only.

Run:  python denso/gateway/app.py            (http://127.0.0.1:9700; settings: see Settings.from_env)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import mimetypes
import shutil
import unicodedata
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

import lookup as catalogue  # noqa: E402  (sibling module; app.py runs as a script)
from jobs import JobRunner  # noqa: E402
from language import language_instruction, named_languages, question_language, small_talk_reply  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MAX_LEVEL = 3
HISTORY_TURNS = 6
PAGE_MARK = re.compile(r"--- \[Trang (\d+)[^\]]*\] ---")
LOOKUP_HINT = re.compile(r"\s*-\s*lookup\.\[[^\]]*\]$|\.\[[^\]]*\]$")
# Vehicle-application lookups go to the lookup tier. Only the *intent* counts: a
# part number alone is not enough, because the knowledge tier is full of them too
# (benchmark Q1 asks about DCRS300260, Q10 about DCP32045).
LOOKUP_QUESTION = re.compile(
    r"\b(fit|fits|fitting|suitable for|compatible with|applicable to)\b.{0,60}\b(car|vehicle|model|engine|motorcycle|my)\b|"
    r"\bfits? (?:a |an |the |my )?(?:\d{4} )?[A-Z][a-z]+|"
    r"\b(which|what)\b.{0,50}\b(plug|blade|wiper|part)\b.{0,50}\bfor (?:a |an |the |my )?(?:\d{4} )?[A-Z][a-z]+|"
    r"\b(vehicle )?applications? (list|table|for)\b|\bcross[- ]reference\b|\bequivalent (of|to)\b|"
    r"\bxe nào\b|\blắp (cho|được)\b|\bdùng cho xe\b",
    re.IGNORECASE,
)
# Placeholder the LightRAG /query route returns when the LLM produced no text. Not the same
# as PROMPTS["fail_response"], which is a deliberate refusal when retrieval finds nothing.
EMPTY_LLM_PLACEHOLDER = "No relevant context found for the query."
# LightRAG doc_status -> UI DocumentIndexStatus
STATUS_MAP = {
    "pending": "uploading",
    "parsing": "parsing",
    "analyzing": "chunking",
    "preprocessed": "chunking",
    "processing": "embedding",
    "processed": "vectorized",
    "failed": "error",
}


# ---------------------------------------------------------------- pure helpers


def display_name(file_path: str) -> str:
    """'Spark Plug Catalogue 2025 - lookup.[native-P!].md' -> 'Spark Plug Catalogue 2025'."""
    name = Path(file_path.replace("\\", "/")).name
    if name.lower().endswith(".md"):
        name = name[:-3]
    return LOOKUP_HINT.sub("", name).strip()


CHUNK_LANG = re.compile(r"--- \[Trang \d+ \| ngôn ngữ: ([a-z-]+)\] ---")
PAGE_LANG = re.compile(r"--- \[Trang (\d+)(?: \| ngôn ngữ: ([a-z-]+))?[^\]]*\] ---")
MAX_PAGES_SHOWN = 6


def pages_from_chunks(chunks: list[str]) -> str | None:
    """Pages of the chunks in the language of the best-ranked chunk.

    A multilingual guide repeats each section once per language, so the context holds
    the same paragraph from many pages; listing all of them ("Pages 1-20") is noise.
    The language reranker ranks the question's language first, so the first chunk's
    language is the one the answer was read from.
    """
    marks = [(int(p), lang) for c in chunks for p, lang in PAGE_LANG.findall(c)]
    # English (the manuals' source language) when the document has it: a Vietnamese question
    # answered from a Vietnamese upload kept the installation manual in vector order, and its
    # first chunk's language gave pages 44-45 of another translation.
    first_lang = "en" if any(lang == "en" for _, lang in marks) else next(
        (m.group(1) for c in chunks for m in [CHUNK_LANG.search(c)] if m), None)
    # A chunk can run across a language boundary (en p.4 -> de p.5): filter page by page.
    pages = sorted({p for p, lang in marks if not first_lang or lang in (first_lang, "mixed", "")})
    if len(pages) > MAX_PAGES_SHOWN:
        return ", ".join(map(str, pages[:MAX_PAGES_SHOWN])) + ", …"
    return ", ".join(map(str, pages)) or None


def excerpt_from_chunks(chunks: list[str], limit: int = 300) -> str | None:
    for c in chunks:
        text = re.sub(r"\s+", " ", PAGE_MARK.sub(" ", re.sub(r"<[^>]+>", " ", c))).strip(" #-")
        if text:
            return text[:limit] + ("…" if len(text) > limit else "")
    return None


def to_citations(references: list[dict], answer: str = "", prefer: set[str] = frozenset()) -> list[dict]:
    """LightRAG references (with include_chunk_content) -> UI Citation objects.

    With the answer, pages and excerpt come from the chunks that support it, not from every
    chunk of the document (a 40-page manual listed "Pages 1, 2, 3, 4, 5, 6, ...").
    """
    out = []
    for ref in references:
        # A question about a language section looks at every chunk: the supporting-chunk filter
        # favours the English chunk (it shares the document name the answer cites) and dropped
        # the Russian one before its page could be chosen.
        chunks = supporting_chunks(ref, answer) if answer and not prefer else chunk_texts(ref)
        out.append({
            "id": f"cit-{ref.get('reference_id', len(out) + 1)}",
            "documentId": display_name(ref.get("file_path", "")),
            "documentName": display_name(ref.get("file_path", "")),
            "pages": supporting_pages(chunks, answer, prefer) or pages_from_chunks(chunks),
            "excerpt": excerpt_from_chunks(chunks),
        })
    return out


def listed_reference_ids(answer: str) -> set[str]:
    """Ids in the answer's own '### References' block ("- [2] guide.md"): the sources it claims."""
    parts = re.split(r"\n#{2,4}\s*References\s*\n", answer, maxsplit=1)
    return set(re.findall(r"^\s*[-*]\s*\[(\d+)\]", parts[1], re.MULTILINE)) if len(parts) > 1 else set()


def strip_reference_section(answer: str) -> str:
    """The UI renders citations itself; drop LightRAG's trailing '### References' block."""
    return re.split(r"\n#{2,4}\s*References\s*\n", answer, maxsplit=1)[0].rstrip()


# Nemotron cites as 【2†L4-L5】 or 【1†file.md】 instead of LightRAG's [2].
BRACKET_CITATION = re.compile(r"\s*【\s*(\d+)[^】]*】")
OTHER_BRACKET = re.compile(r"\s*【[^】]*】")
CITED_ID = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Page marker lines the model sometimes copies from the context into its answer.
LEAKED_PAGE_MARK = re.compile(r"-{2,}\s*\[Trang ([\d\s,–-]+?)\s*(?:\|[^\]]*)?\]\s*-{2,}")
REFUSAL = re.compile(r"(?:do not|don[’']t|does not|doesn[’']t) have enough information|not enough information|"
                     r"(?:context|documents?) (?:does|do) not (?:contain|specify|provide|include|mention|list)|"
                     r"\bno (?:relevant )?information (?:is )?(?:available|provided|found|about|on|regarding)|"
                     r"\b(?:is|are) not (?:specified|listed|mentioned|provided|given|stated) in\b|"
                     r"không (?:có )?(?:đủ )?thông tin|không (?:được )?(?:nêu|đề cập) (?:trong|tới|đến)|không tìm thấy thông tin|"
                     # "Tài liệu được cung cấp không chứa bất kỳ thông tin nào về giá ..." cited three documents.
                     r"(?:tài liệu|ngữ cảnh|văn bản)[^.]{0,40}không (?:chứa|có|ghi|nêu|đề cập|cung cấp)|"
                     r"情報(?:が|は)(?:ありません|見つかりません)|記載(?:が|は)?(?:ありません|されていません)|"
                     r"cannot (?:determine|answer)", re.IGNORECASE)


def is_refusal(answer: str) -> bool:
    """The answer says the documents do not have it - near the start, not as one gap in a real answer.

    Seen live: "there is no information available about Oil 9" cited three documents, and a pattern
    anywhere in the text would also strip the sources of "X is 36 months; Y is not specified in...".
    """
    first = re.split(r"(?<=[.!?。])\s+|\n", answer.strip(), maxsplit=1)[0]
    return bool(REFUSAL.search(first[:300]))
# Decimal figures (6.9, 10,8) or long part numbers (DND08250, 294009-2150): specific enough to locate a source.
# Distinctive words (7+ letters) to match an answer with no figures to its sources; short words
# ("system", "seal", "with") appear in every document. English only: the sources are English.
PAGE_WORD = re.compile(r"(?<![A-Za-z])[A-Za-z][A-Za-z-]{3,}(?![A-Za-z])")
PAGE_STOPWORDS = {"that", "this", "with", "from", "have", "will", "your", "when", "then", "they", "them", "there",
                  "their", "into", "also", "must", "should", "which", "what", "about", "after", "before", "using",
                  "used", "each", "only", "than", "more", "such", "these", "those", "page", "trang"}
CONTENT_WORD = re.compile(r"\b[A-Za-z][A-Za-z-]{6,}\b")
ANSWER_FIGURE = re.compile(r"\b\d+[.,]\d+\b|\b[A-Z]{2,}\d{4,}\b|\b\d{5,}(?:-\d+)?\b")


def strip_reasoning(answer: str) -> str:
    """Drop the model's scratch reasoning (<think>...</think>) that must never reach the user.

    Nemotron sometimes emits it inside the content: as a closed block, as an unclosed
    <think> (cut off, nothing usable after it), or as a stray </think> after leading notes.
    """
    text = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
    if "</think>" in text:          # notes before an orphan closing tag
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:           # unclosed: everything after it is reasoning
        text = text.split("<think>", 1)[0]
    return text.strip()


def clean_answer(answer: str) -> str:
    """Strip reasoning and the references block; normalise model-specific citation markers to [n]."""
    text = strip_reference_section(strip_reasoning(answer))
    text = BRACKET_CITATION.sub(lambda m: f" [{m.group(1)}]", text)
    text = LEAKED_PAGE_MARK.sub(lambda m: f"(trang {m.group(1).strip()})", text)
    return OTHER_BRACKET.sub("", text)


def chunk_texts(ref: dict) -> list[str]:
    c = ref.get("content") or []
    return [c] if isinstance(c, str) else list(c)


def evidence(text: str, words: set[str], figures: set[str]) -> int:
    """How much of the answer a chunk supports: shared distinctive words, figures count triple."""
    t = text.replace(",", ".")
    return (len(words & {w.lower() for w in CONTENT_WORD.findall(t)})
            + 3 * sum(1 for f in figures if f in t))


def answer_terms(answer: str) -> tuple[set[str], set[str]]:
    body = CITED_ID.sub(" ", answer)
    return ({w.lower() for w in CONTENT_WORD.findall(body)},
            {f.replace(",", ".") for f in ANSWER_FIGURE.findall(body)})


def only_cited(references: list[dict], answer: str, prefer: set[str] = frozenset(),
               listed: set[str] = frozenset()) -> list[dict]:
    """See _only_cited; a question about a language section keeps the sources holding that section.

    The SCV guide and its image-text document share a name; for "the Russian section" the
    image document (English/German pages only) was kept and the guide itself dropped.
    """
    kept = _only_cited(references, answer, judge_grounding=not prefer, listed=listed)
    if prefer:
        # The document holding the sections asked about is the evidence here: a short "both say 2
        # guide pins" answer shares too few words with any chunk and was left with no source.
        # The sources covering most of the languages asked about (the guide itself holds both the
        # Russian and the English section; its image-text document only English and German pages).
        langs = {id(r): {m.group(2) for t in chunk_texts(r) for m in PAGE_LANG.finditer(t)} & prefer
                 for r in references}
        # Greedy cover, document text before picture descriptions, then cited sources first:
        # "German and French" kept only the image-text document (its OCR pages carry both tags)
        # and dropped the guide whose text holds the French section.
        # Language sections belong to one document (with its image-text file): the one holding
        # most of the languages asked about, cited ones winning ties. The wiper catalogue (German
        # pages only) was cited, by the model too, for the SCV guide's German section.
        base = _base_name
        held: dict[str, set[str]] = {}
        for r in references:
            held.setdefault(base(r), set()).update(langs[id(r)])
        top = max((len(v) for v in held.values()), default=0)
        tied = {b for b, v in held.items() if len(v) == top}
        family = (tied & {base(r) for r in kept}) or tied
        same = [r for r in references if base(r) in family]
        holding, covered = [], set()
        order = sorted(same, key=lambda r: (" - images" in (r.get("file_path") or ""),
                                            r not in kept, -len(langs[id(r)])))
        for r in order:
            if langs[id(r)] - covered:
                holding.append(r)
                covered |= langs[id(r)]
        if holding:
            return holding
    return kept


def _base_name(ref: dict) -> str:
    return display_name(ref.get("file_path", "")).removesuffix(" - images")


def _loose(text: str) -> str:
    return re.sub(r"[\s_]+", " ", text).lower()


def named_in_answer(references: list[dict], answer: str) -> list[dict]:
    """References whose document the answer names, as the prompt asks: "(Name, p. N)"."""
    text = _loose(answer)
    return [r for r in references if len(_base_name(r)) >= 6 and _loose(_base_name(r)) in text]


# Codes and figures that survive translation: R-134a, DCRS300260, M14, 6,9, 140cc. Brand and unit
# words are in every document and prove nothing.
CODE_TOKEN = re.compile(r"\b(?=[A-Za-z0-9-]*\d)[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]\b|\b[A-Z]{2,}\b")
CODE_STOPWORDS = {"DENSO", "NM", "OK", "EN", "PDF", "AC"}


def sharing_codes(references: list[dict], answer: str) -> list[dict]:
    """The references holding most of the answer's codes and figures; none when it has none."""
    codes = {c for c in CODE_TOKEN.findall(CITED_ID.sub(" ", answer).replace(",", "."))
             if c.upper() not in CODE_STOPWORDS}
    if not codes:
        return []
    score = {id(r): max((sum(1 for c in codes if c in t.replace(",", ".")) for t in chunk_texts(r)), default=0)
             for r in references}
    best = max(score.values(), default=0)
    return [r for r in references if best and score[id(r)] == best]


def _only_cited(references: list[dict], answer: str, judge_grounding: bool = True,
                listed: set[str] = frozenset()) -> list[dict]:
    """The references the answer draws on: never none, never one that does not support it.

    LightRAG returns every document that contributed a context chunk (a whole catalogue next
    to the guide the answer came from), and the model sometimes cites the wrong [n] - a BHT
    kitting answer cited the A/C brochure. A cited reference is kept only when its chunks
    support the answer about as well as the best one; with no usable [n], the best-supported
    references are kept.
    """
    if not references:
        return []
    words, figures = answer_terms(answer)
    score = {id(r): max((evidence(t, words, figures) for t in chunk_texts(r)), default=0) for r in references}
    best = max(score.values())
    # [n] in the text, or the answer's own References block (stripped before the answer is shown):
    # accurate for Vietnamese / Japanese answers, empty for off-topic ones. Greetings and "who are
    # you" never get here (small_talk_reply), they listed two catalogues.
    ids = {i for m in CITED_ID.finditer(answer) for i in re.findall(r"\d+", m.group(1))} | set(listed)
    cited = [r for r in references if str(r.get("reference_id")) in ids]
    # A substantive (English) answer that no retrieved chunk supports came from somewhere else -
    # conversation history, the model's own knowledge. Citing a chunk would present it as
    # sourced (seen live: a Google Play answer cited the Spark Plug Catalogue, p. 4).
    # Judged only for English answers (the documents' language: a Vietnamese answer shares no
    # words with them) and only when none of the answer's figures is in a chunk (a cross-lingual
    # answer quoting the Russian value has few English words in common with the chunks).
    terms = {w.lower() for w in PAGE_WORD.findall(CITED_ID.sub(" ", answer))} - PAGE_STOPWORDS
    figure_found = any(f in t.replace(",", ".") for f in figures for r in references for t in chunk_texts(r))
    if judge_grounding and len(terms) >= 10 and not figure_found and question_language(answer) == "en":
        support = max(len(terms & {w.lower() for w in PAGE_WORD.findall(t)}) for r in references for t in chunk_texts(r) or [""])
        if support < max(3, 0.2 * len(terms)):
            return []
    if best < 3:
        # Too little English text to judge (short or Vietnamese answer): keep only what the answer
        # itself points to. Returning every reference cited two catalogues for "Xin chào!".
        picked = (cited or named_in_answer(references, answer) or quoting_references(references, answer)
                  or sharing_codes(references, answer))
        # The model's own References block can name the wrong source: a Chinook answer listed the
        # Spark Plug Catalogue, which holds none of its words, while the slides held "Chinook".
        # Keep a pick only when it shares about as much of the answer as the best. Language-neutral
        # terms only (names, codes, numbers): with Vietnamese word pairs, any Vietnamese document
        # ("máy nén", "mã lỗi") outscored the English bulletin a Vietnamese answer was read from.
        # Without the answer's own "(Document name, p. N)": a wrong one ("AC Compressor Installation
        # Manual, p. 2" for a fact of the oil bulletin) matched that manual on its own name.
        body = CITATION_PAREN.sub(" ", CITED_ID.sub(" ", answer))
        terms_any = neutral_terms(body)
        overlap = {id(r): max((len(terms_any & neutral_terms(t)) + 3 * ranges_in(body, t) for t in chunk_texts(r)),
                              default=0) for r in references}
        top = max(overlap.values(), default=0)
        if top >= 2:
            sound = [r for r in picked if overlap[id(r)] >= top * 0.5]
            return sound or [r for r in references if overlap[id(r)] == top]
        return picked
    supported = [r for r in references if score[id(r)] >= max(3, best * 0.5)]
    kept = [r for r in cited if r in supported]
    return kept or supported or references


UNICODE_WORD = re.compile(r"[^\W\d_]+")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`#>|]", " ", text)).strip().lower()


def answer_core(answer: str) -> str:
    """A short answer without its "(document, p. N)" and [n]: e.g. "o(b m/2)". Empty for long answers."""
    core = _squash(re.sub(r"\([^()]*\b(?:p\.|trang|ページ)\s*\d+[^()]*\)", " ", CITED_ID.sub(" ", answer))).strip(" .")
    return core if 4 <= len(core) <= 120 else ""


def quoting_references(references: list[dict], answer: str) -> list[dict]:
    """References a short answer quotes verbatim ("O(b m/2)" shares no word with anything)."""
    core = answer_core(answer)
    return [r for r in references if core and any(core in _squash(t) for t in chunk_texts(r))] if core else []


CITATION_PAREN = re.compile(r"\([^()]*\b(?:p\.|page|trang|tr\.|ページ)\s*\d+[^()]*\)", re.IGNORECASE)
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def ranges_in(answer: str, text: str) -> int:
    """How many of the answer's number pairs ("30% đến 50%", "6,9 - 10,8") sit together in `text`.

    Single numbers are in every long manual; a pair printed side by side ("30-50%") is not.
    """
    nums = [n.replace(",", ".") for n in NUMBER.findall(answer)]
    flat = text.replace(",", ".")
    return sum(1 for a, b in set(zip(nums, nums[1:])) if a != b
               and re.search(rf"(?<![\d.]){re.escape(a)}\D{{1,12}}{re.escape(b)}(?![\d.])", flat))


def neutral_terms(text: str) -> set[str]:
    """Terms that read the same in every language: Latin-script words of 4+ letters and whole numbers."""
    return ({w.lower() for w in PAGE_WORD.findall(text)} - PAGE_STOPWORDS) | set(
        re.findall(r"(?<![\d.,])\d{2,}(?![\d.,]?\d)", text))


def page_terms(text: str) -> set[str]:
    """Words a page and an answer can share, in any language.

    English words of 4+ letters, plus pairs of consecutive words: Vietnamese words are
    syllables ("giá trị", "cắt cụt"), so one syllable says little but a pair does. With English
    words only, a Vietnamese answer about alpha-beta scored 0 on the Vietnamese slides that
    define it and cited an English slide (p. 40) that merely mentions it.
    """
    english = {w.lower() for w in PAGE_WORD.findall(text)} - PAGE_STOPWORDS
    words = [w.lower() for w in UNICODE_WORD.findall(text)]
    # Whole numbers too ("b ~ 35, m ~ 100"): decimals and long codes alone left that slide with 1 point.
    numbers = set(re.findall(r"(?<![\d.,])\d{2,}(?![\d.,]?\d)", text))
    return english | numbers | {f"{a} {b}" for a, b in zip(words, words[1:]) if not (a.isascii() and b.isascii())}


def supporting_pages(chunks: list[str], answer: str, prefer: set[str] = frozenset()) -> str | None:
    """Pages, within the supporting chunks, whose text supports the answer best.

    A chunk of a long manual runs across several pages (power-off sits on one page of a
    chunk covering pages 4-18); scoring each page's text keeps the citation on that page.
    """
    if not answer:
        return None
    # Within one document shorter words are safe to compare ("power", "hold", "menu").
    _, figures = answer_terms(answer)
    words = page_terms(CITED_ID.sub(" ", answer))
    # A page's marker repeats after each heading, so its text comes in several parts: score it whole.
    page_text: dict[int, str] = {}
    for chunk in chunks:
        parts = PAGE_MARK.split(chunk)  # [before, page, text, page, text, ...]
        for page, text in zip(parts[1::2], parts[2::2]):
            page_text[int(page)] = page_text.get(int(page), "") + "\n" + text
    scores: dict[int, int] = {}
    core = answer_core(answer)
    named_pages = {int(n) for n in re.findall(r"(?:\bp\.|\bpage|\btrang|\btr\.|ページ)\s*(\d+)", answer, re.IGNORECASE)}
    for page, text in page_text.items():
        t = text.replace(",", ".")
        scores[page] = len(words & page_terms(text)) + 3 * sum(1 for f in figures if f in t)
        if core and core in _squash(text):
            scores[page] += 10  # the short answer is printed on this page
    # The answer names its page itself ("(Trang 27)") and that page does support it: cite it alone.
    # p. 9 shared more words about chess and was cited instead. Only a page holding at least half
    # the best support counts - the model's page can be wrong (a Russian-section answer said p. 6).
    best_any = max(scores.values(), default=0)
    named_ok = sorted(p for p in named_pages if scores.get(p, 0) >= max(1, best_any * 0.5))
    if named_ok and not prefer:
        return ", ".join(map(str, named_ok[:MAX_PAGES_SHOWN]))
    # A question about a language section ("phần tiếng Nga") cites that section: the same figure is
    # on every translation's page (a Russian-section question cited the English and German pages).
    if prefer:
        lang_of = {int(m.group(1)): m.group(2) for c in chunks for m in PAGE_LANG.finditer(c)}
        in_lang = {p: v for p, v in scores.items() if lang_of.get(p) in prefer}
        if in_lang and max(in_lang.values()) >= 2:
            if len(prefer) > 1:
                # A comparison ("Russian vs English", "German and French") cites the best page of
                # each language asked about, not only the one that shares most words.
                picked = set()
                for lang in prefer:
                    own = {p: v for p, v in in_lang.items() if lang_of.get(p) == lang and v >= 2}
                    if own:
                        top = max(own.values())
                        picked |= {p for p, v in own.items() if v >= top * 0.8}
                if picked:
                    return ", ".join(map(str, sorted(picked)[:MAX_PAGES_SHOWN]))
            scores = in_lang
    else:
        # A multilingual guide repeats each step once per language, and words like "SCV", "O-ring",
        # "Common Rail" are on every translation's page: a Vietnamese procedure answer cited
        # "4, 6, 7, 10, 12, 14, ...". Keep the pages of the best-scoring language, English (the
        # manuals' source language) on a tie - the first chunk's language picked the Spanish page.
        lang_of = {int(m.group(1)): m.group(2) for c in chunks for m in PAGE_LANG.finditer(c)}
        by_lang: dict[str, int] = {}
        for p, v in scores.items():
            if lang_of.get(p) not in (None, "mixed"):
                by_lang[lang_of[p]] = max(by_lang.get(lang_of[p], 0), v)
        first = max(by_lang, key=lambda lang: (by_lang[lang], lang == "en"), default=None)
        if first and len(by_lang) > 1:
            own = {p: v for p, v in scores.items() if lang_of.get(p) in (first, "mixed", None)}
            if own and max(own.values()) >= 2:
                scores = own
    best = max(scores.values(), default=0)
    if best < 2:
        return None
    pages = sorted(p for p, v in scores.items() if v >= best * 0.6)
    return ", ".join(map(str, pages[:MAX_PAGES_SHOWN])) + (", …" if len(pages) > MAX_PAGES_SHOWN else "")


def supporting_chunks(ref: dict, answer: str) -> list[str]:
    """The chunks of a reference the answer was read from (for its pages and excerpt)."""
    chunks = chunk_texts(ref)
    # Any language, like supporting_pages: with English words only, the Vietnamese chunk defining
    # alpha-beta (pp. 29-36) lost to chunks naming Kasparov and Minimax, and pp. 8, 9, 46 were cited.
    _, figures = answer_terms(answer)
    terms = page_terms(CITED_ID.sub(" ", answer))
    scored = [(len(terms & page_terms(t)) + 3 * sum(1 for f in figures if f in t.replace(",", ".")), t) for t in chunks]
    best = max((s for s, _ in scored), default=0)
    if best < 3:
        return chunks
    # Keep the chunk holding a page the answer names ("(…, trang 27)"): it was dropped here, before
    # supporting_pages could prefer that page, and p. 1 was cited.
    named = {n for n in re.findall(r"(?:\bp\.|\bpage|\btrang|\btr\.|ページ)\s*(\d+)", answer, re.IGNORECASE)}
    return [t for s, t in sorted(scored, key=lambda x: -x[0])
            if s >= best * 0.5 or (named & set(PAGE_MARK.findall(t)))]


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def raw_file(file_path: str, data_dir: Path, max_level: int = MAX_LEVEL) -> Path | None:
    """The uploaded original behind a LightRAG document ('X - images.[native-P!].md' -> raw/X.pdf).
    Never a path outside data/raw, nor one under raw/level_N above `max_level`."""
    stem = display_name(file_path)
    stem = re.sub(r"\s*-\s*images$", "", stem)
    raw_dir = (data_dir / "raw").resolve()
    if not stem or not raw_dir.is_dir():
        return None
    candidates: list[Path] = []
    meta = data_dir / "parsed" / stem / "meta.json"
    if meta.is_file():
        try:
            source = json.loads(meta.read_text(encoding="utf-8")).get("source_file") or ""
        except (OSError, ValueError):
            source = ""
        if source:
            candidates += [raw_dir / Path(source).name, *raw_dir.glob(f"level_*/{Path(source).name}")]
    # No meta.json (or a stale one): match the stem, in either Unicode normal form.
    want = _nfc(stem)
    candidates += [p for p in raw_dir.rglob("*") if p.is_file() and _nfc(p.stem) == want]
    for p in candidates:
        p = p.resolve()
        if not (p.is_file() and raw_dir in p.parents):
            continue
        folder = p.parent.name
        if folder.startswith("level_") and folder[6:].isdigit() and int(folder[6:]) > max_level:
            continue
        return p
    return None


def incident_context(inc: dict) -> str:
    """The live state of an iot_service incident, for the answer prompt of a chat held in it."""
    lines = [f"- Machine: {inc.get('device', '?')}; alarm: {inc.get('alarm', '?')}; "
             f"severity: {inc.get('severity', '?')}; status: {inc.get('status', '?')}"]
    points = (inc.get("telemetry") or {}).get("points") or []
    if points:
        def reading(pt: dict) -> str:
            limit = f", limit {pt['threshold']:g}" if isinstance(pt.get("threshold"), (int, float)) else ""
            flag = ", OUT OF RANGE" if pt.get("isAnomalous") else ""
            return f"{pt.get('label', pt.get('key'))} {pt.get('value')} {pt.get('unit', '')}".rstrip() + f"{limit}{flag}"
        lines.append("- Sensor readings now: " + "; ".join(reading(pt) for pt in points))
    action = inc.get("proposedAction") or {}
    if action:
        execution = (inc.get("actionExecution") or {}).get("status") or "waiting for approval"
        lines.append(f"- Monitoring agent's proposal ({execution}): {action.get('titleVi', '')}. "
                     f"{action.get('subtitleVi', '')}".rstrip())
    return ("The operator is asking about this live incident on the compressor test bench (data from the "
            "monitoring system, NOT from the documents):\n" + "\n".join(lines) + "\n"
            "Use it to understand the question. Causes, procedures and specifications must still come from the "
            "documents and be cited as usual; sensor values may be quoted as live readings. If the documents do "
            "not cover the question, say so.")


def incident_query(message: str, inc: dict) -> str:
    """Retrieval text for a chat in an incident: a short question ("what do I check next?") retrieves
    nothing on its own, so the fault is added - in Vietnamese questions only, as the alarms are
    Vietnamese and the reranker reads the question's language from the query."""
    if question_language(message) != "vi":
        return message
    fault = (inc.get("alarm") or "").split(":", 1)[-1].strip()
    return f"{message}\n({fault})" if fault and fault.lower() not in message.lower() else message


def classify_target(message: str) -> str:
    return "lookup" if LOOKUP_QUESTION.search(message) else "knowledge"


def to_knowledge_document(doc: dict, level: int) -> dict:
    name = doc.get("file_path", "")
    tier = "lookup" if "lookup.[" in name else "knowledge"
    status = STATUS_MAP.get(doc.get("status", ""), "error")
    return {
        "id": doc.get("id"),
        "name": display_name(name),
        "tags": [tier, f"level_{level}"],
        "sizeBytes": int(doc.get("content_length") or 0),
        "importedAt": doc.get("created_at"),
        "indexStatus": status,
        "progress": 100 if status == "vectorized" else None,
    }


# ---------------------------------------------------------------- config / auth


@dataclass
class Settings:
    level_servers: list[str]
    lookup_server: str | None = None
    users: dict[str, dict] = field(default_factory=dict)
    guest_level: int = 1
    # Team testing on the hosted demo: visitors without a token may upload and delete too.
    # Anyone with the tunnel link can then change the knowledge base - turn it off afterwards.
    guest_can_upload: bool = False
    api_key: str | None = None
    cors: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    # Hosted UI whose URL changes per deployment, e.g. ^https://denso-copilot(-[a-z0-9-]+)?\.vercel\.app$
    cors_regex: str | None = None
    ops_file: Path = HERE / "sample_ops.json"
    actions_log: Path = REPO / "denso" / "logs" / "actions.jsonl"
    # naive beat mix on the benchmark (100% vs 87% with denso_answer.md, half the latency):
    # mix keeps only ~6 text chunks next to the entities, and the answers sit verbatim in tables.
    knowledge_mode: str = "naive"
    # Seconds a chat waits for LightRAG (retrieval + LLM) before answering 504.
    answer_timeout: float = 150.0
    lookup_mode: str = "naive"
    # Keyword search over the lookup catalogues (gateway/lookup.py); empty = LightRAG lookup server only.
    lookup_files: list[Path] = field(default_factory=list)
    lookup_llm_base: str = "http://127.0.0.1:8899/v1"   # OpenAI-compatible; the proxy adds the API key
    lookup_llm_model: str = "nvidia/nemotron-3-super-120b-a12b"
    # Uploads go through the DENSO pipeline (gateway/jobs.py) so their answers cite pages;
    # False sends the raw file straight to LightRAG (no Docling available, e.g. a server).
    upload_pipeline: bool = True
    data_dir: Path = REPO / "denso" / "data"   # pipeline outputs a delete cleans up
    docling_url: str = "http://127.0.0.1:5001"
    # Extra request fields, e.g. {"chat_template_kwargs": {"enable_thinking": false}} for Nemotron.
    lookup_llm_extra_body: dict = field(default_factory=dict)
    # iot_service (e.g. http://127.0.0.1:9710): incidents, telemetry and actions come from it instead
    # of sample_ops.json, and chats in an incident's conversation carry its live state. None = samples.
    iot_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        servers = os.environ.get(
            "DENSO_LEVEL_SERVERS", "http://127.0.0.1:9621,http://127.0.0.1:9622,http://127.0.0.1:9623"
        ).split(",")
        users_file = Path(os.environ.get("DENSO_GATEWAY_USERS", HERE / "users.json"))
        users = json.loads(users_file.read_text(encoding="utf-8")) if users_file.exists() else {}
        return cls(
            level_servers=[s.strip() for s in servers if s.strip()],
            lookup_server=os.environ.get("DENSO_LOOKUP_SERVER") or None,
            users={k: v for k, v in users.items() if not k.startswith("_")},
            guest_level=int(os.environ.get("DENSO_GUEST_LEVEL", "1")),
            guest_can_upload=os.environ.get("DENSO_GUEST_CAN_UPLOAD", "0") == "1",
            api_key=os.environ.get("LIGHTRAG_API_KEY") or None,
            cors=[o.strip() for o in os.environ.get("DENSO_GATEWAY_CORS", "http://localhost:5173").split(",")],
            cors_regex=os.environ.get("DENSO_GATEWAY_CORS_REGEX") or None,
            knowledge_mode=os.environ.get("DENSO_KNOWLEDGE_MODE", "naive"),
            answer_timeout=float(os.environ.get("DENSO_ANSWER_TIMEOUT", "150")),
            lookup_files=sorted(Path(os.environ.get("DENSO_LOOKUP_DIR", REPO / "denso" / "data" / "cleaned_md"))
                                .glob("* - lookup.*.md")),
            lookup_llm_base=os.environ.get("DENSO_LOOKUP_LLM_BASE", "http://127.0.0.1:8899/v1"),
            lookup_llm_model=os.environ.get("DENSO_LOOKUP_LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
            lookup_llm_extra_body=json.loads(os.environ.get("DENSO_LOOKUP_LLM_EXTRA_BODY") or "{}"),
            upload_pipeline=os.environ.get("DENSO_UPLOAD_PIPELINE", "1") != "0",
            docling_url=os.environ.get("DENSO_DOCLING_URL", "http://127.0.0.1:5001"),
            iot_url=(os.environ.get("DENSO_IOT_URL") or "").rstrip("/") or None,
        )


@dataclass
class User:
    name: str
    level: int
    can_upload: bool = False
    # Approve / reject an agent action that iot_service then executes (on the simulator).
    can_approve: bool = False


class ChatRequest(BaseModel):
    conversationId: str
    message: str
    target: str | None = None  # optional override: "knowledge" | "lookup"


def create_app(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    if len(settings.level_servers) != MAX_LEVEL:
        raise ValueError(f"need {MAX_LEVEL} level servers, got {len(settings.level_servers)}")
    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    # A user waiting in the chat gets a clear 504 instead of a spinner for up to 15 minutes.
    client = httpx.AsyncClient(timeout=httpx.Timeout(settings.answer_timeout, connect=10), headers=headers,
                               transport=transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await client.aclose()

    app = FastAPI(title="DENSO Agent Gateway", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors, allow_origin_regex=settings.cors_regex,
                       allow_methods=["*"], allow_headers=["*"])
    history: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=HISTORY_TURNS * 2))
    lookup_rows = catalogue.load_rows(settings.lookup_files)
    runner = JobRunner(REPO, settings.level_servers, docling=settings.docling_url) if settings.upload_pipeline else None

    def job_document(job) -> dict:
        return {"id": f"job-{job.id}", "name": Path(job.name).stem, "tags": ["#Uploaded", f"level_{job.level}"],
                "sizeBytes": job.size, "importedAt": datetime.fromtimestamp(job.created, timezone.utc).isoformat(),
                "indexStatus": job.status, "progress": job.progress, "extractedText": job.error or job.stage}

    async def answer_from_rows(question: str, hits: list, past: list[dict]) -> tuple[str, list[dict]]:
        """Ask the LLM with the keyword-matched catalogue rows; cite the rows it used."""
        body = {
            **settings.lookup_llm_extra_body,
            "model": settings.lookup_llm_model,
            "temperature": 0,
            "reasoning_effort": "low",
            "max_tokens": 2000,
            "messages": [{"role": "system", "content": f"{catalogue.ANSWER_INSTRUCTIONS} {language_instruction(question)}".strip()},
                         *past,
                         {"role": "user", "content": f"Catalogue rows:\n{catalogue.rows_context(hits)}\n\nQuestion: {question}"}],
        }
        try:
            r = await client.post(f"{settings.lookup_llm_base}/chat/completions", json=body)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"the answering LLM did not reply within "
                                                        f"{settings.answer_timeout:.0f} s (free API overloaded) - please ask again")
        if r.status_code != 200:
            raise HTTPException(status_code=503, detail=f"the answering LLM failed ({r.status_code}) - please ask again")
        content = clean_answer((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "")
        if not content:
            raise HTTPException(status_code=503, detail="the answering LLM returned no answer - please ask again")
        if is_refusal(content):
            return content, []  # "not in the catalogue" must not list the rows it rejected
        cited = {int(i) for m in CITED_ID.finditer(content) for i in re.findall(r"\d+", m.group(1))}
        # Without [n], the rows whose part numbers the answer quotes - never every matched row.
        codes = {c for c in CODE_TOKEN.findall(CITED_ID.sub(" ", content).upper()) if any(ch.isdigit() for ch in c)}
        used = ([row for i, (row, _) in enumerate(hits, 1) if i in cited]
                or [row for row, _ in hits if any(re.search(rf"(?<![A-Z0-9]){re.escape(c)}(?![A-Z0-9])", row.text)
                                                  for c in codes)])
        citations = []
        for source in dict.fromkeys(row.source for row in used):
            rows = [row for row in used if row.source == source]
            pages = sorted({row.page for row in rows})
            shown = ", ".join(map(str, pages[:MAX_PAGES_SHOWN])) + (", …" if len(pages) > MAX_PAGES_SHOWN else "")
            citations.append({"id": f"cit-{len(citations) + 1}", "documentId": display_name(source),
                              "documentName": display_name(source), "pages": shown,
                              "excerpt": rows[0].text.strip(" |")[:300]})
        return content, citations

    def current_user(authorization: str | None = Header(default=None)) -> User:
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not token:
            # -GuestUpload is the team-testing mode: guests get every right, approvals included.
            return User(name="guest", level=settings.guest_level, can_upload=settings.guest_can_upload,
                        can_approve=settings.guest_can_upload)
        info = settings.users.get(token)
        if info is None:
            raise HTTPException(status_code=401, detail="unknown token")
        level = int(info.get("level", 1))
        if not 1 <= level <= MAX_LEVEL:
            raise HTTPException(status_code=500, detail="misconfigured user level")
        return User(name=info.get("name", "user"), level=level, can_upload=bool(info.get("can_upload")),
                    can_approve=bool(info.get("can_approve")))

    def ops() -> dict:
        if settings.ops_file.exists():
            return json.loads(settings.ops_file.read_text(encoding="utf-8"))
        return {"incidents": [], "telemetry": {}}

    async def iot(method: str, path: str, **kw) -> dict | list:
        """Call iot_service; its HTTP errors pass through, an unreachable service is a 503."""
        try:
            r = await client.request(method, f"{settings.iot_url}{path}", timeout=15, **kw)
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="the IoT service is not reachable") from None
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text
            except ValueError:
                detail = r.text
            raise HTTPException(status_code=r.status_code, detail=f"IoT service: {detail}")
        return r.json()

    async def incident_for(conversation_id: str) -> dict | None:
        """The iot_service incident whose conversation this is, else None."""
        if not settings.iot_url or conversation_id.startswith("iot-rag-"):  # the IoT agent's own lookups
            return None
        try:
            incidents = await iot("GET", "/agent/incidents")
        except HTTPException:
            return None  # IoT down: answered as a plain document question
        return next((i for i in incidents if i.get("conversationId") == conversation_id), None)

    def log_action(row: dict) -> None:
        settings.actions_log.parent.mkdir(parents=True, exist_ok=True)
        with settings.actions_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    @app.get("/agent/health")
    async def health() -> dict:
        async def probe(url: str) -> dict:
            try:
                r = await client.get(f"{url}/health", timeout=5)
                cfg = r.json().get("configuration", {})
                return {"url": url, "ok": r.status_code == 200, "workspace": cfg.get("workspace")}
            except (httpx.HTTPError, ValueError):
                return {"url": url, "ok": False}
        backends = {f"level_{i + 1}": await probe(u) for i, u in enumerate(settings.level_servers)}
        if settings.lookup_server:
            backends["lookup"] = await probe(settings.lookup_server)
        if settings.iot_url:
            backends["iot"] = await probe(settings.iot_url)
        return {"status": "ok", "backends": backends}

    @app.post("/agent/chat")
    async def chat(req: ChatRequest, user: User = Depends(current_user)) -> dict:
        # In an incident's conversation the question is answered from the documents like any other,
        # with the incident's live state in the prompt (the IoT agent's own chat, in rules mode, only
        # repeats its diagnosis and cannot look anything up).
        inc = await incident_for(req.conversationId)
        reply = small_talk_reply(req.message)
        if reply:
            # A greeting is not a question about the documents: no retrieval, no sources.
            now = datetime.now(timezone.utc).isoformat()
            return {"content": reply, "citations": [], "grounded": True, "target": "knowledge",
                    "llmGenerated": False,
                    "events": [{"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "response_generated",
                                "label": "Small talk - no document lookup"}]}
        # History is per user, not per client-chosen id: a guest sending a level-3 user's
        # conversationId would otherwise get that conversation's answers as context.
        conversation = (user.level, user.name, req.conversationId)
        target = "knowledge" if inc else (req.target or classify_target(req.message))
        unknown = catalogue.unknown_names(lookup_rows, req.message) if target == "lookup" and lookup_rows else set()
        if unknown:
            # No catalogue row mentions this vehicle: vector search still found a look-alike row
            # ("Lada Niva" -> a Lada G4FA row) and the LLM offered its plugs. Say it is not listed.
            names = " ".join(w.title() for w in sorted(unknown))
            content = (f"Không tìm thấy xe {names} trong các catalogue DENSO hiện có, nên tôi không thể chỉ ra "
                       f"mã phụ tùng phù hợp." if question_language(req.message) == "vi" else
                       f"{names} is not listed in the available DENSO catalogues, so I cannot name a matching part.")
            now = datetime.now(timezone.utc).isoformat()
            return {"content": content, "citations": [], "grounded": True, "target": "lookup", "llmGenerated": False,
                    "events": [{"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "knowledge_retrieved",
                                "label": f"No catalogue row mentions {names} (lookup, keyword, level {user.level})",
                                "citations": []}]}
        hits = catalogue.search(lookup_rows, req.message) if target == "lookup" and lookup_rows else []
        if hits:
            # Vehicle-application rows look alike to vector search; keyword matching finds the row.
            content, citations = await answer_from_rows(req.message, hits, list(history[conversation]))
            history[conversation].extend(
                [{"role": "user", "content": req.message}, {"role": "assistant", "content": content}])
            now = datetime.now(timezone.utc).isoformat()
            return {"content": content, "citations": citations, "target": "lookup", "llmGenerated": True,
                    "events": [
                        {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "knowledge_retrieved",
                         "label": f"Matched {len(hits)} catalogue row(s) (lookup, keyword, level {user.level})",
                         "citations": citations},
                        {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "response_generated",
                         "label": "Answer generated"}]}
        if target == "lookup" and settings.lookup_server:
            url, mode = settings.lookup_server, settings.lookup_mode
        else:
            target, url, mode = "knowledge", settings.level_servers[user.level - 1], settings.knowledge_mode
        past = list(history[conversation])
        payload = {
            "query": incident_query(req.message, inc) if inc else req.message,
            "mode": mode,
            "include_references": True,
            "include_chunk_content": True,
            "conversation_history": past or None,
        }
        instruction = language_instruction(req.message)
        extra = [incident_context(inc)] if inc else []
        if instruction:
            extra.append(instruction)
        if extra:
            # Appended to the server's answer prompt (denso_answer.md): the prefix ends with a newline.
            payload["user_prompt"] = "\n" + "\n".join(extra)
        try:
            r = await client.post(f"{url}/query", json=payload)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"the answering LLM did not reply within "
                                                        f"{settings.answer_timeout:.0f} s (free API overloaded) - please ask again")
        except httpx.ConnectError:
            if target != "lookup":
                raise HTTPException(status_code=503, detail=f"LightRAG level_{user.level} server is not running")
            # Lookup server not deployed (compose profile off): answer from the knowledge tier.
            target, url, mode = "knowledge", settings.level_servers[user.level - 1], settings.knowledge_mode
            r = await client.post(f"{url}/query", json={**payload, "mode": mode})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"LightRAG {target} server returned {r.status_code}")
        body = r.json()
        if body.get("response", "").strip() == EMPTY_LLM_PLACEHOLDER:
            # LightRAG substitutes this when the answering LLM returned nothing (timeout,
            # 429, spent quota). Passing it on would read as "the documents have no answer".
            raise HTTPException(status_code=503, detail="the answering LLM returned nothing (quota, rate limit or "
                                                       "timeout) - see denso/logs/llm_proxy.jsonl and the server log")
        content = clean_answer(body.get("response", ""))
        if not content:
            # Only reasoning came back (cut off before the answer): an LLM failure, not an empty answer.
            raise HTTPException(status_code=503, detail="the answering LLM returned only its reasoning, no answer "
                                                        "- please ask again")
        # A "not in the documents" answer cites nothing: a listed source would read as support.
        refused = is_refusal(content)
        named = named_languages(req.message)
        listed = listed_reference_ids(strip_reasoning(body.get("response", "")))
        citations = [] if refused else to_citations(only_cited(body.get("references") or [], content, named, listed),
                                                    content, named)
        grounded = refused or bool(citations)
        history[conversation].extend(
            [{"role": "user", "content": req.message}, {"role": "assistant", "content": content}]
        )
        now = datetime.now(timezone.utc).isoformat()
        events = ([{"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "correlation",
                    "label": f"Incident context added ({inc.get('id')}, {inc.get('device')})"}] if inc else []) + [
            {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "knowledge_retrieved",
             "label": (f"Retrieved {len(citations)} source document(s) ({target}, {mode}, level {user.level})"
                       if grounded else
                       "⚠️ Không có đoạn tài liệu nào khớp câu trả lời này – có thể dựa trên lịch sử hội thoại, cần kiểm tra lại"),
             "citations": citations},
            {"id": f"ev-{uuid.uuid4().hex[:8]}", "timestamp": now, "type": "response_generated",
             "label": "Answer generated", "detail": f"{body.get('response_time', '?')} s"},
        ]
        return {"content": content, "citations": citations, "events": events, "grounded": grounded,
                "target": target, "llmGenerated": body.get("llm_generated", True)}

    @app.get("/agent/documents/jobs/{job_id}")
    async def upload_job(job_id: str, user: User = Depends(current_user)) -> dict:
        job = runner.get(job_id) if runner else None
        if job is None:
            raise HTTPException(status_code=404, detail="upload job not found")
        return job.public()

    @app.get("/agent/documents")
    async def documents(user: User = Depends(current_user)) -> list[dict]:
        url = settings.level_servers[user.level - 1]
        # Uploads still in the pipeline first, so the Knowledge Hub shows their progress.
        out = [job_document(j) for j in (runner.active() if runner else []) if j.level <= user.level]
        page = 1
        while True:
            r = await client.post(f"{url}/documents/paginated", json={"page": page, "page_size": 100})
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail="LightRAG documents listing failed")
            data = r.json()
            out += [to_knowledge_document(d, user.level) for d in data.get("documents", [])]
            if not data.get("pagination", {}).get("has_next"):
                return out
            page += 1

    @app.post("/agent/documents")
    async def upload(
        file: UploadFile = File(...), level: int = Form(1), user: User = Depends(current_user)
    ) -> dict:
        if not user.can_upload:
            raise HTTPException(status_code=403, detail="this user may not upload documents")
        if not 1 <= level <= user.level:
            raise HTTPException(status_code=403, detail=f"cannot upload a level-{level} document as level {user.level}")
        data = await file.read()
        if runner:
            try:
                job = runner.submit(file.filename or "upload", data, level)
            except ValueError as exc:
                raise HTTPException(status_code=415, detail=str(exc)) from None
            return {"status": "accepted", "jobId": job.id, "job": job.public()}
        tracks = {}
        for lv in range(level, MAX_LEVEL + 1):  # cumulative: a level-N document is visible to N..3
            r = await client.post(f"{settings.level_servers[lv - 1]}/documents/upload",
                                  files={"file": (file.filename, data)})
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"upload to level_{lv} failed ({r.status_code})")
            tracks[f"level_{lv}"] = r.json().get("track_id")
        return {"status": "accepted", "trackIds": tracks}

    async def named_documents(url: str, names: set[str]) -> list[str] | None:
        """Ids of the documents on this server whose canonical or uploaded name is in `names`;
        None when the server is not running."""
        ids, page = [], 1
        try:
            while True:
                r = await client.post(f"{url}/documents/paginated", json={"page": page, "page_size": 100})
                r.raise_for_status()
                data = r.json()
                for d in data.get("documents", []):
                    own = {Path(d.get("file_path") or "").name, (d.get("metadata") or {}).get("source_file") or ""}
                    if own & names:
                        ids.append(d["id"])
                if not data.get("pagination", {}).get("has_next"):
                    return list(dict.fromkeys(ids))
                page += 1
        except (httpx.HTTPError, ValueError):
            return None

    async def find_document(url: str, doc_id: str) -> dict | None:
        page = 1
        try:
            while True:
                r = await client.post(f"{url}/documents/paginated", json={"page": page, "page_size": 100})
                r.raise_for_status()
                data = r.json()
                doc = next((d for d in data.get("documents", []) if d.get("id") == doc_id), None)
                if doc or not data.get("pagination", {}).get("has_next"):
                    return doc
                page += 1
        except (httpx.HTTPError, ValueError):
            return None

    @app.get("/agent/documents/{doc_id}/file")
    async def document_file(doc_id: str, user: User = Depends(current_user)) -> FileResponse:
        """The original upload, for the UI's preview; only from a server at the caller's level."""
        doc = None
        for url in settings.level_servers[: user.level]:
            doc = await find_document(url, doc_id)
            if doc:
                break
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found at your access level")
        path = raw_file(doc.get("file_path") or "", settings.data_dir, user.level)
        if path is None:
            raise HTTPException(status_code=404, detail="the original file is not on this server")
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media, filename=path.name, content_disposition_type="inline")

    def remove_local_files(file_path: str) -> list[str]:
        """Pipeline outputs of a deleted document; the raw upload stays (undo by uploading it again)."""
        stem = Path(Path(file_path).name).stem
        stem = stem.split(".[", 1)[0]  # "x.[native-P!]" -> "x"
        data = settings.data_dir
        removed = []
        for p in [data / "cleaned_md" / f"{stem}.md", data / "cleaned_md" / f"{stem}.[native-P!].md",
                  data / "cleaned_md" / f"{stem} - images.[native-P!].md", data / "cleaned_json" / f"{stem}.json"]:
            if p.exists():
                p.unlink()
                removed.append(p.name)
        parsed = (data / "parsed" / stem).resolve()
        # Never more than one folder directly under parsed/ (a name like ".." must not reach data/).
        if stem not in ("", ".", "..") and parsed.is_dir() and parsed.parent == (data / "parsed").resolve():
            shutil.rmtree(parsed)
            removed.append(f"parsed/{stem}/")
        return removed

    @app.delete("/agent/documents/{doc_id}")
    async def delete_document(doc_id: str, user: User = Depends(current_user)) -> dict:
        """Remove a document from every level server holding it: chunks, vectors, its knowledge-
        graph contributions and cache (LightRAG delete_document), then its local pipeline files."""
        if not user.can_upload:
            raise HTTPException(status_code=403, detail="this user may not delete documents")
        if doc_id.startswith("job-"):
            raise HTTPException(status_code=409, detail="this upload is still being processed; delete it when it is ready")
        doc = None
        # The servers this user can see (levels 1..user.level), skipping any that is not running.
        for url in settings.level_servers[: user.level]:
            doc = await find_document(url, doc_id)
            if doc:
                break
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found at your access level")
        names = {Path(doc.get("file_path") or "").name, (doc.get("metadata") or {}).get("source_file") or ""} - {""}
        holders, unreachable = {}, []
        for lv, url in enumerate(settings.level_servers, 1):
            ids = await named_documents(url, names)
            if ids is None:
                # Not running: it may still hold the document, and nothing here can tell. Reported,
                # never passed off as deleted; delete again once that server is up.
                unreachable.append(f"level_{lv}")
            elif ids:
                holders[lv] = (url, ids)
        if min(holders, default=user.level) > user.level:
            raise HTTPException(status_code=403, detail="cannot delete a document above your access level")
        deleted = []
        for lv, (url, ids) in sorted(holders.items()):
            r = await client.request("DELETE", f"{url}/documents/delete_document", json={"doc_ids": ids, "delete_file": False})
            status = r.json().get("status") if r.status_code == 200 else None
            if status == "busy":
                raise HTTPException(status_code=409, detail="the knowledge base is busy indexing another document - try again in a minute")
            if r.status_code != 200 or status not in ("deletion_started", "success"):
                raise HTTPException(status_code=502, detail=f"level_{lv} refused the deletion ({r.status_code} {status})")
            deleted.append(f"level_{lv}")
        # Deletion runs in the background on each server: wait briefly so the UI's next listing is right.
        for _ in range(30):
            remaining = [url for url, _ in holders.values() if await named_documents(url, names)]
            if not remaining:
                break
            await asyncio.sleep(2)
        # Earlier answers quoting the document sit in the conversation history the LLM is given; left
        # there, the next question was answered from them (seen live, right after a delete).
        history.clear()
        return {"status": "deleted", "levels": deleted, "notChecked": unreachable,
                "removedFiles": remove_local_files(doc.get("file_path") or "")}

    # iot_service's read-only control-room dashboard, so it opens at :9700 and through the tunnel
    # (the service itself listens on 127.0.0.1 only). GET only: it has no write routes.
    DASHBOARD_HEADERS = ("x-dashboard-token",)

    async def dashboard_get(request: Request, path: str) -> Response:
        if not settings.iot_url:
            raise HTTPException(status_code=404, detail="the IoT service is not enabled (-WithIoT)")
        headers = {k: v for k, v in request.headers.items() if k.lower() in DASHBOARD_HEADERS}
        try:
            r = await client.get(f"{settings.iot_url}{path}", params=request.query_params, headers=headers, timeout=15)
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="the IoT service is not reachable") from None
        return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_root() -> RedirectResponse:
        return RedirectResponse("/dashboard/")

    @app.get("/dashboard/{path:path}", include_in_schema=False)
    async def dashboard_files(path: str, request: Request) -> Response:
        return await dashboard_get(request, f"/dashboard/{path}")

    @app.get("/api/v1/dashboard/{path:path}", include_in_schema=False)
    async def dashboard_api(path: str, request: Request) -> Response:
        return await dashboard_get(request, f"/api/v1/dashboard/{path}")

    @app.get("/api/v1/stream", include_in_schema=False)
    async def dashboard_stream(request: Request) -> StreamingResponse:
        """The dashboard's server-sent events, relayed as they arrive (no read timeout)."""
        if not settings.iot_url:
            raise HTTPException(status_code=404, detail="the IoT service is not enabled (-WithIoT)")
        if "cf-ray" in request.headers:
            # Through a Cloudflare quick tunnel the events never arrive (it holds the body back),
            # and the open-but-silent stream left the dashboard empty. Refused, its EventSource
            # errors and the dashboard polls /api/v1/dashboard/* every 3 s instead.
            raise HTTPException(status_code=503, detail="live events are not relayed through the tunnel; poll instead")
        headers = {k: v for k, v in request.headers.items() if k.lower() in DASHBOARD_HEADERS}
        upstream = client.build_request("GET", f"{settings.iot_url}/api/v1/stream", params=request.query_params,
                                        headers=headers, timeout=httpx.Timeout(10, read=None))
        try:
            r = await client.send(upstream, stream=True)
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="the IoT service is not reachable") from None
        if r.status_code != 200:
            body = await r.aread()
            await r.aclose()
            return Response(body, status_code=r.status_code, media_type=r.headers.get("content-type"))

        async def relay():
            try:
                async for chunk in r.aiter_bytes():
                    yield chunk
            except httpx.HTTPError:
                pass  # IoT restarted: the dashboard reconnects (or falls back to polling) by itself
            finally:
                await r.aclose()

        # Exactly "text/event-stream": media_type= would append "; charset=utf-8", and cloudflared
        # (the quick tunnel) then buffered the whole stream - the dashboard got nothing remotely.
        return StreamingResponse(relay(), headers={"Content-Type": "text/event-stream",
                                                   "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/agent/incidents")
    async def incidents(user: User = Depends(current_user)) -> list[dict]:
        if settings.iot_url:
            return await iot("GET", "/agent/incidents")
        return ops().get("incidents", [])

    @app.get("/agent/incidents/{incident_id}")
    async def incident(incident_id: str, user: User = Depends(current_user)) -> dict:
        if settings.iot_url:
            return await iot("GET", f"/agent/incidents/{quote(incident_id, safe='')}")
        for inc in ops().get("incidents", []):
            if inc.get("id") == incident_id:
                return inc
        raise HTTPException(status_code=404, detail="incident not found")

    @app.get("/agent/telemetry/{device_id}")
    async def telemetry(device_id: str, user: User = Depends(current_user)) -> dict:
        if settings.iot_url:
            return await iot("GET", f"/agent/telemetry/{quote(device_id, safe='')}")
        # By incident id (sample_ops.json keys) or by the snapshot's own deviceId, the key
        # iot_service uses: the UI polls with whichever it has.
        snaps = ops().get("telemetry", {})
        snap = snaps.get(device_id) or next((s for s in snaps.values() if s.get("deviceId") == device_id), None)
        if snap is None:
            raise HTTPException(status_code=404, detail="no telemetry for this device")
        return snap

    @app.post("/agent/actions/{action_id}/approve")
    async def approve(action_id: str, user: User = Depends(current_user)) -> dict:
        if settings.iot_url:
            if not user.can_approve:
                raise HTTPException(status_code=403, detail="this user may not approve agent actions")
            res = await iot("POST", f"/agent/actions/{quote(action_id, safe='')}/approve")
            log_action({"ts": datetime.now(timezone.utc).isoformat(), "action": action_id, "decision": "approve",
                        "user": user.name, "ack": res.get("ack"), "executed": "by iot_service (simulator)"})
            return res
        ack = f"ACK-{uuid.uuid4().hex[:6].upper()}"
        log_action({"ts": datetime.now(timezone.utc).isoformat(), "action": action_id, "decision": "approve",
                    "user": user.name, "ack": ack, "executed": False,
                    "note": "recorded only - the gateway never sends PLC commands"})
        return {"ack": ack}

    @app.post("/agent/actions/{action_id}/reject")
    async def reject(action_id: str, user: User = Depends(current_user)) -> dict:
        if settings.iot_url:
            if not user.can_approve:
                raise HTTPException(status_code=403, detail="this user may not reject agent actions")
            res = await iot("POST", f"/agent/actions/{quote(action_id, safe='')}/reject")
            log_action({"ts": datetime.now(timezone.utc).isoformat(), "action": action_id, "decision": "reject",
                        "user": user.name, "executed": False})
            return res
        log_action({"ts": datetime.now(timezone.utc).isoformat(), "action": action_id, "decision": "reject",
                    "user": user.name, "executed": False})
        return {"status": "rejected"}

    return app


def main() -> None:
    import uvicorn

    port = int(os.environ.get("DENSO_GATEWAY_PORT", "9700"))
    host = os.environ.get("DENSO_GATEWAY_HOST", "127.0.0.1")  # 0.0.0.0 inside a container only
    uvicorn.run(create_app(Settings.from_env()), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
