"""Standalone tests for our PHI pattern recognizers.

We test the regex patterns directly (not through Presidio) — verifying that
the patterns themselves match the things they should and don't match obvious
non-matches. The Presidio integration is tested separately in
`test_presidio_engine.py`.
"""

from __future__ import annotations

import re

import pytest

presidio_analyzer = pytest.importorskip("presidio_analyzer")

from securepdf.detection.phi_recognizers import (  # noqa: E402
    CONDITIONS_RECOGNIZER,
    ICD10_RECOGNIZER,
    MRN_RECOGNIZER,
)


def _pattern_re(recognizer) -> re.Pattern:
    return re.compile(recognizer.patterns[0].regex, re.IGNORECASE)


def test_mrn_pattern_matches_typical_mrns():
    pat = _pattern_re(MRN_RECOGNIZER)
    assert pat.search("Patient MRN: 4827193")
    assert pat.search("Medical Record 8472910")
    assert pat.search("Patient ID 123456789012")  # 12 digits


def test_mrn_pattern_skips_short_numbers():
    pat = _pattern_re(MRN_RECOGNIZER)
    # 5 digits — below the 6-digit floor.
    assert pat.search("Room 12345") is None
    # But 6 digits would match (correctly — could be a real MRN).
    assert pat.search("Room 123456")


def test_icd10_matches_standard_codes():
    pat = _pattern_re(ICD10_RECOGNIZER)
    for code in ["E11.9", "J45", "F32.0", "A37.81"]:
        assert pat.search(code), f"failed to match {code}"


def test_icd10_rejects_reserved_letters():
    pat = _pattern_re(ICD10_RECOGNIZER)
    # U is reserved by WHO. Anything starting with U should NOT match.
    assert pat.search("U12.3") is None
    # Numeric prefixes never start ICD-10 codes.
    assert pat.search("123.45") is None


def test_conditions_match_common_terms():
    pat = _pattern_re(CONDITIONS_RECOGNIZER)
    for word in ["diabetes", "Hypertension", "depression", "cancer", "HIV"]:
        assert pat.search(word), f"failed to match {word}"


def test_conditions_dont_overmatch_substrings():
    """\\b is a word boundary — adjacent word chars don't create one. Good: 'cancerous'
    does NOT trigger the 'cancer' lexicon entry, preventing false-positive medical flags
    on words that happen to start with a condition prefix."""
    pat = _pattern_re(CONDITIONS_RECOGNIZER)
    assert pat.search("cancerous") is None  # 'cancer' is a prefix, no word boundary after
    assert pat.search("a cancer cell") is not None  # 'cancer' as a standalone word matches
