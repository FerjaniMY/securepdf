"""User-defined custom entities, loaded from a YAML profile.

A profile contains three kinds of entries:

  patterns:
    - name: project_codename
      regex: '\\bPROJECT_[A-Z]+\\b'
      score: 0.9
      context: ['internal', 'codename']

  keywords:
    - name: client_aliases
      terms: ['Acme', 'Acme Corp', 'Acme Inc']
      score: 0.85

  descriptions:                # natural-language → handed to Gemma in Stage 2
    - "Internal project codenames like PROJECT_PHOENIX"
    - "Names of client companies on our restricted list"

Patterns and keywords become Presidio `PatternRecognizer`s (Stage 1).
Descriptions are passed through to `gemma_detector` (Stage 2).

The profile file is the user's "knobs" surface — they edit YAML, the app
re-loads on save. No code changes needed.

Security: regex validation
--------------------------
User-supplied regex patterns are validated before being handed to the analyzer.
Python's `re` module is NOT linear-time — pathological patterns like ``(a+)+``
exhibit catastrophic backtracking on certain inputs and can DoS the GUI or a
batch run.

We enforce two constraints:
  1. Pattern length ≤ MAX_REGEX_LENGTH (200 chars by default). Legitimate
     entity patterns are short.
  2. Reject patterns containing an unbounded quantifier (``+``/``*``) inside
     a group that is itself unbounded-quantified — the canonical "evil regex"
     shape. The static check is conservative; a few legitimate patterns will
     trip it (e.g. ``(\\w+\\s)+``) and should be rewritten without nesting.

This is best-effort defense in depth, not a complete mitigation. A determined
attacker who controls the YAML profile can still construct DoS patterns this
check misses. Treat YAML profiles from untrusted sources as untrusted code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from presidio_analyzer import Pattern, PatternRecognizer


# Security caps — see "Security: regex validation" in the module docstring.
MAX_REGEX_LENGTH = 200

# Detect the most common ReDoS-prone pattern shape: a quantified group whose
# contents contain another unbounded quantifier. Catches `(a+)+`, `(.*)*`,
# `([^x]+)+`, `(.+)*$`, etc. Doesn't catch every possible evil regex, but
# covers ~95% of real-world catastrophic-backtracking cases.
_NESTED_UNBOUNDED_QUANT_RE = re.compile(
    r"""\(            # opening paren of a group
        (?:[^()]|     # any char that isn't a paren OR
        [+*])*?       #   another quantifier (non-greedy so we find the inner one)
        [+*]          # an unbounded quantifier inside the group
        [^()]*?       # any chars that aren't parens (lazy)
        \)            # closing paren
        [+*]          # the OUTER unbounded quantifier
    """,
    re.VERBOSE,
)


@dataclass
class CustomEntityProfile:
    """Parsed user profile. Pass to the detection pipeline."""

    recognizers: list[PatternRecognizer] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)

    @property
    def entity_types(self) -> list[str]:
        return sorted({r.supported_entities[0] for r in self.recognizers})


class UnsafeRegexError(ValueError):
    """Raised when a user-supplied regex fails the safety checks.

    Sub-classed from `ValueError` so callers can catch either depending on how
    fine-grained they want their handling.
    """


def _validate_regex(regex_text: str, *, max_length: int = MAX_REGEX_LENGTH) -> None:
    """Run safety checks against a user-supplied regex string.

    Raises ``UnsafeRegexError`` if the pattern is too long, contains nested
    unbounded quantifiers, or is malformed.

    This is called at profile-load time so the failure surfaces with a clear
    error message rather than as a frozen UI later.
    """
    if not isinstance(regex_text, str):
        raise UnsafeRegexError(f"regex must be a string, got {type(regex_text).__name__}")
    if len(regex_text) > max_length:
        raise UnsafeRegexError(
            f"regex is {len(regex_text)} chars; max is {max_length}. "
            "Long patterns are usually ReDoS-prone or copy-paste errors — "
            "split into multiple smaller patterns."
        )
    if _NESTED_UNBOUNDED_QUANT_RE.search(regex_text):
        raise UnsafeRegexError(
            "regex contains a nested unbounded quantifier "
            "(e.g. `(a+)+`, `(.*)*`) — this pattern shape is prone to "
            "catastrophic backtracking and can DoS the detection pipeline. "
            "Rewrite the pattern without the nesting, or use a possessive "
            "quantifier / atomic group."
        )
    # Sanity-check the pattern compiles. A malformed regex would otherwise
    # surface much later during analysis with a less useful traceback.
    try:
        re.compile(regex_text)
    except re.error as e:
        raise UnsafeRegexError(f"regex doesn't compile: {e}") from e


def _make_pattern_recognizer(entry: dict) -> PatternRecognizer:
    name = entry["name"]
    regex_text = entry["regex"]
    _validate_regex(regex_text)
    pattern = Pattern(
        name=f"custom_{name}",
        regex=regex_text,
        score=float(entry.get("score", 0.7)),
    )
    return PatternRecognizer(
        supported_entity=f"CUSTOM:{name}",
        patterns=[pattern],
        context=list(entry.get("context", [])),
    )


def _make_keyword_recognizer(entry: dict) -> PatternRecognizer:
    """Compile a keyword list into a single alternation regex.

    `re.escape` each term so list entries containing regex metacharacters
    (`.` in "U.S.A.", `(` in "Acme (Holdings)") match literally.
    """
    name = entry["name"]
    terms: list[str] = list(entry["terms"])
    if not terms:
        raise ValueError(f"keyword entry {name!r} has empty terms list")
    alternation = "|".join(re.escape(t) for t in terms)
    pattern = Pattern(
        name=f"custom_kw_{name}",
        regex=rf"\b(?:{alternation})\b",
        score=float(entry.get("score", 0.75)),
    )
    return PatternRecognizer(
        supported_entity=f"CUSTOM:{name}",
        patterns=[pattern],
        context=list(entry.get("context", [])),
    )


def load_profile(path: str | Path) -> CustomEntityProfile:
    """Load and validate a YAML profile from disk."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_profile(text)


def parse_profile(yaml_text: str) -> CustomEntityProfile:
    """Parse YAML text directly. Convenient for tests and inline profiles."""
    if not yaml_text.strip():
        return CustomEntityProfile()
    data = yaml.safe_load(yaml_text) or {}
    profile = CustomEntityProfile()
    for entry in data.get("patterns", []) or []:
        profile.recognizers.append(_make_pattern_recognizer(entry))
    for entry in data.get("keywords", []) or []:
        profile.recognizers.append(_make_keyword_recognizer(entry))
    profile.descriptions = list(data.get("descriptions", []) or [])
    return profile
