# PyInstaller spec for SecurePDF.
#
# Run from the repo root:
#     pyinstaller securepdf.spec --clean --noconfirm
#
# Produces a `dist/SecurePDF/` folder (one-folder mode) containing the app,
# the Python interpreter, and every dependency bundled. On macOS this becomes
# `SecurePDF.app`; on Windows, a folder with `SecurePDF.exe`; on Linux, a
# launcher script + supporting libs.
#
# One-folder mode (not one-file) is intentional:
#   - First-launch latency is much better (no extract-to-tempdir step).
#   - The spaCy model is ~50 MB; one-file would re-extract it every cold start.
#   - Antivirus tools are friendlier to folder builds than to giant .exe blobs.
#
# Bundled in the build:
#   - en_core_web_sm spaCy model (must be installed in the build env)
#   - Presidio analyzer recognizer registry data files
#   - PyMuPDF native binaries (handled automatically)
#   - PySide6 + Qt6 libs (handled automatically)
#
# Not bundled (user installs separately):
#   - Tesseract OCR  — system package; rarely needed for digitally-generated PDFs
#   - Ollama         — separate installer; Stage 2 is optional anyway

# ruff: noqa
# pylint: skip-file
# This is a PyInstaller spec, not a regular Python module — it's executed by
# PyInstaller with a custom global scope. Linters can't follow that.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------
# spaCy ships its model as a Python package — when installed it lives in
# site-packages/en_core_web_sm/. collect_data_files() picks it up automatically.
datas = []
datas += collect_data_files("en_core_web_sm")
datas += collect_data_files("presidio_analyzer")
datas += collect_data_files("spacy")

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
# Presidio loads its recognizers via importlib at runtime — PyInstaller can't
# follow that statically, so we walk the package and add every submodule.
hiddenimports = []
hiddenimports += collect_submodules("presidio_analyzer.predefined_recognizers")
hiddenimports += collect_submodules("securepdf")
# spaCy's pipeline factories are similarly dynamic.
hiddenimports += [
    "spacy.pipeline.morphologizer",
    "spacy.pipeline.lemmatizer",
    "spacy.pipeline.tagger",
    "spacy.pipeline.attributeruler",
    "spacy.pipeline.ner",
    "spacy.pipeline.tok2vec",
    "spacy.pipeline.dep_parser",
    "blis",
    "thinc",
    "srsly.msgpack.util",
]

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
block_cipher = None

a = Analysis(
    ["src/securepdf/gui/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # We don't need Jupyter / IPython / Tk in the shipped app.
        "IPython",
        "jupyter",
        "tkinter",
        "test",
        "tests",
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SecurePDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX-compressed exes trip many antivirus heuristics
    console=False,       # windowed app — no terminal popup
    disable_windowed_traceback=False,
    target_arch=None,    # let PyInstaller pick (x86_64 / arm64)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SecurePDF",
)

# On macOS, wrap the COLLECT into a .app bundle.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SecurePDF.app",
        bundle_identifier="com.securepdf.app",
        info_plist={
            "CFBundleShortVersionString": "0.5.0",
            "CFBundleVersion": "0.5.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
        },
    )
