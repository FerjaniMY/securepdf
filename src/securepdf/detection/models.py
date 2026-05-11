"""Data model for the detection layer.

A `Detection` is one sensitive-text finding on a single page, with everything the
redaction stage needs to either black it out (bbox) or pseudonymize it in a text
export (text + entity_type for consistent labels like [PERSON_1]).

These types are deliberately decoupled from Presidio's own result types — the same
`Detection` can come from Presidio, from Gemma, from a custom regex, or from a
merged pair. Downstream code shouldn't care which engine produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from securepdf.pdf.models import BBox

# Where this detection originated. Affects how the merger handles overlap (Presidio
# generally has better-grounded char offsets; Gemma is fuzzy-match-anchored).
EntitySource = Literal["presidio", "gemma", "regex", "custom", "merged"]


@dataclass(frozen=True)
class Detection:
    """One sensitive-text finding on a single page.

    Attributes
    ----------
    text:
        The exact matched substring (as it appears in `PageContent.text`). For OCR'd
        pages this may contain Tesseract character errors — the detection is still
        valid, but the redaction step should snap to span bboxes rather than trying
        to re-find the literal text.
    entity_type:
        A string identifier — Presidio types ("PERSON", "EMAIL_ADDRESS", "US_SSN"),
        our custom types ("MRN", "ICD10", "US_EIN"), or "CUSTOM:<name>" for
        user-defined entities.
    page:
        0-indexed page number, matching `PageContent.page_number`.
    bbox:
        Union of the bboxes of every span overlapping the detection. This is what
        the redaction renderer draws and what the GUI overlay shows.
    char_start, char_end:
        Half-open offsets into `PageContent.text`. Used by the merger to detect
        overlap between detections and to slice the original text for the
        anonymized export.
    confidence:
        0.0–1.0. From Presidio's analyzer score, or our prompt-defined confidence
        for Gemma findings (typically 0.6–0.9 depending on entity certainty).
    source:
        Which engine produced this — see `EntitySource`.
    span_indices:
        Indices into `PageContent.spans` that this detection covers. Lets the
        redaction stage map back to exact bboxes per word, useful when the
        detection spans multiple words on multiple lines.
    """

    text: str
    entity_type: str
    page: int
    bbox: BBox
    char_start: int
    char_end: int
    confidence: float
    source: EntitySource
    span_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.char_end < self.char_start:
            raise ValueError(
                f"char_end ({self.char_end}) < char_start ({self.char_start})"
            )
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ValueError(f"invalid bbox: {self.bbox}")

    def overlaps(self, other: Detection) -> bool:
        """True if this detection's char range overlaps `other` on the same page."""
        if self.page != other.page:
            return False
        return self.char_start < other.char_end and other.char_start < self.char_end
