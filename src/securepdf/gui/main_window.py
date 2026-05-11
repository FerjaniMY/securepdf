"""SecurePDF main window — wires together the pipeline worker, viewer, and
detection panel.

Layout:

  ┌──────────────────────────────────────────────────────────┐
  │ File  Edit  Help                                         │  ← menu bar
  ├──────────────────────────────────────────────────────────┤
  │ [Open] [Process] [Save Outputs]              [⚙ Prefs]   │  ← toolbar
  ├──────────────────────────────────────────────────────────┤
  │ Ollama banner (if not available)                         │  ← optional
  ├─────────────────────────┬────────────────────────────────┤
  │                         │  Page nav: [<] page 1/5 [>]    │
  │                         │  ╭──────────────────────────╮  │
  │  Documents              │  │                          │  │
  │  • report1.pdf          │  │   PDF preview with bbox   │  │
  │  • report2.pdf          │  │   overlays                │  │
  │  • report3.pdf          │  │                          │  │
  │                         │  ╰──────────────────────────╯  │
  ├─────────────────────────┴────────────────────────────────┤
  │  Detections (12 of 24 will redact)        [✓ All] [✗ All] │
  │  ☑ Page 1 │ PERSON     │ "Jane Doe"       │ 0.85 │ presidio │
  │  ☑ Page 1 │ DATE_TIME  │ "1985-03-22"     │ 0.85 │ presidio │
  │  ...                                                       │
  └────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from securepdf.detection.models import Detection
from securepdf.gui.detection_panel import DetectionPanel
from securepdf.gui.document_session import DocumentSession
from securepdf.gui.onboarding import OllamaBanner
from securepdf.gui.pdf_viewer import PdfViewer
from securepdf.gui.settings_dialog import DetectorSettings, SettingsDialog
from securepdf.gui.worker import PipelineWorker, WorkerJob
from securepdf.pdf.models import PageContent

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level window. Owns sessions, worker thread, and all child widgets."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SecurePDF")
        self.resize(1280, 800)

        # ---- State ----
        # Multiple PDFs can be opened; one is "active" at any time.
        self._sessions: Dict[str, DocumentSession] = {}
        self._active_path: Path | None = None
        self._settings = DetectorSettings()
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None

        # ---- Widgets ----
        self._build_actions()
        self._build_central_widget()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()

        # First-run Ollama check — fires after the window is shown so dialog
        # latency doesn't delay first paint.
        self._ollama_banner.check_and_show()

    # -------------------------------------------------------------------
    # Layout construction
    # -------------------------------------------------------------------

    def _build_actions(self) -> None:
        self._action_open = QAction("&Open PDF…", self)
        self._action_open.setShortcut(QKeySequence.StandardKey.Open)
        self._action_open.triggered.connect(self._on_open)

        self._action_process = QAction("&Process", self)
        self._action_process.setShortcut("Ctrl+R")
        self._action_process.setEnabled(False)
        self._action_process.triggered.connect(self._on_process)

        self._action_save = QAction("&Save Outputs…", self)
        self._action_save.setShortcut(QKeySequence.StandardKey.Save)
        self._action_save.setEnabled(False)
        self._action_save.triggered.connect(self._on_save)

        self._action_prefs = QAction("Preferences…", self)
        self._action_prefs.triggered.connect(self._on_preferences)

        self._action_quit = QAction("&Quit", self)
        self._action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self._action_quit.triggered.connect(self.close)

    def _build_central_widget(self) -> None:
        # The "central" widget actually contains the banner above the splitter.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._ollama_banner = OllamaBanner()
        layout.addWidget(self._ollama_banner)

        outer_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(outer_splitter, 1)

        # Top: file list (left) + viewer (right).
        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._file_list = QListWidget()
        self._file_list.setMinimumWidth(200)
        self._file_list.currentTextChanged.connect(self._on_file_selected)
        top_splitter.addWidget(self._file_list)

        viewer_pane = QWidget()
        vp_layout = QVBoxLayout(viewer_pane)
        vp_layout.setContentsMargins(6, 6, 6, 6)
        nav_row = QHBoxLayout()
        self._prev_btn = QPushButton("← Prev")
        self._next_btn = QPushButton("Next →")
        self._page_label = QLabel("Page —")
        self._prev_btn.clicked.connect(self._on_prev_page)
        self._next_btn.clicked.connect(self._on_next_page)
        self._prev_btn.setEnabled(False)
        self._next_btn.setEnabled(False)
        nav_row.addWidget(self._prev_btn)
        nav_row.addWidget(self._next_btn)
        nav_row.addStretch(1)
        nav_row.addWidget(self._page_label)
        vp_layout.addLayout(nav_row)

        self._viewer = PdfViewer()
        self._viewer.page_changed.connect(self._update_page_label)
        vp_layout.addWidget(self._viewer, 1)
        top_splitter.addWidget(viewer_pane)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 4)

        outer_splitter.addWidget(top_splitter)

        # Bottom: detection panel.
        self._detection_panel = DetectionPanel()
        self._detection_panel.decisions_changed.connect(self._on_decisions_changed)
        self._detection_panel.row_activated.connect(self._on_detection_activated)
        outer_splitter.addWidget(self._detection_panel)
        outer_splitter.setStretchFactor(0, 3)
        outer_splitter.setStretchFactor(1, 2)

        self.setCentralWidget(container)
        self.setAcceptDrops(True)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self._action_open)
        file_menu.addAction(self._action_process)
        file_menu.addAction(self._action_save)
        file_menu.addSeparator()
        file_menu.addAction(self._action_quit)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self._action_prefs)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.addAction(self._action_open)
        tb.addAction(self._action_process)
        tb.addAction(self._action_save)
        tb.addSeparator()
        tb.addAction(self._action_prefs)
        self.addToolBar(tb)

    def _build_status_bar(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        status.addPermanentWidget(self._progress)
        self._status_message = QLabel("Ready")
        status.addWidget(self._status_message, 1)

    # -------------------------------------------------------------------
    # Drag-drop
    # -------------------------------------------------------------------

    def dragEnterEvent(self, event):  # noqa: N802 — Qt method name
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile().lower().endswith(".pdf") for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802 — Qt method name
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local.lower().endswith(".pdf"):
                self._open_pdf(Path(local))

    # -------------------------------------------------------------------
    # File actions
    # -------------------------------------------------------------------

    def _on_open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF files (*.pdf)"
        )
        if path_str:
            self._open_pdf(Path(path_str))

    def _open_pdf(self, path: Path) -> None:
        key = str(path)
        if key not in self._sessions:
            self._sessions[key] = DocumentSession(path=path)
            self._file_list.addItem(path.name)
        # Make this the active doc.
        items = self._file_list.findItems(path.name, Qt.MatchFlag.MatchExactly)
        if items:
            self._file_list.setCurrentItem(items[0])
        self._set_active(path)

    def _on_file_selected(self, text: str) -> None:
        # Map the visible name back to the path. Names are unique within the
        # list since we de-dupe on `key = str(path)` in `_open_pdf`.
        for key in self._sessions:
            if Path(key).name == text:
                self._set_active(Path(key))
                break

    def _set_active(self, path: Path) -> None:
        self._active_path = path
        session = self._sessions[str(path)]
        self._viewer.load(path)
        self._detection_panel.set_session(session)
        self._refresh_overlays()
        self._action_process.setEnabled(True)
        self._action_save.setEnabled(session.processed and session.accepted_count > 0)
        self._prev_btn.setEnabled(self._viewer.page_count > 1)
        self._next_btn.setEnabled(self._viewer.page_count > 1)
        self._update_page_label(self._viewer.current_page)
        self._status_message.setText(f"Loaded: {path.name}")

    # -------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------

    def _on_process(self) -> None:
        if not self._active_path:
            return
        if self._thread and self._thread.isRunning():
            QMessageBox.information(
                self, "Busy", "Already processing. Wait for the current job to finish."
            )
            return
        self._start_worker(
            WorkerJob(
                pdf_path=self._active_path,
                use_stage2=self._settings.use_stage2,
                spacy_model=self._settings.spacy_model,
            )
        )

    def _start_worker(self, job: WorkerJob) -> None:
        # Stand up a fresh thread + worker for each job. Cheap and avoids any
        # state leakage from previous runs.
        self._thread = QThread(self)
        self._worker = PipelineWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(lambda: self._worker.run(job))
        self._worker.pages_ready.connect(self._on_pages_ready)
        self._worker.detections_ready.connect(self._on_detections_ready)
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)

        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._status_message.setText("Working…")
        self._action_process.setEnabled(False)
        self._thread.start()

    @Slot(list)
    def _on_pages_ready(self, pages: list[PageContent]) -> None:
        if not self._active_path:
            return
        session = self._sessions[str(self._active_path)]
        session.set_pages(pages)

    @Slot(list, str)
    def _on_detections_ready(self, detections: list[Detection], pdf_path: str) -> None:
        session = self._sessions.get(pdf_path)
        if session is None:
            return
        session.set_detections(detections)
        self._detection_panel.set_session(session)
        self._refresh_overlays()
        self._action_save.setEnabled(session.accepted_count > 0)

    @Slot(str, int)
    def _on_progress(self, message: str, pct: int) -> None:
        self._status_message.setText(message)
        self._progress.setValue(pct)

    @Slot(str)
    def _on_worker_failed(self, error: str) -> None:
        QMessageBox.critical(self, "Pipeline error", error)

    @Slot()
    def _on_thread_finished(self) -> None:
        self._progress.setVisible(False)
        self._action_process.setEnabled(self._active_path is not None)
        # Drop references so QThread/QObject can be GC'd cleanly.
        self._thread = None
        self._worker = None

    # -------------------------------------------------------------------
    # Save outputs
    # -------------------------------------------------------------------

    def _on_save(self) -> None:
        if not self._active_path:
            return
        session = self._sessions[str(self._active_path)]
        if not session.accepted_detections():
            QMessageBox.information(
                self,
                "Nothing to redact",
                "Accept at least one detection before saving outputs.",
            )
            return

        default_pdf = self._active_path.with_suffix(".redacted.pdf")
        out_pdf, _ = QFileDialog.getSaveFileName(
            self, "Save redacted PDF", str(default_pdf), "PDF (*.pdf)"
        )
        if not out_pdf:
            return
        default_txt = self._active_path.with_suffix(".anonymized.txt")
        out_txt, _ = QFileDialog.getSaveFileName(
            self, "Save anonymized text", str(default_txt), "Text (*.txt)"
        )

        from securepdf.redaction.pipeline import redact

        try:
            result = redact(
                self._active_path,
                session.accepted_detections(),
                pages=session.pages,
                output_pdf=out_pdf,
                output_text=out_txt or None,
                mode="both" if out_txt else "pdf",
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Redaction failed", str(e))
            return

        session.output_pdf = Path(out_pdf)
        session.output_text = Path(out_txt) if out_txt else None
        self._status_message.setText(
            f"Saved {result.pdf_path}"
            + (f" + {result.text_path}" if result.text_path else "")
        )

    # -------------------------------------------------------------------
    # Page navigation
    # -------------------------------------------------------------------

    def _on_prev_page(self) -> None:
        if self._viewer.page_count == 0:
            return
        self._viewer.set_page(max(0, self._viewer.current_page - 1))

    def _on_next_page(self) -> None:
        if self._viewer.page_count == 0:
            return
        self._viewer.set_page(
            min(self._viewer.page_count - 1, self._viewer.current_page + 1)
        )

    def _update_page_label(self, page_index: int) -> None:
        if self._viewer.page_count == 0:
            self._page_label.setText("Page —")
        else:
            self._page_label.setText(
                f"Page {page_index + 1} / {self._viewer.page_count}"
            )

    # -------------------------------------------------------------------
    # Detection panel slots
    # -------------------------------------------------------------------

    def _on_decisions_changed(self) -> None:
        self._refresh_overlays()
        if self._active_path:
            session = self._sessions[str(self._active_path)]
            self._action_save.setEnabled(session.accepted_count > 0)

    def _on_detection_activated(self, idx: int) -> None:
        """Jump the viewer to the page containing the clicked detection."""
        if not self._active_path:
            return
        session = self._sessions[str(self._active_path)]
        if 0 <= idx < session.detection_count:
            target_page = session.detections[idx].page
            self._viewer.set_page(target_page)

    def _refresh_overlays(self) -> None:
        if not self._active_path:
            return
        session = self._sessions[str(self._active_path)]
        overlays = [
            (d, session.decision_for(i)) for i, d in enumerate(session.detections)
        ]
        self._viewer.set_overlays(overlays)

    # -------------------------------------------------------------------
    # Preferences
    # -------------------------------------------------------------------

    def _on_preferences(self) -> None:
        dlg = SettingsDialog(self._settings, parent=self)
        if dlg.exec():
            self._settings = dlg.values()
            log.info("Settings updated: %s", self._settings)
