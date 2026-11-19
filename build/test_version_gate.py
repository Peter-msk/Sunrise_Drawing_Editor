import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.version_gate import PROBE, version_probe_exit, verify_candidate_version


class VersionGateTests(unittest.TestCase):
    def test_exact_versions(self):
        for version in ('1.0.0', '1.1.0'):
            self.assertEqual(version_probe_exit(['app', PROBE, version], version), 42)

    def test_wrong_or_extra_arguments(self):
        for args in (['app', PROBE], ['app', PROBE, '1.1.0'],
                     ['app', PROBE, '1.0.0', 'extra'], ['app', '--self-test', '1.0.0']):
            self.assertEqual(version_probe_exit(args, '1.0.0'), 2)

    def test_exact_probe(self):
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=42)) as run:
            verify_candidate_version('candidate.exe', '1.1.0', {'PYINSTALLER_RESET_ENVIRONMENT': '1'})
            self.assertEqual(run.call_args.args[0], ['candidate.exe', PROBE, '1.1.0'])
            self.assertEqual(run.call_args.kwargs['timeout'], 120)

    def test_legacy_or_wrong_version_rejected(self):
        for code in (0, 1, 2, -1):
            with patch('subprocess.run', return_value=SimpleNamespace(returncode=code)), self.assertRaises(ValueError):
                verify_candidate_version('candidate.exe', '1.1.0', {})

    def test_timeout_propagates(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('candidate.exe', 120)), self.assertRaises(subprocess.TimeoutExpired):
            verify_candidate_version('candidate.exe', '1.1.0', {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
