"""Tests for the PDF redaction renderer.

The most important test in this file is `test_redaction_actually_destroys_text` —
it verifies that after redaction, the sensitive text CANNOT be recovered from the
output PDF. This is the property that distinguishes "true redaction" from "drew a
black box on top".
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from securepdf.detection.models import Detection
from securepdf.redaction.pdf_renderer import render_redacted_pdf
from securepdf.redaction.pseudonyms import PseudonymMap


@pytest.fixture
def sensitive_pdf(tmp_path: Path) -> Path:
    """Build a small PDF with known sensitive content."""
    pdf_path = tmp_path / "sensitive.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Patient: Jane Doe", fontsize=12)
    page.insert_text((72, 100), "Email: jane.doe@example.com", fontsize=12)
    page.insert_text((72, 128), "MRN: 4827193", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _email_bbox(pdf_path: Path) -> tuple[float, float, float, float]:
    """Find the bbox of 'jane.doe@example.com' in the sample PDF."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    words = page.get_text("words")
    doc.close()
    for x0, y0, x1, y1, text, *_ in words:
        if text == "jane.doe@example.com":
            return (float(x0), float(y0), float(x1), float(y1))
    raise RuntimeError("email span not found in fixture PDF — test setup bug")


def _make_detection(bbox, text, entity="EMAIL_ADDRESS") -> Detection:
    return Detection(
        text=text,
        entity_type=entity,
        page=0,
        bbox=bbox,
        char_start=0,  # not used by the renderer
        char_end=len(text),
        confidence=0.95,
        source="presidio",
        span_indices=(0,),
    )


def test_renders_to_output_path(sensitive_pdf, tmp_path):
    out = tmp_path / "redacted.pdf"
    det = _make_detection(_email_bbox(sensitive_pdf), "jane.doe@example.com")
    result = render_redacted_pdf(sensitive_pdf, out, [det])
    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_redaction_actually_destroys_text(sensitive_pdf, tmp_path):
    """The critical property: after redaction, the text isn't extractable from the PDF.

    This is what 'true redaction' means — distinct from drawing a black box on top.
    """
    out = tmp_path / "redacted.pdf"
    det = _make_detection(_email_bbox(sensitive_pdf), "jane.doe@example.com")
    render_redacted_pdf(sensitive_pdf, out, [det])

    # Now open the OUTPUT and try to extract the email.
    doc = fitz.open(out)
    page_text = doc[0].get_text("text")
    doc.close()
    assert "jane.doe@example.com" not in page_text
    # Other sensitive bits we didn't redact should still be present (sanity check
    # — proves we didn't accidentally nuke everything).
    assert "Jane Doe" in page_text
    assert "4827193" in page_text


def test_text_overlay_type(sensitive_pdf, tmp_path):
    out = tmp_path / "redacted_type.pdf"
    det = _make_detection(_email_bbox(sensitive_pdf), "jane.doe@example.com")
    render_redacted_pdf(sensitive_pdf, out, [det], text_overlay="type")
    # The overlay text "[EMAIL_ADDRESS]" should appear in the redacted output.
    doc = fitz.open(out)
    page_text = doc[0].get_text("text")
    doc.close()
    assert "[EMAIL_ADDRESS]" in page_text


def test_text_overlay_pseudonym_requires_map(sensitive_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    det = _make_detection(_email_bbox(sensitive_pdf), "jane.doe@example.com")
    with pytest.raises(ValueError, match="requires a pseudonym_map"):
        render_redacted_pdf(sensitive_pdf, out, [det], text_overlay="pseudonym")


def test_text_overlay_pseudonym_uses_map(sensitive_pdf, tmp_path):
    out = tmp_path / "redacted_pseudo.pdf"
    det = _make_detection(_email_bbox(sensitive_pdf), "jane.doe@example.com")
    pmap = PseudonymMap()
    render_redacted_pdf(
        sensitive_pdf, out, [det], text_overlay="pseudonym", pseudonym_map=pmap
    )
    doc = fitz.open(out)
    page_text = doc[0].get_text("text")
    doc.close()
    assert "[EMAIL_ADDRESS_1]" in page_text


def test_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_redacted_pdf(tmp_path / "nope.pdf", tmp_path / "out.pdf", [])


def test_empty_detections_produces_valid_output(sensitive_pdf, tmp_path):
    """Rendering with zero detections should still produce a valid output PDF —
    just a copy of the input. Edge case worth covering."""
    out = tmp_path / "noop.pdf"
    render_redacted_pdf(sensitive_pdf, out, [])
    doc = fitz.open(out)
    page_text = doc[0].get_text("text")
    doc.close()
    assert "jane.doe@example.com" in page_text  # nothing was redacted
