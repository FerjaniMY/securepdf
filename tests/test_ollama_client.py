"""Tests for the Ollama HTTP client — fully mocked, no live server needed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from securepdf.detection.ollama_client import OllamaClient, OllamaError


def test_is_available_returns_true_on_200():
    with patch("securepdf.detection.ollama_client.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        assert OllamaClient().is_available() is True


def test_is_available_returns_false_on_connection_error():
    with patch("securepdf.detection.ollama_client.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("nope")
        assert OllamaClient().is_available() is False


def test_has_model_finds_match():
    with patch("securepdf.detection.ollama_client.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "gemma2:2b"}, {"name": "llama3:8b"}]
        }
        mock_get.return_value = mock_resp
        assert OllamaClient().has_model("gemma2:2b")
        assert not OllamaClient().has_model("phi3:mini")


def test_has_model_raises_on_http_failure():
    with patch("securepdf.detection.ollama_client.requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("boom")
        with pytest.raises(OllamaError):
            OllamaClient().has_model("gemma2:2b")


def test_generate_json_returns_response_field():
    with patch("securepdf.detection.ollama_client.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": '{"detections": []}'}
        mock_post.return_value = mock_resp
        out = OllamaClient().generate_json("any prompt", model="gemma2:2b")
        assert out == '{"detections": []}'


def test_generate_json_passes_json_format_flag():
    """We rely on Ollama's format='json' enforcement — verify the request carries it."""
    with patch("securepdf.detection.ollama_client.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "{}"}
        mock_post.return_value = mock_resp
        OllamaClient().generate_json("p")
        kwargs = mock_post.call_args.kwargs
        assert kwargs["json"]["format"] == "json"
        assert kwargs["json"]["stream"] is False
        assert kwargs["json"]["options"]["temperature"] == 0.1
