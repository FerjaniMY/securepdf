"""Tests for the YAML custom entity profile loader."""

from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip("yaml")

from securepdf.detection.custom_entities import (  # noqa: E402
    MAX_REGEX_LENGTH,
    UnsafeRegexError,
    _validate_regex,
    parse_profile,
)


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


# ---------------------------------------------------------------------------
# Security: regex validation (added in v0.5.1)
# ---------------------------------------------------------------------------


class TestRegexValidation:
    """Verifies the ReDoS / safety checks in _validate_regex."""

    def test_legitimate_regex_passes(self):
        # Patterns that should be accepted — these are real-world entity shapes.
        for pattern in [
            r"\bPROJECT_[A-Z]+\b",
            r"\b[A-Z]{2,3}-\d{4,8}\b",
            r"\b\d{2}-\d{7}\b",  # the EIN pattern from financial_recognizers
            r"\b[A-TV-Z]\d{2}(?:\.[0-9A-TV-Z]{1,4})?\b",  # ICD-10 from phi_recognizers
            r"^EMP-\d{6}$",
        ]:
            _validate_regex(pattern)  # should not raise

    def test_too_long_rejected(self):
        long_pattern = "a" * (MAX_REGEX_LENGTH + 1)
        with pytest.raises(UnsafeRegexError, match="max is"):
            _validate_regex(long_pattern)

    def test_nested_unbounded_quantifier_rejected(self):
        # The canonical "evil regex" shapes — these should ALL be rejected.
        evil_patterns = [
            r"(a+)+",
            r"(a*)*",
            r"(.*)*",
            r"(.+)*",
            r"([0-9]+)*",
            r"(\d+)+",
        ]
        for pattern in evil_patterns:
            with pytest.raises(UnsafeRegexError, match="nested unbounded quantifier"):
                _validate_regex(pattern)

    def test_single_quantifier_allowed(self):
        # A single unbounded quantifier (no nesting) is fine.
        for pattern in [r"a+", r"a*", r"(?:foo)+", r"\w+", r".*?"]:
            _validate_regex(pattern)  # should not raise

    def test_malformed_regex_rejected(self):
        with pytest.raises(UnsafeRegexError, match="doesn't compile"):
            _validate_regex(r"[unclosed")

    def test_non_string_rejected(self):
        with pytest.raises(UnsafeRegexError, match="must be a string"):
            _validate_regex(12345)  # type: ignore[arg-type]

    def test_profile_with_unsafe_regex_raises(self):
        """End-to-end: an unsafe regex in YAML fails at load, not at runtime."""
        yaml_text = """
patterns:
  - name: evil
    regex: '(a+)+'
"""
        with pytest.raises(UnsafeRegexError):
            parse_profile(yaml_text)

    def test_profile_with_too_long_regex_raises(self):
        long_pattern = "a" * (MAX_REGEX_LENGTH + 1)
        yaml_text = f"""
patterns:
  - name: huge
    regex: '{long_pattern}'
"""
        with pytest.raises(UnsafeRegexError, match="max is"):
            parse_profile(yaml_text)
