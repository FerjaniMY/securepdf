"""Bridge between character offsets (what Presidio + Gemma return) and PDF bboxes
(what we need for redaction and visual overlay).

`PageContent.text` is built as `" ".join(span.text for span in spans)` — so for a
page with spans `["Patient:", "Jane", "Doe"]` the text is `"Patient: Jane Doe"`,
with span 0 occupying chars [0, 8), then a space at 8, span 1 at [9, 13), space
at 13, span 2 at [14, 17).

This module computes those offsets once per page, then provides:
  - `find_overlapping_spans(offsets, start, end)` → indices of spans that overlap
  - `union_bbox(page, span_indices)` → the smallest bbox containing all of them
"""

from __future__ import annotations

from securepdf.pdf.models import BBox, PageContent


def build_span_offsets(page: PageContent) -> list[tuple[int, int]]:
    """Compute (char_start, char_end) for every span on the page.

    Result is parallel to `page.spans` — index i gives the half-open char range
    of `page.spans[i]` within `page.text`.
    """
    offsets: list[tuple[int, int]] = []
    pos = 0
    for span in page.spans:
        start = pos
        end = pos + len(span.text)
        offsets.append((start, end))
        pos = end + 1  # +1 for the joining space (see PageContent.text)
    return offsets


def find_overlapping_spans(
    offsets: list[tuple[int, int]], start: int, end: int
) -> tuple[int, ...]:
    """Return indices of spans that overlap the half-open range [start, end).

    Overlap test: two non-empty ranges overlap iff one starts before the other ends,
    and vice versa. Uses strict inequality so a detection ending exactly at a span
    boundary doesn't pick up the adjacent span.

    Empty ranges (start >= end) overlap nothing — they're treated as no-ops rather
    than as zero-width points contained in any enclosing span. A real detection
    always has end > start, so this is a defensive guard against malformed input.
    """
    if start >= end:
        return ()
    indices: list[int] = []
    for i, (s, e) in enumerate(offsets):
        if s < end and e > start:
            indices.append(i)
    return tuple(indices)


def union_bbox(page: PageContent, span_indices: tuple[int, ...]) -> BBox:
    """Smallest bbox containing all referenced spans.

    Raises ValueError if `span_indices` is empty — a Detection without a bbox
    is meaningless (can't be drawn, can't be redacted, can't be reviewed).
    """
    if not span_indices:
        raise ValueError("cannot compute union_bbox of empty span_indices")

    xs0: list[float] = []
    ys0: list[float] = []
    xs1: list[float] = []
    ys1: list[float] = []
    for i in span_indices:
        x0, y0, x1, y1 = page.spans[i].bbox
        xs0.append(x0)
        ys0.append(y0)
        xs1.append(x1)
        ys1.append(y1)
    return (min(xs0), min(ys0), max(xs1), max(ys1))
