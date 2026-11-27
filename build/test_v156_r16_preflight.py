"""R16 build readiness and evidence lifecycle tests (not a native Windows build)."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from build import final_qa_v150 as qa
from build import preflight
from build.release_metadata import publish_bundle
from build.pe_version import expected_version


class R16Tests(unittest.TestCase):
    def test_dependencies_ready_without_install(self):
        with patch.object(preflight, 'check_python', return_value=[]), \
                patch.object(preflight, 'check_dependencies', return_value=[]), \
                patch.object(qa.subprocess, 'run') as run:
            qa.prepare_build_dependencies()
            run.assert_not_called()

    def test_install_only_missing_and_recheck(self):
        with patch.object(preflight, 'check_python', return_value=[]), \
                patch.object(preflight, 'check_dependencies', side_effect=[['missing Qt'], []]) as check, \
                patch.dict(os.environ, {'BUILD_NO_INSTALL': '0'}), \
                patch.object(qa.subprocess, 'run') as run:
            run.return_value.returncode = 0
            qa.prepare_build_dependencies()
            self.assertEqual(check.call_count, 2)
            self.assertEqual(run.call_args.args[0], [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '-r', 'build/requirements-build.txt'])
            self.assertEqual(run.call_args.kwargs['cwd'], qa.ROOT)

    def test_dependency_failure_blocks_build(self):
        for no_install, pip_status, deps in [('1', 0, [['missing']]), ('0', 1, [['missing']]), ('0', 0, [['missing'], ['still missing']])]:
            with self.subTest(no_install=no_install, pip_status=pip_status, deps=deps), \
                    patch.object(preflight, 'check_python', return_value=[]), \
                    patch.object(preflight, 'check_dependencies', side_effect=deps), \
                    patch.dict(os.environ, {'BUILD_NO_INSTALL': no_install}), \
                    patch.object(qa.subprocess, 'run') as run:
                run.return_value.returncode = pip_status
                with self.assertRaises(RuntimeError):
                    qa.prepare_build_dependencies()
                self.assertEqual(run.call_count, int(no_install != '1'))
        with patch.object(preflight, 'check_python', return_value=['wrong Python']), \
                patch.object(preflight, 'check_dependencies') as check:
            with self.assertRaises(RuntimeError): qa.prepare_build_dependencies()
            check.assert_not_called()

    def test_publish_invalidates_old_final_qa_and_restores_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); exe = root / 'Sunrise Drawing Editor.exe'; exe.write_bytes(b'new signed fixture')
            digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            sha = digest(exe); signature = dict(sha256=sha, trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
            smoke = dict(sha256=sha, passed=True, version_resource=expected_version())
            dist = root / 'dist'; dist.mkdir(); old = dist / exe.name; old.write_bytes(b'old fixture')
            report = dist / 'V150_LOCAL_QA.json'; report.write_bytes(b'old final QA')
            real_replace = os.replace
            def fail_last(src, dst):
                if Path(dst) == old:
                    self.assertFalse(report.exists())
                    raise OSError('simulated final EXE failure')
                return real_replace(src, dst)
            with patch('os.replace', side_effect=fail_last), self.assertRaises(OSError):
                publish_bundle(exe, dist, sha, signature, digest, functional_qa={}, smoke=smoke)
            self.assertEqual(old.read_bytes(), b'old fixture')
            self.assertEqual(report.read_bytes(), b'old final QA')
            publish_bundle(exe, dist, sha, signature, digest, functional_qa={}, smoke=smoke)
            self.assertFalse(report.exists())
            self.assertEqual(digest(old), sha)

    def test_all_preflight_before_qt_and_build(self):
        calls = []
        with patch.object(qa, 'os', SimpleNamespace(name='nt')), \
                patch.object(sys, 'argv', ['final_qa_v150.py', '--all']), \
                patch.object(sys, 'path', list(sys.path)), \
                patch.object(qa, 'prepare_build_dependencies', side_effect=lambda: calls.append('preflight')) as prepare, \
                patch.object(qa, 'native_qt_tests', side_effect=lambda: calls.append('qt') or True), \
                patch.object(qa.subprocess, 'run', side_effect=lambda *a, **k: calls.append('build') or SimpleNamespace(returncode=0)), \
                patch.object(qa, 'postbuild', side_effect=lambda **k: calls.append(('postbuild', k['qt_tests_passed']))):
            self.assertEqual(qa.main(), 0)
            self.assertEqual(calls, ['preflight', 'qt', 'build', ('postbuild', True)])
            calls.clear(); prepare.side_effect = RuntimeError('missing dependencies')
            with self.assertRaises(RuntimeError): qa.main()
            self.assertEqual(calls, [])

    def test_supported_cmd_selects_compatible_python_before_qa(self):
        cmd = (qa.ROOT / 'RUN_V150_FINAL_QA.cmd').read_text(encoding='utf-8')
        self.assertIn('py -3 "build\\preflight.py" python', cmd)
        self.assertIn('python "build\\preflight.py" python', cmd)
        self.assertLess(cmd.index('build\\preflight.py'), cmd.index('build\\final_qa_v150.py'))

if __name__ == '__main__': unittest.main(verbosity=2)
