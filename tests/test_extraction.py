"""End-to-end smoke test for Phase 1.

Generates a synthetic PDF in-memory, extracts text from it, asserts the pipeline
returns reasonable spans. Run with: `pytest tests/`
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from securepdf.pdf.models import PageContent, TextSpan
from securepdf.pdf.pipeline import extract


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Build a tiny multi-page PDF with native text (no OCR needed)."""
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    # Page 1: clean PII-flavoured content (sets up later detection tests too).
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Patient: Jane Doe", fontsize=12)
    page1.insert_text((72, 100), "Email: jane.doe@example.com", fontsize=12)
    page1.insert_text((72, 128), "Phone: +1 (415) 555-0142", fontsize=12)
    # Page 2: also text-layer.
    page2 = doc.new_page()
    page2.insert_text((72, 72), "SSN: 123-45-6789", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_extract_returns_one_page_content_per_page(sample_pdf: Path):
    pages = extract(sample_pdf)
    assert len(pages) == 2
    assert all(isinstance(p, PageContent) for p in pages)


def test_extract_recovers_text(sample_pdf: Path):
    pages = extract(sample_pdf)
    page1_text = pages[0].text
    assert "Jane" in page1_text and "Doe" in page1_text
    assert "jane.doe@example.com" in page1_text
    assert "123-45-6789" in pages[1].text


def test_spans_have_valid_bboxes(sample_pdf: Path):
    pages = extract(sample_pdf)
    for page in pages:
        for span in page.spans:
            assert isinstance(span, TextSpan)
            x0, y0, x1, y1 = span.bbox
            assert x0 < x1 and y0 < y1, f"bad bbox: {span.bbox}"
            assert 0 <= x0 <= page.width and 0 <= x1 <= page.width
            assert 0 <= y0 <= page.height and 0 <= y1 <= page.height
            assert span.source == "pdf"
            assert span.confidence == 1.0


def test_extract_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        extract(tmp_path / "does-not-exist.pdf")
