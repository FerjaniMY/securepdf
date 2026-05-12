"""Custom entity profile editor — structured editing of YAML profiles.

Before this dialog existed, users had to open ``entities.yml`` in a text editor.
Now they can:

  - Add / remove / edit regex patterns in a table
  - Manage keyword groups with their term lists
  - Add / remove / edit natural-language descriptions for the Gemma stage
  - Load and save YAML profile files via the toolbar
  - Validate at Apply time — invalid regexes are caught with a clear inline
    message before the profile is handed to Presidio

The dialog stores state internally as parsed data structures, not raw YAML.
YAML is just the on-disk format we round-trip through.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from securepdf.detection.custom_entities import (
    MAX_REGEX_LENGTH,
    UnsafeRegexError,
    _validate_regex,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Patterns tab — name / regex / score
# ---------------------------------------------------------------------------


class _PatternsTab(QWidget):
    """Table editor for regex patterns. Each row is one PatternRecognizer."""

    PATTERN_COLS = ["Name", "Regex", "Score"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._table = QTableWidget(0, len(self.PATTERN_COLS))
        self._table.setHorizontalHeaderLabels(self.PATTERN_COLS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        add_btn = QPushButton("Add pattern")
        remove_btn = QPushButton("Remove selected")
        remove_btn.setProperty("destructive", True)
        add_btn.clicked.connect(self._add_row)
        remove_btn.clicked.connect(self._remove_selected)

        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)

        help_label = QLabel(
            f"Each pattern compiles to a Presidio `PatternRecognizer`. Regex length "
            f"is capped at {MAX_REGEX_LENGTH} characters and nested unbounded "
            f"quantifiers (e.g. `(a+)+`) are rejected at Apply time."
        )
        help_label.setProperty("role", "subtitle")
        help_label.style().unpolish(help_label)
        help_label.style().polish(help_label)
        help_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(btn_row)
        layout.addWidget(self._table, 1)
        layout.addWidget(help_label)

    def _add_row(self) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem("new_pattern"))
        self._table.setItem(r, 1, QTableWidgetItem(r"\bPROJECT_[A-Z]+\b"))
        self._table.setItem(r, 2, QTableWidgetItem("0.85"))
        self._table.selectRow(r)
        self._table.editItem(self._table.item(r, 0))

    def _remove_selected(self) -> None:
        selected = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for r in selected:
            self._table.removeRow(r)

    # ----- Data round-trip -----

    def load(self, patterns: list[dict]) -> None:
        self._table.setRowCount(0)
        for entry in patterns:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(str(entry.get("name", ""))))
            self._table.setItem(r, 1, QTableWidgetItem(str(entry.get("regex", ""))))
            self._table.setItem(r, 2, QTableWidgetItem(str(entry.get("score", 0.7))))

    def dump(self) -> list[dict]:
        """Snapshot the table state as a list of dict entries (the patterns: section).

        Raises ValueError with row-context if a regex fails validation or a score
        isn't parseable.
        """
        out: list[dict] = []
        for r in range(self._table.rowCount()):
            name = self._cell(r, 0).strip()
            regex = self._cell(r, 1)
            score_text = self._cell(r, 2).strip() or "0.7"
            if not name:
                raise ValueError(f"Patterns row {r + 1}: name is empty")
            if not regex:
                raise ValueError(f"Patterns row {r + 1}: regex is empty")
            try:
                _validate_regex(regex)
            except UnsafeRegexError as e:
                raise ValueError(f"Patterns row {r + 1} ({name!r}): {e}") from e
            try:
                score = float(score_text)
            except ValueError as e:
                raise ValueError(
                    f"Patterns row {r + 1} ({name!r}): score must be a number, got {score_text!r}"
                ) from e
            out.append({"name": name, "regex": regex, "score": score})
        return out

    def _cell(self, row: int, col: int) -> str:
        item = self._table.item(row, col)
        return item.text() if item else ""


# ---------------------------------------------------------------------------
# Keywords tab — list of groups; each group has its own term list
# ---------------------------------------------------------------------------


class _KeywordsTab(QWidget):
    """Split-pane editor for keyword groups."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # Left: list of groups
        self._groups = QListWidget()
        # Each item carries its term-list payload via Qt.UserRole.
        self._groups.currentItemChanged.connect(self._on_group_changed)

        add_group_btn = QPushButton("Add group")
        remove_group_btn = QPushButton("Remove group")
        remove_group_btn.setProperty("destructive", True)
        add_group_btn.clicked.connect(self._add_group)
        remove_group_btn.clicked.connect(self._remove_group)

        left_btn_row = QHBoxLayout()
        left_btn_row.addWidget(add_group_btn)
        left_btn_row.addWidget(remove_group_btn)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(left_btn_row)
        left_layout.addWidget(self._groups, 1)

        # Right: terms for the selected group
        self._terms = QListWidget()
        self._terms.itemChanged.connect(self._on_term_edited)

        add_term_btn = QPushButton("Add term")
        remove_term_btn = QPushButton("Remove term")
        remove_term_btn.setProperty("destructive", True)
        add_term_btn.clicked.connect(self._add_term)
        remove_term_btn.clicked.connect(self._remove_term)

        right_btn_row = QHBoxLayout()
        right_btn_row.addWidget(add_term_btn)
        right_btn_row.addWidget(remove_term_btn)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(right_btn_row)
        right_layout.addWidget(self._terms, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([180, 320])

        help_label = QLabel(
            "Each group becomes a single Presidio recognizer that matches any of "
            "its terms as a whole word. Useful for restricted client names, internal "
            "codenames, or any closed-vocabulary entity."
        )
        help_label.setProperty("role", "subtitle")
        help_label.style().unpolish(help_label)
        help_label.style().polish(help_label)
        help_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(help_label)

    def _add_group(self) -> None:
        name, ok = QInputDialog.getText(self, "New keyword group", "Group name:")
        if not ok or not name.strip():
            return
        item = QListWidgetItem(name.strip())
        item.setData(Qt.ItemDataRole.UserRole, [])
        self._groups.addItem(item)
        self._groups.setCurrentItem(item)

    def _remove_group(self) -> None:
        row = self._groups.currentRow()
        if row >= 0:
            self._groups.takeItem(row)

    def _add_term(self) -> None:
        if self._groups.currentItem() is None:
            return
        term, ok = QInputDialog.getText(self, "New term", "Term:")
        if not ok or not term.strip():
            return
        item = QListWidgetItem(term.strip())
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._terms.addItem(item)
        self._persist_terms_for_current_group()

    def _remove_term(self) -> None:
        row = self._terms.currentRow()
        if row >= 0:
            self._terms.takeItem(row)
            self._persist_terms_for_current_group()

    def _on_group_changed(self, current: QListWidgetItem | None, _previous) -> None:
        self._terms.blockSignals(True)
        self._terms.clear()
        if current is not None:
            for term in current.data(Qt.ItemDataRole.UserRole) or []:
                item = QListWidgetItem(term)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self._terms.addItem(item)
        self._terms.blockSignals(False)

    def _on_term_edited(self, _item: QListWidgetItem) -> None:
        self._persist_terms_for_current_group()

    def _persist_terms_for_current_group(self) -> None:
        group = self._groups.currentItem()
        if group is None:
            return
        terms = [self._terms.item(i).text() for i in range(self._terms.count())]
        group.setData(Qt.ItemDataRole.UserRole, terms)

    # ----- Data round-trip -----

    def load(self, keywords: list[dict]) -> None:
        self._groups.clear()
        self._terms.clear()
        for entry in keywords:
            item = QListWidgetItem(str(entry.get("name", "")))
            item.setData(Qt.ItemDataRole.UserRole, list(entry.get("terms", [])))
            self._groups.addItem(item)

    def dump(self) -> list[dict]:
        out: list[dict] = []
        for i in range(self._groups.count()):
            group = self._groups.item(i)
            name = group.text().strip()
            terms = list(group.data(Qt.ItemDataRole.UserRole) or [])
            terms = [t.strip() for t in terms if t.strip()]
            if not name:
                raise ValueError(f"Keywords group {i + 1}: name is empty")
            if not terms:
                raise ValueError(f"Keywords group {name!r}: needs at least one term")
            out.append({"name": name, "terms": terms})
        return out


# ---------------------------------------------------------------------------
# Descriptions tab — natural language strings handed to the Gemma stage
# ---------------------------------------------------------------------------


class _DescriptionsTab(QWidget):
    """Simple editable list of natural-language entity descriptions."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._list = QListWidget()

        add_btn = QPushButton("Add description")
        edit_btn = QPushButton("Edit selected")
        remove_btn = QPushButton("Remove")
        remove_btn.setProperty("destructive", True)
        add_btn.clicked.connect(self._add)
        edit_btn.clicked.connect(self._edit)
        remove_btn.clicked.connect(self._remove)

        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)

        help_label = QLabel(
            "Plain-English descriptions of custom entities are handed to the Stage 2 "
            "Gemma 2 2B model. Use for entity types that are easier to describe than "
            "to regex — e.g. \"internal codenames like PROJECT_PHOENIX\" or "
            "\"names of clients on our restricted partner list\"."
        )
        help_label.setProperty("role", "subtitle")
        help_label.style().unpolish(help_label)
        help_label.style().polish(help_label)
        help_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(btn_row)
        layout.addWidget(self._list, 1)
        layout.addWidget(help_label)

    def _add(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self, "New description", "Describe an entity to detect:"
        )
        if not ok or not text.strip():
            return
        self._list.addItem(text.strip())

    def _edit(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Edit description", "Description:", item.text()
        )
        if ok:
            item.setText(text.strip())

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)

    # ----- Data round-trip -----

    def load(self, descriptions: list[str]) -> None:
        self._list.clear()
        for d in descriptions:
            self._list.addItem(str(d))

    def dump(self) -> list[str]:
        return [
            self._list.item(i).text().strip()
            for i in range(self._list.count())
            if self._list.item(i).text().strip()
        ]


# ---------------------------------------------------------------------------
# Top-level dialog
# ---------------------------------------------------------------------------


class EntityEditorDialog(QDialog):
    """Modal editor for a YAML custom-entity profile.

    Signals
    -------
    profile_applied(str):
        Emitted with the serialized YAML when the user clicks Apply and the
        profile validates successfully. Listeners can pass this to
        `parse_profile()` to materialize a `CustomEntityProfile`.
    """

    profile_applied = Signal(str)

    def __init__(self, initial_yaml: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Custom entity profile")
        self.setMinimumSize(720, 520)

        # ---- Header ----
        title = QLabel("Custom entity profile")
        title.setProperty("role", "title")
        title.style().unpolish(title)
        title.style().polish(title)

        subtitle = QLabel(
            "Define regex patterns, keyword lists, and natural-language descriptions "
            "that extend SecurePDF's detection. The profile loads at Apply time."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.style().unpolish(subtitle)
        subtitle.style().polish(subtitle)
        subtitle.setWordWrap(True)

        # ---- Tabs ----
        self.patterns_tab = _PatternsTab(self)
        self.keywords_tab = _KeywordsTab(self)
        self.descriptions_tab = _DescriptionsTab(self)

        self._tabs = QTabWidget()
        self._tabs.addTab(self.patterns_tab, "Patterns")
        self._tabs.addTab(self.keywords_tab, "Keywords")
        self._tabs.addTab(self.descriptions_tab, "Descriptions")

        # ---- File toolbar (Load, Save As, Reset) ----
        load_btn = QPushButton("Load YAML…")
        save_btn = QPushButton("Save As YAML…")
        reset_btn = QPushButton("Reset")
        reset_btn.setProperty("destructive", True)
        load_btn.clicked.connect(self._on_load)
        save_btn.clicked.connect(self._on_save_as)
        reset_btn.clicked.connect(self._on_reset)

        file_row = QHBoxLayout()
        file_row.addWidget(load_btn)
        file_row.addWidget(save_btn)
        file_row.addStretch(1)
        file_row.addWidget(reset_btn)

        # ---- Bottom action row ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply
        )
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply_btn.setProperty("primary", True)
        apply_btn.setText("Apply profile")
        apply_btn.clicked.connect(self._on_apply)
        buttons.rejected.connect(self.reject)

        # ---- Layout ----
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(file_row)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(buttons)

        # ---- Initial state ----
        if initial_yaml.strip():
            self._populate_from_yaml(initial_yaml)

    # -------------------------------------------------------------------
    # Data flow
    # -------------------------------------------------------------------

    def current_yaml(self) -> str:
        """Render the editor state as a YAML string. Raises ValueError on invalid input."""
        data: dict = {}
        patterns = self.patterns_tab.dump()
        if patterns:
            data["patterns"] = patterns
        keywords = self.keywords_tab.dump()
        if keywords:
            data["keywords"] = keywords
        descriptions = self.descriptions_tab.dump()
        if descriptions:
            data["descriptions"] = descriptions
        if not data:
            return ""
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def _populate_from_yaml(self, yaml_text: str) -> None:
        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError as e:
            QMessageBox.critical(self, "Invalid YAML", f"Failed to parse profile YAML:\n{e}")
            return
        self.patterns_tab.load(data.get("patterns", []) or [])
        self.keywords_tab.load(data.get("keywords", []) or [])
        self.descriptions_tab.load(data.get("descriptions", []) or [])

    # -------------------------------------------------------------------
    # Slots
    # -------------------------------------------------------------------

    def _on_load(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Load profile YAML", "", "YAML (*.yml *.yaml);;All files (*)"
        )
        if not path_str:
            return
        try:
            text = Path(path_str).read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self._populate_from_yaml(text)

    def _on_save_as(self) -> None:
        try:
            yaml_text = self.current_yaml()
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save profile YAML", "entities.yml", "YAML (*.yml *.yaml)"
        )
        if not path_str:
            return
        Path(path_str).write_text(yaml_text, encoding="utf-8")

    def _on_reset(self) -> None:
        self.patterns_tab.load([])
        self.keywords_tab.load([])
        self.descriptions_tab.load([])

    def _on_apply(self) -> None:
        try:
            yaml_text = self.current_yaml()
        except ValueError as e:
            QMessageBox.warning(self, "Cannot apply", str(e))
            return
        self.profile_applied.emit(yaml_text)
        self.accept()
