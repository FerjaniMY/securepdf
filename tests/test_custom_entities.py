"""Tests for the YAML custom entity profile loader."""

from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip("yaml")

from securepdf.detection.custom_entities import parse_profile  # noqa: E402


def test_empty_profile():
    profile = parse_profile("")
    assert profile.recognizers == []
    assert profile.descriptions == []


def test_pattern_entry():
    yaml_text = """
patterns:
  - name: codename
    regex: '\\bPROJECT_[A-Z]+\\b'
    score: 0.9
    context: ['internal']
"""
    profile = parse_profile(yaml_text)
    assert len(profile.recognizers) == 1
    rec = profile.recognizers[0]
    assert rec.supported_entities == ["CUSTOM:codename"]
    assert rec.patterns[0].score == 0.9


def test_keyword_entry_compiles_to_alternation():
    yaml_text = """
keywords:
  - name: clients
    terms: ['Acme Corp', 'Foo Inc.', 'Bar (LLC)']
    score: 0.85
"""
    profile = parse_profile(yaml_text)
    assert len(profile.recognizers) == 1
    regex = profile.recognizers[0].patterns[0].regex
    # All terms should be present, regex-escaped — note the period and parens.
    assert "Acme\\ Corp" in regex or "Acme Corp" in regex
    assert "Foo\\ Inc\\." in regex or "Foo Inc\\." in regex


def test_descriptions_passed_through():
    yaml_text = """
descriptions:
  - "Internal codenames like PROJECT_X"
  - "Restricted client names"
"""
    profile = parse_profile(yaml_text)
    assert len(profile.descriptions) == 2


def test_keyword_without_terms_raises():
    yaml_text = """
keywords:
  - name: empty
    terms: []
"""
    with pytest.raises(ValueError, match="empty terms"):
        parse_profile(yaml_text)


def test_entity_types_property():
    yaml_text = """
patterns:
  - name: alpha
    regex: '\\bA+\\b'
keywords:
  - name: beta
    terms: ['hello']
"""
    profile = parse_profile(yaml_text)
    assert profile.entity_types == ["CUSTOM:alpha", "CUSTOM:beta"]
