"""Tests for char-offset → span-index → bbox mapping."""

from __future__ import annotations

import pytest

from securepdf.detection.span_mapping import (
    build_span_offsets,
    find_overlapping_spans,
    union_bbox,
)


def test_offsets_match_concatenated_text(synthetic_page):
    offsets = build_span_offsets(synthetic_page)
    text = synthetic_page.text
    for i, (s, e) in enumerate(offsets):
        assert text[s:e] == synthetic_page.spans[i].text


def test_offsets_account_for_joining_spaces(synthetic_page):
    """End of span N + 1 == start of span N+1 (the space sits between them)."""
    offsets = build_span_offsets(synthetic_page)
    for (_, e), (s2, _) in zip(offsets, offsets[1:]):
        assert s2 == e + 1


def test_find_overlapping_spans_single_word(synthetic_page):
    offsets = build_span_offsets(synthetic_page)
    text = synthetic_page.text
    target = "jane.doe@example.com"
    start = text.index(target)
    indices = find_overlapping_spans(offsets, start, start + len(target))
    assert len(indices) == 1
    assert synthetic_page.spans[indices[0]].text == target


def test_find_overlapping_spans_multi_word(synthetic_page):
    """"Jane Doe" covers two spans — index 1 and 2."""
    offsets = build_span_offsets(synthetic_page)
    text = synthetic_page.text
    start = text.index("Jane Doe")
    indices = find_overlapping_spans(offsets, start, start + len("Jane Doe"))
    assert indices == (1, 2)


def test_find_overlapping_spans_empty_range(synthetic_page):
    offsets = build_span_offsets(synthetic_page)
    # An empty range overlaps nothing — strict inequality in the overlap test.
    assert find_overlapping_spans(offsets, 5, 5) == ()


def test_union_bbox_single_span(synthetic_page):
    bbox = union_bbox(synthetic_page, (4,))  # the email span
    assert bbox == synthetic_page.spans[4].bbox


def test_union_bbox_two_adjacent_spans(synthetic_page):
    bbox = union_bbox(synthetic_page, (1, 2))  # "Jane" + "Doe"
    span1, span2 = synthetic_page.spans[1], synthetic_page.spans[2]
    assert bbox[0] == min(span1.bbox[0], span2.bbox[0])
    assert bbox[2] == max(span1.bbox[2], span2.bbox[2])


def test_union_bbox_empty_raises(synthetic_page):
    with pytest.raises(ValueError, match="empty span_indices"):
        union_bbox(synthetic_page, ())
