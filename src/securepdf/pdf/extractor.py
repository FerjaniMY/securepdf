"""PyMuPDF-based text extraction with word-level bounding boxes.

PyMuPDF (imported as `fitz`) gives us word-level extraction via `Page.get_text("words")`,
which returns a list of tuples:

    (x0, y0, x1, y1, "word", block_no, line_no, word_no)

We convert each tuple to a `TextSpan`. The bbox coordinates are in PDF points, in the
standard PyMuPDF convention (origin at top-left of the page, y increasing downward —
this is opposite to the PDF spec's bottom-left origin, but PyMuPDF normalizes so its
own redaction APIs work in the same space).
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from securepdf.pdf.models import PageContent, TextSpan

log = logging.getLogger(__name__)


# A page is treated as "text-layer-empty" when it yields fewer than this many words.
# Tradeoff:
#   - 0/1: only truly empty pages trigger OCR. A scanned PDF with stray watermark text
#          in the text layer would skip OCR — but that's rare in practice.
#   - 5+: aggressive OCR fallback, but real pages with a single line (e.g. a one-field
#          form) get false-flagged and lose their exact-text bboxes to OCR's ~95% recall.
# 1 is the right default. Users can pass --force-ocr to override.
EMPTY_PAGE_WORD_THRESHOLD = 1


def extract_page_text(page: fitz.Page) -> list[TextSpan]:
    """Extract word-level spans from a single fitz.Page using the text layer.

    Returns an empty list if the page has no embedded text (a scanned/image-only page),
    in which case the caller should fall back to OCR.
    """
    words = page.get_text("words")  # list of (x0, y0, x1, y1, text, block, line, word_no)
    page_idx = page.number  # 0-indexed
    spans: list[TextSpan] = []
    for x0, y0, x1, y1, text, _block, _line, _word in words:
        if not text.strip():
            continue
        spans.append(
            TextSpan(
                text=text,
                bbox=(float(x0), float(y0), float(x1), float(y1)),
                page=page_idx,
                source="pdf",
                confidence=1.0,
            )
        )
    return spans


def has_text_layer(page: fitz.Page) -> bool:
    """Heuristic: does this page have a real text layer worth extracting from?

    A scanned PDF is just images per page — `get_text("words")` returns nothing or
    near-nothing. A digitally-generated PDF returns dozens to hundreds of words.
    """
    words = page.get_text("words")
    return len(words) >= EMPTY_PAGE_WORD_THRESHOLD


def extract_pdf(pdf_path: str | Path) -> list[PageContent]:
    """Extract text + bboxes from every page of a PDF using the text layer.

    Pages with no usable text layer come back with empty `spans`. The OCR fallback
    (see `securepdf.pdf.ocr`) is invoked separately by the pipeline for those pages —
    this module deliberately does NOT call OCR itself so its dependencies stay minimal
    (PyMuPDF only, no Tesseract install required for native-text PDFs).
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    pages: list[PageContent] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            spans = extract_page_text(page)
            pages.append(
                PageContent(
                    page_number=page.number,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    spans=spans,
                    source="pdf",
                )
            )
            log.debug("Page %d: %d spans from text layer", page.number, len(spans))

    return pages
