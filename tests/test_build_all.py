import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from build.build_all import execute, plans


class UnifiedBuildTests(unittest.TestCase):
    def test_all_modes_and_missing_tools(self):
        jobs = plans(None, False)
        self.assertEqual([j[0] for j in jobs], ['safe', 'compact', 'lean', 'pyz', 'upx', 'nuitka'])
        self.assertEqual([j[1] is not None for j in jobs], [True, True, True, True, False, False])
        self.assertTrue(all(j[1] for j in plans(Path('upx'), True)))

    def test_fresh_candidate_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / 'dist_lightweight'
            (parent / 'old').mkdir(parents=True)
            def build(*a, **kw):
                (parent / 'new').mkdir()
                return type('Result', (), {'returncode': 0})()
            def check(folder, evidence):
                self.assertEqual(folder.name, 'new')
                return {'mode': 'safe'}
            with patch('build.build_all.subprocess.run', side_effect=build):
                rows, results = execute(root, root / 'base.exe', plans(None, False)[:1], check, {})
            self.assertEqual(len(rows), 1)
            self.assertEqual(results[0]['status'], 'BUILT_QA_PENDING')

    def test_failure_and_missing_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('build.build_all.subprocess.run') as run:
                run.return_value.returncode = 1
                rows, results = execute(root, root / 'base.exe', plans(None, False), None, {})
            self.assertFalse(rows)
            self.assertEqual([r['status'] for r in results], ['FAILED', 'FAILED', 'FAILED', 'FAILED', 'NOT RUN', 'NOT RUN'])

    def test_invalid_new_candidate_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def build(*a, **kw):
                (root / 'dist_lightweight' / 'new').mkdir(parents=True)
                return type('Result', (), {'returncode': 0})()
            with patch('build.build_all.subprocess.run', side_effect=build):
                rows, results = execute(root, root / 'base.exe', plans(None, False)[:1], lambda *a: {'mode': 'compact'}, {})
            self.assertFalse(rows)
            self.assertEqual(results[0]['status'], 'FAILED')


if __name__ == '__main__':
    unittest.main()
