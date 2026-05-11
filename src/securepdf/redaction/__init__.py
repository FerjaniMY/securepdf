"""Redaction & anonymization — the output layer.

Takes the `Detection`s produced by `securepdf.detection` and emits either or both of:

  - A **redacted PDF**: same layout as the original, sensitive spans truly removed
    from the file stream (not just visually covered). Uses PyMuPDF's
    `add_redact_annot()` + `apply_redactions()` — the same technique Acrobat Pro
    uses for true redaction.

  - An **anonymized text export**: page text with sensitive substrings replaced by
    consistent pseudonyms (e.g. `[PERSON_1]`, `[EMAIL_2]`). Ready to paste into
    ChatGPT / Claude without leaking PII.

Public surface:

    from securepdf.redaction import redact, PseudonymMap
    result = redact(input_pdf="in.pdf", detections=dets, pages=pages,
                    output_pdf="out.pdf", output_text="out.txt", mode="both")
"""

from securepdf.redaction.pdf_renderer import render_redacted_pdf
from securepdf.redaction.pipeline import redact
from securepdf.redaction.pseudonyms import PseudonymMap
from securepdf.redaction.text_export import anonymize_page, anonymize_pages

__all__ = [
    "PseudonymMap",
    "anonymize_page",
    "anonymize_pages",
    "redact",
    "render_redacted_pdf",
]
