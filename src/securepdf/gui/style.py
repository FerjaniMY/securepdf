"""Editorial light theme — applied app-wide at startup.

Design direction
----------------
Clean, calm, considered. Off-white background, dark navy text, deliberate red
accent for actions that change state. Refined typography: system serif for
headlines (we set the font via `QFontDatabase` at startup), system sans for
body, monospace for data. Subtle borders, no shadows except very gentle
on focused inputs. Round corners at 4 px — present but quiet.

The whole stylesheet is one big QSS string. Qt's stylesheet engine is roughly
a CSS subset; selectors target widget classes (`QPushButton`), property
states (`:hover`, `:focus`), and dynamic properties (`[primary="true"]`)
that we set on individual widgets to opt them into emphasis variants.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

# Palette — kept here as named constants so other modules can reference the
# exact colors when they need to paint (e.g. PDF bbox overlays in pdf_viewer).
COLOR_BG = "#fafaf7"  # warm off-white, main surface
COLOR_PANEL = "#ffffff"  # cards, dialogs, tree backgrounds
COLOR_PANEL_ALT = "#f7f5ec"  # alternating row tint, hover background
COLOR_PANEL_HEADER = "#f5f3eb"  # toolbar / menubar / table header background
COLOR_BORDER = "#e8e6df"  # default border
COLOR_BORDER_STRONG = "#c8c4b8"  # input borders, button borders
COLOR_TEXT = "#1a1a1a"  # primary text
COLOR_TEXT_HEADING = "#0a0a0a"  # h1/h2 — slightly deeper
COLOR_TEXT_MUTED = "#6a6a60"  # captions, placeholders, disabled

COLOR_ACCENT = "#b3361f"  # editorial red — focus, primary action accent
COLOR_ACCENT_BG = "#ffe2dc"  # red-tinted selection background
COLOR_DESTRUCTIVE = "#b3361f"  # same red — destructive actions
COLOR_SUCCESS = "#2a7a2a"  # accepted-state indicator
COLOR_WARNING_BG = "#fff4d6"  # Ollama banner background
COLOR_WARNING_TEXT = "#5c4408"  # Ollama banner text


EDITORIAL_QSS = f"""
/* ─── Base ─────────────────────────────────────────────────── */
* {{
    color: {COLOR_TEXT};
    font-size: 13px;
}}
QMainWindow, QDialog, QWidget {{
    background-color: {COLOR_BG};
}}

/* ─── Menu bar / menus ─────────────────────────────────────── */
QMenuBar {{
    background-color: {COLOR_PANEL_HEADER};
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 4px 8px;
}}
QMenuBar::item {{
    padding: 6px 12px;
    background: transparent;
    border-radius: 3px;
}}
QMenuBar::item:selected {{ background-color: {COLOR_BORDER}; }}

QMenu {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    padding: 6px 0;
}}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background-color: {COLOR_PANEL_ALT}; }}
QMenu::separator {{
    height: 1px;
    background: {COLOR_BORDER};
    margin: 4px 12px;
}}

/* ─── Toolbar ──────────────────────────────────────────────── */
QToolBar {{
    background-color: {COLOR_PANEL};
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 6px 10px;
    spacing: 6px;
}}
QToolBar::separator {{
    background: {COLOR_BORDER};
    width: 1px;
    margin: 4px 4px;
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 6px 10px;
}}
QToolButton:hover {{
    background-color: {COLOR_PANEL_ALT};
    border-color: {COLOR_BORDER};
}}
QToolButton:disabled {{ color: {COLOR_TEXT_MUTED}; }}

/* ─── Buttons ──────────────────────────────────────────────── */
QPushButton {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER_STRONG};
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 18px;
}}
QPushButton:hover {{
    background-color: {COLOR_PANEL_ALT};
    border-color: #a8a496;
}}
QPushButton:disabled {{
    color: {COLOR_TEXT_MUTED};
    background-color: {COLOR_PANEL_HEADER};
    border-color: {COLOR_BORDER};
}}
QPushButton[primary="true"] {{
    background-color: {COLOR_TEXT_HEADING};
    color: {COLOR_BG};
    border-color: {COLOR_TEXT_HEADING};
}}
QPushButton[primary="true"]:hover {{ background-color: #2a2a2a; }}
QPushButton[destructive="true"] {{
    color: {COLOR_DESTRUCTIVE};
    border-color: {COLOR_DESTRUCTIVE};
}}
QPushButton[destructive="true"]:hover {{
    background-color: #fff5f3;
}}

/* ─── Inputs ───────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER_STRONG};
    border-radius: 4px;
    padding: 6px 8px;
    selection-background-color: {COLOR_ACCENT_BG};
    selection-color: {COLOR_TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {COLOR_ACCENT};
}}
QComboBox::drop-down {{
    width: 22px;
    border-left: 1px solid {COLOR_BORDER};
}}

/* ─── Lists / trees / tables ───────────────────────────────── */
QTreeWidget, QListWidget, QTableWidget, QTableView, QTreeView, QListView {{
    background-color: {COLOR_PANEL};
    alternate-background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_ACCENT_BG};
    selection-color: {COLOR_TEXT};
    outline: 0;
}}
QTreeWidget::item, QListWidget::item, QTableWidget::item {{
    padding: 4px 6px;
}}
QHeaderView::section {{
    background-color: {COLOR_PANEL_HEADER};
    color: {COLOR_TEXT_MUTED};
    font-weight: 600;
    font-size: 11px;
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
}}

/* ─── Status bar ───────────────────────────────────────────── */
QStatusBar {{
    background-color: {COLOR_PANEL_HEADER};
    color: {COLOR_TEXT_MUTED};
    border-top: 1px solid {COLOR_BORDER};
    padding: 2px 8px;
}}
QStatusBar QLabel {{ color: {COLOR_TEXT_MUTED}; }}

/* ─── Splitter ─────────────────────────────────────────────── */
QSplitter::handle {{ background-color: {COLOR_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ─── Tabs ─────────────────────────────────────────────────── */
QTabWidget::pane {{ border: 1px solid {COLOR_BORDER}; background: {COLOR_PANEL}; }}
QTabBar::tab {{
    background: {COLOR_PANEL_HEADER};
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    color: {COLOR_TEXT_MUTED};
    font-weight: 500;
}}
QTabBar::tab:hover {{ color: {COLOR_TEXT}; }}
QTabBar::tab:selected {{
    background: {COLOR_PANEL};
    color: {COLOR_TEXT_HEADING};
    border-bottom: 2px solid {COLOR_ACCENT};
}}

/* ─── Groupbox ─────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    background: {COLOR_BG};
    color: {COLOR_TEXT};
}}

/* ─── Progress bar ─────────────────────────────────────────── */
QProgressBar {{
    background: {COLOR_PANEL_ALT};
    border: none;
    border-radius: 4px;
    max-height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {COLOR_ACCENT};
    border-radius: 4px;
}}

/* ─── Check / radio ─────────────────────────────────────── */
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {COLOR_BORDER_STRONG};
    background: {COLOR_PANEL};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {COLOR_ACCENT};
    border-color: {COLOR_ACCENT};
}}
QCheckBox::indicator:disabled {{
    background: {COLOR_PANEL_ALT};
    border-color: {COLOR_BORDER};
}}

/* ─── Scrollbars ───────────────────────────────────────────── */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border: none;
    width: 10px;
    height: 10px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {COLOR_BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:hover {{ background: #a8a496; }}
QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ─── Dynamic-property variants (used by widgets via setProperty) ── */
QLabel[role="title"] {{
    font-family: "Source Serif 4", "Iowan Old Style", Georgia, serif;
    font-size: 22px;
    font-weight: 600;
    color: {COLOR_TEXT_HEADING};
}}
QLabel[role="subtitle"] {{
    font-size: 14px;
    color: {COLOR_TEXT_MUTED};
}}
QLabel[role="caption"] {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-weight: 500;
}}

/* ─── Tooltip ─────────────────────────────────────────────── */
QToolTip {{
    background-color: {COLOR_TEXT_HEADING};
    color: {COLOR_BG};
    border: none;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 12px;
}}
"""


def apply_editorial_style(app: QApplication) -> None:
    """Apply the editorial light stylesheet to the given QApplication.

    Call once at startup, after QApplication is constructed but before the
    main window is shown. Subsequent widgets pick up the stylesheet automatically.
    """
    app.setStyleSheet(EDITORIAL_QSS)
