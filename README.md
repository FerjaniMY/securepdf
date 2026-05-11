# SecurePDF

Local AI PDF redaction & anonymization. Strip sensitive data (PII, PHI, financial, custom
entities) from PDFs **on your machine** before you send the document to a cloud LLM like
ChatGPT or Claude.

> Nothing leaves your laptop. No GPU required.

## Status

This is **Phase 1 — Foundations**: project scaffold + PDF text extraction + OCR fallback.

Later phases add the detection engine (Presidio + Gemma 2 2B via Ollama), the redaction
renderer, and the PySide6 desktop GUI. See `Project Doc → Tasks` for the roadmap.

## Architecture (target)

```
  PDF in
    │
    ▼
[ Extraction ] ─── PyMuPDF (text + bboxes)
    │              Tesseract OCR fallback for scanned pages
    ▼
[ Detection Stage 1 ] ─── Presidio analyzer (PII, PHI, financial regex/NER)
    │
[ Detection Stage 2 ] ─── Gemma 2 2B via Ollama (contextual / anaphoric / custom)
    │
[ Merge & user review (GUI) ]
    │
    ▼                                       ▼
Redacted PDF                       Anonymized text
(PyMuPDF true redaction)           ([PERSON_1], [EMAIL_2], ...)
```

## Phase 1 modules

- `securepdf.pdf.models` — `TextSpan`, `PageContent` data classes shared across phases
- `securepdf.pdf.extractor` — PyMuPDF-based text + bbox extraction
- `securepdf.pdf.ocr` — Tesseract fallback for image-only pages
- `securepdf.pdf.pipeline` — unified `extract(pdf_path) -> list[PageContent]` entry point

## Install

```bash
# Phase 1 system dependency: tesseract (only needed if you process scanned PDFs)
#   macOS:   brew install tesseract
#   Ubuntu:  sudo apt install tesseract-ocr
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki

pip install -e .[dev]
```

## Quick start (Phase 1)

```python
from securepdf.pdf.pipeline import extract

pages = extract("path/to/document.pdf")
for page in pages:
    print(f"Page {page.page_number} ({page.source}): {len(page.spans)} spans")
    for span in page.spans[:5]:
        print(f"  {span.bbox}  {span.text!r}")
```

Or from the CLI:

```bash
securepdf-extract path/to/document.pdf
```
