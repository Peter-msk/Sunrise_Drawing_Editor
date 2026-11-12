"""Regression for unambiguous, original-safe UI actions adapted from Qt MCP review.

These tests run without Qt; Windows visual inspection is still required.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from drawing_editor.core import LayerInfo
from drawing_editor.state import DrawingState
from drawing_editor.ui_interaction import matching_editable_layers, file_add_status

ROOT = Path(__file__).resolve().parents[1]
WINDOW = (ROOT/'drawing_editor/window.py').read_text(encoding='utf-8')
TREE = ast.parse(WINDOW)
WINDOW_CLASS = next(item for item in TREE.body if isinstance(item, ast.ClassDef)
                    and item.name == 'DrawingWindow')


def method_text(name):
    method = next(n for n in WINDOW_CLASS.body if isinstance(n, ast.FunctionDef)
                  and n.name == name)
    return ast.get_source_segment(WINDOW, method)


class QtMcpUXContracts(unittest.TestCase):
    def test_no_filter_is_no_mutation_scope(self):
        layers = [LayerInfo('1', '저압선', True, False)]
        for query in ('', ' ', '  \t'):
            self.assertEqual(matching_editable_layers(layers, query), ())

    def test_casefold_preserves_layer_keys_and_skips_locked(self):
        layers = [LayerInfo('A', 'GIANT-1', False, False),
                  LayerInfo('B', 'giant-lock', True, True),
                  LayerInfo('C', 'Unrelated', True, False),
                  LayerInfo('D', 'GIANT-2', False, False)]
        self.assertEqual(matching_editable_layers(layers, ' giAnt '), ('A', 'D'))
        self.assertEqual(matching_editable_layers(layers, 'lock'), ())
        self.assertEqual(matching_editable_layers(layers, 'unrelated'), ('C',))
        self.assertEqual(matching_editable_layers(layers, 'none'), ())

    def test_filtered_mutation_does_not_touch_other_layers(self):
        # Only exercise state with a real local drawing; never write to the input.
        path = ROOT/'sample_data'/'SAMPLE_3_LAYERS.dxf'
        state = DrawingState(path)
        state.load_metadata([LayerInfo('A','Tower-1',False,False),
                             LayerInfo('B','Tower-Locked',False,True),
                             LayerInfo('C','River',True,False)],1)
        keys = matching_editable_layers(state.layers(), 'tower')
        self.assertEqual(keys, ('A',))
        state.apply_snapshot({key:True for key in keys})
        self.assertEqual(state.states(), {'A':True,'B':False,'C':True})

    def test_duplicate_file_feedback_is_explicit(self):
        self.assertIn('중복 건너뜀 3개', file_add_status(added=0,duplicates=3,rejected=0))
        self.assertIn('추가 실패 2개', file_add_status(added=1,duplicates=0,rejected=2))
        self.assertNotIn('백그라운드', file_add_status(added=0,duplicates=2,rejected=0))

    def test_named_widgets_support_mcp_style_inspection(self):
        for name in ('fileList','fileRemoveSelectedButton','allLayersOnButton',
                     'allLayersOffButton','filteredLayersOnButton','filteredLayersOffButton',
                     'applyLayerRuleButton','layerSearch','layerList','exportDrawingsButton'):
            with self.subTest(name=name):
                self.assertIn(f"setObjectName('{name}')", WINDOW)
        self.assertNotIn("setObjectName('subAction')", WINDOW)
        self.assertNotIn("setObjectName('themeButton')", WINDOW)

    def test_filtered_action_is_separate_from_global_action(self):
        self.assertIn('self.layer_on_button.clicked.connect(lambda:self.set_all_layers(True))', WINDOW)
        self.assertIn('self.filter_on_button.clicked.connect(lambda: self.set_filtered_layers(True))', WINDOW)
        fragment = method_text('set_filtered_layers')
        self.assertIn('matching_editable_layers(', fragment)
        self.assertIn('doc.apply_snapshot(changes)', fragment)
        self.assertNotIn('doc.set_all(',fragment)
        self.assertEqual(fragment.count('self.request_preview()'), 1)

    def test_source_filter_alone_cannot_change_layer_state(self):
        fragment = method_text('_filter_layers')
        self.assertNotIn('set_visibility(',fragment)
        self.assertNotIn('apply_snapshot(',fragment)
        self.assertIn('self.filtered_actions.setVisible(',fragment)

    def test_remove_selected_list_does_not_delete_original(self):
        fragment = method_text('_remove_file_items')
        self.assertIn('self.documents.pop(',fragment)
        self.assertIn('self.file_list.takeItem(',fragment)
        self.assertIn('self.file_list.blockSignals(True)',fragment)
        self.assertIn('self._selection_changed(',fragment)
        self.assertNotIn('.unlink(',fragment)
        self.assertNotIn('.remove(',fragment)

    def test_batch_remove_requires_explicit_confirmation(self):
        fragment = method_text('remove_selected_files')
        self.assertIn('len(items) > 1',fragment)
        self.assertIn('QMessageBox.question(',fragment)
        self.assertIn('QMessageBox.StandardButton.No',fragment)
        self.assertIn('self._remove_file_items(items)',fragment)

    def test_explorer_drop_remains_local_and_ui_only(self):
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef)
                   and n.name == 'FileDropList')
        source = ast.get_source_segment(WINDOW,cls)
        self.assertIn('url.isLocalFile()',source)
        self.assertIn('self.filesDropped.emit(paths)',source)
        self.assertNotIn('shutil',source)

    def test_scope_buttons_are_keyboard_and_accessibility_ready(self):
        for snippet in ('self.file_list.addAction(self.remove_selected_action)',
                        'Qt.ShortcutContext.WidgetShortcut',
                        'self.filter_on_button.setAccessibleName(',
                        'self.filter_off_button.setAccessibleName(',
                        "self.remove_selected_button.setAccessibleName("):
            self.assertIn(snippet,WINDOW)

    def test_styles_are_scoped_and_engine_is_unmodified_by_new_actions(self):
        self.assertIn('QWidget#drawingRoot QPushButton[uxRole="subAction"]',WINDOW)
        self.assertIn('self._sync_current_layer_rows()',method_text('set_filtered_layers'))
        self.assertNotIn('write_bytes(',method_text('set_filtered_layers'))


if __name__ == '__main__':
    unittest.main()
