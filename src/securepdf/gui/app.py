"""SecurePDF desktop app entry point.

Launches a QApplication, builds a `MainWindow`, and runs the event loop.

CLI: `securepdf-gui` or `python -m securepdf.gui`.

Headless mode (testing / CI)
----------------------------
Tests set `QT_QPA_PLATFORM=offscreen` before importing PySide6 so widgets can be
constructed without a display server. We don't need any special handling here —
PySide6 reads the env var directly.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication


def main(argv: list[str] | None = None) -> int:
    """Run the SecurePDF desktop app and return the exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Import here, after logging is configured, so the MainWindow gets a clean
    # logger configuration. Also keeps `import securepdf.gui` cheap when used
    # from non-GUI consumers (e.g. the tests for `app.main` as a smoke check).
    from securepdf.gui.main_window import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("SecurePDF")
    app.setOrganizationName("SecurePDF")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
