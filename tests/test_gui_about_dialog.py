"""Smoke test for the AboutDialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_constructs_and_shows_version(qapp):
    from securepdf import __version__
    from securepdf.gui.about_dialog import AboutDialog

    dlg = AboutDialog()
    # The version label is one of the first children — find by traversal.
    found_version = False
    for widget in dlg.findChildren(type(dlg.children()[0]).__class__):  # type: ignore[arg-type]
        # Simple text-search across all QLabels.
        if hasattr(widget, "text"):
            try:
                if __version__ in widget.text():
                    found_version = True
                    break
            except Exception:
                pass
    # Fallback: scan all QLabels directly.
    if not found_version:
        from PySide6.QtWidgets import QLabel

        for label in dlg.findChildren(QLabel):
            if __version__ in label.text():
                found_version = True
                break
    assert found_version, f"AboutDialog should display version {__version__}"
    dlg.close()


def test_constructs_without_parent(qapp):
    """Confirm the dialog works as a standalone window too."""
    from securepdf.gui.about_dialog import AboutDialog

    dlg = AboutDialog(parent=None)
    assert dlg.windowTitle() == "About SecurePDF"
    dlg.close()
