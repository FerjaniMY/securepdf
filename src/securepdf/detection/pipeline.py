"""Detection pipeline orchestrator.

Run order
---------
  1. Stage 1: Presidio (built-ins + PHI + financial + custom recognizers)
  2. Stage 2: Gemma 2 2B (contextual; passes Stage 1 results as hints)
  3. Merger: dedupe overlapping spans, union bboxes, prefer higher confidence

Stage 2 is best-effort — if Ollama isn't running, we log a warning and continue
with Stage 1 alone rather than failing the whole detection.

Public entry points
-------------------
  - `detect(pages, profile=None, **kwargs)` — programmatic
  - `_cli(argv)` — `securepdf-detect` command for development sanity checks
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from securepdf.detection import gemma_detector, presidio_engine
from securepdf.detection.custom_entities import CustomEntityProfile, load_profile
from securepdf.detection.merger import merge_detections
from securepdf.detection.models import Detection
from securepdf.detection.ollama_client import DEFAULT_MODEL, OllamaClient
from securepdf.detection.presidio_engine import DEFAULT_SCORE_THRESHOLD
from securepdf.pdf.models import PageContent

log = logging.getLogger(__name__)


def detect(
    pages: list[PageContent],
    *,
    profile: CustomEntityProfile | None = None,
    spacy_model: str = "en_core_web_sm",
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ollama_client: OllamaClient | None = None,
    ollama_model: str = DEFAULT_MODEL,
    use_stage2: bool = True,
) -> list[Detection]:
    """Full detection pass over a list of PageContent.

    Returns merged detections sorted by (page, char_start). The result is what the
    GUI's review pane should display and what the redaction step consumes.
    """
    # Stage 1: register any custom recognizers from the profile, then analyze.
    analyzer = presidio_engine.make_engine(spacy_model=spacy_model)
    if profile:
        for r in profile.recognizers:
            analyzer.registry.add_recognizer(r)

    stage1: list[Detection] = []
    for page in pages:
        stage1.extend(
            presidio_engine.detect_page(
                page, analyzer, score_threshold=score_threshold
            )
        )
    log.info("Stage 1 (Presidio): %d detections", len(stage1))

    # Stage 2: Gemma contextual pass, with Stage 1 results as hints.
    stage2: list[Detection] = []
    if use_stage2:
        client = ollama_client or OllamaClient()
        descriptions = list(profile.descriptions) if profile else []
        stage2 = gemma_detector.detect_pages(
            pages,
            client=client,
            model=ollama_model,
            stage1_detections=stage1,
            custom_descriptions=descriptions,
        )
        log.info("Stage 2 (Gemma): %d detections", len(stage2))

    # Merge and return.
    merged = merge_detections(stage1 + stage2, pages)
    log.info("Merged: %d detections (down from %d)", len(merged), len(stage1) + len(stage2))
    return merged


def _cli(argv: list[str] | None = None) -> int:
    """`securepdf-detect` — extract + detect on a PDF, dump findings as JSON.

    Lightweight, intended for development sanity checks. The real interface is
    the desktop GUI built in Phase 4.
    """
    from securepdf.pdf.pipeline import extract  # local import: avoids circular dep at module load

    parser = argparse.ArgumentParser(
        prog="securepdf-detect",
        description="Run Phase 2 detection on a PDF and print findings.",
    )
    parser.add_argument("pdf", type=Path, help="Path to a PDF file")
    parser.add_argument("--profile", type=Path, help="YAML custom entity profile")
    parser.add_argument(
        "--spacy-model",
        default="en_core_web_sm",
        help="spaCy model (en_core_web_sm for fast, en_core_web_lg for accurate)",
    )
    parser.add_argument(
        "--no-stage2",
        action="store_true",
        help="Skip the Gemma contextual pass (Stage 1 only)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pages = extract(args.pdf)
    profile = load_profile(args.profile) if args.profile else None
    detections = detect(
        pages,
        profile=profile,
        spacy_model=args.spacy_model,
        use_stage2=not args.no_stage2,
    )

    output = {
        "pdf": str(args.pdf),
        "pages": len(pages),
        "detections": [
            {
                "page": d.page,
                "entity_type": d.entity_type,
                "text": d.text,
                "char_start": d.char_start,
                "char_end": d.char_end,
                "bbox": list(d.bbox),
                "confidence": round(d.confidence, 3),
                "source": d.source,
            }
            for d in detections
        ],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
