"""Tests for the memory guard's decision step (denso/tools/mem_guard.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from mem_guard import GuardState, decide  # noqa: E402


def run(samples, unload=1.5, kill=0.8, step=5.0):
    state, out = GuardState(), []
    for i, gb in enumerate(samples):
        out.append(decide(gb, state, unload, kill, now=1000 + i * step))
    return out


def test_plenty_of_ram_does_nothing():
    assert run([6.0, 4.0, 2.0]) == [[], [], []]


def test_unload_once_then_cooldown():
    assert run([1.2, 1.2, 1.2]) == [["unload_ollama"], [], []]


def test_unload_again_after_cooldown():
    assert run([1.2, 1.2], step=61) == [["unload_ollama"], ["unload_ollama"]]


def test_kill_needs_two_low_samples_in_a_row():
    # A single dip (e.g. a short spike) must not kill a resumable job.
    assert run([0.5, 2.0, 0.5])[2] == []
    assert "kill_jobs" in run([0.5, 0.5])[1]


def test_kill_streak_resets_after_kill():
    out = run([0.5, 0.5, 0.5])
    assert "kill_jobs" in out[1] and "kill_jobs" not in out[2]
