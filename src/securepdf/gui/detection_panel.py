"""Detection review panel — list of all detections with accept/reject checkboxes.

Layout:

  ┌──────────────────────────────────────────────────────┐
  │ [Accept all]  [Reject all]   12 of 24 will redact    │
  ├──────────────────────────────────────────────────────┤
  │ Type: [all v]  Source: [all v]  Min conf: [0.0]  🔍  │  ← filter row (v0.6)
  ├──────────────────────────────────────────────────────┤
  │ ☑ Page 1 │ PERSON       │ "Jane Doe"      │ 0.85 │ … │
  │ ☐ Page 1 │ DATE_TIME    │ "1985-03-22"    │ 0.85 │ … │
  │ ☑ Page 2 │ EMAIL_ADDRES │ "j.doe@…"       │ 1.00 │ … │
  │ ...                                                  │
  └──────────────────────────────────────────────────────┘

The panel is dumb: it renders state from a `DocumentSession` and emits a signal
when the user toggles a row. The MainWindow listens, mutates the session, and
asks the viewer to repaint.

The filter row is purely view-state — it hides rows but doesn't mutate
`session.decisions`. Hidden rows are still part of `accepted_detections()`.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from securepdf.gui.document_session import Decision, DocumentSession


# Columns in display order. Indices used in setCheckState etc.
COL_ACCEPT, COL_PAGE, COL_TYPE, COL_TEXT, COL_CONF, COL_SOURCE = range(6)
COLUMN_LABELS = ["", "Page", "Type", "Text", "Conf", "Source"]


class DetectionPanel(QWidget):
    """Reactive widget around a `DocumentSession`."""

    # Emitted whenever any row's accept/reject state changes (single, accept-all,
    # or reject-all). The MainWindow re-paints the viewer and updates the count.
    decisions_changed = Signal()
    # Emitted when the user clicks a row, so the viewer can jump to that page.
    row_activated = Signal(int)  # global detection index

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._session: DocumentSession | None = None
        self._suppress_change_signal = False  # while we're bulk-populating

        # --- Toolbar row ---
        self._accept_all_btn = QPushButton("Accept all")
        self._reject_all_btn = QPushButton("Reject all")
        self._summary_label = QLabel("No document loaded")
        self._summary_label.setProperty("role", "subtitle")
        self._summary_label.style().unpolish(self._summary_label)
        self._summary_label.style().polish(self._summary_label)
        self._summary_label.setStyleSheet("padding-left: 12px;")

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._accept_all_btn)
        toolbar.addWidget(self._reject_all_btn)
        toolbar.addWidget(self._summary_label, 1)

        # --- Filter row (new in v1.0) ---
        self._text_filter = QLineEdit()
        self._text_filter.setPlaceholderText("Filter text…")
        self._text_filter.setMaximumWidth(220)

        self._type_filter = QComboBox()
        self._type_filter.addItem("All types", "")
        self._type_filter.setMinimumWidth(160)

        self._source_filter = QComboBox()
        self._source_filter.addItem("All sources", "")
        for source in ("presidio", "gemma", "regex", "custom", "merged"):
            self._source_filter.addItem(source, source)

        self._conf_filter = QDoubleSpinBox()
        self._conf_filter.setRange(0.0, 1.0)
        self._conf_filter.setSingleStep(0.05)
        self._conf_filter.setDecimals(2)
        self._conf_filter.setValue(0.0)
        self._conf_filter.setSuffix("  conf")
        self._conf_filter.setMaximumWidth(110)

        self._visible_count_label = QLabel("")
        self._visible_count_label.setProperty("role", "caption")
        self._visible_count_label.style().unpolish(self._visible_count_label)
        self._visible_count_label.style().polish(self._visible_count_label)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 4, 0, 0)
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Filter:"))
        filter_row.addWidget(self._text_filter, 1)
        filter_row.addWidget(self._type_filter)
        filter_row.addWidget(self._source_filter)
        filter_row.addWidget(self._conf_filter)
        filter_row.addWidget(self._visible_count_label)

        # --- Tree ---
        self._tree = QTreeWidget()
        self._tree.setColumnCount(len(COLUMN_LABELS))
        self._tree.setHeaderLabels(COLUMN_LABELS)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Sane initial column widths.
        header = self._tree.header()
        header.setSectionResizeMode(COL_ACCEPT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_PAGE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_CONF, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.ResizeToContents)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addLayout(filter_row)
        layout.addWidget(self._tree, 1)

        # --- Signals ---
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._accept_all_btn.clicked.connect(self._on_accept_all)
        self._reject_all_btn.clicked.connect(self._on_reject_all)
        # Filters all converge on a single re-apply method.
        self._text_filter.textChanged.connect(self._apply_filter)
        self._type_filter.currentIndexChanged.connect(self._apply_filter)
        self._source_filter.currentIndexChanged.connect(self._apply_filter)
        self._conf_filter.valueChanged.connect(self._apply_filter)

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def set_session(self, session: DocumentSession | None) -> None:
        """Bind the panel to a document session (or `None` to clear)."""
        self._session = session
        self._populate()

    def refresh_summary(self) -> None:
        """Update the "X of Y will redact" label without re-populating the tree."""
        self._update_summary()

    # -------------------------------------------------------------------
    # Population
    # -------------------------------------------------------------------

    def _populate(self) -> None:
        """Rebuild the tree from the bound session."""
        self._suppress_change_signal = True
        try:
            self._tree.clear()
            # Rebuild the entity-type filter to match the session.
            self._type_filter.blockSignals(True)
            self._type_filter.clear()
            self._type_filter.addItem("All types", "")
            seen_types = sorted(
                {d.entity_type for d in (self._session.detections if self._session else [])}
            )
            for t in seen_types:
                self._type_filter.addItem(t, t)
            self._type_filter.blockSignals(False)

            if self._session is None or not self._session.detections:
                self._update_summary()
                self._update_visible_count()
                return
            for i, det in enumerate(self._session.detections):
                item = QTreeWidgetItem()
                item.setData(0, Qt.ItemDataRole.UserRole, i)  # global detection idx
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                accepted = self._session.decision_for(i) == Decision.ACCEPTED
                item.setCheckState(
                    COL_ACCEPT,
                    Qt.CheckState.Checked if accepted else Qt.CheckState.Unchecked,
                )
                item.setText(COL_PAGE, str(det.page + 1))  # 1-indexed for users
                item.setText(COL_TYPE, det.entity_type)
                item.setText(COL_TEXT, det.text)
                item.setText(COL_CONF, f"{det.confidence:.2f}")
                item.setText(COL_SOURCE, det.source)
                self._tree.addTopLevelItem(item)
            self._update_summary()
            self._apply_filter()
        finally:
            self._suppress_change_signal = False

    # -------------------------------------------------------------------
    # Filter
    # -------------------------------------------------------------------

    def _apply_filter(self) -> None:
        """Hide/show rows based on filter state. Doesn't mutate session decisions."""
        if self._session is None:
            self._update_visible_count()
            return
        needle = self._text_filter.text().strip().lower()
        wanted_type = self._type_filter.currentData() or ""
        wanted_source = self._source_filter.currentData() or ""
        min_conf = float(self._conf_filter.value())

        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            idx = item.data(0, Qt.ItemDataRole.UserRole)
            if idx is None:
                continue
            det = self._session.detections[int(idx)]
            visible = True
            if needle:
                hay = (det.text + " " + det.entity_type).lower()
                if needle not in hay:
                    visible = False
            if visible and wanted_type and det.entity_type != wanted_type:
                visible = False
            if visible and wanted_source and det.source != wanted_source:
                visible = False
            if visible and det.confidence < min_conf:
                visible = False
            item.setHidden(not visible)
        self._update_visible_count()

    def _update_visible_count(self) -> None:
        if self._session is None or not self._session.detections:
            self._visible_count_label.setText("")
            return
        visible = sum(
            1 for i in range(self._tree.topLevelItemCount())
            if not self._tree.topLevelItem(i).isHidden()
        )
        total = self._tree.topLevelItemCount()
        if visible == total:
            self._visible_count_label.setText(f"{total} detections")
        else:
            self._visible_count_label.setText(f"{visible} of {total} shown")

    # -------------------------------------------------------------------
    # Slots
    # -------------------------------------------------------------------

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._suppress_change_signal or self._session is None:
            return
        if column != COL_ACCEPT:
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        new_decision = (
            Decision.ACCEPTED
            if item.checkState(COL_ACCEPT) == Qt.CheckState.Checked
            else Decision.REJECTED
        )
        self._session.set_decision(int(idx), new_decision)
        self._update_summary()
        self.decisions_changed.emit()

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        self.row_activated.emit(int(idx))

    def _on_accept_all(self) -> None:
        if self._session is None:
            return
        self._session.accept_all()
        self._populate()
        self.decisions_changed.emit()

    def _on_reject_all(self) -> None:
        if self._session is None:
            return
        self._session.reject_all()
        self._populate()
        self.decisions_changed.emit()

    # -------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------

    def _update_summary(self) -> None:
        s = self._session
        if s is None or not s.detections:
            self._summary_label.setText("No detections yet — open and process a PDF")
            return
        self._summary_label.setText(
            f"{s.accepted_count} of {s.detection_count} will be redacted"
        )

    # -------------------------------------------------------------------
    # Test helpers (used by `test_gui_detection_panel.py`)
    # -------------------------------------------------------------------

    def item_count(self) -> int:
        return self._tree.topLevelItemCount()

    def items(self) -> Iterable[QTreeWidgetItem]:
        for i in range(self._tree.topLevelItemCount()):
            yield self._tree.topLevelItem(i)

    def set_filter_text(self, text: str) -> None:
        """Test helper — set the text filter and trigger application."""
        self._text_filter.setText(text)

    def visible_row_count(self) -> int:
        return sum(
            1 for i in range(self._tree.topLevelItemCount())
            if not self._tree.topLevelItem(i).isHidden()
        )
