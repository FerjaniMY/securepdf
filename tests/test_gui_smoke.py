"""GUI smoke test — instantiate the MainWindow without crashing.

This is the broadest possible safety net: if any widget class has a typo, an
import cycle, or a signal-connection error, this test catches it before merge.
We don't simulate user interaction here — that's covered by the focused widget
tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_main_window_constructs(qapp):
    # Stub the Ollama check so the banner doesn't try a network call during the test.
    with patch("securepdf.gui.onboarding.OllamaClient") as mock_client:
        instance = MagicMock()
        instance.is_available.return_value = True
        mock_client.return_value = instance
        from securepdf.gui.main_window import MainWindow
        window = MainWindow()
        assert window.windowTitle() == "SecurePDF"
        # No active document yet, so Process/Save should be disabled.
        assert window._action_process.isEnabled() is False  # noqa: SLF001
        assert window._action_save.isEnabled() is False  # noqa: SLF001
        window.close()


def test_main_window_drag_drop_accepts_pdf_urls(qapp):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDragEnterEvent
    from PySide6.QtCore import QPointF, Qt

    with patch("securepdf.gui.onboarding.OllamaClient") as mock_client:
        instance = MagicMock()
        instance.is_available.return_value = True
        mock_client.return_value = instance
        from securepdf.gui.main_window import MainWindow
        window = MainWindow()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/test.pdf")])
    event = QDragEnterEvent(
        QPointF(10.0, 10.0).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(event)
    assert event.isAccepted()
    window.close()
