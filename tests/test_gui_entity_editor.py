"""Tests for the EntityEditorDialog — data round-trip and validation."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_round_trip_patterns_keywords_descriptions(qapp):
    """Load YAML → tabs populated → dump back → same content."""
    from securepdf.gui.entity_editor import EntityEditorDialog

    yaml_in = """
patterns:
  - name: project_codename
    regex: '\\bPROJECT_[A-Z]+\\b'
    score: 0.9
keywords:
  - name: clients
    terms:
      - Acme Corp
      - Foo Inc.
descriptions:
  - Internal codenames like PROJECT_PHOENIX
  - Restricted client names
"""
    dlg = EntityEditorDialog(yaml_in)

    # Patterns: one row.
    assert dlg.patterns_tab.dump() == [
        {"name": "project_codename", "regex": "\\bPROJECT_[A-Z]+\\b", "score": 0.9}
    ]
    # Keywords: one group with two terms.
    assert dlg.keywords_tab.dump() == [
        {"name": "clients", "terms": ["Acme Corp", "Foo Inc."]}
    ]
    # Descriptions: two strings.
    assert dlg.descriptions_tab.dump() == [
        "Internal codenames like PROJECT_PHOENIX",
        "Restricted client names",
    ]

    # Render back to YAML — round-trip should be re-parseable.
    rendered = dlg.current_yaml()
    assert "project_codename" in rendered
    assert "Acme Corp" in rendered
    assert "PROJECT_PHOENIX" in rendered


def test_empty_initial_yaml_yields_empty_tabs(qapp):
    from securepdf.gui.entity_editor import EntityEditorDialog

    dlg = EntityEditorDialog("")
    assert dlg.patterns_tab.dump() == []
    assert dlg.keywords_tab.dump() == []
    assert dlg.descriptions_tab.dump() == []
    assert dlg.current_yaml() == ""


def test_unsafe_regex_rejected_on_apply(qapp):
    """A ReDoS-prone regex in the patterns tab should raise ValueError on dump()."""
    from securepdf.gui.entity_editor import EntityEditorDialog

    yaml_in = """
patterns:
  - name: evil
    regex: '(a+)+'
    score: 0.9
"""
    dlg = EntityEditorDialog(yaml_in)
    with pytest.raises(ValueError, match="nested unbounded quantifier"):
        dlg.patterns_tab.dump()


def test_invalid_score_rejected(qapp):
    """Non-numeric score should surface a row-specific error."""
    from securepdf.gui.entity_editor import EntityEditorDialog
    from PySide6.QtWidgets import QTableWidgetItem

    dlg = EntityEditorDialog("")
    dlg.patterns_tab.load([{"name": "x", "regex": r"\bx\b", "score": 0.5}])
    # Corrupt the score cell.
    dlg.patterns_tab._table.setItem(0, 2, QTableWidgetItem("not-a-number"))  # noqa: SLF001
    with pytest.raises(ValueError, match="score must be a number"):
        dlg.patterns_tab.dump()


def test_empty_keyword_group_rejected(qapp):
    """A keyword group with no terms should raise on dump."""
    from securepdf.gui.entity_editor import EntityEditorDialog
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    dlg = EntityEditorDialog("")
    # Add a group with no terms.
    item = QListWidgetItem("empty_group")
    item.setData(Qt.ItemDataRole.UserRole, [])
    dlg.keywords_tab._groups.addItem(item)  # noqa: SLF001

    with pytest.raises(ValueError, match="needs at least one term"):
        dlg.keywords_tab.dump()


def test_apply_signal_emits_yaml(qapp):
    """Clicking Apply (via _on_apply) emits profile_applied with the YAML."""
    from securepdf.gui.entity_editor import EntityEditorDialog

    yaml_in = """
descriptions:
  - foo
  - bar
"""
    dlg = EntityEditorDialog(yaml_in)
    captured = []
    dlg.profile_applied.connect(captured.append)
    dlg._on_apply()  # noqa: SLF001 — bypass the button click; tests the slot directly
    assert len(captured) == 1
    assert "foo" in captured[0] and "bar" in captured[0]
