"""PDF page viewer with detection bbox overlays + optional side-by-side preview.

Rendering pipeline
------------------
PyMuPDF can rasterize a page to a PNG at any DPI. We render once per page-change
or zoom-change, paint detection bboxes on top (color-coded by Accept/Reject
state), then display as a QPixmap.

When `set_redacted_preview_path()` is called and `show_redacted_preview()` is
toggled on, we render BOTH the original page and the redacted page from a
second PDF and paint them side-by-side with a vertical separator. This lets
the user verify the redacted output before saving without round-tripping
through the file system.

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

# Side-by-side preview separator color (matches the editorial border color).
SPLIT_SEPARATOR = QColor(0xc8, 0xc4, 0xb8, 255)
SPLIT_LABEL_BG = QColor(0xfa, 0xfa, 0xf7, 240)
SPLIT_LABEL_TEXT = QColor(0x6a, 0x6a, 0x60, 255)


class PdfViewer(QWidget):
    """Single-page viewer that scrolls horizontally/vertically when content overflows.

    External API:
        - `load(pdf_path)`              — open a PDF
        - `set_page(page_index)`        — show this page
        - `set_overlays(items)`         — overlay these on every render
        - `set_redacted_preview_path()` — pass a second PDF for side-by-side preview
        - `show_redacted_preview(bool)` — toggle side-by-side rendering
        - `signals.page_changed(int)`   — emitted when the page index changes
    """

    page_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pdf_path: Path | None = None
        self._redacted_preview_path: Path | None = None
        self._show_preview: bool = False
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
        self._image_label.setStyleSheet("background-color: #f0eee5;")
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
        # When loading a fresh document, drop any stale redacted-preview path
        # from a previous document. The MainWindow re-supplies it after Process.
        self._redacted_preview_path = None
        self._show_preview = False
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

    def set_redacted_preview_path(self, path: Path | None) -> None:
        """Supply the redacted-PDF file path used by the side-by-side preview.

        Pass `None` to clear (e.g. when overlays change and the preview is stale).
        """
        self._redacted_preview_path = path
        if self._pdf_path:
            self._render()

    def show_redacted_preview(self, on: bool) -> None:
        """Toggle the side-by-side preview. Repaints immediately."""
        self._show_preview = bool(on)
        if self._pdf_path:
            self._render()

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def has_redacted_preview(self) -> bool:
        return self._redacted_preview_path is not None and self._redacted_preview_path.exists()

    @property
    def is_showing_preview(self) -> bool:
        return self._show_preview

    # -------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------

    def _render(self) -> None:
        assert self._pdf_path is not None

        # Render the original (always).
        original_pixmap = self._render_page(self._pdf_path, self._current_page, paint_overlays=True)

        if self._show_preview and self.has_redacted_preview:
            # Render the redacted version too (no overlays — it's the "after" view).
            assert self._redacted_preview_path is not None
            redacted_pixmap = self._render_page(
                self._redacted_preview_path, self._current_page, paint_overlays=False
            )
            combined = self._compose_side_by_side(original_pixmap, redacted_pixmap)
            self._image_label.setPixmap(combined)
            self._image_label.resize(combined.size())
        else:
            self._image_label.setPixmap(original_pixmap)
            self._image_label.resize(original_pixmap.size())

    def _render_page(self, pdf_path: Path, page_index: int, *, paint_overlays: bool) -> QPixmap:
        """Rasterize a single page from `pdf_path` and optionally paint overlays."""
        import fitz

        with fitz.open(pdf_path) as doc:
            if page_index >= len(doc):
                # Redacted PDF may have fewer pages than original if the user
                # never processed it. Return a placeholder.
                return self._placeholder_pixmap("Preview unavailable for this page")
            page = doc[page_index]
            matrix = fitz.Matrix(self._scale, self._scale)
            pixmap_data = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pixmap_data.tobytes("png")

        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, "PNG")

        if paint_overlays and self._overlays:
            painter = QPainter(pixmap)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                for det, decision in self._overlays:
                    if det.page != page_index:
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

        return pixmap

    def _placeholder_pixmap(self, message: str) -> QPixmap:
        """Build a small placeholder pixmap (used when a page has no preview yet)."""
        pixmap = QPixmap(400, 300)
        pixmap.fill(QColor(0xf0, 0xee, 0xe5))
        painter = QPainter(pixmap)
        try:
            painter.setPen(QPen(SPLIT_LABEL_TEXT))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, message)
        finally:
            painter.end()
        return pixmap

    def _compose_side_by_side(self, left: QPixmap, right: QPixmap) -> QPixmap:
        """Place `left` and `right` next to each other with a labeled separator.

        The two pixmaps may have different heights; pad the shorter one so the
        composite stays a clean rectangle.
        """
        gap = 24  # separator thickness + breathing room
        width = left.width() + right.width() + gap
        height = max(left.height(), right.height())
        combined = QPixmap(width, height)
        combined.fill(QColor(0xfa, 0xfa, 0xf7))

        painter = QPainter(combined)
        try:
            painter.drawPixmap(0, (height - left.height()) // 2, left)
            painter.drawPixmap(
                left.width() + gap,
                (height - right.height()) // 2,
                right,
            )
            # Separator line.
            painter.setPen(QPen(SPLIT_SEPARATOR, 1))
            mid_x = left.width() + gap // 2
            painter.drawLine(mid_x, 0, mid_x, height)

            # Labels.
            painter.setPen(QPen(SPLIT_LABEL_TEXT))
            font = painter.font()
            font.setPointSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(8, 18, "ORIGINAL")
            painter.drawText(left.width() + gap + 8, 18, "REDACTED")
        finally:
            painter.end()
        return combined

    def _bbox_to_pixmap_rect(self, bbox: tuple[float, float, float, float]) -> QRectF:
        """Map a PDF-point bbox to pixmap pixel coordinates at current scale."""
        x0, y0, x1, y1 = bbox
        s = self._scale
        return QRectF(x0 * s, y0 * s, (x1 - x0) * s, (y1 - y0) * s)
