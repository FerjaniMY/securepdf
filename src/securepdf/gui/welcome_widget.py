"""Welcome / empty-state widget — shown when no document is open.

Replaces the default empty central area with a centered drop zone, a
helpful headline, and an "Open PDF…" button. Accepts drag-drop directly so
users can drop without going through the menu.

The visual: a soft beige card with a dashed border, centered in the viewer
pane, with a small icon (rendered via the system font), a serif headline, a
muted sub-line, and the action button.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class WelcomeWidget(QWidget):
    """Empty-state widget shown when no document is loaded.

    Signals
    -------
    open_requested:  user clicked the Open button
    files_dropped(list[Path]):  user dropped one or more PDF paths on the widget
    """

    open_requested = Signal()
    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        # The card — centered in the widget so the drop zone has breathing room.
        self._card = QFrame()
        self._card.setObjectName("welcome_card")
        # Inline style: the global stylesheet doesn't know about this object, and
        # the dashed border is welcome-screen-specific.
        self._card.setStyleSheet(
            "#welcome_card {"
            "  background-color: #f7f5ec;"
            "  border: 2px dashed #c8c4b8;"
            "  border-radius: 14px;"
            "}"
        )
        self._card.setMinimumSize(480, 320)
        self._card.setMaximumSize(620, 420)

        # Card contents.
        icon = QLabel("📄")
        icon.setStyleSheet("font-size: 56px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Drag a PDF here")
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Force the stylesheet's role="title" selector to re-apply on this widget.
        title.style().unpolish(title)
        title.style().polish(title)

        subtitle = QLabel(
            "SecurePDF processes documents entirely on your laptop.\n"
            "Nothing ever leaves the machine."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.style().unpolish(subtitle)
        subtitle.style().polish(subtitle)

        self._open_btn = QPushButton("Open PDF…")
        self._open_btn.setProperty("primary", True)
        self._open_btn.clicked.connect(self.open_requested.emit)
        # Make the button a comfortable mid-size, centered in its row.
        self._open_btn.setMinimumWidth(140)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._open_btn)
        btn_row.addStretch(1)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(48, 40, 48, 40)
        card_layout.setSpacing(16)
        card_layout.addStretch(1)
        card_layout.addWidget(icon)
        card_layout.addSpacing(8)
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(20)
        card_layout.addLayout(btn_row)
        card_layout.addStretch(1)

        # Centering wrapper.
        outer = QHBoxLayout(self)
        outer.addStretch(1)
        v = QVBoxLayout()
        v.addStretch(1)
        v.addWidget(self._card)
        v.addStretch(1)
        outer.addLayout(v)
        outer.addStretch(1)

    # -------------------------------------------------------------------
    # Drag-drop — accept PDFs and emit `files_dropped`.
    # -------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt method
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(u.toLocalFile().lower().endswith(".pdf") for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt method
        paths: list[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local.lower().endswith(".pdf"):
                paths.append(Path(local))
        if paths:
            self.files_dropped.emit(paths)
