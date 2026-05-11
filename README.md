# SecurePDF

Local AI PDF redaction & anonymization. Strip sensitive data (PII, PHI, financial,
custom entities) from PDFs **on your machine** before you send the document to a
cloud LLM like ChatGPT or Claude.

> Nothing leaves your laptop. No GPU required.

## Status

- **Phase 1 — Foundations** ✅ project scaffold, PDF text extraction (PyMuPDF), OCR fallback (Tesseract)
- **Phase 2 — Detection** ✅ Presidio Stage 1 + Gemma 2 2B Stage 2 via Ollama + merger
- **Phase 3 — Redaction & anonymization** ✅ true PDF redaction + pseudonymized text export
- **Phase 4 — PySide6 desktop GUI** ⏳ next
- **Phase 5 — Polish & packaging** ⏳

## Architecture

```
  PDF in
    │
    ▼
[ Extraction ] ─── PyMuPDF (text + bboxes)
    │              Tesseract OCR fallback for scanned pages
    ▼
[ Detection Stage 1 ] ─── Presidio analyzer
    │                       - Built-ins (PERSON, EMAIL, SSN, CREDIT_CARD, IBAN, …)
    │                       - PHI: MRN, ICD-10, condition lexicon
    │                       - Financial: US EIN, US routing
    │                       - Custom: user-defined regex/keywords
    │
[ Detection Stage 2 ] ─── Gemma 2 2B via Ollama
    │                       - Contextual / anaphoric references
    │                       - User-defined entities by description
    │                       - Stage 1 results passed as hints
    │
[ Merger ] ─── Dedupe overlapping spans, union bboxes
    │
    ▼                                       ▼
Redacted PDF                       Anonymized text
(PyMuPDF true redaction)           ([PERSON_1], [EMAIL_2], …)
   (Phase 3)                           (Phase 3)
```

## Modules

**PDF I/O (`securepdf.pdf`)**
- `models.py` — `TextSpan`, `PageContent` data classes
- `extractor.py` — PyMuPDF word-level text extraction
- `ocr.py` — Tesseract fallback @ 300 DPI with px→pt coord conversion
- `pipeline.py` — unified `extract(pdf)` entry point + `securepdf-extract` CLI

**Detection (`securepdf.detection`)**
- `models.py` — `Detection` data class (page-anchored, with bbox + char range)
- `span_mapping.py` — char-offset → span-indices → union bbox bridge
- `phi_recognizers.py` — MRN, ICD-10, conditions
- `financial_recognizers.py` — US EIN, US routing number
- `presidio_engine.py` — Stage 1 orchestrator
- `ollama_client.py` — HTTP client for the local Ollama server
- `gemma_detector.py` — Stage 2 contextual detector
- `merger.py` — overlap-dedupe with union bboxes
- `custom_entities.py` — YAML profile loader (regex / keywords / LLM descriptions)
- `pipeline.py` — full `detect(pages)` orchestrator + `securepdf-detect` CLI

**Redaction (`securepdf.redaction`)**
- `pseudonyms.py` — `PseudonymMap` (consistent `[PERSON_1]`-style aliasing, case-insensitive)
- `text_export.py` — anonymized text with pseudonyms substituted in place
- `pdf_renderer.py` — PyMuPDF true redaction (text physically removed, not just covered)
- `pipeline.py` — `redact(pdf, detections)` orchestrator + `securepdf-redact` CLI

## Install

```bash
# System deps
#   macOS:   brew install tesseract && brew install ollama
#   Linux:   apt install tesseract-ocr && curl -fsSL https://ollama.com/install.sh | sh
#   Windows: see tesseract / ollama installer pages
ollama pull gemma2:2b   # ~1.6 GB, one-time

pip install -e .[dev]
python -m spacy download en_core_web_sm   # for tests
# Production: en_core_web_lg (better PERSON recall)
```

## Quick start

```python
from securepdf.pdf.pipeline import extract
from securepdf.detection import detect

pages = extract("medical_record.pdf")
detections = detect(pages)
for d in detections:
    print(f"page {d.page}: {d.entity_type:20s} → {d.text!r}  (conf={d.confidence:.2f})")
```

Or from the CLI:

```bash
securepdf-extract  medical_record.pdf
securepdf-detect   medical_record.pdf
securepdf-detect   medical_record.pdf --no-stage2   # Presidio only (no Ollama)
securepdf-detect   medical_record.pdf --profile entities.yml   # custom entities

# Full pipeline: extract → detect → redact (Phase 3)
securepdf-redact   medical_record.pdf
securepdf-redact   medical_record.pdf --mode text                        # text only
securepdf-redact   medical_record.pdf --mode pdf --text-overlay type     # label boxes
securepdf-redact   medical_record.pdf --text-overlay pseudonym           # cross-ref text & PDF
```

Custom entity profile example (`entities.yml`):

```yaml
patterns:
  - name: project_codename
    regex: '\bPROJECT_[A-Z]+\b'
    score: 0.9
    context: ['internal', 'codename']

keywords:
  - name: client_aliases
    terms: ['Acme', 'Acme Corp', 'Acme Inc']
    score: 0.85

descriptions:
  - "Internal project codenames like PROJECT_PHOENIX"
  - "Names of clients on our restricted partner list"
```

## Tests

```bash
PYTHONPATH=src pytest tests/
```
