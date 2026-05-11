"""Shared data models for the extraction → detection → redaction pipeline.

These structures are the contract between Phase 1 (extraction) and the later phases
(detection, redaction). Keep them small, dataclass-based, and source-agnostic so a
PHI recognizer or a redaction renderer doesn't care whether the text came from a real
text layer or from OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# A bbox is given in PDF coordinate space: (x0, y0, x1, y1) where (0,0) is bottom-left
# in PyMuPDF's `Page.rect`-relative system (PyMuPDF normalizes this — see notes in
# extractor.py for the exact convention used).
BBox = tuple[float, float, float, float]

# Where the text came from. Affects downstream confidence: OCR'd text can have character
# errors; PDF-layer text is exact.
Source = Literal["pdf", "ocr"]


@dataclass(frozen=True)
class TextSpan:
    """A single piece of extracted text with its location on the page.

    A "span" here is roughly word-level granularity — fine enough to draw tight redaction
    boxes around individual matches (e.g. just the SSN, not the whole line).
    """

    text: str
    bbox: BBox
    page: int  # 0-indexed page number
    source: Source = "pdf"
    confidence: float = 1.0  # 1.0 for native PDF text; <1.0 for OCR (Tesseract conf / 100)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ValueError(f"invalid bbox (x1<x0 or y1<y0): {self.bbox}")


@dataclass
class PageContent:
    """All extracted content for a single page, plus enough metadata for redaction."""

    page_number: int  # 0-indexed
    width: float  # in PDF points
    height: float  # in PDF points
    spans: list[TextSpan] = field(default_factory=list)
    source: Source = "pdf"  # how this page as a whole was extracted

    @property
    def text(self) -> str:
        """Concatenated page text — convenient for passing whole pages to an LLM."""
        return " ".join(span.text for span in self.spans)

    def __len__(self) -> int:
        return len(self.spans)
