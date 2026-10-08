"""Check that the chatbot answers in the question's language without mixing languages.

Usage:
    python denso/scripts/eval_language.py --name baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from language import question_language  # noqa: E402

QUESTIONS = [
    ("vi", "Mô-men xoắn siết bu-lông SCV trên bơm Common Rail diesel là bao nhiêu?"),
    ("vi", "Dầu DENSO nào dùng cho máy nén kiểu TV với môi chất R-134a?"),
    ("vi", "Vì sao gioăng cao su trong hệ thống điều hòa bị phồng và cần làm gì?"),
    ("vi", "Quy trình lắp SCV mới lên bơm Common Rail gồm những bước nào?"),
    ("vi", "Phần tiếng Nga của hướng dẫn SCV ghi mô-men xoắn là bao nhiêu?"),
    ("en", "What is the run-in procedure after installing a new A/C compressor?"),
    ("en", "Why can rubber seals in an A/C system become swollen?"),
    ("en", "Does the SCV torque in the Russian-language section match the English section?"),
    ("ja", "ディーゼル用SCVの取付ボルトの締め付けトルクはいくつですか?"),
    ("ja", "新しいエアコンコンプレッサーを取り付けた後の慣らし運転の手順を教えてください。"),
]
# Verbatim by design: codes (DND08250, R-134a, M14), numbers with units, URLs, citations.
VERBATIM = re.compile(r"https?://\S+|\[[\d,\s]+\]|\([^)]*\b(?:p\.|trang|ページ)\s*\d+[^)]*\)|"
                      r"\b[A-Z0-9][A-Z0-9-]*\d[A-Z0-9/-]*\b|\b\d+(?:[.,]\d+)?\s*(?:Nm|N·m|km|mm|cc|ml|°C|%)?")
SENTENCE = re.compile(r"[^.!?。\n]+[.!?。]?")
# Document names are verbatim too ("... installation guide (đa ngôn ngữ)" is not a Vietnamese sentence).
DOC_NAMES = sorted({f.name.split(" - ")[0].split(".[")[0].removesuffix(".md")
                    for f in (ROOT / "data" / "cleaned_md").glob("*.md")}, key=len, reverse=True)


def strip_names(text: str) -> str:
    for name in DOC_NAMES:
        text = text.replace(name, " ").replace(name.replace("_", " "), " ")
    return text


def mixed_sentences(answer: str, lang: str) -> list[tuple[str, str]]:
    text = VERBATIM.sub(" ", re.sub(r"[*#`>|]", " ", strip_names(answer)))
    out = []
    for s in SENTENCE.findall(text):
        letters = re.sub(r"[^\w]|\d|_", "", s)
        if len(letters) < 20:
            continue
        found = question_language(s)
        if found and found != lang:
            out.append((found, s.strip()[:120]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", default="http://127.0.0.1:9700")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    args = ap.parse_args()

    rows = []
    with httpx.Client(base_url=args.gateway, timeout=400) as client:
        for lang, q in QUESTIONS:
            r = client.post("/agent/chat", json={"conversationId": f"lang-{time.time()}", "message": q})
            answer = r.json().get("content", "") if r.status_code == 200 else f"HTTP {r.status_code}"
            answer_lang = question_language(VERBATIM.sub(" ", strip_names(answer)))
            mixed = mixed_sentences(answer, lang)
            rows.append({"lang": lang, "question": q, "answer_lang": answer_lang, "mixed": mixed, "answer": answer})
            ok = answer_lang == lang and not mixed
            print(f"{'OK ' if ok else 'BAD'} [{lang}->{answer_lang}] mixed={len(mixed)} | {q[:50]}", flush=True)
            for found, s in mixed[:3]:
                print(f"      {found}: {s}")
    good = sum(r["answer_lang"] == r["lang"] and not r["mixed"] for r in rows)
    report = [f"# Answer language ({args.name})", "",
              f"Answered entirely in the question's language: **{good}/{len(rows)}**", "",
              "| Q lang | answer lang | mixed sentences | question |", "|---|---|---|---|"]
    report += [f"| {r['lang']} | {r['answer_lang']} | {len(r['mixed'])} | {r['question']} |" for r in rows]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"language_{args.name}.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (args.out / f"language_{args.name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "\n".join(report))


if __name__ == "__main__":
    main()
