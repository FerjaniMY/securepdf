"""Background pipeline runner using Qt's QThread + signals.

Why a worker thread
-------------------
Running `extract()` + `detect()` on the GUI thread freezes the window for
multiple seconds (potentially minutes with the Gemma stage). PyQt's standard
answer is `QThread` with a worker `QObject` moved onto it.

Signal contract
---------------
The worker emits four signals the GUI listens to:

  pages_ready(pages)      — after PDF extraction; UI can render the document
  detections_ready(detections, document_path)
                          — after detection finishes
  progress(message, pct)  — for status bar updates ("Detecting page 3/12")
  failed(error_message)   — if anything raised; the GUI shows a dialog

The worker takes a `WorkerJob` so callers configure exactly what to run; the
worker itself doesn't know GUI state.

Custom entity profiles
----------------------
A profile can be supplied either as a path to a YAML file on disk (the
headless CLI path) OR as a YAML string in memory (the GUI path, where the
entity editor dialog hands us back the live YAML). Either, never both —
inline takes precedence if both are set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from securepdf.detection.custom_entities import (
    CustomEntityProfile,
    load_profile,
    parse_profile,
)
from securepdf.detection.models import Detection
from securepdf.pdf.models import PageContent

log = logging.getLogger(__name__)


@dataclass
class WorkerJob:
    """Configuration for one pipeline run."""

    pdf_path: Path
    use_stage2: bool = True
    spacy_model: str = "en_core_web_sm"
    profile_path: Path | None = None  # optional YAML custom entities (from disk)
    profile_yaml: str = ""  # optional YAML body (from GUI editor); wins over path


class PipelineWorker(QObject):
    """Run extract → detect on a Qt thread and emit progress signals.

    Used pattern:
        thread = QThread()
        worker = PipelineWorker()
        worker.moveToThread(thread)
        thread.started.connect(lambda: worker.run(job))
        worker.detections_ready.connect(on_done)
        worker.failed.connect(on_error)
        thread.start()
    """

    pages_ready = Signal(list)  # list[PageContent]
    detections_ready = Signal(list, str)  # list[Detection], pdf_path (str)
    progress = Signal(str, int)  # status message, percent (0–100)
    failed = Signal(str)
    finished = Signal()  # always fires last, success or failure

    @Slot(object)
    def run(self, job: WorkerJob) -> None:
        """Execute the pipeline. This method runs on the worker thread.

        We import the pipeline modules here, not at module top, to defer the
        spaCy model load until the first job runs — keeps GUI startup snappy.
        """
        try:
            self.progress.emit(f"Extracting {job.pdf_path.name}…", 0)
            from securepdf.pdf.pipeline import extract
            pages: list[PageContent] = extract(job.pdf_path)
            self.pages_ready.emit(pages)
            self.progress.emit(f"Extracted {len(pages)} pages", 20)

            profile: CustomEntityProfile | None = None
            if job.profile_yaml.strip():
                self.progress.emit("Parsing custom entity profile…", 25)
                profile = parse_profile(job.profile_yaml)
            elif job.profile_path:
                self.progress.emit("Loading custom entity profile…", 25)
                profile = load_profile(job.profile_path)

            self.progress.emit("Detecting sensitive content…", 30)
            from securepdf.detection import detect
            detections: list[Detection] = detect(
                pages,
                profile=profile,
                spacy_model=job.spacy_model,
                use_stage2=job.use_stage2,
            )
            self.progress.emit(
                f"Found {len(detections)} sensitive spans", 100
            )
            self.detections_ready.emit(detections, str(job.pdf_path))
        except Exception as e:  # noqa: BLE001 — surface any pipeline error to the UI
            log.exception("Pipeline worker failed")
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            self.finished.emit()
