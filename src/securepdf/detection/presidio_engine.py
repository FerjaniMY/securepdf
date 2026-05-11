"""Stage 1 detection: Microsoft Presidio with our custom PHI/financial recognizers.

This module wraps `AnalyzerEngine` and adapts its results to our `Detection`
data model, mapping character offsets back to PDF span bboxes via `span_mapping`.

Design notes
------------
- We construct the analyzer once and reuse it. spaCy model load takes ~1s; doing
  it per page would dominate latency.
- The default spaCy model is `en_core_web_sm` (fast, ~12 MB). For production,
  call `make_engine(spacy_model="en_core_web_lg")` for better PERSON/LOCATION
  recall. We surface this as a parameter so tests can stay fast.
- Custom recognizers are registered alongside Presidio's defaults. Disabling
  the defaults is a deliberate non-feature for now — over-detection followed by
  user review is safer than under-detection followed by an LLM leak.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from securepdf.detection.financial_recognizers import FINANCIAL_RECOGNIZERS
from securepdf.detection.models import Detection
from securepdf.detection.phi_recognizers import PHI_RECOGNIZERS
from securepdf.detection.span_mapping import (
    build_span_offsets,
    find_overlapping_spans,
    union_bbox,
)
from securepdf.pdf.models import PageContent

log = logging.getLogger(__name__)

# Default minimum score to surface. Below this, Presidio considers the match
# "borderline noise" — usually safer to drop it (Gemma's contextual pass will
# pick up real borderline cases).
DEFAULT_SCORE_THRESHOLD = 0.4


@lru_cache(maxsize=2)
def make_engine(spacy_model: str = "en_core_web_sm") -> AnalyzerEngine:
    """Construct an AnalyzerEngine with our custom recognizers registered.

    Cached per `spacy_model` because spaCy model load is the dominant init cost.
    """
    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": spacy_model}],
        }
    )
    nlp_engine = provider.create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])

    # Layer our custom recognizers on top of Presidio's built-in registry.
    for recognizer in PHI_RECOGNIZERS + FINANCIAL_RECOGNIZERS:
        analyzer.registry.add_recognizer(recognizer)

    log.info(
        "Presidio engine ready (spaCy=%s, recognizers=%d)",
        spacy_model,
        len(analyzer.registry.recognizers),
    )
    return analyzer


def detect_page(
    page: PageContent,
    analyzer: AnalyzerEngine,
    *,
    entities: Iterable[str] | None = None,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[Detection]:
    """Run Presidio over a single page and convert results to `Detection`s.

    Skips pages with no spans (e.g. image-only pages where OCR is unavailable —
    no text means nothing for Stage 1 to analyze).
    """
    if not page.spans:
        return []

    text = page.text
    results = analyzer.analyze(
        text=text,
        entities=list(entities) if entities else None,
        language="en",
        score_threshold=score_threshold,
    )

    offsets = build_span_offsets(page)
    detections: list[Detection] = []
    for r in results:
        span_indices = find_overlapping_spans(offsets, r.start, r.end)
        if not span_indices:
            # Defensive: a Presidio match that doesn't land on any span shouldn't
            # happen (we constructed `text` from the spans), but if it does we
            # skip rather than crash — a Detection without a bbox is unusable.
            log.warning(
                "Presidio match for %s at [%d,%d) didn't map to any span; skipping",
                r.entity_type,
                r.start,
                r.end,
            )
            continue
        detections.append(
            Detection(
                text=text[r.start : r.end],
                entity_type=r.entity_type,
                page=page.page_number,
                bbox=union_bbox(page, span_indices),
                char_start=r.start,
                char_end=r.end,
                confidence=float(r.score),
                source="presidio",
                span_indices=span_indices,
            )
        )

    log.debug("Page %d: Presidio → %d detections", page.page_number, len(detections))
    return detections


def detect_pages(
    pages: list[PageContent],
    *,
    spacy_model: str = "en_core_web_sm",
    entities: Iterable[str] | None = None,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[Detection]:
    """Run Stage 1 over every page; returns flat list of Detections."""
    analyzer = make_engine(spacy_model=spacy_model)
    out: list[Detection] = []
    for page in pages:
        out.extend(
            detect_page(
                page,
                analyzer,
                entities=entities,
                score_threshold=score_threshold,
            )
        )
    return out
