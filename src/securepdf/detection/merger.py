"""Merge detections from Stage 1 (Presidio) and Stage 2 (Gemma).

Overlap semantics
-----------------
Two detections on the same page overlap if their character ranges intersect.
Overlapping detections are merged into one with:
  - bbox  = union of the input bboxes (so the redaction covers both)
  - text  = exact substring of `page.text` over the union char range
  - char_start = min(starts), char_end = max(ends)
  - entity_type = the higher-confidence detection's type
  - confidence = max(confidences)
  - source = "merged" (sentinel — see `EntitySource`)
  - span_indices = sorted union of indices

This is deliberately greedy: a chain of three overlapping detections
A∩B and B∩C, even if A and C don't overlap, becomes a single merged group.
That matches user expectations — if the GUI shows them as one "highlight",
they should be redacted as one.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from securepdf.detection.models import Detection
from securepdf.pdf.models import PageContent


def _merge_group(group: list[Detection], page: PageContent) -> Detection:
    """Collapse a list of overlapping detections into a single merged Detection."""
    if len(group) == 1:
        return group[0]

    best = max(group, key=lambda d: d.confidence)
    start = min(d.char_start for d in group)
    end = max(d.char_end for d in group)
    span_indices = tuple(sorted({i for d in group for i in d.span_indices}))

    xs0 = [d.bbox[0] for d in group]
    ys0 = [d.bbox[1] for d in group]
    xs1 = [d.bbox[2] for d in group]
    ys1 = [d.bbox[3] for d in group]
    bbox = (min(xs0), min(ys0), max(xs1), max(ys1))

    return Detection(
        text=page.text[start:end],
        entity_type=best.entity_type,
        page=best.page,
        bbox=bbox,
        char_start=start,
        char_end=end,
        confidence=max(d.confidence for d in group),
        source="merged",
        span_indices=span_indices,
    )


def merge_detections(
    detections: Iterable[Detection], pages: list[PageContent]
) -> list[Detection]:
    """Merge overlapping detections across all sources.

    `pages` is needed because the merged Detection's `text` is sliced from
    `page.text` (so a merge of "Jane" + "Doe" with a one-char gap becomes
    "Jane Doe" — the actual text on the page).
    """
    page_lookup = {p.page_number: p for p in pages}
    by_page: dict[int, list[Detection]] = defaultdict(list)
    for d in detections:
        by_page[d.page].append(d)

    merged: list[Detection] = []
    for page_num, page_dets in by_page.items():
        page = page_lookup.get(page_num)
        if page is None:
            # Shouldn't happen — a detection without a corresponding PageContent
            # is malformed input. We pass through unchanged rather than crash.
            merged.extend(page_dets)
            continue

        # Sort by start offset, walk forward, group while ranges overlap.
        page_dets.sort(key=lambda d: (d.char_start, d.char_end))
        current_group: list[Detection] = []
        current_end = -1
        for d in page_dets:
            if d.char_start < current_end:
                # Overlaps the running group — extend.
                current_group.append(d)
                current_end = max(current_end, d.char_end)
            else:
                if current_group:
                    merged.append(_merge_group(current_group, page))
                current_group = [d]
                current_end = d.char_end
        if current_group:
            merged.append(_merge_group(current_group, page))

    # Stable final order: by (page, char_start) so the GUI review list is intuitive.
    merged.sort(key=lambda d: (d.page, d.char_start))
    return merged
