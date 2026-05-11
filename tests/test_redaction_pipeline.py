"""End-to-end test for the Phase 3 pipeline.

Builds a small PDF, fakes detections (no Presidio/Gemma needed), runs the full
`redact()` orchestrator, and asserts both artifacts came out clean.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from securepdf.detection.models import Detection
from securepdf.pdf.pipeline import extract
from securepdf.redaction.pipeline import redact


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Patient: Jane Doe", fontsize=12)
    page.insert_text((72, 100), "Email: jane.doe@example.com", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _make_email_detection(pages, page_idx: int = 0) -> Detection:
    page = pages[page_idx]
    # Find the email span.
    for i, span in enumerate(page.spans):
        if span.text == "jane.doe@example.com":
            text = page.text
            # The span's char range in page.text.
            from securepdf.detection.span_mapping import build_span_offsets
            offsets = build_span_offsets(page)
            start, end = offsets[i]
            return Detection(
                text=text[start:end],
                entity_type="EMAIL_ADDRESS",
                page=page_idx,
                bbox=span.bbox,
                char_start=start,
                char_end=end,
                confidence=0.95,
                source="presidio",
                span_indices=(i,),
            )
    raise RuntimeError("test setup: email span not found")


def test_pipeline_both_mode(sample_pdf, tmp_path):
    pages = extract(sample_pdf)
    dets = [_make_email_detection(pages)]

    result = redact(
        sample_pdf,
        dets,
        pages=pages,
        output_pdf=tmp_path / "redacted.pdf",
        output_text=tmp_path / "anon.txt",
        mode="both",
    )

    # PDF: text destroyed.
    assert result.pdf_path is not None and result.pdf_path.exists()
    doc = fitz.open(result.pdf_path)
    assert "jane.doe@example.com" not in doc[0].get_text("text")
    doc.close()

    # Text: pseudonym in place of email.
    assert result.text is not None
    assert "[EMAIL_ADDRESS_1]" in result.text
    assert "jane.doe@example.com" not in result.text
    assert result.text_path is not None and result.text_path.exists()
    assert "[EMAIL_ADDRESS_1]" in result.text_path.read_text()

    # Pseudonym map populated.
    assert result.pseudonym_map is not None
    assert len(result.pseudonym_map) == 1


def test_pipeline_pdf_only(sample_pdf, tmp_path):
    pages = extract(sample_pdf)
    dets = [_make_email_detection(pages)]
    result = redact(
        sample_pdf,
        dets,
        pages=pages,
        output_pdf=tmp_path / "redacted.pdf",
        mode="pdf",
    )
    assert result.pdf_path is not None
    assert result.text is None
    assert result.text_path is None


def test_pipeline_text_only(sample_pdf, tmp_path):
    pages = extract(sample_pdf)
    dets = [_make_email_detection(pages)]
    result = redact(
        sample_pdf,
        dets,
        pages=pages,
        output_text=tmp_path / "anon.txt",
        mode="text",
    )
    assert result.pdf_path is None
    assert result.text is not None
    assert "[EMAIL_ADDRESS_1]" in result.text


def test_pipeline_pdf_requires_output_path(sample_pdf):
    pages = extract(sample_pdf)
    dets = [_make_email_detection(pages)]
    with pytest.raises(ValueError, match="output_pdf is None"):
        redact(sample_pdf, dets, pages=pages, mode="pdf")
