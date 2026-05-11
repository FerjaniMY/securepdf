"""Tests for batch processing.

We stub the inner `extract`/`detect`/`redact` calls so these tests run quickly
and don't depend on the spaCy model or Presidio being installed. The focus
here is the *batch orchestration*: input discovery, output paths, skip-existing,
manifest format, error capture.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from securepdf.batch.pipeline import FileResult, run_batch


@pytest.fixture
def pdf_tree(tmp_path: Path) -> Path:
    """Build an input tree:
      tmp/
        a.pdf
        b.pdf
        sub/c.pdf
    """
    for rel in ["a.pdf", "b.pdf", "sub/c.pdf"]:
        full = tmp_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), f"contents of {rel}", fontsize=12)
        doc.save(full)
        doc.close()
    return tmp_path


def _stubbed_pipeline(monkeypatch):
    """Replace the three inner pipeline functions with fast stubs."""
    monkeypatch.setattr(
        "securepdf.pdf.pipeline.extract",
        lambda path: ["fake_page"],
    )
    monkeypatch.setattr(
        "securepdf.detection.detect",
        lambda pages, **kw: ["d1", "d2", "d3"],
    )

    def _fake_redact(input_pdf, detections, pages=None, output_pdf=None, output_text=None, mode="both"):
        from securepdf.redaction.pipeline import RedactionResult
        if output_pdf:
            Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
            Path(output_pdf).write_text("fake redacted pdf bytes")
        if output_text:
            Path(output_text).parent.mkdir(parents=True, exist_ok=True)
            Path(output_text).write_text("fake anonymized text")
        return RedactionResult(
            pdf_path=Path(output_pdf) if output_pdf else None,
            text="fake anonymized text" if output_text else None,
            text_path=Path(output_text) if output_text else None,
        )

    monkeypatch.setattr("securepdf.redaction.pipeline.redact", _fake_redact)


def test_processes_all_pdfs_in_tree(pdf_tree, tmp_path, monkeypatch):
    _stubbed_pipeline(monkeypatch)
    out = tmp_path / "out"
    summary = run_batch(pdf_tree, out, use_stage2=False)
    assert summary.total == 3
    assert summary.succeeded == 3
    assert summary.failed == 0


def test_preserves_subdirectory_structure(pdf_tree, tmp_path, monkeypatch):
    _stubbed_pipeline(monkeypatch)
    out = tmp_path / "out"
    run_batch(pdf_tree, out, use_stage2=False)
    assert (out / "a.redacted.pdf").exists()
    assert (out / "sub" / "c.redacted.pdf").exists()


def test_writes_manifest_json(pdf_tree, tmp_path, monkeypatch):
    _stubbed_pipeline(monkeypatch)
    out = tmp_path / "out"
    run_batch(pdf_tree, out, use_stage2=False)
    manifest_path = out / "manifest.json"
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert data["total"] == 3
    assert data["succeeded"] == 3
    assert len(data["files"]) == 3
    # Each entry has the expected schema.
    for f in data["files"]:
        assert "input_path" in f
        assert "detection_count" in f
        assert "elapsed_seconds" in f


def test_skips_files_with_existing_outputs(pdf_tree, tmp_path, monkeypatch):
    _stubbed_pipeline(monkeypatch)
    out = tmp_path / "out"
    # First run — processes all 3.
    s1 = run_batch(pdf_tree, out, use_stage2=False)
    assert s1.skipped == 0
    # Second run — should skip all 3.
    s2 = run_batch(pdf_tree, out, use_stage2=False)
    assert s2.skipped == 3
    assert s2.succeeded == 0


def test_force_reprocesses_existing(pdf_tree, tmp_path, monkeypatch):
    _stubbed_pipeline(monkeypatch)
    out = tmp_path / "out"
    run_batch(pdf_tree, out, use_stage2=False)
    s2 = run_batch(pdf_tree, out, use_stage2=False, force=True)
    assert s2.skipped == 0
    assert s2.succeeded == 3


def test_continues_on_per_file_error(pdf_tree, tmp_path, monkeypatch):
    """If extract raises for one file, the batch records the error and continues."""
    bad = pdf_tree / "b.pdf"

    def _failing_extract(path):
        if Path(path) == bad:
            raise RuntimeError("boom")
        return ["fake_page"]

    monkeypatch.setattr("securepdf.pdf.pipeline.extract", _failing_extract)
    monkeypatch.setattr("securepdf.detection.detect", lambda p, **kw: [])

    def _stub_redact(input_pdf, detections, **kw):
        from securepdf.redaction.pipeline import RedactionResult
        out_pdf = kw.get("output_pdf")
        if out_pdf:
            Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
            Path(out_pdf).write_text("ok")
        return RedactionResult(pdf_path=Path(out_pdf) if out_pdf else None)

    monkeypatch.setattr("securepdf.redaction.pipeline.redact", _stub_redact)

    out = tmp_path / "out"
    summary = run_batch(pdf_tree, out, mode="pdf", use_stage2=False)
    assert summary.total == 3
    assert summary.succeeded == 2
    assert summary.failed == 1
    failures = [f for f in summary.files if f.error]
    assert len(failures) == 1
    assert "boom" in failures[0].error


def test_progress_callback_fires_for_each_file(pdf_tree, tmp_path, monkeypatch):
    _stubbed_pipeline(monkeypatch)
    out = tmp_path / "out"
    captured: list = []
    run_batch(pdf_tree, out, use_stage2=False, on_progress=captured.append)
    assert len(captured) == 3
    assert all(isinstance(r, FileResult) for r in captured)


def test_raises_when_input_dir_missing(tmp_path):
    with pytest.raises(NotADirectoryError):
        run_batch(tmp_path / "does-not-exist", tmp_path / "out")
