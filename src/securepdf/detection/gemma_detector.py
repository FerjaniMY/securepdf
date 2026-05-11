"""Stage 2 detection: contextual / fuzzy entity detection via Gemma 2 2B on Ollama.

What this layer is for
----------------------
Stage 1 (Presidio) is great at structured PII (emails, SSNs, MRNs) and named
entities (PERSON via spaCy). It misses:

  - Anaphoric references: "the patient", "her doctor", "his daughter"
  - Narrative PII: "Mr. Smith called yesterday from his Berlin apartment"
  - User-defined custom entities described in natural language
    (e.g. "internal project codenames like PROJECT_PHOENIX")

Gemma 2 2B at temperature 0.1 with a constrained JSON output is a good fit:
small enough to run on CPU (~2.5 GB RAM), capable enough to handle these cases.

How matches map back to bboxes
------------------------------
The LLM returns substrings of the page text. We find them in `page.text` with
a simple case-insensitive search; once found, the char range is mapped to span
indices via `span_mapping`, identical to the Stage 1 path. If the LLM returns a
substring that's not present verbatim (rare with temperature=0.1, but possible),
we skip it rather than fuzz-match — false-anchored bboxes are worse than a
missed detection.

Graceful degradation
--------------------
If Ollama isn't running or the model isn't pulled, `detect_pages` logs a warning
and returns an empty list. The pipeline as a whole still produces Stage 1
detections — Phase 2 doesn't hard-require Ollama to be useful.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Sequence

from securepdf.detection.models import Detection
from securepdf.detection.ollama_client import DEFAULT_MODEL, OllamaClient, OllamaError
from securepdf.detection.span_mapping import (
    build_span_offsets,
    find_overlapping_spans,
    union_bbox,
)
from securepdf.pdf.models import PageContent

log = logging.getLogger(__name__)


# Confidence we assign to Gemma findings. The model itself doesn't return calibrated
# scores; we use a fixed value below Presidio's typical 0.85+ so the merger prefers
# Presidio when both stages agree on a span.
GEMMA_CONFIDENCE = 0.7


def build_prompt(
    page_text: str,
    *,
    existing_detections: Sequence[Detection] = (),
    custom_descriptions: Sequence[str] = (),
) -> str:
    """Compose the Stage 2 prompt.

    We tell Gemma what Presidio already found (so it doesn't waste tokens re-finding
    them) and what user-defined entities to look for. The output format is locked
    to a tiny JSON schema; Ollama's `format="json"` mode enforces validity.
    """
    already = "\n".join(
        f'  - "{d.text}" ({d.entity_type})' for d in existing_detections
    ) or "  (none yet)"

    custom_block = (
        "\nALSO look for these user-defined custom entities:\n"
        + "\n".join(f"  - {desc}" for desc in custom_descriptions)
        if custom_descriptions
        else ""
    )

    return f"""You are a privacy-focused PII detector. Find sensitive information in the TEXT below that should be removed before it is shared with a third-party AI service like ChatGPT.

A rule-based system already found these entities (do NOT report them again):
{already}

Look for everything else that's sensitive:
  - Anaphoric references to a person: "the patient", "her doctor", "his sister"
  - Specific places that identify someone: "the apartment on Maple Street"
  - Sensitive narrative content rules miss
  - Medical conditions, treatments, or diagnoses mentioned in passing{custom_block}

Respond with valid JSON ONLY, exactly this shape:
{{"detections": [{{"text": "<exact substring from TEXT>", "type": "<ENTITY_TYPE>", "reason": "<why this is sensitive>"}}]}}

Rules:
- "text" MUST be an exact substring of TEXT (same case, no paraphrasing).
- Use short uppercase types like PERSON_REFERENCE, LOCATION, MEDICAL, CUSTOM.
- If nothing else is sensitive, return {{"detections": []}}.

TEXT:
\"\"\"
{page_text}
\"\"\"
"""


def _parse_response(raw: str) -> list[dict]:
    """Extract the `detections` list from Gemma's JSON, tolerating minor schema drift."""
    if not raw or not raw.strip():
        return []
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # Gemma occasionally wraps JSON in ```json fences despite format=json. Strip
        # them and retry once before giving up.
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.warning("Gemma returned invalid JSON: %s; raw=%r", e, raw[:200])
            return []

    detections = obj.get("detections")
    if not isinstance(detections, list):
        log.warning("Gemma response missing `detections` list: %r", obj)
        return []
    return [d for d in detections if isinstance(d, dict) and "text" in d]


def _find_substring(text: str, needle: str) -> tuple[int, int] | None:
    """Locate `needle` in `text`. Case-insensitive fallback if the exact case fails.

    Returns the (start, end) of the first match, or None if the substring isn't
    present at all. We don't fuzz beyond case because false-anchored bboxes are
    worse than skipping a detection — the merger will drop it cleanly.
    """
    idx = text.find(needle)
    if idx >= 0:
        return idx, idx + len(needle)
    # Case-insensitive fallback.
    lower_idx = text.lower().find(needle.lower())
    if lower_idx >= 0:
        return lower_idx, lower_idx + len(needle)
    return None


def detect_page(
    page: PageContent,
    *,
    client: OllamaClient | None = None,
    model: str = DEFAULT_MODEL,
    existing_detections: Sequence[Detection] = (),
    custom_descriptions: Sequence[str] = (),
) -> list[Detection]:
    """Run Stage 2 on one page. Skips empty pages and returns [] on any Ollama error."""
    if not page.spans:
        return []

    client = client or OllamaClient()
    if not client.is_available():
        log.info("Ollama unavailable; skipping Stage 2 for page %d", page.page_number)
        return []

    text = page.text
    # Only pass Stage 1 detections from THIS page as already-found hints.
    page_hints = [d for d in existing_detections if d.page == page.page_number]
    prompt = build_prompt(
        text,
        existing_detections=page_hints,
        custom_descriptions=custom_descriptions,
    )

    try:
        raw = client.generate_json(prompt, model=model)
    except OllamaError as e:
        log.warning("Stage 2 generate failed on page %d: %s", page.page_number, e)
        return []

    findings = _parse_response(raw)
    offsets = build_span_offsets(page)
    detections: list[Detection] = []
    for f in findings:
        needle = str(f.get("text", "")).strip()
        if not needle:
            continue
        loc = _find_substring(text, needle)
        if loc is None:
            log.debug("Gemma returned %r but not found in page; skipping", needle)
            continue
        start, end = loc
        span_indices = find_overlapping_spans(offsets, start, end)
        if not span_indices:
            continue
        entity_type = str(f.get("type", "GEMMA_FINDING")).upper().strip() or "GEMMA_FINDING"
        detections.append(
            Detection(
                text=text[start:end],
                entity_type=entity_type,
                page=page.page_number,
                bbox=union_bbox(page, span_indices),
                char_start=start,
                char_end=end,
                confidence=GEMMA_CONFIDENCE,
                source="gemma",
                span_indices=span_indices,
            )
        )

    log.debug("Page %d: Gemma → %d detections", page.page_number, len(detections))
    return detections


def detect_pages(
    pages: list[PageContent],
    *,
    client: OllamaClient | None = None,
    model: str = DEFAULT_MODEL,
    stage1_detections: Sequence[Detection] = (),
    custom_descriptions: Sequence[str] = (),
) -> list[Detection]:
    """Run Stage 2 over every page."""
    client = client or OllamaClient()
    out: list[Detection] = []
    for page in pages:
        out.extend(
            detect_page(
                page,
                client=client,
                model=model,
                existing_detections=stage1_detections,
                custom_descriptions=custom_descriptions,
            )
        )
    return out
