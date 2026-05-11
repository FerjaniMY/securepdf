"""Tests for the detection review panel widget.

Uses the offscreen Qt platform from conftest, so no display is required.
Focuses on data binding: the panel must reflect the session's state, and user
toggles must propagate back into the session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# PySide6 widgets need libGL even in offscreen mode on Linux. If we can't import
# them, skip all tests in this module. (The `qapp` fixture also skips, but doing
# this at module level avoids surfacing every test as an ERROR during collection.)
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from securepdf.detection.models import Detection
from securepdf.gui.document_session import Decision, DocumentSession


def _det(page: int = 0, entity: str = "PERSON", text: str = "Jane Doe") -> Detection:
    return Detection(
        text=text,
        entity_type=entity,
        page=page,
        bbox=(0, 0, 50, 14),
        char_start=0,
        char_end=len(text),
        confidence=0.9,
        source="presidio",
        span_indices=(0,),
    )


@pytest.fixture
def panel_with_session(qapp):
    from securepdf.gui.detection_panel import DetectionPanel
    session = DocumentSession(path=Path("/x.pdf"))
    session.set_detections([_det(entity="PERSON"), _det(entity="EMAIL_ADDRESS"), _det(page=1, entity="MRN")])
    panel = DetectionPanel()
    panel.set_session(session)
    return panel, session


def test_set_session_populates_tree(panel_with_session):
    panel, _ = panel_with_session
    assert panel.item_count() == 3


def test_panel_clears_when_session_set_to_none(panel_with_session, qapp):
    panel, _ = panel_with_session
    panel.set_session(None)
    assert panel.item_count() == 0


def test_columns_show_expected_data(panel_with_session):
    from securepdf.gui.detection_panel import (
        COL_CONF,
        COL_PAGE,
        COL_SOURCE,
        COL_TEXT,
        COL_TYPE,
    )
    panel, _ = panel_with_session
    item = next(panel.items())
    assert item.text(COL_PAGE) == "1"  # 1-indexed for users (detection page 0)
    assert item.text(COL_TYPE) == "PERSON"
    assert item.text(COL_TEXT) == "Jane Doe"
    assert item.text(COL_CONF) == "0.90"
    assert item.text(COL_SOURCE) == "presidio"


def test_reject_all_button_drops_accepted_count(panel_with_session):
    panel, session = panel_with_session
    assert session.accepted_count == 3
    panel._on_reject_all()  # noqa: SLF001 — invoking via slot to avoid Qt clicks
    assert session.accepted_count == 0


def test_accept_all_button_restores_acceptance(panel_with_session):
    panel, session = panel_with_session
    session.reject_all()
    panel._on_accept_all()  # noqa: SLF001
    assert session.accepted_count == 3


def test_decisions_changed_signal_fires_on_bulk(panel_with_session):
    panel, _ = panel_with_session
    captured: list = []
    panel.decisions_changed.connect(lambda: captured.append(True))
    panel._on_reject_all()  # noqa: SLF001
    panel._on_accept_all()  # noqa: SLF001
    assert len(captured) == 2
