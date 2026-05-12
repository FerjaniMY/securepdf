"""SecurePDF main window — wires together the pipeline worker, viewer, and
detection panel.

Layout:

  ┌──────────────────────────────────────────────────────────┐
  │ File  Edit  Help                                         │  ← menu bar
  ├──────────────────────────────────────────────────────────┤
  │ [Open] [Process] [Save] [Preview redacted]   [⚙ Prefs]   │  ← toolbar
  ├──────────────────────────────────────────────────────────┤
  │ Ollama banner (if not available)                         │  ← optional
  ├─────────────────────────┬────────────────────────────────┤
  │                         │  Page nav: [<] page 1/5 [>]    │
  │  Documents              │  ╭──────────────────────────╮  │
  │  • report1.pdf          │  │   PDF preview            │  │
  │  • report2.pdf          │  │   (or welcome panel)     │  │
  │                         │  ╰──────────────────────────╯  │
  ├─────────────────────────┴────────────────────────────────┤
  │ Detections (filter row) (12 of 24)  [✓ All] [✗ All]      │
  │ ☑ Page 1 │ PERSON     │ "Jane Doe"      │ 0.85 │ presidio │
  │ ...                                                       │
  └────────────────────────────────────────────────────────────┘

v1.0 additions
--------------
- Welcome / empty-state widget shown when no document is loaded
- Recent files submenu (last 10 PDFs, persisted via QSettings)
- Help → About dialog
- Edit → "Custom entity profile…" opens the new entity editor
- "Preview redacted" toggle in the page-nav row, renders side-by-side
- Unified Save Outputs dialog replaces the previous two-QFileDialog flow
- Window state, splitter positions, recent files, and DetectorSettings
  all persist via QSettings between sessions
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Dict

from PySide6.QtCore import Qt, QThread, QSettings, Slot
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
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from securepdf.detection.models import Detection
from securepdf.gui.about_dialog import AboutDialog
from securepdf.gui.detection_panel import DetectionPanel
from securepdf.gui.document_session import DocumentSession
from securepdf.gui.entity_editor import EntityEditorDialog
from securepdf.gui.onboarding import OllamaBanner
from securepdf.gui.pdf_viewer import PdfViewer
from securepdf.gui.save_dialog import SaveOutputsDialog, write_pseudonym_map
from securepdf.gui.settings_dialog import DetectorSettings, SettingsDialog
from securepdf.gui.welcome_widget import WelcomeWidget
from securepdf.gui.worker import PipelineWorker, WorkerJob
from securepdf.pdf.models import PageContent

log = logging.getLogger(__name__)


# QSettings keys for window/splitter/recent state.
_QS_GEOMETRY = "window/geometry"
_QS_STATE = "window/state"
_QS_SPLITTER_OUTER = "splitter/outer"
_QS_SPLITTER_TOP = "splitter/top"
_QS_RECENT = "recent_files"

# Max number of files in the Recent submenu.
_RECENT_MAX = 10


class MainWindow(QMainWindow):
    """Top-level window. Owns sessions, worker thread, and all child widgets."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SecurePDF")
        self.resize(1280, 800)

        # ---- Persistence ----
        self._qsettings = QSettings("SecurePDF", "SecurePDF")
        self._settings = DetectorSettings.load_from(self._qsettings)
        raw_recent = self._qsettings.value(_QS_RECENT, []) or []
        # QSettings on some platforms hands back a str instead of a list when
        # there's exactly one entry; coerce defensively.
        if isinstance(raw_recent, str):
            raw_recent = [raw_recent]
        self._recent_files: list[str] = [str(p) for p in raw_recent][:_RECENT_MAX]

        # ---- Per-document state ----
        self._sessions: Dict[str, DocumentSession] = {}
        self._active_path: Path | None = None
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        # Tempdir for redacted-preview PDFs (used by the side-by-side viewer
        # mode). Lazily created on first preview request; cleaned up on quit.
        self._preview_tempdir: Path | None = None

        # ---- Widgets ----
        self._build_actions()
        self._build_central_widget()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._restore_window_state()

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

        self._action_prefs = QAction("&Preferences…", self)
        self._action_prefs.triggered.connect(self._on_preferences)

        self._action_edit_profile = QAction("Custom &entity profile…", self)
        self._action_edit_profile.triggered.connect(self._on_edit_profile)

        self._action_about = QAction("&About SecurePDF", self)
        self._action_about.triggered.connect(self._on_about)

        self._action_quit = QAction("&Quit", self)
        self._action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self._action_quit.triggered.connect(self.close)

    def _build_central_widget(self) -> None:
        # The "central" widget contains the banner above the splitter layout.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._ollama_banner = OllamaBanner()
        layout.addWidget(self._ollama_banner)

        # Outer splitter: top = (file list + viewer); bottom = detection panel.
        self._outer_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(self._outer_splitter, 1)

        # Top splitter: file list (left) + viewer pane (right).
        self._top_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._file_list = QListWidget()
        self._file_list.setMinimumWidth(200)
        self._file_list.currentTextChanged.connect(self._on_file_selected)
        self._top_splitter.addWidget(self._file_list)

        viewer_pane = QWidget()
        vp_layout = QVBoxLayout(viewer_pane)
        vp_layout.setContentsMargins(6, 6, 6, 6)

        # Navigation row: prev / next page, preview toggle, page label.
        nav_row = QHBoxLayout()
        self._prev_btn = QPushButton("← Prev")
        self._next_btn = QPushButton("Next →")
        self._page_label = QLabel("Page —")
        self._preview_toggle = QPushButton("Preview redacted")
        self._preview_toggle.setCheckable(True)
        self._preview_toggle.setEnabled(False)
        self._preview_toggle.toggled.connect(self._on_toggle_preview)
        self._prev_btn.clicked.connect(self._on_prev_page)
        self._next_btn.clicked.connect(self._on_next_page)
        self._prev_btn.setEnabled(False)
        self._next_btn.setEnabled(False)
        nav_row.addWidget(self._prev_btn)
        nav_row.addWidget(self._next_btn)
        nav_row.addStretch(1)
        nav_row.addWidget(self._preview_toggle)
        nav_row.addWidget(self._page_label)
        vp_layout.addLayout(nav_row)

        # Stacked widget: index 0 = welcome, index 1 = real PDF viewer.
        self._viewer_stack = QStackedWidget()
        self._welcome = WelcomeWidget()
        self._welcome.open_requested.connect(self._on_open)
        self._welcome.files_dropped.connect(self._on_files_dropped)
        self._viewer = PdfViewer()
        self._viewer.page_changed.connect(self._update_page_label)
        self._viewer_stack.addWidget(self._welcome)
        self._viewer_stack.addWidget(self._viewer)
        self._viewer_stack.setCurrentIndex(0)
        vp_layout.addWidget(self._viewer_stack, 1)

        self._top_splitter.addWidget(viewer_pane)
        self._top_splitter.setStretchFactor(0, 1)
        self._top_splitter.setStretchFactor(1, 4)
        self._outer_splitter.addWidget(self._top_splitter)

        # Bottom: detection panel.
        self._detection_panel = DetectionPanel()
        self._detection_panel.decisions_changed.connect(self._on_decisions_changed)
        self._detection_panel.row_activated.connect(self._on_detection_activated)
        self._outer_splitter.addWidget(self._detection_panel)
        self._outer_splitter.setStretchFactor(0, 3)
        self._outer_splitter.setStretchFactor(1, 2)

        self.setCentralWidget(container)
        self.setAcceptDrops(True)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self._action_open)
        # Recent submenu — populated dynamically each time the menu is shown.
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self._action_process)
        file_menu.addAction(self._action_save)
        file_menu.addSeparator()
        file_menu.addAction(self._action_quit)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self._action_prefs)
        edit_menu.addAction(self._action_edit_profile)

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self._action_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.addAction(self._action_open)
        tb.addAction(self._action_process)
        tb.addAction(self._action_save)
        tb.addSeparator()
        tb.addAction(self._action_edit_profile)
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
    # Window state persistence
    # -------------------------------------------------------------------

    def _restore_window_state(self) -> None:
        """Restore window/splitter state from QSettings (if previously saved)."""
        geom = self._qsettings.value(_QS_GEOMETRY)
        if geom:
            self.restoreGeometry(geom)
        state = self._qsettings.value(_QS_STATE)
        if state:
            self.restoreState(state)
        outer_state = self._qsettings.value(_QS_SPLITTER_OUTER)
        if outer_state:
            self._outer_splitter.restoreState(outer_state)
        top_state = self._qsettings.value(_QS_SPLITTER_TOP)
        if top_state:
            self._top_splitter.restoreState(top_state)

    def closeEvent(self, event):  # noqa: N802 — Qt method name
        """Persist state and clean up the preview tempdir."""
        try:
            self._qsettings.setValue(_QS_GEOMETRY, self.saveGeometry())
            self._qsettings.setValue(_QS_STATE, self.saveState())
            self._qsettings.setValue(_QS_SPLITTER_OUTER, self._outer_splitter.saveState())
            self._qsettings.setValue(_QS_SPLITTER_TOP, self._top_splitter.saveState())
            self._qsettings.setValue(_QS_RECENT, self._recent_files[:_RECENT_MAX])
            self._settings.save_to(self._qsettings)
        except Exception:  # noqa: BLE001 — never block close on a setting save failure
            log.exception("Failed to persist window state on close")

        if self._preview_tempdir and self._preview_tempdir.exists():
            shutil.rmtree(self._preview_tempdir, ignore_errors=True)

        super().closeEvent(event)

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

    def _on_files_dropped(self, paths: list[Path]) -> None:
        for p in paths:
            self._open_pdf(p)

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
        if not path.exists():
            # Recent file may have been deleted/moved. Clean up + tell user.
            QMessageBox.warning(self, "File not found", f"{path}\n\nNo longer accessible.")
            if str(path) in self._recent_files:
                self._recent_files.remove(str(path))
            return

        key = str(path)
        if key not in self._sessions:
            self._sessions[key] = DocumentSession(path=path)
            self._file_list.addItem(path.name)

        # Maintain recent-files order: most-recent first, cap at N.
        if key in self._recent_files:
            self._recent_files.remove(key)
        self._recent_files.insert(0, key)
        self._recent_files = self._recent_files[:_RECENT_MAX]

        # Flip the stacked widget to show the real viewer (away from welcome).
        self._viewer_stack.setCurrentIndex(1)

        items = self._file_list.findItems(path.name, Qt.MatchFlag.MatchExactly)
        if items:
            self._file_list.setCurrentItem(items[0])
        self._set_active(path)

    def _on_file_selected(self, text: str) -> None:
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
        # Reset preview toggle for the newly-active doc.
        self._preview_toggle.blockSignals(True)
        self._preview_toggle.setChecked(False)
        self._preview_toggle.setEnabled(session.processed and session.accepted_count > 0)
        self._preview_toggle.blockSignals(False)
        self._viewer.show_redacted_preview(False)
        self._prev_btn.setEnabled(self._viewer.page_count > 1)
        self._next_btn.setEnabled(self._viewer.page_count > 1)
        self._update_page_label(self._viewer.current_page)
        self._status_message.setText(f"Loaded: {path.name}")

    # -------------------------------------------------------------------
    # Recent files menu
    # -------------------------------------------------------------------

    def _rebuild_recent_menu(self) -> None:
        """Refresh the Recent submenu just before it's shown."""
        self._recent_menu.clear()
        # Filter out non-existing paths so they don't reappear.
        self._recent_files = [p for p in self._recent_files if Path(p).exists()][:_RECENT_MAX]
        if not self._recent_files:
            placeholder = self._recent_menu.addAction("(no recent files)")
            placeholder.setEnabled(False)
            return
        for path_str in self._recent_files:
            p = Path(path_str)
            action = self._recent_menu.addAction(p.name)
            action.setToolTip(path_str)
            # Bind path explicitly via default argument — closures over loop
            # variables are a classic Python bug otherwise.
            action.triggered.connect(lambda checked=False, path=p: self._open_pdf(path))
        self._recent_menu.addSeparator()
        clear = self._recent_menu.addAction("Clear Recent")
        clear.triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        self._recent_files.clear()
        self._qsettings.setValue(_QS_RECENT, [])

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
                profile_yaml=self._settings.profile_yaml,
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
        self._preview_toggle.setEnabled(session.accepted_count > 0)

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
    # Save outputs (unified dialog)
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

        dlg = SaveOutputsDialog(self._active_path, parent=self)
        if not dlg.exec():
            return
        choice = dlg.result_data()
        if not choice.has_anything:
            return

        # Run the redaction pipeline based on the user's selection.
        from securepdf.redaction.pipeline import redact

        # `redact()` handles either PDF, text, or both. The map JSON is a GUI
        # add-on we serialize ourselves from the returned PseudonymMap.
        mode = (
            "both"
            if choice.save_pdf and choice.save_text
            else "pdf"
            if choice.save_pdf
            else "text"
        )
        try:
            result = redact(
                self._active_path,
                session.accepted_detections(),
                pages=session.pages,
                output_pdf=choice.pdf_path if choice.save_pdf else None,
                output_text=choice.text_path if choice.save_text else None,
                mode=mode,
            )
            if choice.save_map and result.pseudonym_map and choice.map_path:
                write_pseudonym_map(
                    choice.map_path,
                    result.pseudonym_map.as_key_dict(),
                )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Redaction failed", str(e))
            return

        session.output_pdf = choice.pdf_path
        session.output_text = choice.text_path
        parts = []
        if result.pdf_path:
            parts.append(str(result.pdf_path))
        if result.text_path:
            parts.append(str(result.text_path))
        if choice.save_map and choice.map_path:
            parts.append(str(choice.map_path))
        self._status_message.setText("Saved: " + ", ".join(parts))

    # -------------------------------------------------------------------
    # Side-by-side preview
    # -------------------------------------------------------------------

    def _on_toggle_preview(self, on: bool) -> None:
        """Render or hide the redacted preview."""
        if not self._active_path:
            self._preview_toggle.setChecked(False)
            return
        session = self._sessions[str(self._active_path)]
        if on and session.accepted_detections():
            try:
                self._render_redacted_preview(session)
            except Exception as e:  # noqa: BLE001
                log.exception("Preview render failed")
                QMessageBox.critical(self, "Preview failed", str(e))
                self._preview_toggle.setChecked(False)
                return
            self._viewer.show_redacted_preview(True)
            self._status_message.setText("Showing side-by-side redacted preview")
        else:
            self._viewer.show_redacted_preview(False)
            if on:
                # User toggled on but there's nothing accepted; auto-clear.
                self._preview_toggle.setChecked(False)

    def _render_redacted_preview(self, session: DocumentSession) -> None:
        """Render the accepted detections to a tempfile and hand it to the viewer."""
        from securepdf.redaction.pdf_renderer import render_redacted_pdf

        if self._preview_tempdir is None:
            self._preview_tempdir = Path(tempfile.mkdtemp(prefix="securepdf_preview_"))
        preview_path = self._preview_tempdir / f"preview_{session.path.name}"
        render_redacted_pdf(
            session.path,
            preview_path,
            session.accepted_detections(),
        )
        self._viewer.set_redacted_preview_path(preview_path)

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
            self._preview_toggle.setEnabled(session.accepted_count > 0)
            # If preview is showing, re-render so the user sees the impact of
            # their decision change immediately.
            if self._viewer.is_showing_preview and session.accepted_detections():
                try:
                    self._render_redacted_preview(session)
                except Exception:  # noqa: BLE001
                    log.exception("Failed to refresh preview after decision change")

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
    # Preferences / entity editor / about
    # -------------------------------------------------------------------

    def _on_preferences(self) -> None:
        dlg = SettingsDialog(self._settings, parent=self)
        if dlg.exec():
            self._settings = dlg.values()
            self._settings.save_to(self._qsettings)
            log.info("Settings updated")

    def _on_edit_profile(self) -> None:
        dlg = EntityEditorDialog(self._settings.profile_yaml, parent=self)
        dlg.profile_applied.connect(self._on_profile_applied)
        dlg.exec()

    def _on_profile_applied(self, yaml_text: str) -> None:
        self._settings.profile_yaml = yaml_text
        self._settings.save_to(self._qsettings)
        if yaml_text.strip():
            self._status_message.setText(
                f"Custom entity profile applied ({len(yaml_text)} chars). "
                "Press Process to re-detect with the new profile."
            )
        else:
            self._status_message.setText("Custom entity profile cleared")

    def _on_about(self) -> None:
        AboutDialog(parent=self).exec()
