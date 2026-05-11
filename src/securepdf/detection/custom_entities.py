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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from presidio_analyzer import Pattern, PatternRecognizer


@dataclass
class CustomEntityProfile:
    """Parsed user profile. Pass to the detection pipeline."""

    recognizers: list[PatternRecognizer] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)

    @property
    def entity_types(self) -> list[str]:
        return sorted({r.supported_entities[0] for r in self.recognizers})


def _make_pattern_recognizer(entry: dict) -> PatternRecognizer:
    name = entry["name"]
    pattern = Pattern(
        name=f"custom_{name}",
        regex=entry["regex"],
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
