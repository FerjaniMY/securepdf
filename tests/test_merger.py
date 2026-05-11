"""Tests for the detection merger.

The merger is pure logic — given a list of Detections and pages, produce a
deduped list. No external services, fully synthetic input.
"""

from __future__ import annotations

from securepdf.detection.merger import merge_detections
from securepdf.detection.models import Detection


def _det(start: int, end: int, source: str, conf: float, page: int = 0, entity: str = "X") -> Detection:
    return Detection(
        text="x" * (end - start),
        entity_type=entity,
        page=page,
        bbox=(float(start), 0.0, float(end), 14.0),
        char_start=start,
        char_end=end,
        confidence=conf,
        source=source,
        span_indices=(0,),
    )


def test_no_overlap_passes_through(multi_page):
    a = _det(0, 4, "presidio", 0.9, page=0)
    b = _det(10, 14, "gemma", 0.7, page=0)
    merged = merge_detections([a, b], multi_page)
    assert len(merged) == 2
    assert {d.source for d in merged} == {"presidio", "gemma"}


def test_overlapping_detections_merged(multi_page):
    """Two detections covering the same range → one merged detection."""
    a = _det(0, 8, "presidio", 0.9, page=0, entity="PERSON")
    b = _det(4, 12, "gemma", 0.7, page=0, entity="PERSON_REFERENCE")
    merged = merge_detections([a, b], multi_page)
    assert len(merged) == 1
    m = merged[0]
    assert m.source == "merged"
    assert m.char_start == 0 and m.char_end == 12
    assert m.entity_type == "PERSON"  # higher confidence wins
    assert m.confidence == 0.9


def test_merger_keeps_page_groups_separate(multi_page):
    a = _det(0, 4, "presidio", 0.9, page=0)
    b = _det(0, 4, "presidio", 0.9, page=1)  # same range, different page
    merged = merge_detections([a, b], multi_page)
    assert len(merged) == 2
    assert {d.page for d in merged} == {0, 1}


def test_transitive_overlap_collapses_to_one(multi_page):
    """A overlaps B, B overlaps C — even if A and C don't directly overlap, the
    chain collapses into a single merged detection (greedy grouping)."""
    a = _det(0, 5, "presidio", 0.9, page=0)
    b = _det(4, 10, "gemma", 0.7, page=0)
    c = _det(9, 14, "presidio", 0.6, page=0)
    merged = merge_detections([a, b, c], multi_page)
    assert len(merged) == 1
    assert merged[0].char_start == 0 and merged[0].char_end == 14


def test_output_sorted_by_page_then_start(multi_page):
    a = _det(10, 14, "presidio", 0.9, page=1)
    b = _det(0, 4, "presidio", 0.9, page=0)
    c = _det(5, 9, "presidio", 0.9, page=0)
    merged = merge_detections([a, b, c], multi_page)
    assert [(d.page, d.char_start) for d in merged] == [(0, 0), (0, 5), (1, 10)]
