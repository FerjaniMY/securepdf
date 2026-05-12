"""Tests for the WelcomeWidget — drop zone and Open button signal."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_constructs(qapp):
    from securepdf.gui.welcome_widget import WelcomeWidget

    w = WelcomeWidget()
    assert w.acceptDrops()


def test_open_button_emits_signal(qapp):
    from securepdf.gui.welcome_widget import WelcomeWidget

    w = WelcomeWidget()
    captured = []
    w.open_requested.connect(lambda: captured.append(True))
    w._open_btn.click()  # noqa: SLF001
    assert captured == [True]


def test_drag_enter_accepts_pdf_urls(qapp):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent

    from securepdf.gui.welcome_widget import WelcomeWidget

    w = WelcomeWidget()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/test.pdf")])
    event = QDragEnterEvent(
        QPointF(10.0, 10.0).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.dragEnterEvent(event)
    assert event.isAccepted()


def test_drag_enter_rejects_non_pdf(qapp):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent

    from securepdf.gui.welcome_widget import WelcomeWidget

    w = WelcomeWidget()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/test.txt")])
    event = QDragEnterEvent(
        QPointF(10.0, 10.0).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.dragEnterEvent(event)
    assert not event.isAccepted()
