"""Tests for the anonymized text exporter."""

from __future__ import annotations

from securepdf.detection.models import Detection
from securepdf.pdf.models import PageContent, TextSpan
from securepdf.redaction.pseudonyms import PseudonymMap
from securepdf.redaction.text_export import (
    PAGE_SEPARATOR,
    anonymize_page,
    anonymize_pages,
)


def _make_detection(text: str, page: int, char_start: int, char_end: int, entity: str = "PERSON") -> Detection:
    return Detection(
        text=text,
        entity_type=entity,
        page=page,
        bbox=(0.0, 0.0, 10.0, 14.0),
        char_start=char_start,
        char_end=char_end,
        confidence=0.9,
        source="presidio",
        span_indices=(0,),
    )


def test_no_detections_returns_unchanged_text(synthetic_page):
    pmap = PseudonymMap()
    result = anonymize_page(synthetic_page, [], pmap)
    assert result == synthetic_page.text


def test_single_detection_replaced(synthetic_page):
    """Replace 'jane.doe@example.com' with a pseudonym."""
    pmap = PseudonymMap()
    text = synthetic_page.text
    start = text.index("jane.doe@example.com")
    det = _make_detection("jane.doe@example.com", 0, start, start + 20, entity="EMAIL")
    result = anonymize_page(synthetic_page, [det], pmap)
    assert "jane.doe@example.com" not in result
    assert "[EMAIL_1]" in result


def test_multiple_detections_all_replaced(synthetic_page):
    pmap = PseudonymMap()
    text = synthetic_page.text
    email_start = text.index("jane.doe@example.com")
    mrn_start = text.index("4827193")
    icd_start = text.index("E11.9")
    dets = [
        _make_detection("jane.doe@example.com", 0, email_start, email_start + 20, "EMAIL"),
        _make_detection("4827193", 0, mrn_start, mrn_start + 7, "MRN"),
        _make_detection("E11.9", 0, icd_start, icd_start + 5, "ICD10"),
    ]
    result = anonymize_page(synthetic_page, dets, pmap)
    assert "[EMAIL_1]" in result
    assert "[MRN_1]" in result
    assert "[ICD10_1]" in result
    assert "jane.doe" not in result
    assert "4827193" not in result
    assert "E11.9" not in result


def test_detections_replaced_left_to_right_correctly(synthetic_page):
    """If multiple detections are out of order, we sort and apply correctly."""
    pmap = PseudonymMap()
    text = synthetic_page.text
    email_start = text.index("jane.doe@example.com")
    mrn_start = text.index("4827193")
    # Pass detections in reverse order — exporter must sort internally.
    dets = [
        _make_detection("4827193", 0, mrn_start, mrn_start + 7, "MRN"),
        _make_detection("jane.doe@example.com", 0, email_start, email_start + 20, "EMAIL"),
    ]
    result = anonymize_page(synthetic_page, dets, pmap)
    # Order in output mirrors order in original text.
    assert result.index("[EMAIL_1]") < result.index("[MRN_1]")


def test_consistent_pseudonyms_across_pages():
    """Same name on two pages → same pseudonym."""
    spans_p0 = [TextSpan(text="Hello", bbox=(0, 0, 30, 14), page=0)]
    spans_p1 = [TextSpan(text="Hello", bbox=(0, 0, 30, 14), page=1)]
    pages = [
        PageContent(page_number=0, width=100, height=100, spans=spans_p0),
        PageContent(page_number=1, width=100, height=100, spans=spans_p1),
    ]
    dets = [
        _make_detection("Hello", 0, 0, 5, "GREETING"),
        _make_detection("Hello", 1, 0, 5, "GREETING"),
    ]
    text, pmap = anonymize_pages(pages, dets)
    assert text.count("[GREETING_1]") == 2  # same pseudonym both times
    assert len(pmap) == 1


def test_anonymize_pages_inserts_separator():
    spans_p0 = [TextSpan(text="Alpha", bbox=(0, 0, 30, 14), page=0)]
    spans_p1 = [TextSpan(text="Beta", bbox=(0, 0, 30, 14), page=1)]
    pages = [
        PageContent(page_number=0, width=100, height=100, spans=spans_p0),
        PageContent(page_number=1, width=100, height=100, spans=spans_p1),
    ]
    text, _ = anonymize_pages(pages, [])
    assert PAGE_SEPARATOR in text
    assert text.startswith("Alpha")
    assert text.endswith("Beta")


def test_detections_on_other_pages_ignored():
    """A page's anonymizer doesn't apply detections from other pages."""
    spans = [TextSpan(text="Alpha", bbox=(0, 0, 30, 14), page=0)]
    page = PageContent(page_number=0, width=100, height=100, spans=spans)
    # Detection claims to be on page 1 — should be ignored when anonymizing page 0.
    det = _make_detection("Alpha", 1, 0, 5, "X")
    result = anonymize_page(page, [det], PseudonymMap())
    assert result == "Alpha"
