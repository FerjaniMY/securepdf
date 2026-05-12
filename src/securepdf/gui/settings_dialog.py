"""Preferences dialog for detector configuration.

Knobs exposed:
  - Use Stage 2 (Gemma contextual pass)
  - Sensitivity threshold (Presidio score floor, 0.0–1.0)
  - Ollama host (default http://localhost:11434)
  - spaCy model name (en_core_web_sm / en_core_web_lg)

These map 1:1 to `detect()` keyword arguments. The dialog is dumb: it reads
from / writes to a plain dataclass; the MainWindow persists it via `QSettings`.

The custom-entity profile YAML is also held on `DetectorSettings` but is
edited in a separate dialog (`entity_editor.py`); this dialog never touches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings
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


# QSettings keys — kept here so the dialog and MainWindow agree on the names.
_KEY_USE_STAGE2 = "detector/use_stage2"
_KEY_SCORE_THRESHOLD = "detector/score_threshold"
_KEY_OLLAMA_HOST = "detector/ollama_host"
_KEY_SPACY_MODEL = "detector/spacy_model"
_KEY_PROFILE_YAML = "detector/profile_yaml"


@dataclass
class DetectorSettings:
    """In-memory settings. Persisted by the MainWindow via `QSettings`."""

    use_stage2: bool = True
    score_threshold: float = 0.4
    ollama_host: str = "http://localhost:11434"
    spacy_model: str = "en_core_web_sm"
    # The YAML body of the currently-applied custom-entity profile. Empty string
    # means "no custom profile" — the headless pipeline accepts None for that.
    profile_yaml: str = field(default="")

    # -------------------------------------------------------------------
    # QSettings round-trip
    # -------------------------------------------------------------------

    def save_to(self, settings: QSettings) -> None:
        settings.setValue(_KEY_USE_STAGE2, self.use_stage2)
        settings.setValue(_KEY_SCORE_THRESHOLD, self.score_threshold)
        settings.setValue(_KEY_OLLAMA_HOST, self.ollama_host)
        settings.setValue(_KEY_SPACY_MODEL, self.spacy_model)
        settings.setValue(_KEY_PROFILE_YAML, self.profile_yaml)

    @classmethod
    def load_from(cls, settings: QSettings) -> "DetectorSettings":
        # QSettings.value returns the raw Qt type; coerce explicitly to avoid
        # surprises like booleans coming back as the strings "true"/"false" on
        # some platforms (ini backend).
        def _as_bool(v, default: bool) -> bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("1", "true", "yes")
            return default

        return cls(
            use_stage2=_as_bool(settings.value(_KEY_USE_STAGE2, True), True),
            score_threshold=float(settings.value(_KEY_SCORE_THRESHOLD, 0.4)),
            ollama_host=str(settings.value(_KEY_OLLAMA_HOST, "http://localhost:11434")),
            spacy_model=str(settings.value(_KEY_SPACY_MODEL, "en_core_web_sm")),
            profile_yaml=str(settings.value(_KEY_PROFILE_YAML, "") or ""),
        )


class SettingsDialog(QDialog):
    """Modal preferences dialog."""

    def __init__(self, current: DetectorSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self._current = current

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
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> DetectorSettings:
        """Read the dialog's current state back as a `DetectorSettings`.

        Preserves `profile_yaml` from the input settings — the entity profile
        is edited in a separate dialog.
        """
        return DetectorSettings(
            use_stage2=self._stage2.isChecked(),
            score_threshold=float(self._threshold.value()),
            ollama_host=self._ollama_host.text().strip() or "http://localhost:11434",
            spacy_model=self._spacy.currentText(),
            profile_yaml=self._current.profile_yaml,
        )
