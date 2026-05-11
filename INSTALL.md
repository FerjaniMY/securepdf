# Installing SecurePDF

SecurePDF runs entirely on your machine. No GPU is required, no cloud calls
are made. The trade-off is a non-trivial first-time install: you'll be pulling
~2 GB total once you've installed everything.

## System requirements

| | Minimum | Recommended |
|---|---|---|
| OS | macOS 11 / Windows 10 / Ubuntu 22.04 | latest |
| RAM | 4 GB | 8 GB+ |
| Disk | 3 GB free | 5 GB+ |
| Python | 3.10 | 3.11 |
| CPU | Any modern x86_64 / arm64 | 4+ cores |
| GPU | not required | — |

## Quick install (developers)

```bash
git clone https://github.com/FerjaniMY/securepdf.git
cd securepdf
pip install -e ".[dev]"
python -m spacy download en_core_web_sm     # ~13 MB
```

That's it for the **Stage 1 (Presidio)** path. Stage 2 (Gemma contextual
detection) requires Ollama:

```bash
# macOS
brew install ollama && brew services start ollama
ollama pull gemma2:2b                        # ~1.6 GB

# Linux
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma2:2b

# Windows
# Download installer from https://ollama.com/download
# Then in PowerShell:
ollama pull gemma2:2b
```

OCR for scanned PDFs needs Tesseract:

```bash
# macOS:    brew install tesseract
# Ubuntu:   sudo apt install tesseract-ocr
# Windows:  https://github.com/UB-Mannheim/tesseract/wiki
```

## Per-OS notes

### Linux (Debian / Ubuntu)

PySide6 needs `libgl1` even in offscreen mode for tests:

```bash
sudo apt install libgl1 libxkbcommon-x11-0
```

### Windows

PySide6 ships its own runtime — no extra system installs needed. If `pip
install pymupdf` complains, you may need the Microsoft C++ Build Tools.

### macOS

On Apple Silicon, use Python 3.11+ via Homebrew or python.org. The
en_core_web_lg spaCy model (which Presidio recommends for production) builds
correctly via `pip install` if your `pip` is recent (24.0+).

## Production install (better PERSON detection)

The default `en_core_web_sm` is small and fast but its NER is mediocre. For
real PII redaction work, install the large model:

```bash
python -m spacy download en_core_web_lg     # ~500 MB
```

Then in Preferences → Settings, switch the spaCy model to `en_core_web_lg`.

## Verifying the install

```bash
# All four CLIs should print help:
securepdf-extract --help
securepdf-detect --help
securepdf-redact --help
securepdf-batch --help
securepdf-gui --help

# Run the test suite:
pytest tests/        # should show ~89 passing
```

## Building installers (advanced)

The `securepdf.spec` PyInstaller config bundles the app into a single folder
that ships without requiring a Python install on the target machine:

```bash
pip install pyinstaller
pyinstaller securepdf.spec --clean --noconfirm
# Output: dist/SecurePDF/
```

On macOS this also produces `dist/SecurePDF.app`. On Windows, a folder with
`SecurePDF.exe`. On Linux, a launcher script + supporting libs.

Note: PyInstaller builds are platform-specific — build on macOS for `.app`,
on Windows for `.exe`, etc. CI artifacts for all three platforms are planned
but not yet wired up.

## Troubleshooting

**`ModuleNotFoundError: No module named 'en_core_web_sm'`**
You skipped `python -m spacy download en_core_web_sm`. Run it.

**`OSError: libGL.so.1: cannot open shared object file`** *(Linux)*
You need `sudo apt install libgl1`.

**`presidio-analyzer` install fails on Apple Silicon**
Upgrade `pip` (`pip install --upgrade pip`) — older pips don't pick up the
arm64 wheels for some Presidio deps.

**GUI starts but "Ollama not detected" banner shows**
That's fine — Stage 2 is optional. Either install Ollama (see above) or
ignore the banner; Stage 1 alone covers most standard PII.

**`securepdf-redact` produces a PDF with my data still extractable**
File an issue with a redacted-but-leaking PDF — that would be a bug. The
test suite has a specific "truly destroys text" assertion to prevent this
regressing.
