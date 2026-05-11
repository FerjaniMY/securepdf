"""Phase 3 pipeline: unified entry point + CLI for producing redacted outputs.

Given a source PDF and a list of Detections (from Phase 2), produce one or both of:
  - A truly-redacted PDF (via `pdf_renderer.render_redacted_pdf`)
  - An anonymized text export with consistent pseudonyms (via `text_export.anonymize_pages`)

The two outputs share a single `PseudonymMap` instance, so if you choose
`text_overlay="pseudonym"` on the PDF output AND request the text export, the
pseudonyms line up between them — `[PERSON_1]` on the PDF refers to the same
person as `[PERSON_1]` in the text.

This module wires together the three previous phases:
  Phase 1 (extract) → Phase 2 (detect) → Phase 3 (redact).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path
from typing import Literal

from securepdf.detection.models import Detection
from securepdf.pdf.models import PageContent
from securepdf.redaction.pdf_renderer import RGB, TextOverlay, render_redacted_pdf
from securepdf.redaction.pseudonyms import PseudonymMap
from securepdf.redaction.text_export import anonymize_pages

log = logging.getLogger(__name__)

Mode = Literal["pdf", "text", "both"]


@dataclasses.dataclass
class RedactionResult:
    """Everything produced by a redaction run, returned to callers.

    Both fields can be `None` depending on the requested mode. The `pseudonym_map`
    is always populated when text mode (or both) was requested — callers can
    persist it alongside the output for later rehydration.
    """

    pdf_path: Path | None = None
    text: str | None = None
    text_path: Path | None = None
    pseudonym_map: PseudonymMap | None = None


def redact(
    input_pdf: str | Path,
    detections: list[Detection],
    *,
    pages: list[PageContent] | None = None,
    output_pdf: str | Path | None = None,
    output_text: str | Path | None = None,
    mode: Mode = "both",
    text_overlay: TextOverlay = "none",
    fill_color: RGB = (0.0, 0.0, 0.0),
) -> RedactionResult:
    """Produce redacted artifacts.

    Parameters
    ----------
    input_pdf:
        Path to the source PDF.
    detections:
        Detections from `securepdf.detection.detect(pages)`.
    pages:
        Page contents from `securepdf.pdf.extract(input_pdf)`. Required for text
        output. If `pages is None` and text output is requested, we run extraction
        here as a convenience — but the caller already has them in the normal
        workflow.
    output_pdf, output_text:
        Where to write the artifacts. May be `None` if you don't want that mode.
    mode:
        Which artifacts to produce: "pdf", "text", or "both".
    text_overlay:
        For the redacted PDF: "none" (default, plain fill), "type" (label boxes
        with `[ENTITY_TYPE]`), or "pseudonym" (use `PseudonymMap` to cross-ref
        the text export).
    fill_color:
        Box fill color, RGB in 0-1 space. Default black.

    Returns
    -------
    `RedactionResult` with whichever fields the chosen mode populated.
    """
    pmap = PseudonymMap()
    result = RedactionResult(pseudonym_map=pmap)

    want_text = mode in ("text", "both")
    want_pdf = mode in ("pdf", "both")

    # Text output uses the pseudonym map; if the PDF asks for pseudonyms on the
    # overlay, we want the same map to be the one driving both. Run text first
    # so the map is populated when the PDF renderer consults it.
    if want_text:
        if pages is None:
            from securepdf.pdf.pipeline import extract  # local: avoid circular at import time
            pages = extract(input_pdf)
        text, _ = anonymize_pages(pages, detections, pmap)
        result.text = text
        if output_text:
            out = Path(output_text)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            result.text_path = out
            log.info("Wrote anonymized text: %s (%d chars)", out, len(text))

    if want_pdf:
        if output_pdf is None:
            raise ValueError("mode includes 'pdf' but output_pdf is None")
        result.pdf_path = render_redacted_pdf(
            input_pdf,
            output_pdf,
            detections,
            fill_color=fill_color,
            text_overlay=text_overlay,
            pseudonym_map=pmap if text_overlay == "pseudonym" else None,
        )
        log.info("Wrote redacted PDF: %s (%d redactions)", result.pdf_path, len(detections))

    return result


def _cli(argv: list[str] | None = None) -> int:
    """`securepdf-redact` — full pipeline runner from PDF to redacted outputs.

    Convenience CLI: extract → detect → redact. The desktop GUI in Phase 4 will
    be the polished UX; this is for development sanity checks and headless batch.
    """
    from securepdf.detection import detect
    from securepdf.pdf.pipeline import extract

    parser = argparse.ArgumentParser(
        prog="securepdf-redact",
        description="Run the full SecurePDF pipeline: extract → detect → redact.",
    )
    parser.add_argument("pdf", type=Path, help="Input PDF")
    parser.add_argument("--output-pdf", type=Path, help="Where to write the redacted PDF")
    parser.add_argument("--output-text", type=Path, help="Where to write the anonymized text")
    parser.add_argument(
        "--mode",
        choices=["pdf", "text", "both"],
        default="both",
        help="Which outputs to produce",
    )
    parser.add_argument(
        "--text-overlay",
        choices=["none", "type", "pseudonym"],
        default="none",
        help="Overlay text on redaction boxes",
    )
    parser.add_argument("--no-stage2", action="store_true", help="Skip Gemma contextual pass")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pages = extract(args.pdf)
    detections = detect(pages, use_stage2=not args.no_stage2)
    log.info("Detected %d sensitive spans across %d pages", len(detections), len(pages))

    # Sensible defaults for outputs if user didn't pass them.
    if args.mode in ("pdf", "both") and not args.output_pdf:
        args.output_pdf = args.pdf.with_name(args.pdf.stem + ".redacted.pdf")
    if args.mode in ("text", "both") and not args.output_text:
        args.output_text = args.pdf.with_name(args.pdf.stem + ".anonymized.txt")

    result = redact(
        args.pdf,
        detections,
        pages=pages,
        output_pdf=args.output_pdf,
        output_text=args.output_text,
        mode=args.mode,
        text_overlay=args.text_overlay,
    )

    summary = {
        "input": str(args.pdf),
        "detections": len(detections),
        "pdf": str(result.pdf_path) if result.pdf_path else None,
        "text": str(result.text_path) if result.text_path else None,
        "pseudonyms": len(result.pseudonym_map) if result.pseudonym_map else 0,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
