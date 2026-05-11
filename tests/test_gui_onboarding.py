"""Tests for the Ollama detection banner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def _client_factory(available: bool):
    """Build a factory that returns a stub OllamaClient with the given availability."""

    def factory():
        c = MagicMock()
        c.is_available.return_value = available
        return c

    return factory


@pytest.fixture
def banner_factory(qapp):
    from securepdf.gui.onboarding import OllamaBanner

    def _make(available: bool):
        return OllamaBanner(client_factory=_client_factory(available))

    return _make


def test_banner_hidden_when_ollama_available(banner_factory):
    banner = banner_factory(available=True)
    banner.check_and_show()
    assert banner.is_showing is False


def test_banner_shown_when_ollama_missing(banner_factory):
    banner = banner_factory(available=False)
    banner.check_and_show()
    assert banner.is_showing is True


def test_banner_dismiss_hides_and_emits_signal(banner_factory):
    banner = banner_factory(available=False)
    banner.check_and_show()
    captured = []
    banner.dismissed.connect(lambda: captured.append(True))
    banner._on_dismiss()  # noqa: SLF001
    assert banner.is_showing is False
    assert captured == [True]


def test_banner_treats_exception_as_not_available(qapp):
    """If the client check throws, we should still display the banner (fail-safe)."""
    from securepdf.gui.onboarding import OllamaBanner

    def _broken_factory():
        raise RuntimeError("client init failed")

    banner = OllamaBanner(client_factory=_broken_factory)
    banner.check_and_show()
    assert banner.is_showing is True
