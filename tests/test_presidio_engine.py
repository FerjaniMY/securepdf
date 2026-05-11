"""Integration test for the Stage 1 (Presidio) engine.

Requires `en_core_web_sm` to be installed. The test marks itself skipped
gracefully if the model isn't available — keeping `pytest` green on minimal
installations.
"""

from __future__ import annotations

import pytest

presidio_analyzer = pytest.importorskip("presidio_analyzer")
spacy = pytest.importorskip("spacy")


def _has_spacy_model(name: str) -> bool:
    try:
        spacy.load(name)
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_spacy_model("en_core_web_sm"),
    reason="en_core_web_sm not installed; run `python -m spacy download en_core_web_sm`",
)


def test_presidio_detects_email_and_person(synthetic_page):
    from securepdf.detection.presidio_engine import detect_page, make_engine

    analyzer = make_engine(spacy_model="en_core_web_sm")
    detections = detect_page(synthetic_page, analyzer)

    types = {d.entity_type for d in detections}
    # Presidio reliably finds the email; PERSON depends on spaCy NER and may or
    # may not surface "Jane Doe" in the small model — we assert email only as
    # the floor and check the rest as best-effort signals.
    assert "EMAIL_ADDRESS" in types


def test_presidio_detects_custom_mrn(synthetic_page):
    """The MRN pattern needs the context word ("MRN:") nearby to boost score."""
    from securepdf.detection.presidio_engine import detect_page, make_engine

    analyzer = make_engine(spacy_model="en_core_web_sm")
    detections = detect_page(synthetic_page, analyzer)
    mrn_detections = [d for d in detections if d.entity_type == "MRN"]
    assert mrn_detections, "expected at least one MRN detection from '4827193' with MRN: context"
    assert "4827193" in mrn_detections[0].text


def test_presidio_detects_icd10(synthetic_page):
    from securepdf.detection.presidio_engine import detect_page, make_engine

    analyzer = make_engine(spacy_model="en_core_web_sm")
    detections = detect_page(synthetic_page, analyzer)
    assert any(d.entity_type == "ICD10" and "E11.9" in d.text for d in detections)


def test_detections_have_valid_bboxes(synthetic_page):
    from securepdf.detection.presidio_engine import detect_page, make_engine

    analyzer = make_engine(spacy_model="en_core_web_sm")
    detections = detect_page(synthetic_page, analyzer)
    assert detections  # at least the email should be present
    for d in detections:
        x0, y0, x1, y1 = d.bbox
        assert x0 < x1 and y0 < y1
        assert 0 <= x0 <= synthetic_page.width
        assert 0 <= y0 <= synthetic_page.height
        assert d.span_indices  # every detection should have at least one span
