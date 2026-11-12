"""Static UI-layout contract tests when a Windows / Qt GUI runtime is unavailable.
These checks do NOT replace visually inspecting the actual PySide6 window.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'drawing_editor' / 'window.py').read_text(encoding='utf-8')
ICONS = ROOT / 'assets'


class UIContractTests(unittest.TestCase):
    def test_python_ui_compiles_and_implements_elided_label(self):
        tree = ast.parse(SOURCE)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        self.assertIn('ElidedLabel', names)
        self.assertIn('DrawingWindow', names)
        self.assertIn('Qt.TextElideMode.ElideMiddle', SOURCE)

    def test_every_dynamic_icon_has_real_valid_svg(self):
        names = set(re.findall(r"self\._icon\('([a-z_]+)'\)", SOURCE))
        names |= set(re.findall(r"\('([a-z_]+)',\s*'[^']+'", SOURCE)) & {
            'add','remove','prev','next','fit','sun','moon'
        }
        for name in names:
            path = ICONS / f'icon_{name}.svg'
            self.assertTrue(path.is_file(), str(path))
            root = ElementTree.parse(path).getroot()
            self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')
            self.assertGreater(len(list(root.iter())), 2)
        self.assertGreaterEqual(len(names), 12)

    def test_white_icon_on_orange_export_and_cancel(self):
        self.assertIn("self.export_button.setIcon(self._icon('export_white'))", SOURCE)
        self.assertIn("self.export_button.setIcon(self._icon('stop_white'))", SOURCE)
        for name in ('export_white','stop_white'):
            text = (ICONS / f'icon_{name}.svg').read_text(encoding='utf-8')
            self.assertIn('stroke="#FFFFFF"', text)

    def test_layer_search_does_not_call_visibility_mutation(self):
        tree = ast.parse(SOURCE)
        clazz = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name=='DrawingWindow')
        method = next(x for x in clazz.body if isinstance(x, ast.FunctionDef) and x.name=='_filter_layers')
        body = ast.get_source_segment(SOURCE, method)
        self.assertIn('casefold()',body)
        self.assertIn('item.setHidden(not visible)',body)
        self.assertNotIn('set_visibility(',body)
        self.assertNotIn('set_all(',body)

    def test_layer_search_has_clearing_and_selection_summary(self):
        self.assertIn('self.layer_search.setClearButtonEnabled(True)', SOURCE)
        self.assertIn('self._update_layer_summary(matches=matches)', SOURCE)
        self.assertIn("suffix = f' · 검색 {matches}개'", SOURCE)

    def test_all_layer_buttons_explicitly_ignore_filter(self):
        self.assertIn('검색 결과와 관계없이 현재 도면의 모든 변경 가능한 레이어', SOURCE)
        self.assertIn('self.set_all_layers(True)', SOURCE)
        self.assertIn('self.set_all_layers(False)', SOURCE)

    def test_page_and_zoom_controls_are_in_preview(self):
        a = SOURCE.index("preview_frame, preview_layout = self._panel")
        b = SOURCE.index('root.addLayout(columns,1)', a)
        part = SOURCE[a:b]
        for control in ('page_prev_button','page_next_button','zoom_out_button',
                        'zoom_in_button','zoom_label','fit_button'):
            self.assertIn('self.'+control,part)
        self.assertNotIn("('□'",part)

    def test_export_is_not_duplicated_in_toolbar(self):
        toolbar = SOURCE[SOURCE.index('def _build_ui'):SOURCE.index('root_widget = QWidget()')]
        self.assertNotIn("toolbar.addAction(self._icon('export')", toolbar)
        self.assertIn("self.add_action = toolbar.addAction",toolbar)
        self.assertIn("self.remove_action = toolbar.addAction",toolbar)

    def test_resolution_original_remains_default_and_user_modes_exist(self):
        options = ['original','hd','fhd','qhd','uhd','custom','dpi']
        source = SOURCE[SOURCE.index("for name, mode in [('원본 자동"):
                        SOURCE.index('self.resolution_combo.setMinimumWidth', SOURCE.index("for name, mode in [('원본 자동"))]
        for mode in options:
            self.assertIn("'"+mode+"'",source)
        self.assertEqual(source.count("'original'"),1)
        self.assertIn("self.png_button.setChecked(True)",SOURCE)

    def test_dpi_adaptive_layout_and_ctrl_access(self):
        self.assertIn('QApplication.primaryScreen()', SOURCE)
        self.assertIn('screen.availableGeometry()', SOURCE)
        self.assertIn('self.setMinimumSize(970,510)', SOURCE)
        self.assertIn('compact = self.width() < 1190', SOURCE)
        for shortcut in ['Ctrl+O','Ctrl+S','Ctrl+F','Ctrl+0','Ctrl+PgUp','Ctrl+PgDown']:
            self.assertIn(shortcut, SOURCE)

    def test_buttons_disable_for_unloaded_documents_and_export_can_cancel(self):
        self.assertIn('can_export = bool(selected) and all(d.loaded for d in selected)',SOURCE)
        self.assertIn('self.export_button.setEnabled(self._export_busy or can_export)',SOURCE)
        self.assertIn("if self._export_busy:",SOURCE)
        self.assertIn('self._export_cancel.set()',SOURCE)

    def test_input_and_build_not_regressed_by_ui(self):
        command = (ROOT/'BUILD_ONEFILE.cmd').read_text(encoding='utf-8').lower()
        self.assertIn('--onefile',command)
        self.assertNotIn('powershell.exe',command)
        self.assertNotIn(' -m venv',command)
        self.assertIn('--exclude-module "pyqt5"',command)
        self.assertIn('--add-data "%cd%\\assets;assets"',command)


if __name__ == '__main__':
    unittest.main()
