"""Unified Save Outputs dialog — one window for all three outputs.

Replaces the previous two-QFileDialog flow. Now: a single dialog with a
checkbox + path picker per output type (redacted PDF, anonymized text,
pseudonym map JSON). Clearer UX, fewer clicks.

`SaveOutputsResult.cancelled` tells the caller whether the user accepted or
cancelled — semantically cleaner than `QDialog.exec()` for callers that just
want "did they pick something to save".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class SaveOutputsResult:
    """What the user chose. Inspect after `dialog.exec()` returns."""

    cancelled: bool = True
    save_pdf: bool = False
    pdf_path: Path | None = None
    save_text: bool = False
    text_path: Path | None = None
    save_map: bool = False
    map_path: Path | None = None

    @property
    def has_anything(self) -> bool:
        return self.save_pdf or self.save_text or self.save_map


class _OutputRow(QWidget):
    """One row in the dialog: checkbox + path field + Browse button.

    Encapsulates the enable/disable interaction so the parent dialog doesn't
    need to track three sets of widgets manually.
    """

    def __init__(
        self,
        label: str,
        default_path: Path,
        file_filter: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._file_filter = file_filter
        self._default_path = default_path

        self.checkbox = QCheckBox(label)
        self.checkbox.setChecked(True)
        self.checkbox.toggled.connect(self._on_toggled)

        self.path_edit = QLineEdit(str(default_path))
        self.path_edit.setMinimumWidth(360)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._on_browse)
        self.browse_btn.setMaximumWidth(90)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.checkbox)
        row.addStretch(1)
        # Make the row align nicely: fixed-width label area, then expanding path
        # under it (in a vertical sub-layout so the path doesn't squeeze tight
        # against the checkbox).
        sub = QVBoxLayout()
        sub.setContentsMargins(0, 0, 0, 0)
        sub.setSpacing(4)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_btn)
        sub.addLayout(path_row)
        row.addLayout(sub, 4)

    def is_enabled(self) -> bool:
        return self.checkbox.isChecked()

    def path(self) -> Path:
        return Path(self.path_edit.text().strip()) if self.path_edit.text().strip() else self._default_path

    def _on_toggled(self, checked: bool) -> None:
        self.path_edit.setEnabled(checked)
        self.browse_btn.setEnabled(checked)

    def _on_browse(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save As", str(self.path()), self._file_filter
        )
        if chosen:
            self.path_edit.setText(chosen)


class SaveOutputsDialog(QDialog):
    """Unified Save Outputs dialog.

    Constructor takes the input PDF path so output defaults are placed next to it
    (e.g. ``report.pdf`` → ``report.redacted.pdf``).
    """

    def __init__(
        self,
        input_pdf: Path,
        *,
        has_pseudonym_map: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Save outputs")
        self.setMinimumWidth(540)

        # ---- Header ----
        title = QLabel("Save outputs")
        title.setProperty("role", "title")
        title.style().unpolish(title)
        title.style().polish(title)

        subtitle = QLabel(
            "Choose which artifacts to save. The redacted PDF preserves the original "
            "layout with sensitive spans physically removed; the anonymized text is "
            "ready to paste into ChatGPT or Claude."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.style().unpolish(subtitle)
        subtitle.style().polish(subtitle)
        subtitle.setWordWrap(True)

        # ---- Rows ----
        default_pdf = input_pdf.with_name(input_pdf.stem + ".redacted.pdf")
        default_txt = input_pdf.with_name(input_pdf.stem + ".anonymized.txt")
        default_map = input_pdf.with_name(input_pdf.stem + ".pseudonyms.json")

        self.pdf_row = _OutputRow(
            "Redacted PDF — same layout, text destroyed",
            default_pdf,
            "PDF (*.pdf)",
            parent=self,
        )
        self.text_row = _OutputRow(
            "Anonymized text — pseudonyms like [PERSON_1]",
            default_txt,
            "Text (*.txt)",
            parent=self,
        )
        self.map_row = _OutputRow(
            "Pseudonym map JSON — decoder key for rehydration",
            default_map,
            "JSON (*.json)",
            parent=self,
        )
        # Pseudonym map needs anonymized text to be meaningful; default off if
        # the caller signaled no map is available yet (e.g. all detections rejected).
        if not has_pseudonym_map:
            self.map_row.checkbox.setChecked(False)
            self.map_row.checkbox.setEnabled(False)
        else:
            # Saving the decoder key is optional — opt-in by default off, since
            # it lets anyone reverse the anonymization if they get both files.
            self.map_row.checkbox.setChecked(False)
            self.map_row.path_edit.setEnabled(False)
            self.map_row.browse_btn.setEnabled(False)

        # ---- Separator + warning ----
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e8e6df;")

        warning = QLabel(
            "<b>About the pseudonym map.</b> If you keep this file alongside the "
            "anonymized text, anyone with both can recover the original. Leave it "
            "unchecked unless you specifically need to rehydrate the document later."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background-color: #fff4d6; border-left: 4px solid #e0b040; "
            "padding: 10px 12px; color: #5c4408; border-radius: 3px;"
        )

        # ---- Action buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        self._save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        self._save_btn.setText("Save outputs")
        self._save_btn.setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Re-evaluate Save button state whenever any checkbox changes.
        for row in (self.pdf_row, self.text_row, self.map_row):
            row.checkbox.toggled.connect(self._update_save_state)
        self._update_save_state()

        # ---- Layout ----
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        layout.addWidget(self.pdf_row)
        layout.addWidget(self.text_row)
        layout.addWidget(self.map_row)
        layout.addWidget(sep)
        layout.addWidget(warning)
        layout.addWidget(buttons)

    # -------------------------------------------------------------------
    # Result extraction
    # -------------------------------------------------------------------

    def result_data(self) -> SaveOutputsResult:
        """Snapshot the dialog state — call after `exec()`."""
        return SaveOutputsResult(
            cancelled=False,
            save_pdf=self.pdf_row.is_enabled(),
            pdf_path=self.pdf_row.path() if self.pdf_row.is_enabled() else None,
            save_text=self.text_row.is_enabled(),
            text_path=self.text_row.path() if self.text_row.is_enabled() else None,
            save_map=self.map_row.is_enabled(),
            map_path=self.map_row.path() if self.map_row.is_enabled() else None,
        )

    def _update_save_state(self) -> None:
        """Disable Save when nothing's selected."""
        any_selected = (
            self.pdf_row.checkbox.isChecked()
            or self.text_row.checkbox.isChecked()
            or self.map_row.checkbox.isChecked()
        )
        self._save_btn.setEnabled(any_selected)


def write_pseudonym_map(path: Path, mapping: dict[str, str]) -> None:
    """Persist a `PseudonymMap.as_key_dict()` to disk as pretty JSON.

    Kept in this module (not `redaction/`) because it's a GUI-specific export —
    the headless pipeline doesn't need it. Stored as JSON so users can `cat`
    it without parsing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
