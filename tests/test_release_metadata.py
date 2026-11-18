import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build.release_metadata import build_metadata, NAME


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'drawing_editor').mkdir()
        (self.root / 'drawing_editor/release_feed.py').write_text("APP_VERSION = '1.0.0'\n")
        self.live = self.root / 'latest.json'
        self.live.write_text(json.dumps({'schema_version': 1, 'app_id': 'sunrise_drawing_editor',
                                         'latest_version': '1.0.0', 'official_release': True,
                                         'automatic_update_available': True, 'release_notes': 'test'}))
        (self.root / 'notice.txt').write_text('공지사항 1.0.0\n', encoding='utf-8')
        self.exe = self.root / NAME
        self.exe.write_bytes(b'MZ test')
        self.sha = hashlib.sha256(self.exe.read_bytes()).hexdigest()

    def generate(self, trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY'):
        return build_metadata(self.exe, self.sha, {'sha256': self.sha, 'trust': trust}, root=self.root)

    def test_actual_digest_size_and_urls(self):
        files = self.generate()
        data = json.loads(files['latest.json'])
        self.assertEqual(set(files), {'latest.json', 'notice.txt'})
        self.assertEqual(data['sha256'], self.sha)
        self.assertEqual(data['file_size_bytes'], 7)
        self.assertTrue(data['download_url'].endswith('/v1.0.0/Sunrise%20Drawing%20Editor.exe'))
        self.assertEqual(files['notice.txt'].decode(), '공지사항 1.0.0\n')

    def test_live_feed_unchanged_and_candidate_disabled(self):
        before = self.live.read_bytes()
        for trust in ('SELF_SIGNED_UNTRUSTED_TEST_ONLY', 'TRUSTED_BY_WINDOWS_POLICY'):
            data = json.loads(self.generate(trust)['latest.json'])
            for key in ('official_release', 'automatic_update_available', 'update_endpoint_configured'):
                self.assertIs(data[key], False)
        self.assertEqual(self.live.read_bytes(), before)

    def test_version_mismatch(self):
        data = json.loads(self.live.read_text())
        data['latest_version'] = '2.0.0'
        self.live.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.generate()

    def test_empty_notice_and_wrong_hash(self):
        with self.assertRaises(ValueError):
            build_metadata(self.exe, self.sha, {'sha256': '0'*64}, root=self.root)
        (self.root / 'notice.txt').write_text(' ')
        with self.assertRaises(ValueError):
            self.generate()

    def test_bundle_and_rollback(self):
        from unittest.mock import patch
        import os
        from build.release_metadata import publish_bundle
        dist = self.root / 'dist'
        signature = {'sha256': self.sha, 'trust': 'SELF_SIGNED_UNTRUSTED_TEST_ONLY'}
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        publish_bundle(self.exe, dist, self.sha, signature, digest, root=self.root)
        previous = {p.relative_to(dist): p.read_bytes() for p in dist.rglob('*') if p.is_file()}
        self.assertEqual(len(previous), 5)
        self.exe.write_bytes(b'MZ changed')
        signature['sha256'] = digest(self.exe)
        replace = os.replace
        def locked(src, target):
            if Path(target) == dist / NAME:
                raise PermissionError('locked executable')
            return replace(src, target)
        with patch('os.replace', side_effect=locked), self.assertRaises(PermissionError):
            publish_bundle(self.exe, dist, signature['sha256'], signature, digest, root=self.root)
        self.assertEqual({p.relative_to(dist): p.read_bytes() for p in dist.rglob('*') if p.is_file()}, previous)
