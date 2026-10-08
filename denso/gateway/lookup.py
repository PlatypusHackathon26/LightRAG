"""Keyword search over vehicle-application catalogue rows (model, engine code, year).

Embeddings cannot tell near-identical rows apart; this matches the words that matter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")
YEAR_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})?(?!\d)")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
DISPLACEMENT = re.compile(r"\b(\d\.\d{1,2})\s*L?\b", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
# Words that say what is asked, not which vehicle: they appear in every question.
STOPWORDS = {
    "WHICH", "WHAT", "DENSO", "SPARK", "PLUG", "PLUGS", "FITS", "FIT", "FOR", "THE", "A", "AN", "MY", "IS",
    "ARE", "LISTED", "CAR", "VEHICLE", "MODEL", "ENGINE", "YEAR", "WIPER", "BLADE", "BLADES", "PART",
    "NUMBER", "WITH", "AND", "OF", "TO", "IN", "DO", "DOES", "USE", "USED", "RECOMMENDED", "SUITABLE",
    "BUGI", "NAO", "LAP", "CHO", "DOI", "XE", "NAM", "DUNG", "LOAI", "GAT", "MUA", "CUA", "LA", "GI",
}
MAKES = {"TOYOTA", "HONDA", "NISSAN", "MAZDA", "SUZUKI", "MITSUBISHI", "HYUNDAI", "KIA", "FORD", "LADA",
         "CHEVROLET", "DAEWOO", "ISUZU", "SUBARU", "DAIHATSU", "LEXUS", "BMW", "MERCEDES", "AUDI", "VOLKSWAGEN",
         "VW", "PEUGEOT", "RENAULT", "CITROEN", "SKODA", "OPEL", "FIAT", "VOLVO", "PROTON", "PERODUA", "VINFAST"}


@dataclass(frozen=True)
class Row:
    source: str   # catalogue file name
    page: int
    text: str     # the row without its page cell, upper-case


@dataclass(frozen=True)
class Query:
    words: frozenset[str]      # model words and codes, upper-case
    makes: frozenset[str]
    years: tuple[int, ...]
    displacements: tuple[str, ...]
    product: str | None = None   # "spark" / "wiper" when the question names the product


def ascii_upper(text: str) -> str:
    import unicodedata
    text = text.replace("đ", "d").replace("Đ", "D")  # NFKD does not decompose đ
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()


def parse_query(question: str) -> Query:
    q = ascii_upper(question)
    displacements = tuple(dict.fromkeys(DISPLACEMENT.findall(q)))
    years = tuple(int(y) for y in YEAR.findall(q))
    # Remove displacements ("1.3L" would split into "1" + "3L") and year ranges before taking words.
    rest = YEAR_RANGE.sub(" ", DISPLACEMENT.sub(" ", q))
    words, makes = set(), set()
    for w in WORD.findall(rest):
        if w in MAKES:
            makes.add(w)
        elif w not in STOPWORDS and len(w) >= 2 and not YEAR.fullmatch(w) and not re.fullmatch(r"\d+", w):
            words.add(w)
    return Query(frozenset(words), frozenset(makes), years, displacements, product_of(q))


def product_of(question_upper: str) -> str | None:
    """Which catalogue the question is about, when it says so."""
    if re.search(r"\bWIPER|\bGAT\b|\bCAN GAT\b|\bLUOI GAT\b", question_upper):
        return "wiper"
    if re.search(r"\bSPARK\s*PLUG|\bBUGI\b", question_upper):
        return "spark"
    return None


def load_rows(paths: list[Path]) -> list[Row]:
    rows = []
    for path in paths:
        name = path.name
        for line in path.read_text(encoding="utf-8").splitlines():
            m = ROW.match(line.strip())
            if m:
                rows.append(Row(name, int(m.group(1)), ascii_upper(m.group(2))))
    return rows


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"(?<![A-Z0-9]){re.escape(word)}(?![A-Z0-9])", text))


def score(row: Row, q: Query) -> float:
    text = row.text
    s = 0.0
    model_hits = 0
    for w in q.words:
        if _has_word(text, w):
            has_digit = any(c.isdigit() for c in w)
            s += 4 if has_digit else 3      # codes (NRE180, 1NR-FE) are the strongest evidence
            model_hits += 1
    if q.words and not model_hits:
        return 0.0                          # the asked model / code must be on the row
    s += sum(1 for mk in q.makes if mk in text)
    for d in q.displacements:
        # "1.3L", "1.33L" or a bare "VIOS 1.5" / "1.5J" - but not "11.3" or "1.35"
        if re.search(rf"(?<![\d.]){re.escape(d)}(?:\d?\s*L|(?![\d.]))", text):
            s += 2
    if q.years:
        ranges = [(int(a), int(b) if b else 2100) for a, b in YEAR_RANGE.findall(text)]
        if ranges:
            s += 3 if any(a <= y <= b for y in q.years for a, b in ranges) else -4
    return s


def unknown_names(rows: list[Row], question: str) -> set[str]:
    """Capitalised model names in the question that no catalogue row contains anywhere.

    "Lada Niva": no row says NIVA, but one Lada row matched on LADA alone and the answer
    offered its plugs for the Niva. A named vehicle the catalogue never mentions is not listed.
    """
    named = {ascii_upper(w) for w in re.findall(r"\b[A-Z][A-Za-z0-9-]+\b", question)}
    q = parse_query(question)
    candidates = (named & q.words) - MAKES
    vocab = {w for r in rows for w in WORD.findall(r.text)}
    return {w for w in candidates if w not in vocab}


def search(rows: list[Row], question: str, limit: int = 12, min_score: float = 3.0) -> list[tuple[Row, float]]:
    q = parse_query(question)
    if not q.words and not q.makes:
        return []
    if unknown_names(rows, question):
        return []  # the gateway then asks the lookup server, whose answer can say "not listed"
    if q.product:
        key = "WIPER" if q.product == "wiper" else "SPARK"
        rows = [r for r in rows if key in r.source.upper()] or rows
    # A chassis / engine code in the question ("RE3") picks the rows that show it: given a
    # "CR-V 2008" row without the code too, the model chose it and claimed it covers RE3.
    codes = {w for w in q.words if any(c.isdigit() for c in w)}
    with_codes = [r for r in rows if codes and all(_has_word(r.text, c) for c in codes)]
    rows = with_codes or rows
    scored = [(r, score(r, q)) for r in rows]
    hits = sorted((x for x in scored if x[1] >= min_score), key=lambda x: (-x[1], x[0].page))
    if not hits and q.years:
        # The model is listed but not for that year ("Lada Niva 2015": NIVA 2006-2013): its rows
        # are the evidence that lets the answer say which years are covered.
        undated = Query(q.words, q.makes, (), q.displacements, q.product)
        hits = sorted((x for x in ((r, score(r, undated)) for r in rows) if x[1] >= min_score),
                      key=lambda x: (-x[1], x[0].page))
    seen, out = set(), []
    for r, s in hits:
        if (r.source, r.text) not in seen:
            seen.add((r.source, r.text))
            out.append((r, s))
        if len(out) == limit:
            break
    return out


def rows_context(hits: list[tuple[Row, float]]) -> str:
    """Catalogue rows for the LLM, each with its file and page."""
    return "\n".join(f"[{i}] {r.source} | page {r.page} | {r.text}" for i, (r, _) in enumerate(hits, 1))


ANSWER_INSTRUCTIONS = (
    "You answer vehicle-application questions from DENSO catalogue rows. Use ONLY the rows below; "
    "they are OCR'd table rows whose columns may be shifted (model, engine size and code, specification, "
    "production years, DENSO part numbers, quantity). List every row that matches the vehicle asked about "
    "with its engine, years and DENSO part number(s), and cite the row number like [2] and its page. "
    "When the question gives a chassis or engine code (e.g. RE3, NRE180), the rows naming that code come "
    "first; never claim a row covers a code it does not show. "
    "If the asked year falls outside every matching row's years, or no row matches the model, say so plainly "
    "instead of guessing. Answer in the language of the question."
)
