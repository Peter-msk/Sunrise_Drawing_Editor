"""R17 final QA: exact published bundle coherence, using mock native evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build import final_qa_v150 as qa
from build.release_metadata import publish_bundle
from build.pe_version import expected_version


class BundleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        exe = self.root / 'Sunrise Drawing Editor.exe'
        exe.write_bytes(b'signed fixture, not an executable')
        self.sha = hashlib.sha256(exe.read_bytes()).hexdigest()
        self.signature = dict(sha256=self.sha, embedded_certificate_match=True,
                              trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
        self.dist = self.root / 'dist'
        publish_bundle(exe, self.dist, self.sha, self.signature,
                       lambda p: hashlib.sha256(p.read_bytes()).hexdigest(), functional_qa={},
                       smoke=dict(sha256=self.sha, passed=True, version_resource=expected_version()))
        self.report = self.dist / 'V150_LOCAL_QA.json'
        for ctx in (patch.object(qa, 'ROOT', self.root),
                    patch('build.pe_version.verify_version_resource', return_value=expected_version()),
                    patch('build.functional_gate.read_functional_qa'),
                    patch('build.sign_release.group_pin', return_value=None)):
            ctx.start(); self.addCleanup(ctx.stop)

    def test_intact_bundle(self):
        result = qa.postbuild(qt_tests_passed=True)
        self.assertEqual(result['status'], 'INTERNAL_QA_ONLY')
        self.assertEqual(result['sha256'], self.sha)

    def test_wrong_or_missing_checksum_rejected(self):
        path = self.dist / 'SHA256.txt'
        path.write_text('0'*64 + '  Sunrise Drawing Editor.exe\n', encoding='utf-8')
        self.assert_rejected()
        path.unlink()
        self.assert_rejected()

    def test_stale_metadata_and_enabled_feed_rejected(self):
        path = self.dist / 'release-metadata' / 'latest.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for key, value in [('sha256', '0'*64), ('latest_version', '1.1.1'),
                           ('file_size_bytes', 1), ('automatic_update_available', True),
                           ('official_release', True), ('update_endpoint_configured', True),
                           ('group_certificate_pin_verified', True)]:
            with self.subTest(key=key):
                path.write_text(json.dumps(dict(original, **{key: value})), encoding='utf-8')
                self.assert_rejected()
        path.unlink()
        self.assert_rejected()

    def test_stale_notice_rejected(self):
        path = self.dist / 'release-metadata' / 'notice.txt'
        path.write_text('previous notice', encoding='utf-8')
        self.assert_rejected()
        path.unlink()
        self.assert_rejected()

    def assert_rejected(self):
        self.report.write_text('old evidence', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            qa.postbuild(qt_tests_passed=True)
        self.assertFalse(self.report.exists())


if __name__ == '__main__': unittest.main(verbosity=2)
