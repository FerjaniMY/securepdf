"""Tests for the unified Save Outputs dialog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_default_state_pdf_and_text_selected(qapp):
    from securepdf.gui.save_dialog import SaveOutputsDialog

    dlg = SaveOutputsDialog(Path("/tmp/report.pdf"))
    result = dlg.result_data()
    # `cancelled` is False here because we manually snapshot — it's the caller's
    # responsibility to set cancelled=True when QDialog.exec() returns 0.
    assert result.save_pdf is True
    assert result.save_text is True
    assert result.save_map is False  # opt-in by default — risky
    assert result.has_anything is True


def test_default_paths_match_input_stem(qapp):
    from securepdf.gui.save_dialog import SaveOutputsDialog

    dlg = SaveOutputsDialog(Path("/tmp/medical_record.pdf"))
    result = dlg.result_data()
    assert result.pdf_path is not None
    assert result.pdf_path.name == "medical_record.redacted.pdf"
    assert result.text_path is not None
    assert result.text_path.name == "medical_record.anonymized.txt"


def test_unchecking_all_disables_save_button(qapp):
    from securepdf.gui.save_dialog import SaveOutputsDialog

    dlg = SaveOutputsDialog(Path("/tmp/x.pdf"))
    dlg.pdf_row.checkbox.setChecked(False)
    dlg.text_row.checkbox.setChecked(False)
    # map_row is unchecked by default
    assert not dlg._save_btn.isEnabled()  # noqa: SLF001
    # Re-check one — save becomes available again.
    dlg.text_row.checkbox.setChecked(True)
    assert dlg._save_btn.isEnabled()  # noqa: SLF001


def test_paths_none_when_box_unchecked(qapp):
    from securepdf.gui.save_dialog import SaveOutputsDialog

    dlg = SaveOutputsDialog(Path("/tmp/x.pdf"))
    dlg.pdf_row.checkbox.setChecked(False)
    result = dlg.result_data()
    assert result.save_pdf is False
    assert result.pdf_path is None
    # Text still on by default.
    assert result.save_text is True
    assert result.text_path is not None


def test_write_pseudonym_map_round_trip(tmp_path):
    """The helper writes JSON we can re-load and parse."""
    from securepdf.gui.save_dialog import write_pseudonym_map

    out = tmp_path / "decoder.json"
    mapping = {"[PERSON_1]": "Jane Doe", "[EMAIL_ADDRESS_1]": "jane@example.com"}
    write_pseudonym_map(out, mapping)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded == mapping
