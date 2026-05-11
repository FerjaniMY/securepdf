"""Standalone tests for financial pattern recognizers."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("presidio_analyzer")

from securepdf.detection.financial_recognizers import (  # noqa: E402
    US_EIN_RECOGNIZER,
    US_ROUTING_RECOGNIZER,
)


def _pattern_re(recognizer) -> re.Pattern:
    return re.compile(recognizer.patterns[0].regex)


def test_ein_matches_hyphenated_form():
    pat = _pattern_re(US_EIN_RECOGNIZER)
    assert pat.search("EIN: 12-3456789")
    assert pat.search("Tax ID 87-6543210")


def test_ein_skips_other_hyphenated_numbers():
    pat = _pattern_re(US_EIN_RECOGNIZER)
    # Phone-like: 555-1234567 has 3 digits before the hyphen, EIN has 2.
    assert pat.search("Phone 555-1234567") is None
    # SSN-like: 123-45-6789 doesn't match the EIN regex (different shape).
    assert pat.search("SSN: 123-45-6789") is None


def test_routing_matches_9_digits():
    pat = _pattern_re(US_ROUTING_RECOGNIZER)
    assert pat.search("Routing: 021000021")


def test_routing_pattern_alone_is_low_confidence():
    """Routing recognizer's score is 0.35 — only context boost makes it surface."""
    assert US_ROUTING_RECOGNIZER.patterns[0].score < 0.4
