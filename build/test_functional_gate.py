"""Targeted regression for the hash-bound packaged functional QA gate."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build.functional_gate import read_functional_qa, STATUS, REQUIRED, V130_REQUIRED, V140_REQUIRED, EXTRACTION_REQUIRED


class FunctionalGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'FUNCTIONAL_QA.json'
        self.sha = 'a' * 64
        self.data = dict(schema_version=1, sha256=self.sha, status=STATUS,
                         checks_passed=sorted(REQUIRED), not_run=['gui_dpi_theme_rdp'])

    def check(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        return read_functional_qa(self.path, self.sha)

    def test_valid(self):
        self.assertEqual(self.check(), self.data)

    def test_new_version_requires_new_checks(self):
        self.check()
        with self.assertRaises(RuntimeError):read_functional_qa(self.path,self.sha,version='1.3.0')
        self.assertEqual(read_functional_qa(self.path,self.sha,version='1.2.0'),self.data)
        self.data['checks_passed']=sorted(V130_REQUIRED)
        self.check()
        self.assertEqual(read_functional_qa(self.path,self.sha,version='1.3.0'),self.data)

    def test_v140_requires_vector_evidence(self):
        self.data['checks_passed']=sorted(V130_REQUIRED)
        self.check()
        with self.assertRaises(RuntimeError):read_functional_qa(self.path,self.sha,version='1.4.0')
        self.data['checks_passed']=sorted(V140_REQUIRED)
        self.check()
        self.assertEqual(read_functional_qa(self.path,self.sha,version='1.4.0'),self.data)
        self.assertEqual(read_functional_qa(self.path,self.sha,version='1.3.0'),self.data)

    def test_extraction_only_evidence(self):
        self.data['checks_passed']=sorted(V140_REQUIRED)
        self.check()
        with self.assertRaises(RuntimeError):read_functional_qa(self.path,self.sha,version='1.4.0',extraction_only=True)
        self.data['checks_passed']=sorted(EXTRACTION_REQUIRED)
        self.check()
        self.assertEqual(read_functional_qa(self.path,self.sha,version='1.4.0',extraction_only=True),self.data)
        self.assertEqual(read_functional_qa(self.path,self.sha,version='1.4.0'),self.data)
        self.data['checks_passed'].remove('dxf_compound_native');self.check()
        with self.assertRaises(RuntimeError):read_functional_qa(self.path,self.sha,version='1.4.0',extraction_only=True)

    def test_missing(self):
        with self.assertRaises(RuntimeError):
            read_functional_qa(self.path, self.sha)

    def test_wrong_hash(self):
        self.data['sha256'] = 'b' * 64
        with self.assertRaises(RuntimeError):
            self.check()

    def test_missing_checks(self):
        self.data['checks_passed'].pop()
        with self.assertRaises(RuntimeError):
            self.check()

    def test_status(self):
        self.data['status'] = 'FAIL'
        with self.assertRaises(RuntimeError):
            self.check()

    def test_duplicate(self):
        self.data['checks_passed'].append(self.data['checks_passed'][0])
        with self.assertRaises(RuntimeError):
            self.check()

    def test_pending_conflict(self):
        self.data['not_run'].append(next(iter(REQUIRED)))
        with self.assertRaises(RuntimeError):
            self.check()

    def test_malformed(self):
        self.path.write_bytes(b'{oops')
        with self.assertRaises(RuntimeError):
            read_functional_qa(self.path, self.sha)

    def test_oversize(self):
        self.path.write_bytes(b' ' * 65537)
        with self.assertRaises(RuntimeError):
            read_functional_qa(self.path, self.sha)


if __name__ == '__main__':
    unittest.main(verbosity=2)
