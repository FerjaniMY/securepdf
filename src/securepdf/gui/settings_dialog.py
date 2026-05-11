"""Preferences dialog for detector configuration.

Knobs exposed:
  - Use Stage 2 (Gemma contextual pass)
  - Sensitivity threshold (Presidio score floor, 0.0–1.0)
  - Ollama host (default http://localhost:11434)
  - spaCy model name (en_core_web_sm / en_core_web_lg)

These map 1:1 to `detect()` keyword arguments. The dialog is dumb: it reads
from / writes to a plain dataclass; the MainWindow persists it via `QSettings`.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)


@dataclass
class DetectorSettings:
    """In-memory settings. Persisted by the MainWindow via `QSettings`."""

    use_stage2: bool = True
    score_threshold: float = 0.4
    ollama_host: str = "http://localhost:11434"
    spacy_model: str = "en_core_web_sm"


class SettingsDialog(QDialog):
    """Modal preferences dialog."""

    def __init__(self, current: DetectorSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")

        self._stage2 = QCheckBox("Use Stage 2 — Gemma contextual detection (requires Ollama)")
        self._stage2.setChecked(current.use_stage2)

        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.0, 1.0)
        self._threshold.setSingleStep(0.05)
        self._threshold.setDecimals(2)
        self._threshold.setValue(current.score_threshold)
        self._threshold.setToolTip(
            "Presidio matches below this confidence score are dropped. Higher = "
            "fewer false positives, lower = more recall."
        )

        self._ollama_host = QLineEdit(current.ollama_host)
        self._ollama_host.setPlaceholderText("http://localhost:11434")

        self._spacy = QComboBox()
        self._spacy.addItems(["en_core_web_sm", "en_core_web_lg"])
        self._spacy.setCurrentText(current.spacy_model)
        self._spacy.setToolTip(
            "Small is fast (~12 MB) but less accurate on names/places. "
            "Large (~500 MB) for production use."
        )

        form = QFormLayout()
        form.addRow(self._stage2)
        form.addRow("Sensitivity threshold:", self._threshold)
        form.addRow("Ollama host:", self._ollama_host)
        form.addRow("spaCy model:", self._spacy)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> DetectorSettings:
        """Read the dialog's current state back as a `DetectorSettings`."""
        return DetectorSettings(
            use_stage2=self._stage2.isChecked(),
            score_threshold=float(self._threshold.value()),
            ollama_host=self._ollama_host.text().strip() or "http://localhost:11434",
            spacy_model=self._spacy.currentText(),
        )
