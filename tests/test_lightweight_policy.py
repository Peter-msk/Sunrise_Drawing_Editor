import tempfile
import unittest
from pathlib import Path
from build.lightweight_policy import filter_toc, removal_reason


class LightweightPolicyTests(unittest.TestCase):
    def entry(self, dest, kind='BINARY', src=None):
        return (dest, src or 'C:/Python/Lib/site-packages/' + dest, kind)

    def test_safe_only_selected_translations(self):
        for lang in ('ko', 'en', 'ko_KR', 'en_US'):
            self.assertFalse(removal_reason(self.entry('PySide6/translations/qtbase_' + lang + '.qm', 'DATA'), 'safe'))
        self.assertTrue(removal_reason(self.entry('PySide6/translations/qtbase_de.qm', 'DATA'), 'safe'))
        self.assertFalse(removal_reason(self.entry('PySide6/translations/license.qm', 'DATA'), 'safe'))
        self.assertFalse(removal_reason(self.entry('PySide6/plugins/imageformats/qwebp.dll'), 'safe'))
        self.assertFalse(removal_reason(self.entry('PySide6/opengl32sw.dll'), 'safe'))

    def test_compact_exact_allowlist(self):
        for dest in ('PySide6/plugins/imageformats/qwebp.dll', 'PySide6/opengl32sw.dll'):
            self.assertTrue(removal_reason(self.entry(dest), 'compact'))
        self.assertTrue(removal_reason(self.entry('opengl32sw.dll', src='C:/Python/PySide6/opengl32sw.dll'), 'compact'))
        for dest in ('PySide6/plugins/platforms/qwindows.dll', 'PySide6/plugins/imageformats/qsvg.dll',
                     'PySide6/plugins/imageformats/qjpeg.dll', 'PySide6/plugins/imageformats/qico.dll',
                     'PySide6/plugins/iconengines/qsvgicon.dll', 'PySide6/Qt6Core.dll', 'PySide6/Qt6Gui.dll',
                     'PySide6/Qt6Widgets.dll', 'pymupdf/mupdf.dll', 'numpy.libs/blas.dll',
                     'PIL/_imaging.pyd', 'libssl-3.dll', 'assets/app.ico', 'PySide6/plugins/imageformats/new.dll'):
            self.assertFalse(removal_reason(self.entry(dest), 'compact'), dest)

    def test_not_qt_owned_or_wrong_kind(self):
        self.assertFalse(removal_reason(self.entry('PySide6/plugins/imageformats/qwebp.dll', src='C:/other/qwebp.dll'), 'compact'))
        self.assertFalse(removal_reason(self.entry('other/translations/qtbase_de.qm', 'DATA'), 'safe'))
        self.assertFalse(removal_reason(self.entry('PySide6/plugins/imageformats/qwebp.dll', 'DATA'), 'compact'))

    def test_unknown_profile(self):
        with self.assertRaises(ValueError):
            filter_toc([], 'other')

    def test_toc_order_and_source_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'PySide6' / 'qtbase_de.qm'
            source.parent.mkdir()
            source.write_bytes(b'12345')
            a = self.entry('PySide6/Qt6Core.dll')
            b = self.entry('PySide6/translations/qtbase_de.qm', 'DATA', str(source))
            c = self.entry('PySide6/Qt6Gui.dll')
            kept, removed = filter_toc([a, b, c], 'safe')
            self.assertEqual(kept, [a, c])
            self.assertEqual(removed[0]['source_bytes'], 5)
            self.assertEqual(removed[0]['name'], b[0])

    def test_windows_separator(self):
        self.assertTrue(removal_reason(self.entry(r'PySide6\Qt\translations\qtbase_fr.qm', 'DATA'), 'safe'))


if __name__ == '__main__':
    unittest.main()
