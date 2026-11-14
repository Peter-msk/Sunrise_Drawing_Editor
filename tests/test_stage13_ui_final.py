"""Stage13 native UI regression contracts; no GUI display required."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

from drawing_editor.ui_design import THEMES, panel_layout

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'drawing_editor/window.py').read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)
WINDOW=next(item for item in TREE.body if isinstance(item,ast.ClassDef)
            and item.name=='DrawingWindow')

def method(name):
    item=next(x for x in WINDOW.body if isinstance(x,ast.FunctionDef) and x.name==name)
    return ast.get_source_segment(SOURCE,item)


class FinalUiOwnershipTests(unittest.TestCase):
    def test_compact_two_row_navigation_preserves_every_button(self):
        build=method('_build_ui')
        responsive=method('_apply_responsive_layout')
        for text in ('preview_controls = QBoxLayout(QBoxLayout.Direction.LeftToRight)',
                     'page_controls = QHBoxLayout()', 'zoom_controls = QHBoxLayout()',
                     'preview_controls.addLayout(page_controls, 1)',
                     'preview_controls.addLayout(zoom_controls)'):
            self.assertIn(text,build)
        self.assertIn('QBoxLayout.Direction.TopToBottom if narrow',responsive)
        self.assertIn("self.fit_button.setText('' if narrow else '맞춤')",responsive)
        for name in ('page_prev_button','page_next_button','zoom_out_button',
                     'zoom_in_button','fit_button'):
            self.assertIn('self.'+name+'.setAccessibleName(',build)

    def test_keyboard_export_shortcut_cannot_cancel_running_batch(self):
        build=method('_build_ui')
        shortcut=method('_export_shortcut')
        self.assertIn("('Ctrl+S', self._export_shortcut)",build)
        self.assertIn('if not self._export_busy:',shortcut)
        self.assertIn('self.export_selected()',shortcut)
        self.assertNotIn('self._export_cancel.set()',shortcut)

    def test_theme_style_has_focus_and_four_panel_consistency(self):
        theme=method('_apply_theme')
        self.assertIn('QToolBar#toolbar QToolButton:focus',theme)
        self.assertIn('QFrame#layerSearchFrame',theme)
        self.assertIn('QGroupBox#exportPanel QLabel',theme)
        self.assertIn('QGroupBox#exportPanel QRadioButton',theme)
        self.assertIn('self.layer_search_icon.setPixmap(',theme)
        self.assertIn('QWidget#drawingRoot',theme)
        self.assertEqual(set(THEMES),{'light','dark'})

    def test_minimum_preview_reserve_by_breakpoint(self):
        for width in (760,900,1120,1510):
            p=panel_layout(width)
            # Reserve root gutters, inter-pane spacing, and panel borders;
            # the real-Qt geometry audit independently checks actual bounds.
            reserve=width-(p.file_width+p.layer_width+64)
            self.assertGreaterEqual(reserve,260,f'{width}px preview squeezed')

    def test_export_footer_persistent_and_accessible(self):
        build=method('_build_ui')
        self.assertIn('root.addWidget(footer)',build)
        self.assertIn('self.work_scroll',build)
        self.assertIn("self.export_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)",build)
        self.assertIn("self.progress.setAccessibleDescription(",build)
        self.assertIn("self.progress.setToolTip('일괄 이미지 추출 진행률')",build)


if __name__=='__main__':
    unittest.main()
