"""Source-contract regression for responsive file switches and theme parity.

Run with: python -m unittest tests.test_dxf_pdf_switch_theme_20261113
These contracts do not replace the Windows 402MiB DXF -> OnMap runtime QA.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / 'drawing_editor/core.py').read_text('utf-8')
WINDOW = (ROOT / 'drawing_editor/window.py').read_text('utf-8')


def method(source, owner, method_name):
    tree = ast.parse(source)
    obj = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    fn = next(n for n in obj.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    return ast.get_source_segment(source, fn)


class SwitchContract(unittest.TestCase):
    def test_old_render_cancelled_before_view_rebuild(self):
        src = method(WINDOW, 'DrawingWindow', '_selection_changed')
        self.assertLess(src.index('self._preview_cancel.set()'), src.index('self.layer_list.clear()'))

    def test_cad_fast_backend_has_periodic_cancel_checks(self):
        cls = next(n for n in ast.parse(CORE).body
                   if isinstance(n, ast.ClassDef) and n.name == '_CancelableFastCADBackend')
        names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue({'draw_line','draw_path','draw_image','_checkpoint'} <= names)
        self.assertIn('128', ast.get_source_segment(CORE, cls))
        self.assertIn('self._check_preview_cancel()', method(CORE, 'DrawingDocument', '_cad_as_pdf'))

    def test_thread_cache_invalidated_before_switch(self):
        fn = next(n for n in ast.parse(CORE).body
                  if isinstance(n, ast.FunctionDef) and n.name == '_thread_document')
        src = ast.get_source_segment(CORE, fn)
        self.assertLess(src.index('_cache.document = None'), src.index('previous.close()'))


class ThemeContract(unittest.TestCase):
    def test_palette_and_toolbar_text_are_explicit(self):
        src = method(WINDOW, 'DrawingWindow', '_apply_theme')
        self.assertIn('QPalette.ColorRole.ButtonText', src)
        self.assertIn('QPalette.ColorGroup.Disabled', src)
        self.assertIn('QToolBar#toolbar QToolButton', src)
        self.assertIn('color:{fg};', src)
        self.assertIn('button.setIconSize(QSize(18, 18))', src)


if __name__ == '__main__':
    unittest.main()
