import tempfile
import unittest
from pathlib import Path
from build.lean_policy import LEAN_EXCLUDES, optional_qt, prune_qt


class LeanPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def entry(self, dest, kind='BINARY'):
        src = self.root / dest
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b'fixture')
        return (dest, str(src), kind)

    def test_exact_scope(self):
        for name in ('Qt6Quick.dll', 'Qt6Pdf.dll', 'plugins/imageformats/qpdf.dll'):
            self.assertTrue(optional_qt(self.entry('PySide6/' + name)))
        for name in ('Qt6Gui.dll', 'Qt6Svg.dll', 'Qt6OpenGL.dll', 'Qt6QmlUnknown.dll',
                     'plugins/platforms/qwindows.dll', 'plugins/imageformats/qjpeg.dll'):
            self.assertFalse(optional_qt(self.entry('PySide6/' + name)))
        self.assertFalse(optional_qt(self.entry('other/Qt6Pdf.dll')))
        self.assertFalse(optional_qt(self.entry('PySide6/Qt6Pdf.dll', 'DATA')))
        self.assertNotIn('lxml', LEAN_EXCLUDES)
        self.assertNotIn('PIL.AvifImagePlugin', LEAN_EXCLUDES)

    def test_optional_family_removed_together(self):
        entries = [self.entry('PySide6/' + n) for n in ('Qt6Gui.dll', 'Qt6Pdf.dll', 'plugins/imageformats/qpdf.dll')]
        kept, removed, blocked = prune_qt(entries, lambda p: {'qt6pdf.dll'} if p.endswith('qpdf.dll') else set())
        self.assertEqual(kept, entries[:1])
        self.assertEqual(len(removed), 2)
        self.assertEqual(sum(x['source_bytes'] for x in removed), 14)
        self.assertFalse(blocked)

    def test_transitive_retention(self):
        entries = [self.entry('PySide6/' + n) for n in ('Qt6Gui.dll', 'Qt6Quick.dll', 'Qt6Qml.dll')]
        deps = {'Qt6Gui.dll': {'Qt6Quick.dll'}, 'Qt6Quick.dll': {'Qt6Qml.dll'}}
        kept, removed, blocked = prune_qt(entries, lambda p: deps.get(Path(p).name, set()))
        self.assertEqual(kept, entries)
        self.assertFalse(removed)
        self.assertEqual(len(blocked), 2)

    def test_parser_error_blocks_candidate(self):
        entries = [self.entry('PySide6/Qt6Pdf.dll')]
        def fail(p):
            raise ValueError('unreadable PE')
        with self.assertRaises(ValueError):
            prune_qt(entries, fail)

    def test_no_candidates_skips_parser(self):
        entries = [self.entry('PySide6/Qt6Core.dll')]
        self.assertEqual(prune_qt(entries, lambda p: self.fail('unexpected parsing')), (entries, [], []))


if __name__ == '__main__':
    unittest.main()
