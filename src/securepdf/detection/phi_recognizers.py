"""Custom PHI (Protected Health Information) recognizers for Presidio's Stage 1.

Presidio's defaults cover demographic PII (PERSON, EMAIL, PHONE, SSN, etc.) but
medical-specific identifiers — MRNs, ICD-10 codes, common condition names —
need recognizers we write ourselves.

These run BEFORE the Gemma contextual pass, so anything they catch deterministically
saves an LLM call. The conditions list is intentionally small here; it's a starter
seed. Production deployments would extend it with domain-specific terms (the user
can do this through the custom entity profile in `custom_entities.py`).
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

# ---------------------------------------------------------------------------
# Medical Record Number (MRN)
# ---------------------------------------------------------------------------
# MRNs vary wildly between health systems (Epic, Cerner, custom hospital IDs).
# The reliable signal is the *context* — words like "MRN", "Medical Record",
# "Patient ID" near a digit string of 6–12 chars. Without the context, a 7-digit
# number is also valid as a phone number, an SSN fragment, or a part number.
#
# Score:
#   0.5 = pattern hit (just a 6–12 digit number). Borderline; might be noise.
#   0.85 = pattern + context word nearby. High confidence.
#
# Presidio handles the context-boost automatically when `context` words appear
# within a window of the match.
_MRN_PATTERN = Pattern(
    name="mrn_pattern",
    # 6–12 digit numbers. The boundary anchors prevent partial-match inside e.g.
    # a long account number.
    regex=r"\b\d{6,12}\b",
    score=0.5,
)
MRN_RECOGNIZER = PatternRecognizer(
    supported_entity="MRN",
    patterns=[_MRN_PATTERN],
    context=["mrn", "medical record", "patient id", "patient #", "patient number", "mr#", "mr #"],
)


# ---------------------------------------------------------------------------
# ICD-10 diagnosis codes
# ---------------------------------------------------------------------------
# Format: one letter (A–T, V–Z; U is reserved), two digits or alphanumerics, then
# an optional decimal extension of 1–4 chars. Examples:
#   E11.9  (diabetes type 2)
#   J45    (asthma)
#   F32.0  (depression, mild)
#   S72.001A  (femur fracture, initial encounter)
#
# This pattern is specific enough that the regex alone is high-confidence.
_ICD10_PATTERN = Pattern(
    name="icd10_pattern",
    regex=r"\b[A-TV-Z]\d{2}(?:\.[0-9A-TV-Z]{1,4})?\b",
    score=0.85,
)
ICD10_RECOGNIZER = PatternRecognizer(
    supported_entity="ICD10",
    patterns=[_ICD10_PATTERN],
    context=["icd", "diagnosis", "code"],
)


# ---------------------------------------------------------------------------
# Medical conditions (lexicon-based)
# ---------------------------------------------------------------------------
# A small starter list of conditions that, if mentioned, are themselves PHI under
# HIPAA. Real deployments should extend this — the goal here is to demonstrate
# the lexicon approach and catch the most common terms.
#
# Score is modest (0.6) because these words appear in non-medical contexts too
# ("financial depression"). The Stage 2 Gemma pass can re-evaluate borderline
# cases with context.
_CONDITIONS = [
    "diabetes",
    "hypertension",
    "depression",
    "anxiety",
    "cancer",
    "HIV",
    "AIDS",
    "hepatitis",
    "pregnancy",
    "schizophrenia",
    "bipolar",
    "alzheimer",
    "dementia",
    "asthma",
    "epilepsy",
]
_CONDITIONS_PATTERN = Pattern(
    name="conditions_lexicon",
    regex=r"\b(?:" + "|".join(_CONDITIONS) + r")\b",
    score=0.6,
)
CONDITIONS_RECOGNIZER = PatternRecognizer(
    supported_entity="MEDICAL_CONDITION",
    patterns=[_CONDITIONS_PATTERN],
    context=["patient", "diagnosed", "history", "condition", "treatment"],
)


PHI_RECOGNIZERS = [MRN_RECOGNIZER, ICD10_RECOGNIZER, CONDITIONS_RECOGNIZER]


def all_phi_entity_types() -> list[str]:
    """Entity types exposed by this module — for analyzer config and tests."""
    return ["MRN", "ICD10", "MEDICAL_CONDITION"]
