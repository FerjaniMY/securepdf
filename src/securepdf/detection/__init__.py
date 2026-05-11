"""Detection engine — the heart of SecurePDF.

Two-stage architecture:

  Stage 1 — Presidio (fast, deterministic):
      Built-in PII recognizers + our custom PHI and financial recognizers.
      Runs in milliseconds on CPU. Catches structured patterns (emails, SSNs,
      MRNs, ICD-10, IBANs) and named entities (PERSON, LOCATION via spaCy).

  Stage 2 — Gemma 2 2B via Ollama (contextual):
      Catches what Stage 1 misses: anaphoric references ("the patient", "her
      doctor"), narrative PII, and user-defined custom entities described in
      natural language.

  Merger:
      Dedupes overlapping spans across both stages, unioning bounding boxes
      and preferring the higher-confidence source where they overlap.

Public surface:

    from securepdf.detection import detect, Detection
    detections = detect(pages, profile=None)
"""

from securepdf.detection.models import Detection, EntitySource
from securepdf.detection.pipeline import detect

__all__ = ["Detection", "EntitySource", "detect"]
