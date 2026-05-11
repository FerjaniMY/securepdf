"""PDF page viewer with detection bbox overlays.

Rendering pipeline
------------------
PyMuPDF can rasterize a page to a PNG at any DPI. We render once per page-change
or zoom-change, paint detection bboxes on top (color-coded by Accept/Reject
state), then display as a QPixmap.

Coordinate transformation
-------------------------
PyMuPDF page coordinates are PDF points (72 DPI). The rendered pixmap is at
`render_dpi` DPI, so we multiply detection bboxes by `render_dpi/72` to get
pixel-space rectangles. This is the inverse of the OCR module's px→pt mapping.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from securepdf.detection.models import Detection
from securepdf.gui.document_session import Decision

log = logging.getLogger(__name__)

# Render DPI: 144 = 2x scale on a 72dpi page. Sharp enough for review on a HiDPI
# screen, modest enough to render in <100ms per page on CPU.
RENDER_DPI = 144

# Highlight colors. RGBA in 0-255 space.
COLOR_ACCEPTED = QColor(255, 64, 64, 80)   # translucent red — "will be redacted"
COLOR_REJECTED = QColor(128, 128, 128, 60)  # translucent gray — "rejected, will not redact"
COLOR_ACCEPTED_OUTLINE = QColor(220, 0, 0, 200)
COLOR_REJECTED_OUTLINE = QColor(120, 120, 120, 200)


class PdfViewer(QWidget):
    """Single-page viewer that scrolls horizontally/vertically when content overflows.

    External API:
        - `load(pdf_path)`              — open a PDF
        - `set_page(page_index)`        — show this page
        - `set_detections(decisions, dets)` — overlay these on every render
        - `signals.page_changed(int)`   — emitted when the page index changes
    """

    page_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pdf_path: Path | None = None
        # Each entry: (Detection, Decision). Used to color overlays.
        self._overlays: list[tuple[Detection, Decision]] = []
        self._current_page = 0
        self._page_count = 0
        self._scale: float = RENDER_DPI / 72.0  # pdf-points → pixels

        # --- UI ---
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(False)
        self._image_label = QLabel()
        self._image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background-color: #222;")
        self._image_label.setText("No document loaded")
        self._image_label.setMinimumSize(400, 300)
        self._scroll.setWidget(self._image_label)
        self._layout.addWidget(self._scroll)

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def load(self, pdf_path: Path) -> None:
        """Open a PDF and show page 0."""
        self._pdf_path = pdf_path
        # Defer import: PyMuPDF is heavy, and the GUI shell shouldn't pay the
        # cost until a PDF is actually opened.
        import fitz
        with fitz.open(pdf_path) as doc:
            self._page_count = len(doc)
        self.set_page(0)

    def set_page(self, page_index: int) -> None:
        if not self._pdf_path:
            return
        if not 0 <= page_index < self._page_count:
            return
        self._current_page = page_index
        self._render()
        self.page_changed.emit(page_index)

    def set_overlays(self, items: list[tuple[Detection, Decision]]) -> None:
        """Replace the overlay list. The viewer re-paints immediately."""
        self._overlays = items
        if self._pdf_path:
            self._render()

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def current_page(self) -> int:
        return self._current_page

    # -------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------

    def _render(self) -> None:
        assert self._pdf_path is not None
        import fitz

        # Render the underlying page to a QPixmap.
        with fitz.open(self._pdf_path) as doc:
            page = doc[self._current_page]
            matrix = fitz.Matrix(self._scale, self._scale)
            pixmap_data = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pixmap_data.tobytes("png")

        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, "PNG")

        # Paint overlays on top.
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for det, decision in self._overlays:
                if det.page != self._current_page:
                    continue
                rect = self._bbox_to_pixmap_rect(det.bbox)
                if decision == Decision.ACCEPTED:
                    painter.setBrush(QBrush(COLOR_ACCEPTED))
                    painter.setPen(QPen(COLOR_ACCEPTED_OUTLINE, 1.5))
                else:
                    painter.setBrush(QBrush(COLOR_REJECTED))
                    painter.setPen(QPen(COLOR_REJECTED_OUTLINE, 1.0, Qt.PenStyle.DashLine))
                painter.drawRect(rect)
        finally:
            painter.end()

        self._image_label.setPixmap(pixmap)
        self._image_label.resize(pixmap.size())

    def _bbox_to_pixmap_rect(self, bbox: tuple[float, float, float, float]) -> QRectF:
        """Map a PDF-point bbox to pixmap pixel coordinates at current scale."""
        x0, y0, x1, y1 = bbox
        s = self._scale
        return QRectF(x0 * s, y0 * s, (x1 - x0) * s, (y1 - y0) * s)
