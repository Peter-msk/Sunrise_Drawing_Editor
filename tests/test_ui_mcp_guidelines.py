"""GUI-independent UI behavior contracts inspired by public UI/UX MCP guidance.

No assertion here claims Qt/Windows visual testing or MCP server execution.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from drawing_editor.ui_design import THEMES, panel_layout

ROOT = Path(__file__).resolve().parents[1]
WINDOW = (ROOT / 'drawing_editor' / 'window.py').read_text(encoding='utf-8')


def _luminance(hex_color: str) -> float:
    values = [int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
           for v in values]
    return sum(v * k for v, k in zip(rgb, (.2126, .7152, .0722)))


def _contrast(a: str, b: str) -> float:
    x, y = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (x + .05) / (y + .05)


class UIMCPGuidelineContracts(unittest.TestCase):
    def test_responsive_layout_preserves_canvas_at_minimum(self):
        for width in (760, 780, 800, 850, 900, 970, 1080, 1120, 1280, 1340, 1920):
            layout = panel_layout(width)
            with self.subTest(width=width):
                self.assertGreaterEqual(width - layout.file_width - layout.layer_width - 36,
                                        320, 'insufficient central preview width')
                self.assertGreaterEqual(layout.file_width, 150)
                self.assertGreaterEqual(layout.layer_width, 230)

    def test_responsive_layout_does_not_resize_for_nearby_widths(self):
        self.assertEqual(panel_layout(970), panel_layout(1050))
        self.assertEqual(panel_layout(1170), panel_layout(1290))
        self.assertNotEqual(panel_layout(900), panel_layout(899))

    def test_theme_primary_action_has_readable_contrast(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertGreaterEqual(_contrast(theme.primary, '#FFFFFF'), 4.5)
                self.assertGreaterEqual(_contrast(theme.primary_hover, '#FFFFFF'), 4.5)
                self.assertGreaterEqual(_contrast(theme.foreground, theme.panel), 7.0)
                self.assertGreaterEqual(_contrast(theme.muted, theme.panel), 4.5)
                self.assertGreaterEqual(_contrast(theme.active_text, theme.selection), 4.5)

    def test_drag_drop_only_allows_local_supported_documents(self):
        tree = ast.parse(WINDOW)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FileDropList')
        methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue({'dragEnterEvent', 'dragMoveEvent', 'dropEvent', '_paths'} <= methods)
        portion = ast.get_source_segment(WINDOW, cls)
        for expected in ("'.pdf'", "'.dxf'", "'.dwg'", 'url.isLocalFile()',
                         'self.filesDropped.emit(paths)', 'event.acceptProposedAction()'):
            self.assertIn(expected, portion)
        self.assertNotIn('write_bytes(', portion)
        self.assertNotIn('unlink(', portion)

    def test_drop_list_connected_to_existing_file_pipeline(self):
        self.assertIn('self.file_list = FileDropList()', WINDOW)
        self.assertIn('self.file_list.filesDropped.connect(self.add_files)', WINDOW)

    def test_canvas_has_nonblocking_placeholder(self):
        self.assertIn("self.empty_label.setObjectName('canvasEmpty')", WINDOW)
        self.assertIn('WA_TransparentForMouseEvents', WINDOW)
        self.assertIn('self.empty_label.hide()', WINDOW)
        self.assertIn('self.empty_label.show()', WINDOW)

    def test_layer_search_empty_state_is_display_only(self):
        tree = ast.parse(WINDOW)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DrawingWindow')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_filter_layers')
        fragment = ast.get_source_segment(WINDOW, method)
        self.assertIn('self.layer_empty_hint.setVisible(', fragment)
        self.assertNotIn('set_visibility(', fragment)
        self.assertNotIn('set_all_layers(', fragment)

    def test_export_button_reflects_multi_file_selection_without_changing_engine(self):
        self.assertIn("self.export_button.setText(f'{count}개 도면 추출'", WINDOW)
        self.assertIn("self.export_target_hint.setText(f'추출 대상 {count}개'", WINDOW)
        self.assertIn('self._export_busy or can_export', WINDOW)

    def test_keyboard_focus_and_accessible_names(self):
        for phrase in ('_configure_tab_order', 'QWidget.setTabOrder(before, after)',
                       'setAccessibleName(\'레이어명 검색\')',
                       'setAccessibleName(\'도면 파일 목록\')',
                       'setAccessibleName(\'미리보기 확대\')',
                       'setAccessibleName(\'이미지 저장 경로\')'):
            self.assertIn(phrase, WINDOW)
        self.assertIn('QPushButton:focus', WINDOW)

    def test_theme_ui_is_local_not_installed_as_system_library(self):
        self.assertIn('from .ui_design import THEMES, panel_layout', WINDOW)
        self.assertIn("root_widget.setObjectName('drawingRoot')", WINDOW)
        self.assertIn('QWidget#drawingRoot QPushButton', WINDOW)
        self.assertIn('self.work_scroll = QScrollArea()', WINDOW)
        self.assertIn('root.addWidget(self.work_scroll, 1)', WINDOW)
        self.assertNotIn('mcp', (ROOT / 'requirements.txt').read_text(encoding='utf-8').lower())

    def test_cad_engine_and_output_source_remain_separate(self):
        self.assertIn('from .core import (DrawingDocument', WINDOW)
        self.assertIn('plan_exports(docs,directory,opts)', WINDOW)
        self.assertIn('self._output_options()', WINDOW)


if __name__ == '__main__':
    unittest.main()
