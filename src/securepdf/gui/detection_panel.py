"""Detection review panel — list of all detections with accept/reject checkboxes.

Layout:

  ┌──────────────────────────────────────────────────────┐
  │ [Accept all]  [Reject all]   12 of 24 will redact    │
  ├──────────────────────────────────────────────────────┤
  │ ☑ Page 1 │ PERSON       │ "Jane Doe"      │ 0.85 │ … │
  │ ☐ Page 1 │ DATE_TIME    │ "1985-03-22"    │ 0.85 │ … │
  │ ☑ Page 2 │ EMAIL_ADDRES │ "j.doe@…"       │ 1.00 │ … │
  │ ...                                                  │
  └──────────────────────────────────────────────────────┘

The panel is dumb: it renders state from a `DocumentSession` and emits a signal
when the user toggles a row. The MainWindow listens, mutates the session, and
asks the viewer to repaint.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
        self._summary_label.setStyleSheet("color: #666; padding-left: 12px;")

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._accept_all_btn)
        toolbar.addWidget(self._reject_all_btn)
        toolbar.addWidget(self._summary_label, 1)

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
        layout.addWidget(self._tree, 1)

        # --- Signals ---
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._accept_all_btn.clicked.connect(self._on_accept_all)
        self._reject_all_btn.clicked.connect(self._on_reject_all)

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
            if self._session is None or not self._session.detections:
                self._update_summary()
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
        finally:
            self._suppress_change_signal = False

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
