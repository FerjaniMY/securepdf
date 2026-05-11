"""Shared pytest fixtures.

Phase 2 tests need PageContent instances with realistic bboxes. We build them
in memory rather than rendering a PDF — keeps tests fast and deterministic.

Phase 4 GUI tests need a headless Qt. We set QT_QPA_PLATFORM=offscreen at the
TOP of this module — before anyone imports PySide6 — so all later imports pick
it up. The fixture `qapp` provides a singleton QApplication that survives the
whole test session.
"""

from __future__ import annotations

import os
# Must be set before PySide6 is imported. conftest.py runs before any test
# module, and many test modules import PySide6 at module top, so we set this
# here unconditionally — there's no display server in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from securepdf.pdf.models import PageContent, TextSpan


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for any test that constructs Qt widgets.

    Reusing a single QApplication across tests is the supported PySide6 pattern —
    multiple QApplications per process aren't allowed. Tests that don't need Qt
    simply don't request this fixture.

    On systems without the required graphics shared libraries (libGL, libEGL),
    importing PySide6.QtWidgets raises ImportError even with QT_QPA_PLATFORM=
    offscreen. We skip rather than fail in that case — the same tests pass on
    any developer machine or a CI image with the system libs installed
    (`apt install libgl1` on Debian/Ubuntu).
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as e:
        pytest.skip(f"PySide6 import failed (missing system libs?): {e}")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _span(text: str, x0: float, y0: float, page: int = 0) -> TextSpan:
    """Build a TextSpan with a realistic bbox sized to the text length."""
    # 6pt per char is roughly accurate for 12pt monospace; bbox shape just needs
    # to be valid for tests, not visually correct.
    return TextSpan(
        text=text,
        bbox=(x0, y0, x0 + len(text) * 6.0, y0 + 14.0),
        page=page,
        source="pdf",
        confidence=1.0,
    )


@pytest.fixture
def synthetic_page() -> PageContent:
    """A single page with PHI/PII content laid out as if on a real form.

    Concatenated text: "Patient: Jane Doe Email: jane.doe@example.com MRN: 4827193 Diagnosis: E11.9"
    Each token is its own span with a sensible bbox.
    """
    spans = [
        _span("Patient:", 72, 72),
        _span("Jane", 130, 72),
        _span("Doe", 160, 72),
        _span("Email:", 72, 92),
        _span("jane.doe@example.com", 120, 92),
        _span("MRN:", 72, 112),
        _span("4827193", 110, 112),
        _span("Diagnosis:", 72, 132),
        _span("E11.9", 140, 132),
    ]
    return PageContent(
        page_number=0,
        width=595.0,
        height=842.0,
        spans=spans,
        source="pdf",
    )


@pytest.fixture
def multi_page() -> list[PageContent]:
    """Two pages — useful for testing page-aware logic in the merger and pipeline."""
    page0_spans = [
        _span("Patient:", 72, 72),
        _span("Jane", 130, 72),
        _span("Doe", 160, 72),
    ]
    page1_spans = [
        _span("SSN:", 72, 72, page=1),
        _span("123-45-6789", 110, 72, page=1),
    ]
    return [
        PageContent(page_number=0, width=595, height=842, spans=page0_spans, source="pdf"),
        PageContent(page_number=1, width=595, height=842, spans=page1_spans, source="pdf"),
    ]
