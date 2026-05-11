"""Tests for the GUI's per-document state machine.

This module imports nothing from PySide6, so the tests run fast regardless of
the Qt environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from securepdf.detection.models import Detection
from securepdf.gui.document_session import Decision, DocumentSession
from securepdf.pdf.models import PageContent, TextSpan


def _make_det(page: int = 0, entity: str = "PERSON") -> Detection:
    return Detection(
        text="Jane Doe",
        entity_type=entity,
        page=page,
        bbox=(0, 0, 50, 14),
        char_start=0,
        char_end=8,
        confidence=0.9,
        source="presidio",
        span_indices=(0,),
    )


def test_fresh_session_is_unprocessed():
    s = DocumentSession(path=Path("/x.pdf"))
    assert s.processed is False
    assert s.page_count == 0
    assert s.detection_count == 0
    assert s.accepted_count == 0
    assert s.accepted_detections() == []


def test_set_detections_marks_processed_and_accepts_all():
    s = DocumentSession(path=Path("/x.pdf"))
    s.set_detections([_make_det(), _make_det(entity="EMAIL")])
    assert s.processed is True
    assert s.detection_count == 2
    assert s.accepted_count == 2
    assert all(d == Decision.ACCEPTED for d in s.decisions.values())


def test_individual_decision_flip():
    s = DocumentSession(path=Path("/x.pdf"))
    s.set_detections([_make_det(), _make_det()])
    s.set_decision(0, Decision.REJECTED)
    assert s.accepted_count == 1
    assert len(s.accepted_detections()) == 1


def test_set_decision_out_of_range_raises():
    s = DocumentSession(path=Path("/x.pdf"))
    s.set_detections([_make_det()])
    with pytest.raises(IndexError):
        s.set_decision(5, Decision.REJECTED)


def test_accept_all_and_reject_all():
    s = DocumentSession(path=Path("/x.pdf"))
    s.set_detections([_make_det(), _make_det()])
    s.reject_all()
    assert s.accepted_count == 0
    s.accept_all()
    assert s.accepted_count == 2


def test_detections_on_page_filters_correctly():
    s = DocumentSession(path=Path("/x.pdf"))
    s.set_detections([_make_det(page=0), _make_det(page=1), _make_det(page=0)])
    page0 = list(s.detections_on_page(0))
    page1 = list(s.detections_on_page(1))
    assert [i for i, _ in page0] == [0, 2]
    assert [i for i, _ in page1] == [1]


def test_set_pages_clamps_current_page():
    s = DocumentSession(path=Path("/x.pdf"))
    s.current_page = 5
    spans = [TextSpan(text="x", bbox=(0, 0, 10, 14), page=0)]
    s.set_pages([PageContent(page_number=0, width=100, height=100, spans=spans)])
    assert s.current_page == 0  # clamped to last valid index
