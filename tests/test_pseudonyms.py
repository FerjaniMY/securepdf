"""Tests for the PseudonymMap — consistency, case-insensitivity, key export."""

from __future__ import annotations

from securepdf.redaction.pseudonyms import PseudonymMap


def test_same_text_gets_same_pseudonym():
    pmap = PseudonymMap()
    a = pmap.pseudonym_for("PERSON", "Jane Doe")
    b = pmap.pseudonym_for("PERSON", "Jane Doe")
    assert a == b == "[PERSON_1]"


def test_different_text_increments_index():
    pmap = PseudonymMap()
    assert pmap.pseudonym_for("PERSON", "Jane Doe") == "[PERSON_1]"
    assert pmap.pseudonym_for("PERSON", "John Smith") == "[PERSON_2]"


def test_different_entity_types_have_separate_counters():
    pmap = PseudonymMap()
    pmap.pseudonym_for("PERSON", "Jane Doe")
    pmap.pseudonym_for("PERSON", "John Smith")
    assert pmap.pseudonym_for("EMAIL_ADDRESS", "x@example.com") == "[EMAIL_ADDRESS_1]"


def test_case_insensitive_match():
    """JANE DOE and Jane Doe and jane doe all refer to the same person."""
    pmap = PseudonymMap()
    a = pmap.pseudonym_for("PERSON", "Jane Doe")
    b = pmap.pseudonym_for("PERSON", "JANE DOE")
    c = pmap.pseudonym_for("PERSON", "jane doe")
    assert a == b == c


def test_whitespace_normalization():
    pmap = PseudonymMap()
    a = pmap.pseudonym_for("PERSON", "Jane  Doe")  # double space
    b = pmap.pseudonym_for("PERSON", " Jane Doe ")  # padding
    c = pmap.pseudonym_for("PERSON", "Jane Doe")
    assert a == b == c


def test_key_dict_preserves_first_seen_casing():
    pmap = PseudonymMap()
    pmap.pseudonym_for("PERSON", "Jane Doe")
    pmap.pseudonym_for("PERSON", "JANE DOE")  # second occurrence; first casing wins
    key_dict = pmap.as_key_dict()
    assert key_dict["[PERSON_1]"] == "Jane Doe"


def test_len_and_contains():
    pmap = PseudonymMap()
    assert len(pmap) == 0
    assert ("PERSON", "Jane Doe") not in pmap
    pmap.pseudonym_for("PERSON", "Jane Doe")
    assert len(pmap) == 1
    assert ("PERSON", "Jane Doe") in pmap
    assert ("PERSON", "JANE DOE") in pmap  # case-insensitive contains
