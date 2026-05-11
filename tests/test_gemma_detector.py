"""Tests for the Gemma Stage 2 detector — Ollama client is mocked throughout."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from securepdf.detection import gemma_detector
from securepdf.detection.models import Detection


def _client_returning(payload: dict):
    client = MagicMock()
    client.is_available.return_value = True
    client.generate_json.return_value = json.dumps(payload)
    return client


def test_skips_when_ollama_unavailable(synthetic_page):
    client = MagicMock()
    client.is_available.return_value = False
    dets = gemma_detector.detect_page(synthetic_page, client=client)
    assert dets == []
    client.generate_json.assert_not_called()


def test_anchors_to_exact_substring(synthetic_page):
    client = _client_returning(
        {"detections": [{"text": "jane.doe@example.com", "type": "EMAIL"}]}
    )
    dets = gemma_detector.detect_page(synthetic_page, client=client)
    assert len(dets) == 1
    d = dets[0]
    assert d.text == "jane.doe@example.com"
    assert d.source == "gemma"
    assert d.entity_type == "EMAIL"
    # The bbox should match the email span on the page.
    assert d.bbox == synthetic_page.spans[4].bbox


def test_skips_substrings_not_in_text(synthetic_page):
    """If Gemma hallucinates a detection that isn't in the page, we drop it
    rather than fuzz-match to the wrong location."""
    client = _client_returning(
        {"detections": [{"text": "NOT_ON_THIS_PAGE_42", "type": "PERSON"}]}
    )
    dets = gemma_detector.detect_page(synthetic_page, client=client)
    assert dets == []


def test_case_insensitive_fallback(synthetic_page):
    client = _client_returning(
        {"detections": [{"text": "JANE DOE", "type": "PERSON"}]}
    )
    dets = gemma_detector.detect_page(synthetic_page, client=client)
    assert len(dets) == 1
    # Anchored to the actual page case, not the LLM's uppercase output.
    assert dets[0].text == "Jane Doe"


def test_handles_invalid_json_gracefully(synthetic_page):
    client = MagicMock()
    client.is_available.return_value = True
    client.generate_json.return_value = "not json at all"
    dets = gemma_detector.detect_page(synthetic_page, client=client)
    assert dets == []


def test_strips_markdown_code_fences(synthetic_page):
    """Gemma occasionally fences JSON in ```json despite format=json."""
    client = MagicMock()
    client.is_available.return_value = True
    client.generate_json.return_value = (
        '```json\n{"detections": [{"text": "Jane Doe", "type": "PERSON"}]}\n```'
    )
    dets = gemma_detector.detect_page(synthetic_page, client=client)
    assert len(dets) == 1
    assert dets[0].text == "Jane Doe"


def test_prompt_includes_stage1_hints(synthetic_page):
    client = _client_returning({"detections": []})
    stage1 = [
        Detection(
            text="Jane Doe",
            entity_type="PERSON",
            page=0,
            bbox=(0, 0, 50, 14),
            char_start=9,
            char_end=17,
            confidence=0.9,
            source="presidio",
            span_indices=(1, 2),
        )
    ]
    gemma_detector.detect_page(synthetic_page, client=client, existing_detections=stage1)
    prompt = client.generate_json.call_args.args[0]
    assert '"Jane Doe"' in prompt
    assert "PERSON" in prompt


def test_prompt_includes_custom_descriptions(synthetic_page):
    client = _client_returning({"detections": []})
    gemma_detector.detect_page(
        synthetic_page,
        client=client,
        custom_descriptions=["Internal codenames like PROJECT_PHOENIX"],
    )
    prompt = client.generate_json.call_args.args[0]
    assert "PROJECT_PHOENIX" in prompt
