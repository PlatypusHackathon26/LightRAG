"""Tests for the LLM-free fact scorer, using real benchmark ground truths."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from score_facts import extract, score_answer  # noqa: E402


def q(truth: str, answerable: bool = True) -> dict:
    return {"ground_truth_answer": truth, "answerable_from_documents": answerable}


def test_part_numbers_ignore_dashes_and_case():
    codes, numbers = extract("DCRS300260 (294009-2150).")
    assert codes == {"dcrs300260", "2940092150"} and numbers == set()
    assert score_answer(q("DCRS300260 (294009-2150)."), "Part no. dcrs300260 / 2940092150")["score"] == 1.0


def test_glued_units_match_spaced_units():
    truth = "DCP32045 has an oil quantity of 140cc, while DCP32060 has 110cc."
    assert score_answer(q(truth), "DCP32045: 140 cc; DCP32060: 110 cc")["score"] == 1.0


def test_thousands_vs_russian_decimal_comma():
    assert extract("approximately 20,000 km versus 100,000 km")[1] == {20000.0, 100000.0}
    assert extract("от 6,9 до 10,8 Н-м")[1] == {6.9, 10.8}


def test_fractions_are_single_values():
    assert extract("about 1/2 turn (about 1/12 turn for a used plug)")[1] == {0.5, 1 / 12}


def test_unicode_look_alikes_from_real_answers():
    # Real gpt-oss answers: U+2011 non-breaking hyphen, U+00BD ½, U+202F narrow nbsp.
    assert score_answer(q("DCRS300260 (294009-2150)."), "**DCRS300260 (294009‑2150)**")["score"] == 1.0
    assert score_answer(q("about 1/2 turn"), "about ½ turn")["score"] == 1.0
    assert score_answer(q("6.9-10.8 Nm"), "6.9 – 10.8 N·m")["score"] == 1.0


def test_list_markers_are_not_facts():
    assert extract("1) Mark connector; 2) Loosen bolts; 3) Remove the O-ring")[1] == set()


def test_partial_answer_reports_missing_facts():
    s = score_answer(q("The torque is 6.9 to 10.8 Nm."), "Tighten to 10.8 Nm.")
    assert s["score"] == 0.5 and s["missing"] == ["6.9"]


def test_prose_only_truth_is_left_to_the_judge():
    assert score_answer(q("Only the DENSO recommended compressor oil may be used."), "anything")["kind"] == "prose"


def test_abstention_needs_a_refusal():
    truth = "Không đủ thông tin trong bộ tài liệu được cung cấp."
    assert score_answer(q(truth, False), "The catalogue does not specify a km interval for Iridium Racing.")["score"] == 1.0
    assert score_answer(q(truth, False), "Replace Iridium Racing plugs every 10,000 km.")["score"] == 0.0


def test_units_are_not_codes():
    # Regression: "120 cm³ - 50 cm³ = 70 cm³" (Q25) produced a bogus "cm3" code fact.
    codes, numbers = extract("120 cm³ - 50 cm³ = 70 cm³")
    assert codes == set() and numbers == {120.0, 50.0, 70.0}


def test_refusal_with_have_enough():
    # Nemotron declines with "I do not have enough information to answer." (Q30, level_1_nvidia).
    from score_facts import REFUSAL
    assert REFUSAL.search("I do not have enough information to answer.")
    assert REFUSAL.search("The documents don't have sufficient data.")
    # Typographic apostrophe, as Nemotron writes it (lookup eval L10).
    assert REFUSAL.search("I don’t have enough information to determine which spark plug fits.")


def test_a_number_written_as_a_word_counts():
    from score_facts import score_answer

    q = {"answerable_from_documents": True, "ground_truth_answer": "Yes - both require 2 guide pins."}
    assert score_answer(q, "Both sections agree that two guide pins are required.")["score"] == 1.0
