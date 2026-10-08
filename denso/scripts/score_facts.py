"""Score benchmark answers without an LLM: are the ground truth's numbers and codes in the answer?

Usage:
    python denso/scripts/score_facts.py --name level_1_knowledge
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH = ROOT / "data" / "evaluation" / "Benchmark_30_QA.json"
DEFAULT_OUT = ROOT / "results"

# A code mixes letters and digits (DCRS300260, R-134a, M14, DRA-012) or is a
# dashed digit group (294009-2150).
CODE = re.compile(r"(?<![\w-])(?:(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|\d+-\d{3,})(?![\w-])")
# A number: 1/12 (fraction) / 20,000 (thousands) / 6,9 (decimal comma) / 10.8 / 40
NUMBER = re.compile(r"(?<![\w.,/])\d+(?:/\d+|(?:[.,]\d+)*)(?![\w/])")
# "140cc" and "140 cc" are the same fact: split a number from a glued unit first.
GLUED_UNIT = re.compile(r"(\d)(cc|mm|cm3|cm³|ml|nm|km|kpa|mpa|kg|°c)\b", re.IGNORECASE)
LIST_MARKER = re.compile(r"(?:(?<=\s)|^)(?:\d+|[a-z])\)")
REFUSAL = re.compile(
    r"not (?:enough|sufficient)|(?:do not|don[\'’]t|does not|doesn[\'’]t) have (?:enough|sufficient)|insufficient|no (?:information|data|figure|value|km)|"
    r"does(?: not|n't) (?:specify|state|provide|list|mention|include|give)|"
    r"(?:is|are) not (?:specified|stated|provided|listed|mentioned|available|given)|"
    r"not (?:specified|stated|provided|listed|mentioned) in|cannot (?:be )?(?:determine|found|answer)|"
    r"unable to|\[no-context\]|không đủ thông tin|không có thông tin",
    re.IGNORECASE,
)


def parse_number(tok: str) -> float | None:
    if "/" in tok:
        num, den = tok.split("/")
        return int(num) / int(den) if int(den) else None
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", tok):  # 20,000 / 100,000.5
        tok = tok.replace(",", "")
    elif re.fullmatch(r"\d+,\d+", tok):  # 6,9 decimal comma
        tok = tok.replace(",", ".")
    try:
        return float(tok)
    except ValueError:
        return None


# Units that look like codes after normalisation (cm³ -> cm3): never facts on their own.
NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
UNIT_TOKENS = {"cm3", "cm2", "mm2", "mm3", "m2", "m3", "km2", "co2"}
DASHES = re.compile(r"[‐-―−﹘﹣－]")


def normalize(text: str) -> str:
    """LLMs write look-alike characters: non-breaking hyphen 294009‑2150, ½, narrow no-break spaces.

    NFKC turns ½ into 1⁄2 and odd spaces into plain ones; the fraction slash and every
    Unicode dash are then mapped to ASCII so numbers and codes compare as written.
    """
    text = unicodedata.normalize("NFKC", text).replace("⁄", "/")
    return DASHES.sub("-", text)


def norm_code(code: str) -> str:
    return code.lower().replace("-", "")


def extract(text: str) -> tuple[set[str], set[float]]:
    """Return (codes, numbers) mentioned in text. Numbers inside codes are not counted twice."""
    text = GLUED_UNIT.sub(r"\1 \2", LIST_MARKER.sub(" ", normalize(text)))
    codes = {norm_code(m.group(0)) for m in CODE.finditer(text)} - UNIT_TOKENS
    stripped = CODE.sub(" ", text)
    numbers = {n for m in NUMBER.finditer(stripped) if (n := parse_number(m.group(0))) is not None}
    return codes, numbers


def score_answer(question: dict, answer: str) -> dict:
    if not question.get("answerable_from_documents", True):
        declined = bool(REFUSAL.search(answer))
        return {"kind": "abstention", "score": 1.0 if declined else 0.0, "declined": declined}
    codes, numbers = extract(question["ground_truth_answer"])
    if not codes and not numbers:
        return {"kind": "prose", "score": None}
    _, a_numbers = extract(answer)
    # "two guide pins" states the fact 2 (Q28 scored 0% for a correct answer).
    a_numbers |= {float(NUMBER_WORDS[w]) for w in re.findall(r"[a-z]+", answer.lower()) if w in NUMBER_WORDS}
    # Codes are searched in the dash-less answer, so "294009-2150", "2940092150"
    # and "R-134a"/"R134a" all match; the boundaries keep "M12" out of "M120".
    flat = GLUED_UNIT.sub(r"\1 \2", normalize(answer).lower().replace("-", ""))
    found_codes = {c for c in codes if re.search(rf"(?<![a-z0-9]){re.escape(c)}(?![a-z0-9])", flat)}
    found_numbers = {n for n in numbers if any(abs(n - x) < 1e-9 for x in a_numbers)}
    total = len(codes) + len(numbers)
    return {
        "kind": "facts",
        "score": (len(found_codes) + len(found_numbers)) / total,
        "missing": sorted(codes - found_codes) + sorted(f"{n:g}" for n in numbers - found_numbers),
        "total": total,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="Benchmark run label (results/benchmark_<name>.json)")
    ap.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--all", action="store_true", help="Score every result, not only questions answered in all modes")
    args = ap.parse_args()

    questions = {q["id"]: q for q in json.loads(args.bench.read_text(encoding="utf-8"))}
    results = json.loads((args.out / f"benchmark_{args.name}.json").read_text(encoding="utf-8"))
    modes_of: dict[str, set] = defaultdict(set)
    for key in results:
        mode, qid = key.split(":")
        modes_of[qid].add(mode)
    all_modes = set().union(*modes_of.values()) if modes_of else set()
    paired = {qid for qid, ms in modes_of.items() if ms == all_modes}
    per_mode: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for key, res in results.items():
        if not args.all and key.split(":")[1] not in paired:
            continue
        mode, qid = key.split(":")
        q = questions[int(qid)]
        per_mode[mode].append((q, score_answer(q, res["answer"])))

    scope = "all results" if args.all else f"{len(paired)} questions answered in every mode"
    lines = [f"# Fact-based scores ({args.name}; {scope})", "",
             "| Mode | Fact recall | All facts present | Abstention correct | Scored (facts/abst./prose) |",
             "|---|---|---|---|---|"]
    detail = ["", "## Missing facts", ""]
    by_cat: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for mode, rows in per_mode.items():
        facts = [s for _, s in rows if s["kind"] == "facts"]
        abst = [s for _, s in rows if s["kind"] == "abstention"]
        prose = [s for _, s in rows if s["kind"] == "prose"]
        def pct(vals: list[float]) -> str:
            return f"{sum(vals) / len(vals):.0%}" if vals else "-"
        lines.append(f"| {mode} | {pct([s['score'] for s in facts])} | {pct([float(s['score'] == 1.0) for s in facts])} "
                     f"| {pct([s['score'] for s in abst])} | {len(facts)}/{len(abst)}/{len(prose)} |")
        for q, s in sorted(rows, key=lambda r: r[0]["id"]):
            if s["score"] is not None:
                by_cat[q["category"]][mode].append(s["score"])
            if s["kind"] == "facts" and s["missing"]:
                detail.append(f"- [{mode}] Q{q['id']} ({s['score']:.0%} of {s['total']}): missing {', '.join(s['missing'])}")
            if s["kind"] == "abstention" and not s["declined"]:
                detail.append(f"- [{mode}] Q{q['id']}: did not decline (abstention question)")
    modes = list(per_mode)
    lines += ["", "## By category (fact recall / abstention)", "",
              "| Category | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
    for cat, sc in sorted(by_cat.items()):
        lines.append(f"| {cat} | " + " | ".join(
            f"{sum(v) / len(v):.0%} ({len(v)})" if (v := sc.get(m)) else "-" for m in modes) + " |")
    report = "\n".join(lines + detail) + "\n"
    (args.out / f"benchmark_{args.name}_facts.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
