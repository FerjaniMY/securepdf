"""First-run Ollama detection banner.

Why a banner, not a wizard
--------------------------
A modal wizard on first launch makes the app feel heavy. A dismissable banner
at the top of the main window communicates the same information with no
friction: "Ollama is not detected. Stage 2 (contextual detection) will be
skipped. [Install Ollama] [Dismiss]".

If the user already has Ollama running, the banner never appears. If they
dismiss it once, we store that preference and don't show it again unless they
explicitly reset it via Help → Reset banners.

The actual install happens out-of-band (clicking "Install Ollama" opens
ollama.com in their browser). Bundling an installer is a Phase 5 packaging
concern, not a Phase 4 GUI concern.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from securepdf.detection.ollama_client import DEFAULT_MODEL, OllamaClient

log = logging.getLogger(__name__)


class OllamaBanner(QFrame):
    """Dismissable yellow strip shown when Ollama isn't running."""

    dismissed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        client_factory: Callable[[], OllamaClient] = OllamaClient,
    ):
        super().__init__(parent)
        self._client_factory = client_factory
        self.setStyleSheet(
            "QFrame { background-color: #FFF4D6; border-bottom: 1px solid #E0B040; }"
            "QLabel { color: #5C4408; }"
        )
        self.setVisible(False)

        self._label = QLabel(
            "Ollama not detected — Stage 2 (contextual AI detection) will be skipped."
        )
        self._install_btn = QPushButton("Install Ollama")
        self._dismiss_btn = QPushButton("Dismiss")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._install_btn)
        layout.addWidget(self._dismiss_btn)

        self._install_btn.clicked.connect(self._on_install)
        self._dismiss_btn.clicked.connect(self._on_dismiss)

    def check_and_show(self) -> None:
        """Run the detection check and show the banner if Ollama isn't available.

        Synchronous — the check is a single HTTP call with a 5s timeout, so this
        doesn't block the UI noticeably. If we ever wire this up to a slow
        endpoint we can swap to a QThread.
        """
        try:
            client = self._client_factory()
            available = client.is_available()
        except Exception:  # noqa: BLE001 — surface any error as "not available"
            available = False
            log.debug("OllamaClient check raised; treating as not-available")

        if available:
            # Also check the model is pulled — without it, Stage 2 will fail at
            # generation time. But model-pull errors are surfaced by the worker,
            # so we don't push a separate banner for them.
            self.setVisible(False)
        else:
            self.setVisible(True)

    # -------------------------------------------------------------------
    # Slots
    # -------------------------------------------------------------------

    def _on_install(self) -> None:
        QDesktopServices.openUrl(QUrl("https://ollama.com/download"))

    def _on_dismiss(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()

    # -------------------------------------------------------------------
    # Test hook
    # -------------------------------------------------------------------

    @property
    def is_showing(self) -> bool:
        return self.isVisible()
