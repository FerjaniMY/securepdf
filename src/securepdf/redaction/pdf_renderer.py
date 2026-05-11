"""True PDF redaction via PyMuPDF.

The critical distinction
------------------------
Most "PDF redaction" tools you'll find online draw an opaque rectangle on top of
the sensitive text. The visual is correct, but the text is still in the file —
anyone with Ctrl-A can copy-paste it back out. That's not redaction.

PyMuPDF's `add_redact_annot()` + `apply_redactions()` is what Adobe Acrobat Pro
calls "true redaction": the underlying text content is physically removed from
the PDF stream and replaced with the fill rectangle. After `apply_redactions()`,
extracting text from the redacted region returns nothing — we verify this in
`tests/test_pdf_renderer.py`.

Configuration knobs
-------------------
- `fill_color`: RGB tuple in 0-1 space. Default (0, 0, 0) = black.
- `text_overlay`:
    - None             → no text on the box. Most conservative; nothing leaks.
    - "type"           → entity type label like "[PERSON]" on each box. Useful
                          for review / auditing — but reveals what KIND of data
                          was there (which is sometimes fine, sometimes not).
    - "pseudonym"      → pseudonym like "[PERSON_1]" on each box. Lets a reader
                          cross-reference the redacted PDF with an anonymized
                          text export and a pseudonym key.
- `text_color`: only relevant when `text_overlay` is set. Default white.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Literal

import fitz

from securepdf.detection.models import Detection
from securepdf.redaction.pseudonyms import PseudonymMap

log = logging.getLogger(__name__)

# RGB color tuples in PyMuPDF's 0–1 space.
RGB = tuple[float, float, float]

TextOverlay = Literal["none", "type", "pseudonym"]


def render_redacted_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    detections: Iterable[Detection],
    *,
    fill_color: RGB = (0.0, 0.0, 0.0),
    text_color: RGB = (1.0, 1.0, 1.0),
    text_overlay: TextOverlay = "none",
    pseudonym_map: PseudonymMap | None = None,
) -> Path:
    """Apply true redaction to `input_pdf`, writing the result to `output_pdf`.

    Returns the output path.

    Raises ValueError if `text_overlay="pseudonym"` without a `pseudonym_map`.
    """
    if text_overlay == "pseudonym" and pseudonym_map is None:
        raise ValueError("text_overlay='pseudonym' requires a pseudonym_map")

    input_path = Path(input_pdf)
    output_path = Path(output_pdf)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    doc = fitz.open(input_path)
    try:
        # Group detections by page so we can apply all redactions to each page in
        # one pass. PyMuPDF requires `apply_redactions()` per page after the
        # annotations are queued.
        by_page: dict[int, list[Detection]] = {}
        for d in detections:
            by_page.setdefault(d.page, []).append(d)

        for page_idx, page_dets in by_page.items():
            if page_idx >= len(doc):
                log.warning(
                    "Detection on page %d but PDF has %d pages; skipping",
                    page_idx,
                    len(doc),
                )
                continue
            page = doc[page_idx]
            for d in page_dets:
                rect = fitz.Rect(*d.bbox)
                overlay_text = _overlay_text(d, text_overlay, pseudonym_map)
                # cross_out=False: no strikethrough line through the box. The
                # default cross_out adds an X-line that visually noisier than
                # a clean fill block.
                page.add_redact_annot(
                    rect,
                    text=overlay_text,
                    fill=fill_color,
                    text_color=text_color,
                    cross_out=False,
                )
            # apply_redactions destroys the underlying text. Default keeps images
            # and line-art intact — we only want text gone.
            page.apply_redactions()
            log.debug("Page %d: applied %d redactions", page_idx, len(page_dets))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        # garbage=4 removes unused objects (defragments), deflate=True compresses
        # the result. The original text in unused streams would otherwise persist
        # in the file until the next clean save — belt-and-braces.
        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()

    return output_path


def _overlay_text(
    d: Detection,
    overlay_mode: TextOverlay,
    pmap: PseudonymMap | None,
) -> str | None:
    if overlay_mode == "none":
        return None
    if overlay_mode == "type":
        return f"[{d.entity_type}]"
    if overlay_mode == "pseudonym":
        # Defensive raise (not assert) — `assert` is stripped under `python -O`
        # and a stripped check would propagate as `AttributeError: 'NoneType'
        # object has no attribute 'pseudonym_for'`. The function entry guard
        # should already have caught this, but belt-and-braces here.
        if pmap is None:
            raise ValueError("text_overlay='pseudonym' requires a pseudonym_map")
        return pmap.pseudonym_for(d.entity_type, d.text)
    return None
