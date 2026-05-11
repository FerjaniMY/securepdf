"""SecurePDF desktop GUI (PySide6).

The Qt layer wraps the headless pipeline (`extract` → `detect` → `redact`) in a
drag-and-drop interface with human-in-the-loop review of every detection before
redactions are committed.

Entry point: `python -m securepdf.gui` or the installed `securepdf-gui` console script.

Import hygiene
--------------
This package's __init__ deliberately does NOT eager-import PySide6. Tests for
non-Qt sub-modules (e.g. `document_session.py`, which is pure data) should be
runnable in environments without a graphical toolkit. Import the specific
modules you need (e.g. `from securepdf.gui.app import main`).
"""

# Intentionally no top-level imports. See module docstring for rationale.
