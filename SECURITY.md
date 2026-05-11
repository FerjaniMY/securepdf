# Security Policy

## Reporting a vulnerability

Please **do not open a public GitHub issue** for security-sensitive bugs.

Email vulnerability reports to the maintainer via the email address listed on
[github.com/FerjaniMY](https://github.com/FerjaniMY), or open a private
[security advisory](https://github.com/FerjaniMY/securepdf/security/advisories/new)
directly on GitHub.

Include:
- A description of the issue and its impact
- Steps to reproduce (a minimal sample file is hugely helpful for PDF parsing issues)
- The version of SecurePDF you tested
- Your name / handle if you'd like credit in the advisory

We aim to acknowledge reports within 72 hours and to publish a fixed release within
14 days for critical issues, longer for less severe ones. Coordinated disclosure
preferred.

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | ✅ Yes — current     |
| < 0.5   | ❌ Pre-release, no support |

## What SecurePDF does — and does *not* — guarantee

SecurePDF is a privacy tool. People rely on its guarantees, so the limits of those
guarantees should be explicit.

### What we guarantee

1. **True text destruction in the redacted PDF.** When you apply redactions to a
   detection, the underlying text is physically removed from the PDF content
   stream — not just visually covered. This is verified by an end-to-end test
   that opens the output PDF and asserts the sensitive substring cannot be
   recovered via `fitz.get_text()`. If that ever fails, it's a critical bug.

2. **No data leaves your machine** during normal operation. There are no
   telemetry calls, no cloud APIs, no analytics. The optional Stage 2 contextual
   detection sends page text only to a local Ollama process on `localhost`.

3. **Open-source code path.** Every line of code that touches your document is
   in this repository under an MIT license. You can audit it yourself.

### What we do NOT guarantee

1. **Complete detection of all sensitive content.** Detection is best-effort.
   We catch the standard PII types reliably (emails, SSNs, credit cards, etc.),
   but false negatives exist — particularly for:
   - Unusual name spellings
   - Names embedded in larger phrases
   - Sensitive information conveyed by context only
   - Custom-format identifiers we don't have a recognizer for

   **The GUI's human-review step is not optional in our threat model.** A user
   who clicks "Save Outputs" without reviewing every detection has not used the
   tool correctly.

2. **Pseudonym irreversibility.** The pseudonyms in the anonymized text export
   (`[PERSON_1]`, `[EMAIL_2]`, …) are stable labels, not cryptographically
   blinded. If you keep the `PseudonymMap` alongside the output, recovering the
   original is trivial (that's by design). Against a determined adversary with
   ONLY the anonymized text and no decoder map, the pseudonyms are not
   reversible, but dataset-correlation attacks (e.g. matching `[PERSON_1]` to
   public information) remain a real threat for any pseudonymization scheme.

3. **OCR completeness for scanned PDFs.** Tesseract OCR has well-documented
   limits — small fonts, low-quality scans, handwriting. Sensitive text the
   OCR misreads will not be flagged for redaction. For high-stakes scanned
   documents, post-process the output PDF manually as well.

4. **Resistance to a malicious YAML profile.** Custom entity profiles can
   contain regular expressions. We validate them against the most common
   ReDoS-prone shapes and cap their length, but a profile from an untrusted
   source should be treated as untrusted code — review it before loading it.

5. **Defense against memory-safety bugs in dependencies.** SecurePDF builds on
   PyMuPDF, spaCy, Presidio, PyTesseract, Pillow, and PySide6. Vulnerabilities
   in any of those could affect SecurePDF too. We pin minimum dependency
   versions to CVE-clean baselines and recommend keeping deps updated.

## Threat model summary

| Threat | In scope? | Mitigation |
|---|---|---|
| Sensitive text recoverable from output PDF | **Yes** | True redaction (verified by test) |
| Sensitive text leaked to a cloud LLM during processing | **Yes** | All processing local; Stage 2 talks only to `localhost` |
| Crash / DoS via crafted PDF | Partially | We rely on PyMuPDF's robustness; report any crashes |
| Code execution via crafted PDF | Partially | We rely on PyMuPDF's robustness; report immediately |
| ReDoS via malicious YAML profile | Yes — best effort | Regex length cap + nested-quantifier check |
| Path traversal in batch mode | Yes | Output paths verified via `Path.relative_to(output_root)` |
| User detects nothing because they never reviewed | Out of scope | GUI requires review; CLI documents that auto-accept is risky |
| Determined adversary on the same machine reading loopback traffic to Ollama | Out of scope | Use a firewall; we can't defend against a malicious local process |
| Determined adversary with the PseudonymMap "decoder key" | Out of scope | Don't save the map if you don't need rehydration |

## Hardening checklist for sensitive use

- Run with `INFO`-level logging (the default). `DEBUG` may include page-text
  substrings in log output.
- Don't share `PseudonymMap` decoder files unless you also intend to share the
  pseudonymized text — they together let anyone reverse the redaction.
- For very sensitive documents (medical records, legal discovery), do the
  redaction on an air-gapped machine; you don't need Ollama for Stage 2 to be
  useful, so disable it via `--no-stage2` if you can't trust your network.
- Review every detection in the GUI before clicking Save Outputs — auto-accept
  is the default for UX reasons (over-redaction beats leakage), but you still
  need to scan the list for false negatives.
- Keep dependencies updated. We pin minimum versions; the `pip-audit` tool can
  flag dependencies with known CVEs in your install.
