import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from build.compression_policy import upx_selection
from build.build_compression import comparison, snapshot
from drawing_editor import runtime_packaging as runtime


class CompressionTests(unittest.TestCase):
    def test_upx_allowlist(self):
        entries = [('numpy.libs/blas.dll', 'C:/site/numpy.libs/libscipy_openblas64.dll', 'BINARY'),
                   ('Qt6Core.dll', 'C:/site/PySide6/Qt6Core.dll', 'BINARY'),
                   ('mupdf.dll', 'C:/site/pymupdf/mupdf.dll', 'BINARY')]
        self.assertEqual(upx_selection(entries), (['libscipy_openblas64.dll'], ['mupdf.dll', 'qt6core.dll']))

    def test_collision_and_unknown_are_excluded(self):
        name = 'libopenblas.dll'
        entries = [(name, 'C:/site/numpy.libs/' + name, 'BINARY'),
                   (name, 'C:/other/' + name, 'BINARY')]
        self.assertEqual(upx_selection(entries), ([], [name]))

    def test_no_baseline_or_negative_savings(self):
        self.assertIsNone(comparison(None, {'exe_bytes': 100})['saved_bytes'])
        self.assertEqual(comparison({'exe_bytes': 100}, {'exe_bytes': 110})['saved_percent'], -10)

    def test_snapshot_rejects_non_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'x.exe'
            f.write_bytes(b'NO')
            with self.assertRaises(ValueError):
                snapshot(f)
            f.write_bytes(b'MZ123')
            self.assertEqual(snapshot(f)['exe_bytes'], 5)

    def test_nuitka_worker_explicit_path_and_clean_env(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, '_nuitka_exe', None):
            self.assertIsNone(runtime.nuitka_worker_command('--cad-worker', tmp, 0))
            f = Path(tmp) / 'x.exe'
            f.write_bytes(b'MZ')
            runtime.configure_nuitka_candidate(f)
            with patch.dict('os.environ', {'NUITKA_ONEFILE_PARENT': '1', 'NUITKA_ORIGINAL_ARGV0': 'x', 'KEEP': 'yes'}, clear=True):
                cmd, kwargs = runtime.nuitka_worker_command('--batch-worker', tmp, 0)
            self.assertEqual(cmd, [str(f.resolve()), '--batch-worker', tmp])
            self.assertEqual(kwargs['env'], {'KEEP': 'yes'})

    def test_nuitka_rejects_wrong_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'x.txt'
            f.write_bytes(b'text')
            with self.assertRaises(RuntimeError):
                runtime.configure_nuitka_candidate(f)


if __name__ == '__main__':
    unittest.main()
