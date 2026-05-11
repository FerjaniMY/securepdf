"""Anonymized text export — produce LLM-safe text with consistent pseudonyms.

Walks each page's text, replacing each detection's char range with its pseudonym.
This is the primary output for users whose goal is "paste this into ChatGPT" —
the redacted PDF (`pdf_renderer.py`) is for keeping the document's visual format.

Why character ranges, not span-by-span
--------------------------------------
The detection layer (Phase 2) gave us `(char_start, char_end)` half-open offsets
into `page.text`. Those offsets are the source of truth: they were validated
against the span structure when the Detection was built. Re-doing the work
span-by-span here would risk drift if a detection were to cover a partial span
(e.g. a custom regex matching mid-word).
"""

from __future__ import annotations

from typing import Iterable

from securepdf.detection.models import Detection
from securepdf.pdf.models import PageContent
from securepdf.redaction.pseudonyms import PseudonymMap

PAGE_SEPARATOR = "\n\n---PAGE BREAK---\n\n"


def anonymize_page(
    page: PageContent,
    detections: Iterable[Detection],
    pmap: PseudonymMap,
) -> str:
    """Anonymize one page's text using the shared `pmap`.

    Detections from other pages are silently ignored — callers can pass the whole
    document's detection list without pre-filtering.
    """
    # Only this page's detections, sorted by char_start. The merger already produces
    # a sorted list, but we sort here to be robust if callers pass an unsorted list.
    page_dets = sorted(
        (d for d in detections if d.page == page.page_number),
        key=lambda d: d.char_start,
    )

    text = page.text
    out: list[str] = []
    pos = 0
    for d in page_dets:
        # Defensive: skip detections that don't slot cleanly into the page text.
        # After the merger, overlaps shouldn't exist within a page; if one slips
        # through, we'd silently emit corrupted output otherwise.
        if d.char_start < pos:
            continue
        out.append(text[pos:d.char_start])
        out.append(pmap.pseudonym_for(d.entity_type, d.text))
        pos = d.char_end
    out.append(text[pos:])
    return "".join(out)


def anonymize_pages(
    pages: list[PageContent],
    detections: Iterable[Detection],
    pmap: PseudonymMap | None = None,
) -> tuple[str, PseudonymMap]:
    """Anonymize every page, returning the combined text and the pseudonym map.

    The map is returned so callers can persist it as a "decoder key" alongside the
    anonymized text — useful for users who later need to rehydrate the original
    document (e.g. apply edits from an LLM back to the original).
    """
    # `if pmap is None` rather than truthiness — an empty PseudonymMap evaluates
    # falsy (via __len__), so `pmap or PseudonymMap()` would silently replace a
    # caller-provided empty map and orphan all the writes.
    if pmap is None:
        pmap = PseudonymMap()
    detections_list = list(detections)
    page_texts = [anonymize_page(p, detections_list, pmap) for p in pages]
    return PAGE_SEPARATOR.join(page_texts), pmap
