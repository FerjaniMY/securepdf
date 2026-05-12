"""About dialog — version, license, links, bundled dependencies.

Standard for any shipped desktop app. Signals project maturity ("real app, not
a side hack") and gives users a single place to confirm what version they're
running before filing an issue.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from securepdf import __version__


# Kept in sync with pyproject.toml — these are the runtime dependencies we
# bundle in a PyInstaller build. The About dialog surfaces them so users have
# a clear answer to "what does this app actually run on my machine?".
BUNDLED_DEPS = [
    ("PyMuPDF (fitz)", "PDF I/O + true redaction primitives", "https://pymupdf.readthedocs.io/"),
    ("Microsoft Presidio", "Stage 1 PII detection engine", "https://microsoft.github.io/presidio/"),
    ("spaCy", "NER backbone used by Presidio", "https://spacy.io/"),
    ("PyTesseract", "OCR wrapper around the Tesseract binary", "https://github.com/madmaze/pytesseract"),
    ("Pillow", "Image handling for OCR page rendering", "https://python-pillow.org/"),
    ("Ollama", "Local LLM runtime for Stage 2 (Gemma 2 2B); optional", "https://ollama.com/"),
    ("PySide6", "Qt6 desktop UI framework", "https://www.qt.io/qt-for-python"),
]


class AboutDialog(QDialog):
    """Modal About panel — version, license, links, bundled deps."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("About SecurePDF")
        self.setMinimumSize(560, 540)

        # ---- Hero: app name + version ----
        name = QLabel("SecurePDF")
        name.setProperty("role", "title")
        name.style().unpolish(name)
        name.style().polish(name)

        version = QLabel(f"Version {__version__}  ·  MIT License")
        version.setProperty("role", "subtitle")
        version.style().unpolish(version)
        version.style().polish(version)

        tagline = QLabel(
            "Local AI PDF redaction & anonymization. Strip sensitive data "
            "from PDFs on your machine before sending them to cloud LLMs."
        )
        tagline.setWordWrap(True)

        # ---- Action row: open repo / security policy / install docs ----
        repo_btn = QPushButton("View on GitHub")
        repo_btn.setProperty("primary", True)
        repo_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/FerjaniMY/securepdf"))
        )
        security_btn = QPushButton("Security policy")
        security_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/FerjaniMY/securepdf/blob/main/SECURITY.md")
            )
        )
        install_btn = QPushButton("Install guide")
        install_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/FerjaniMY/securepdf/blob/main/INSTALL.md")
            )
        )

        action_row = QHBoxLayout()
        action_row.addWidget(repo_btn)
        action_row.addWidget(security_btn)
        action_row.addWidget(install_btn)
        action_row.addStretch(1)

        # ---- Separator ----
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e8e6df;")

        # ---- Bundled deps list ----
        deps_header = QLabel("Built on")
        deps_header.setProperty("role", "caption")
        deps_header.style().unpolish(deps_header)
        deps_header.style().polish(deps_header)

        deps_widget = QWidget()
        deps_layout = QVBoxLayout(deps_widget)
        deps_layout.setContentsMargins(0, 0, 0, 0)
        deps_layout.setSpacing(8)
        for dep_name, dep_desc, dep_url in BUNDLED_DEPS:
            row = self._make_dep_row(dep_name, dep_desc, dep_url)
            deps_layout.addWidget(row)
        deps_layout.addStretch(1)

        deps_scroll = QScrollArea()
        deps_scroll.setWidget(deps_widget)
        deps_scroll.setWidgetResizable(True)
        deps_scroll.setFrameShape(QFrame.Shape.NoFrame)
        deps_scroll.setMinimumHeight(180)

        # ---- Close button ----
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        # ---- Layout ----
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)
        root.addWidget(name)
        root.addWidget(version)
        root.addWidget(tagline)
        root.addLayout(action_row)
        root.addWidget(sep)
        root.addWidget(deps_header)
        root.addWidget(deps_scroll, 1)
        root.addWidget(buttons)

    def _make_dep_row(self, name: str, desc: str, url: str) -> QWidget:
        """Build a single row in the deps list."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        name_label = QLabel(f"<b>{name}</b>")
        name_label.setMinimumWidth(160)

        desc_label = QLabel(desc)
        desc_label.setStyleSheet("color: #6a6a60;")
        desc_label.setWordWrap(True)

        link_btn = QPushButton("Site")
        link_btn.setMaximumWidth(60)
        link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))

        layout.addWidget(name_label)
        layout.addWidget(desc_label, 1)
        layout.addWidget(link_btn)
        return row
