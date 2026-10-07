"""Tests for the proxy's 429 interpretation (denso/tools/llm_rate_proxy.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from llm_rate_proxy import rate_limit_wait  # noqa: E402

# Shape of Google AI Studio's OpenAI-compatible 429 body.
GOOGLE_PER_MINUTE = """[{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
  {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
    {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
     "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
  {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "39s"}]}}]"""
GOOGLE_PER_DAY = GOOGLE_PER_MINUTE.replace("PerMinute", "PerDay").replace('"39s"', '"12s"')


def test_cerebras_header_wins():
    assert rate_limit_wait("86400", "{}", 300) == 86400


def test_google_per_minute_uses_retry_delay():
    assert rate_limit_wait(None, GOOGLE_PER_MINUTE, 300) == 40


def test_google_per_day_is_spent_even_with_short_delay():
    # A short retryDelay on a per-day violation must not make the proxy retry all day.
    assert rate_limit_wait(None, GOOGLE_PER_DAY, 300) > 300


def test_unknown_body_defaults_to_short_wait():
    assert rate_limit_wait(None, "rate limited", 300) == 20
