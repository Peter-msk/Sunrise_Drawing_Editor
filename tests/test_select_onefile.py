import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from build.select_onefile import GATES, NAME, STATUS, collect, decide, evaluate, run_matrix, snapshot


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / 'base.exe'
        self.base.write_bytes(b'MZ' + b'0'*98)
        self.baseline = snapshot(self.base)

    def fixture(self, mode='safe', size=80, approve=True, trust='TRUSTED_BY_WINDOWS_POLICY'):
        parent = 'dist_lightweight' if mode in ('safe', 'compact') else 'dist_compression'
        folder = self.root / parent / mode
        folder.mkdir(parents=True)
        exe = folder / NAME
        exe.write_bytes(b'MZ' + b'1'*(size-2))
        actual = snapshot(exe)
        records = {'SIZE_COMPARISON.json': {'profile': mode, 'candidate': actual, 'baseline': self.baseline, 'status': STATUS},
                   'SIGNATURE_STATUS.json': {'sha256': actual['sha256'], 'windows_exe_smoke_pass': True, 'trust': trust}}
        if approve:
            records['QA_APPROVAL.json'] = {'schema_version': 1, 'candidate_sha256': actual['sha256'],
                                           'baseline_sha256': self.baseline['sha256'], 'reviewer': 'test',
                                           'gates': dict.fromkeys(GATES, 'PASS')}
        for name, value in records.items():
            (folder / name).write_text(json.dumps(value), encoding='utf-8')
        return folder

    def test_no_evidence_keeps_baseline(self):
        self.assertEqual(decide(collect(self.root, self.baseline))['status'], 'KEEP_BASELINE')
        folder = self.fixture(approve=False)
        self.assertFalse(evaluate(folder, self.baseline)['eligible_for_review'])

    def test_smallest_eligible_only_recommends(self):
        self.fixture('safe', 80)
        self.fixture('compact', 70)
        result = decide(collect(self.root, self.baseline))
        self.assertEqual(result['recommendation']['mode'], 'compact')
        self.assertEqual(result['official_default'], 'baseline')
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')

    def test_experimental_and_untrusted_blocked(self):
        a = self.fixture('nuitka', 40)
        b = self.fixture('upx', 50, trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
        self.assertFalse(evaluate(a, self.baseline)['eligible_for_review'])
        self.assertFalse(evaluate(b, self.baseline)['eligible_for_review'])

    def test_threshold_and_wrong_baseline(self):
        folder = self.fixture(size=96)
        self.assertFalse(evaluate(folder, self.baseline)['eligible_for_review'])
        wrong = dict(self.baseline, sha256='0'*64)
        self.assertIsNone(evaluate(folder, wrong)['saving_percent'])

    def test_tampered_exe_rejected(self):
        folder = self.fixture()
        (folder / NAME).write_bytes(b'MZ' + b'x'*78)
        with self.assertRaises(ValueError):
            evaluate(folder, self.baseline)
        self.assertFalse(collect(self.root, self.baseline)[0]['eligible_for_review'])

    def test_incomplete_qa_blocked(self):
        folder = self.fixture()
        path = folder / 'QA_APPROVAL.json'
        data = json.loads(path.read_text())
        data['gates'].pop(GATES[0])
        path.write_text(json.dumps(data))
        self.assertFalse(evaluate(folder, self.baseline)['eligible_for_review'])

    def test_matrix_optional_tools_and_failure(self):
        with patch('build.select_onefile.subprocess.run') as run:
            run.return_value.returncode = 1
            result = run_matrix(self.base)
            self.assertEqual([x['mode'] for x in result], ['safe', 'compact'])
            self.assertTrue(all(x['returncode'] == 1 for x in result))
            run.reset_mock()
            result = run_matrix(self.base, Path('upx'), True)
            self.assertEqual([x['mode'] for x in result], ['safe', 'compact', 'upx', 'nuitka'])
            self.assertEqual(run.call_count, 4)


if __name__ == '__main__':
    unittest.main()
