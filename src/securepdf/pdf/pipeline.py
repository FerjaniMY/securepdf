"""Unified extraction entry point: PDF text layer first, OCR fallback per page.

This is the public surface for Phase 1. Downstream phases (detection, redaction) call
`extract(path)` and get a list of `PageContent` regardless of whether each page came
from a real text layer or from OCR.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import fitz

from securepdf.pdf import ocr
from securepdf.pdf.extractor import extract_page_text, has_text_layer
from securepdf.pdf.models import PageContent

log = logging.getLogger(__name__)


def extract(pdf_path: str | Path, force_ocr: bool = False) -> list[PageContent]:
    """Extract text + bboxes from every page of a PDF.

    For each page:
      1. Try the embedded text layer (fast, exact).
      2. If that's empty (scanned page) AND Tesseract is available, OCR the page.
      3. Otherwise return an empty page with a warning logged.

    Set `force_ocr=True` to bypass the text layer entirely — useful when the text
    layer exists but is corrupt (e.g. some scanners produce a hidden text layer
    full of garbage that would fool the detection engine).
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    tesseract_ok = ocr.is_tesseract_available()
    pages: list[PageContent] = []

    with fitz.open(pdf_path) as doc:
        for page in doc:
            use_ocr = force_ocr or not has_text_layer(page)

            if use_ocr:
                if tesseract_ok:
                    pages.append(ocr.ocr_page_content(page))
                    log.info("Page %d: OCR (%d spans)", page.number, len(pages[-1]))
                else:
                    log.warning(
                        "Page %d has no text layer and Tesseract is not installed; "
                        "returning empty page. Install tesseract to OCR scanned pages.",
                        page.number,
                    )
                    pages.append(
                        PageContent(
                            page_number=page.number,
                            width=float(page.rect.width),
                            height=float(page.rect.height),
                            spans=[],
                            source="pdf",
                        )
                    )
            else:
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
                log.info("Page %d: text layer (%d spans)", page.number, len(spans))

    return pages


def _cli(argv: list[str] | None = None) -> int:
    """`securepdf-extract` command: dump extraction results for a PDF.

    Lightweight — intended for sanity-checking the pipeline during development. The
    real interface is the desktop GUI built in Phase 4.
    """
    parser = argparse.ArgumentParser(
        prog="securepdf-extract",
        description="Extract text + bboxes from a PDF (Phase 1 sanity check).",
    )
    parser.add_argument("pdf", type=Path, help="Path to a PDF file")
    parser.add_argument("--force-ocr", action="store_true", help="Skip the text layer; OCR every page")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug logs")
    parser.add_argument("--limit", type=int, default=10, help="Max spans to preview per page")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pages = extract(args.pdf, force_ocr=args.force_ocr)
    total_spans = sum(len(p) for p in pages)
    print(f"\n{args.pdf}: {len(pages)} pages, {total_spans} total spans\n")

    for page in pages:
        print(f"── Page {page.page_number} [{page.source}] — {len(page)} spans " f"({page.width:.0f}×{page.height:.0f} pt)")
        for span in page.spans[: args.limit]:
            x0, y0, x1, y1 = span.bbox
            print(
                f"   ({x0:6.1f},{y0:6.1f})–({x1:6.1f},{y1:6.1f})"
                f"  conf={span.confidence:.2f}  {span.text!r}"
            )
        if len(page) > args.limit:
            print(f"   ... and {len(page) - args.limit} more")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
