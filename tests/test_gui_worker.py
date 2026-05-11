"""Tests for the PipelineWorker signal flow.

We don't actually run a PDF through here — we stub `extract` and `detect` at
import time, then drive the worker's `run()` synchronously (since it's just a
function on a QObject; the threading is the caller's concern).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6.QtCore", exc_type=ImportError)


@pytest.fixture
def worker(qapp):
    from securepdf.gui.worker import PipelineWorker
    return PipelineWorker()


def _capture_signal(signal):
    """Return a list that's appended to every time `signal` fires.

    Lets tests assert on emission count and arguments without QSignalSpy gymnastics.
    """
    captured: list = []

    def _slot(*args):
        captured.append(args)

    signal.connect(_slot)
    return captured


def test_worker_emits_signals_in_order(worker, tmp_path):
    from securepdf.gui.worker import WorkerJob

    pages_emissions = _capture_signal(worker.pages_ready)
    detections_emissions = _capture_signal(worker.detections_ready)
    finished_emissions = _capture_signal(worker.finished)
    failed_emissions = _capture_signal(worker.failed)

    fake_pages = ["page0", "page1"]
    fake_dets = ["det1", "det2", "det3"]

    with patch("securepdf.pdf.pipeline.extract", return_value=fake_pages):
        with patch("securepdf.detection.detect", return_value=fake_dets):
            job = WorkerJob(pdf_path=tmp_path / "x.pdf", use_stage2=False)
            worker.run(job)

    assert len(pages_emissions) == 1
    assert pages_emissions[0][0] == fake_pages
    assert len(detections_emissions) == 1
    assert detections_emissions[0][0] == fake_dets
    assert detections_emissions[0][1] == str(tmp_path / "x.pdf")
    assert len(finished_emissions) == 1
    assert failed_emissions == []  # no errors


def test_worker_emits_failed_on_exception(worker, tmp_path):
    from securepdf.gui.worker import WorkerJob

    failed_emissions = _capture_signal(worker.failed)
    finished_emissions = _capture_signal(worker.finished)

    def _broken_extract(_path):
        raise RuntimeError("extraction blew up")

    with patch("securepdf.pdf.pipeline.extract", side_effect=_broken_extract):
        job = WorkerJob(pdf_path=tmp_path / "x.pdf", use_stage2=False)
        worker.run(job)

    assert len(failed_emissions) == 1
    assert "extraction blew up" in failed_emissions[0][0]
    # finished should still fire — the cleanup signal is in `finally`.
    assert len(finished_emissions) == 1


def test_worker_progress_fires_multiple_times(worker, tmp_path):
    from securepdf.gui.worker import WorkerJob

    progress_emissions = _capture_signal(worker.progress)

    with patch("securepdf.pdf.pipeline.extract", return_value=[]):
        with patch("securepdf.detection.detect", return_value=[]):
            worker.run(WorkerJob(pdf_path=tmp_path / "x.pdf", use_stage2=False))

    # At minimum: "Extracting", "Extracted N pages", "Detecting", "Found N spans".
    assert len(progress_emissions) >= 3
