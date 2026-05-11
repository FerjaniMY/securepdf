"""Custom financial recognizers that complement Presidio's defaults.

Presidio ships with CREDIT_CARD, IBAN_CODE, US_BANK_NUMBER, CRYPTO. We add:
  - US_EIN (Employer Identification Number / federal tax ID)
  - US_ROUTING (ABA routing transit number, 9 digits with context)

Tax IDs are particularly important for financial document anonymization — a stray
EIN in a contract or invoice uniquely identifies an organization.
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

# US EIN: XX-XXXXXXX (two digits, hyphen, seven digits). The hyphen is part of
# the format — without it, the pattern collides with most 9-digit numbers (SSNs,
# phone numbers without dashes, account numbers). The hyphenated form is rare
# enough in random text that it's high-confidence even without context.
_EIN_PATTERN = Pattern(
    name="us_ein_pattern",
    regex=r"\b\d{2}-\d{7}\b",
    score=0.8,
)
US_EIN_RECOGNIZER = PatternRecognizer(
    supported_entity="US_EIN",
    patterns=[_EIN_PATTERN],
    context=["ein", "tax id", "tax-id", "taxpayer", "employer identification"],
)


# ABA routing number: exactly 9 digits. Almost always accompanied by context
# (the number alone is indistinguishable from a phone number or zip+4). Score
# is low without context — Presidio bumps it when context words appear.
_ROUTING_PATTERN = Pattern(
    name="us_routing_pattern",
    regex=r"\b\d{9}\b",
    score=0.35,
)
US_ROUTING_RECOGNIZER = PatternRecognizer(
    supported_entity="US_ROUTING",
    patterns=[_ROUTING_PATTERN],
    context=["routing", "aba", "rtn", "transit", "wire"],
)


FINANCIAL_RECOGNIZERS = [US_EIN_RECOGNIZER, US_ROUTING_RECOGNIZER]


def all_financial_entity_types() -> list[str]:
    return ["US_EIN", "US_ROUTING"]
