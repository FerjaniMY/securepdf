"""Consistent pseudonym assignment across a document.

The contract: the same sensitive text appearing N times in a document gets the
same pseudonym N times. "Jane Doe" → "[PERSON_1]" everywhere, even if it's
spelled "JANE DOE" in one place and "Jane Doe" in another (case-insensitive match).

We do NOT collapse different entities into one pseudonym just because they look
similar — "Jane Doe" (PERSON) and "Jane Doe" (some custom entity) get different
pseudonyms because the key includes entity_type.

Why this matters
----------------
When a user pastes anonymized text into ChatGPT and asks "who paid John?", the
LLM needs to be able to reason about the same person referenced multiple times.
If we'd given "John Smith" three different pseudonyms throughout the document,
that signal is destroyed.
"""

from __future__ import annotations

from collections import defaultdict


class PseudonymMap:
    """Map (entity_type, text) → pseudonym.

    Pseudonyms have the form `[<ENTITY_TYPE>_<INDEX>]`, with index starting at 1
    and incrementing per entity_type. So the first PERSON becomes `[PERSON_1]`,
    the second `[PERSON_2]`, while emails count separately: `[EMAIL_ADDRESS_1]`.

    Text normalization
    ------------------
    We lowercase + strip whitespace before keying. Two reasons:
      1. Casing variations refer to the same entity (JANE DOE / Jane Doe).
      2. Whitespace artifacts from text extraction (trailing space on a word that
         appeared at the end of a line) shouldn't fragment the mapping.

    We preserve the original text in `as_key_dict()` so the user can rebuild the
    document if they keep the mapping as a key.
    """

    def __init__(self) -> None:
        # Key: (entity_type, normalized_text); value: assigned pseudonym.
        self._map: dict[tuple[str, str], str] = {}
        # Key: pseudonym; value: a representative original (first seen casing).
        self._originals: dict[str, str] = {}
        self._counts: dict[str, int] = defaultdict(int)

    def pseudonym_for(self, entity_type: str, text: str) -> str:
        """Return the pseudonym for this entity. Same key → same pseudonym every call."""
        norm = self._normalize(text)
        key = (entity_type, norm)
        if key not in self._map:
            self._counts[entity_type] += 1
            pseudonym = f"[{entity_type}_{self._counts[entity_type]}]"
            self._map[key] = pseudonym
            self._originals[pseudonym] = text  # keep the first-seen casing
        return self._map[key]

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    def as_key_dict(self) -> dict[str, str]:
        """Return {pseudonym: original_text} — useful for the user to keep as a decoder.

        The original_text is the first-seen casing for that entity; if the document
        used both "Jane Doe" and "JANE DOE", the key dict shows "Jane Doe".
        """
        return dict(self._originals)

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, key: tuple[str, str]) -> bool:
        entity_type, text = key
        return (entity_type, self._normalize(text)) in self._map
