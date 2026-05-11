"""Minimal HTTP client for the local Ollama server (https://ollama.com).

We don't pull in the official `ollama` Python SDK — its surface is larger than
we need and its async semantics complicate the synchronous GUI pipeline.
A 100-line `requests`-based wrapper does the job.

Ollama listens on `http://localhost:11434` by default. The user installs Ollama
once (via OS installer), and `app first-run` calls `pull_model("gemma2:2b")`
which downloads ~1.6 GB on first use and caches it forever after.

This client honors HTTPS_PROXY via `requests` — important because the agent
container's egress is firewalled.
"""

from __future__ import annotations

import json
import logging
from typing import Iterator

import requests

log = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "gemma2:2b"
DEFAULT_TIMEOUT = 60.0  # generation timeout per page; pulls have their own.


class OllamaError(RuntimeError):
    """Raised when an Ollama call fails (server down, model missing, bad JSON)."""


class OllamaClient:
    """Thin wrapper around the Ollama HTTP API.

    Methods are deliberately synchronous; the desktop GUI runs detection on a
    background thread, so async would just add complexity here.
    """

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT):
        self.host = host.rstrip("/")
        self.timeout = timeout

    # -------------------------------------------------------------------
    # Health
    # -------------------------------------------------------------------

    def is_available(self) -> bool:
        """True if the Ollama server is up and responding.

        Used by the GUI's onboarding wizard and by `gemma_detector` to decide
        whether to attempt the Stage 2 pass (or skip with a logged warning).
        """
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5.0)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def has_model(self, model: str = DEFAULT_MODEL) -> bool:
        """True if `model` is already pulled locally."""
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5.0)
            r.raise_for_status()
            tags = r.json().get("models", [])
            return any(t.get("name", "").startswith(model) for t in tags)
        except requests.RequestException as e:
            raise OllamaError(f"failed to list models: {e}") from e

    # -------------------------------------------------------------------
    # Model management
    # -------------------------------------------------------------------

    def pull_model(self, model: str = DEFAULT_MODEL) -> Iterator[dict]:
        """Stream pull progress for `model`. Yields each status line as a dict.

        Callers (e.g. the GUI progress bar) consume the stream; if they just
        want to block until done, `list(pull_model(...))` works.
        """
        try:
            with requests.post(
                f"{self.host}/api/pull",
                json={"name": model, "stream": True},
                stream=True,
                timeout=600.0,  # large model download can take minutes on slow nets
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("ollama pull: skipping malformed line: %r", line[:80])
        except requests.RequestException as e:
            raise OllamaError(f"pull failed: {e}") from e

    # -------------------------------------------------------------------
    # Generation
    # -------------------------------------------------------------------

    def generate_json(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        num_predict: int = 1024,
    ) -> str:
        """Run a generation, requesting structured JSON output. Returns raw response text.

        Parsing/repair is the caller's responsibility (see `gemma_detector._parse_response`).
        We ask Ollama for `format="json"` which constrains the model to emit valid JSON —
        but Gemma at 2B sometimes still produces minor schema deviations, so callers must
        validate.

        Low temperature (0.1) because we want deterministic extraction, not creative writing.
        """
        try:
            r = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": temperature,
                        "num_predict": num_predict,
                    },
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("response", "")
        except requests.RequestException as e:
            raise OllamaError(f"generate failed: {e}") from e
