"""Locked-only search and catalog accessibility regression, stdlib-only Qt source audit.

Qt and the PDF/DXF rendering engine are not imported. The GUI search handler
is AST-extracted and executed with a small fake widget contract so that the
actual search method is tested without a Windows display server.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from drawing_editor.ui_interaction import (
    layer_search_feedback, matching_editable_layers,
)

ROOT = Path(__file__).resolve().parents[1]
WINDOW = (ROOT / "drawing_editor" / "window.py").read_text(encoding="utf-8")
TREE = ast.parse(WINDOW)
WINDOW_CLASS = next(
    obj for obj in TREE.body if isinstance(obj, ast.ClassDef) and obj.name == "DrawingWindow"
)


def source_of(method: str) -> str:
    node = next(
        obj for obj in WINDOW_CLASS.body
        if isinstance(obj, ast.FunctionDef) and obj.name == method
    )
    return ast.get_source_segment(WINDOW, node)


def search_method():
    node = next(
        obj for obj in WINDOW_CLASS.body
        if isinstance(obj, ast.FunctionDef) and obj.name == "_filter_layers"
    )
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {"layer_search_feedback": layer_search_feedback}
    exec(compile(module, str(ROOT / "drawing_editor" / "window.py"), "exec"),
         namespace)
    return namespace["_filter_layers"]


class Label:
    def __init__(self):
        self.text_value = None
        self.visible = None

    def setText(self, value):
        self.text_value = value

    def setVisible(self, flag):
        self.visible = flag


class Entry:
    def __init__(self, name):
        self.name = name
        self.hidden = False

    def text(self, column):
        assert column == 0
        return self.name

    def setHidden(self, flag):
        self.hidden = bool(flag)


class FakeButton:
    def __init__(self):
        self.enabled = False

    def isEnabled(self):
        return self.enabled


class FakeContext:
    def __init__(self, query, layers):
        self.query = query
        self.layers = layers
        self.rows = [Entry(layer.name) for layer in layers]
        self.layer_list = SimpleNamespace(
            topLevelItemCount=lambda: len(self.rows),
            topLevelItem=lambda i: self.rows[i],
        )
        self.layer_search = SimpleNamespace(text=lambda: query)
        self.filter_on_button = FakeButton()
        self.layer_empty_hint = Label()
        self.filtered_actions = Label()
        self.summary_matches = None
        self.synchronized = 0

    def _update_layer_summary(self, matches):
        self.summary_matches = matches

    def _sync_actions(self):
        self.synchronized += 1
        self.filter_on_button.enabled = bool(
            matching_editable_layers(self.layers, self.layer_search.text())
        )


class LockedLayerSearchStage9(unittest.TestCase):
    def setUp(self):
        self.layers = (
            SimpleNamespace(key="A", name="Tower-locked", locked=True),
            SimpleNamespace(key="B", name="Tower-editable", locked=False),
            SimpleNamespace(key="C", name="River", locked=False),
        )

    def test_pure_search_feedback_states(self):
        self.assertEqual(layer_search_feedback("", 3, 3), (False, ""))
        self.assertEqual(layer_search_feedback("Tower", 2, 1), (True, ""))
        no_match = layer_search_feedback("xyz", 0, 0)
        self.assertFalse(no_match[0])
        self.assertIn("없습니다", no_match[1])
        locked = layer_search_feedback("locked", 1, 0)
        self.assertFalse(locked[0])
        self.assertIn("잠겨", locked[1])

    def test_only_locked_match_reports_reason_and_hides_inert_buttons(self):
        context = FakeContext("locked", self.layers)
        search_method()(context, "locked")
        self.assertEqual(context.summary_matches, 1)
        self.assertEqual(context.synchronized, 1)
        self.assertFalse(context.filtered_actions.visible)
        self.assertTrue(context.layer_empty_hint.visible)
        self.assertIn("잠겨", context.layer_empty_hint.text_value)
        self.assertEqual([x.hidden for x in context.rows], [False, True, True])

    def test_editable_match_shows_scoped_actions(self):
        context = FakeContext("editable", self.layers)
        search_method()(context, "editable")
        self.assertTrue(context.filtered_actions.visible)
        self.assertFalse(context.layer_empty_hint.visible)
        self.assertEqual(context.summary_matches, 1)

    def test_mixed_locked_editable_matches_remain_actionable(self):
        context = FakeContext("tower", self.layers)
        search_method()(context, "tower")
        self.assertTrue(context.filtered_actions.visible)
        self.assertFalse(context.layer_empty_hint.visible)
        self.assertEqual(context.summary_matches, 2)

    def test_no_results_has_specific_message_without_buttons(self):
        context = FakeContext("unmatched", self.layers)
        search_method()(context, "unmatched")
        self.assertFalse(context.filtered_actions.visible)
        self.assertTrue(context.layer_empty_hint.visible)
        self.assertIn("없습니다", context.layer_empty_hint.text_value)
        self.assertTrue(all(x.hidden for x in context.rows))

    def test_cleared_search_removes_previous_error_state(self):
        context = FakeContext("", self.layers)
        search_method()(context, "")
        self.assertFalse(context.filtered_actions.visible)
        self.assertFalse(context.layer_empty_hint.visible)
        self.assertEqual(context.layer_empty_hint.text_value, "")
        self.assertTrue(all(not x.hidden for x in context.rows))

    def test_catalog_pending_ready_error_has_accessible_descriptions(self):
        for method in ("add_files", "_catalog_ready", "_error"):
            with self.subTest(method=method):
                self.assertIn("Qt.ItemDataRole.AccessibleDescriptionRole",
                              source_of(method))

    def test_filter_remains_display_only_and_preserves_locked_layers(self):
        source = source_of("_filter_layers")
        self.assertNotIn("set_visibility(", source)
        self.assertNotIn("apply_snapshot(", source)
        self.assertNotIn("set_all_layers(", source)
        self.assertIn("self._sync_actions()", source)
        self.assertIn("self.filtered_actions.setVisible(show_actions)", source)


if __name__ == "__main__":
    unittest.main()
