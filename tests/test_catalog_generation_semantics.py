"""Pure-Python regression: stale catalog results must not mutate a new row.

This suite needs no Qt installation and is run on the same helper used by the
real GUI success and failure callbacks.
"""
from pathlib import Path
import unittest
from drawing_editor.ui_interaction import catalog_result_is_current


class CatalogRegistrationTest(unittest.TestCase):
    def test_normal(self):
        self.assertTrue(catalog_result_is_current(
            5, 'C:/drawing.dxf', 'C:/drawing.dxf',
            {'C:/drawing.dxf': 5}, {'C:/drawing.dxf': object()}))

    def test_older_job_rejected_after_readd(self):
        latest = {'C:/drawing.dxf': 8}
        docs = {'C:/drawing.dxf': object()}
        self.assertFalse(catalog_result_is_current(
            7, 'C:/drawing.dxf', 'C:/drawing.dxf', latest, docs))
        self.assertTrue(catalog_result_is_current(
            8, 'C:/drawing.dxf', 'C:/drawing.dxf', latest, docs))

    def test_removed(self):
        self.assertFalse(catalog_result_is_current(
            3, 'C:/drawing.dxf', 'C:/drawing.dxf', {}, {}))

    def test_wrong_file(self):
        self.assertFalse(catalog_result_is_current(
            3, 'D:/other.pdf', 'C:/drawing.dxf',
            {'D:/other.pdf': 3}, {'D:/other.pdf': object()}))

    def test_missing_queued_request(self):
        self.assertFalse(catalog_result_is_current(
            3, 'C:/drawing.dxf', None,
            {'C:/drawing.dxf': 3}, {'C:/drawing.dxf': object()}))

    def test_error_callback_never_marks_readded_row(self):
        self.assertFalse(catalog_result_is_current(
            4, 'C:/drawing.dxf', 'C:/drawing.dxf',
            {'C:/drawing.dxf': 6}, {'C:/drawing.dxf': object()}))

    def test_gui_both_callbacks_use_the_shared_fence(self):
        source = (Path(__file__).resolve().parents[1] /
                  'drawing_editor' / 'window.py').read_text(encoding='utf-8')
        self.assertIn('catalog_result_is_current(seq,path,expected_path,', source)
        self.assertIn('catalog_result_is_current(seq,path,path,', source)


if __name__ == '__main__':
    unittest.main()
