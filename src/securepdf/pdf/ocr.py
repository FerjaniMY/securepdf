"""Tesseract OCR fallback for scanned / image-only PDF pages.

We render the page to a raster image via PyMuPDF, then run Tesseract on it with
`image_to_data()` (which gives per-word bboxes and per-word confidence — exactly what
we need to construct `TextSpan`s consistent with the text-layer path).

Important coordinate-space note:
    Tesseract returns pixel coordinates in the rendered raster. We render at a known
    DPI and divide by the scale factor to convert back to PDF points so that bboxes
    from OCR can be drawn on the original PDF page (for redaction) using the same
    coordinate system as text-layer bboxes.
"""

from __future__ import annotations

import logging
from io import BytesIO

import fitz
import pytesseract
from PIL import Image

from securepdf.pdf.models import PageContent, TextSpan

log = logging.getLogger(__name__)

# 300 DPI is the sweet spot for Tesseract accuracy. Higher gains diminishing returns and
# costs a lot more CPU; lower (150 DPI) noticeably hurts character recognition on small
# fonts common in forms / medical reports.
RENDER_DPI = 300

# PDF native DPI baseline. Used to compute the scale factor when converting Tesseract's
# pixel coordinates back into PDF points.
PDF_BASE_DPI = 72

# Tesseract reports confidence as 0–100; anything below this is dropped as garbage.
# This is conservative — Tesseract gives -1 for non-words (whitespace) and ~30 for
# clear misreads. 40 keeps borderline reads without admitting obvious noise.
MIN_TESSERACT_CONFIDENCE = 40


def _render_page(page: fitz.Page, dpi: int = RENDER_DPI) -> tuple[Image.Image, float]:
    """Render a fitz.Page to a PIL Image at the given DPI. Returns (image, scale).

    `scale` is the multiplier from PDF points → image pixels (i.e. dpi/72). We return
    it so callers can convert back: pdf_coord = pixel_coord / scale.
    """
    scale = dpi / PDF_BASE_DPI
    matrix = fitz.Matrix(scale, scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png")))
    return image, scale


def ocr_page(page: fitz.Page, dpi: int = RENDER_DPI) -> list[TextSpan]:
    """OCR a single page and return TextSpans in PDF coordinate space."""
    image, scale = _render_page(page, dpi)
    page_idx = page.number

    # `image_to_data` is the structured Tesseract output: each row is one detected
    # token with pixel bbox + confidence. We use it (not `image_to_string`) because we
    # need the per-word coordinates to draw tight redaction boxes.
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    spans: list[TextSpan] = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            continue
        if conf < MIN_TESSERACT_CONFIDENCE:
            continue

        # Pixel bbox in the rendered image — convert back to PDF points.
        px = data["left"][i]
        py = data["top"][i]
        pw = data["width"][i]
        ph = data["height"][i]
        bbox = (px / scale, py / scale, (px + pw) / scale, (py + ph) / scale)

        spans.append(
            TextSpan(
                text=text,
                bbox=bbox,
                page=page_idx,
                source="ocr",
                confidence=conf / 100.0,
            )
        )

    log.debug("Page %d: %d OCR spans @ %d DPI", page_idx, len(spans), dpi)
    return spans


def ocr_page_content(page: fitz.Page, dpi: int = RENDER_DPI) -> PageContent:
    """Convenience wrapper: produce a fully-populated PageContent from OCR."""
    spans = ocr_page(page, dpi=dpi)
    return PageContent(
        page_number=page.number,
        width=float(page.rect.width),
        height=float(page.rect.height),
        spans=spans,
        source="ocr",
    )


def is_tesseract_available() -> bool:
    """Check whether the Tesseract binary is installed and callable.

    The pipeline uses this to decide between "fall back to OCR" and "skip the page with
    a warning" when a PDF page has no text layer and Tesseract isn't installed.
    """
    try:
        pytesseract.get_tesseract_version()
        return True
    except (pytesseract.TesseractNotFoundError, OSError):
        return False
