import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from build.audit_onefile import classify, inventory, main


class OnefileAuditTests(unittest.TestCase):
    def test_accounting_and_sorting(self):
        toc = {'PYZ.pyz': (0, 100, 100, 0, 'z'),
               'PySide6/Qt6Core.dll': (100, 200, 400, 1, 'b'),
               'opengl32sw.dll': (300, 50, 100, 1, 'b')}
        report = inventory(toc, 400)
        self.assertEqual(report['packed_payload_bytes'], 350)
        self.assertEqual(report['other_bytes'], 50)
        self.assertEqual(report['groups']['Qt / PySide6']['packed_bytes'], 250)
        self.assertEqual(report['entries'][0]['name'], 'PySide6/Qt6Core.dll')
        self.assertEqual(report['review_candidate_bytes'], 50)
        self.assertEqual(report['groups']['Python PYZ']['entries'], 1)

    def test_windows_paths_and_protected_entries(self):
        for name, group in [(r'PySide6\plugins\platforms\qwindows.dll', 'Qt / PySide6'),
                            (r'pymupdf\mupdf.dll', 'MuPDF / PyMuPDF'),
                            (r'numpy.libs\libopenblas.dll', 'NumPy / BLAS'),
                            (r'PIL\_imaging.pyd', 'Pillow'),
                            ('python312.dll', 'Python / runtime'), ('libssl-3.dll', 'TLS / crypto')]:
            self.assertEqual(classify(name, 'b'), (group, ''))
        self.assertTrue(classify(r'PySide6\translations\qtbase_de.qm', 'x')[1])
        self.assertTrue(classify(r'PySide6\plugins\imageformats\qgif.dll', 'b')[1])
        self.assertFalse(classify(r'PySide6\plugins\imageformats\qsvg.dll', 'b')[1])

    def test_malformed_inventory(self):
        for toc in ({}, {'a': (0, 501, 501, 0, 'b')},
                    {'a': (-1, 1, 1, 0, 'b')}, {'a': (0, 1, 1, 2, 'b')},
                    {'a': (0, 20, 20, 0, 'b'), 'b': (10, 20, 20, 0, 'b')}):
            with self.assertRaises(ValueError):
                inventory(toc, 500)

    def test_input_and_existing_report_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'app.exe'
            exe.write_bytes(b'MZ123')
            report = Path(tmp) / 'report.json'
            report.write_text('earlier report')
            with patch('build.audit_onefile.audit', return_value={}):
                self.assertEqual(main([str(exe), '--report', str(exe)]), 1)
                self.assertEqual(main([str(exe), '--report', str(report)]), 1)
            self.assertEqual(exe.read_bytes(), b'MZ123')
            self.assertEqual(report.read_text(), 'earlier report')

    def test_report_written_from_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'app.exe'
            exe.write_bytes(b'MZ123')
            output = Path(tmp) / 'report.json'
            result = inventory({'a': (0, 3, 4, 1, 'b')}, 5)
            result['sha256'] = '0'*64
            with patch('build.audit_onefile.audit', return_value=result):
                self.assertEqual(main([str(exe), '--report', str(output)]), 0)
            self.assertIn('"packed_payload_bytes": 3', output.read_text())


if __name__ == '__main__':
    unittest.main()
